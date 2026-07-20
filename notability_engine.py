"""
注目理由付きスポーツ通知サービス - 通知理由生成エンジン (プロトタイプ)

役割:
  1. 試合データ(スケジュール・順位表・個人成績)を取得する
  2. 各試合について「なぜ注目か」の理由をルールベースで生成する
  3. 全試合分をまとめて1つのJSONとして出力する(端末側でフィルタリングする前提)

想定運用:
  GitHub Actions で毎朝1回実行 → 出力JSONを GitHub Pages に置く
  → スマホアプリが定期的に取得し、端末内のフォロー設定と照合してフィルタ・通知

注意:
  このコード実行環境はネットワークアクセスが無効なため、MLB Stats API /
  football-data.org への実際のリクエスト・レスポンスは未検証。エンドポイント
  やフィールド名はWeb検索で実在を確認した情報を基に書いているが、実行して
  初めて分かる差異(フィールド名の揺れ等)が残っている前提で扱うこと。
  --mock オプションはロジック部分(スコアリング・理由生成)のみ動作確認済み。

使い方:
  python3 notability_engine.py --mock                     # ロジックのみ確認
  python3 notability_engine.py --source mlb                # MLBのみ実データ取得
  FOOTBALL_DATA_API_KEY=xxx python3 notability_engine.py --source soccer
  FOOTBALL_DATA_API_KEY=xxx python3 notability_engine.py --source all
"""

import json
import argparse
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import requests  # ローカル実行時に使用。この環境では未使用(mockモードのみ動作)
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# データモデル
# ---------------------------------------------------------------------------

@dataclass
class Standing:
    team_id: str
    division_rank: int
    games_back: float  # 首位との差(0.0なら首位)
    win_streak: int  # 正の値=連勝、負の値=連敗


@dataclass
class PlayerHighlight:
    name: str
    team_id: str
    is_japanese: bool
    stat_context: str  # 例: "本塁打王争いトップ", "防御率リーグ2位"


@dataclass
class Game:
    game_id: str
    league: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    players: list = field(default_factory=list)  # list[PlayerHighlight]


@dataclass
class Reason:
    tag: str
    text: str
    weight: int


# ---------------------------------------------------------------------------
# 注目理由の判定ルール
# ---------------------------------------------------------------------------
# 判定ルールはここに集約する。新しい注目軸を足したい場合はこの関数群に追加していく。

def rule_japanese_player(game: Game) -> list[Reason]:
    reasons = []
    for p in game.players:
        if p.is_japanese:
            reasons.append(
                Reason(
                    tag="JP",
                    text=f"{p.name}が{p.stat_context}の中での出場",
                    weight=3,
                )
            )
    return reasons


def rule_division_race(game: Game, standings: dict) -> list[Reason]:
    reasons = []
    home = standings.get(game.home_team_id)
    away = standings.get(game.away_team_id)
    if home and away:
        # 両チームの首位との差が僅差、かつ同地区想定の場合を「首位攻防戦」とみなす
        if abs(home.games_back - away.games_back) <= 2.0 and (
            home.games_back <= 3.0 or away.games_back <= 3.0
        ):
            reasons.append(
                Reason(
                    tag="div",
                    text=(
                        f"{game.home_team_name} vs {game.away_team_name} は"
                        f"首位攻防戦、ゲーム差はわずか{abs(home.games_back - away.games_back):.1f}"
                    ),
                    weight=2,
                )
            )
    return reasons


def rule_win_streak(game: Game, standings: dict) -> list[Reason]:
    reasons = []
    for team_id, team_name in (
        (game.home_team_id, game.home_team_name),
        (game.away_team_id, game.away_team_name),
    ):
        s = standings.get(team_id)
        if s and abs(s.win_streak) >= 5:
            kind = "連勝" if s.win_streak > 0 else "連敗"
            reasons.append(
                Reason(
                    tag="streak",
                    text=f"{team_name}は{abs(s.win_streak)}{kind}中",
                    weight=2,
                )
            )
    return reasons


ALL_RULES = [rule_japanese_player, rule_division_race, rule_win_streak]


def generate_reasons(game: Game, standings: dict) -> list[Reason]:
    reasons: list[Reason] = []
    for rule in ALL_RULES:
        if rule is rule_japanese_player:
            reasons.extend(rule(game))
        else:
            reasons.extend(rule(game, standings))
    return reasons


def score_game(reasons: list[Reason]) -> int:
    return sum(r.weight for r in reasons)


# ---------------------------------------------------------------------------
# 出力JSON組み立て
# ---------------------------------------------------------------------------

def build_output(games: list[Game], standings: dict) -> dict:
    output_games = []
    for g in games:
        reasons = generate_reasons(g, standings)
        output_games.append(
            {
                "game_id": g.game_id,
                "league": g.league,
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "matchup": f"{g.home_team_name} vs {g.away_team_name}",
                "score": score_game(reasons),
                "reasons": [
                    {"tag": r.tag, "text": r.text, "weight": r.weight} for r in reasons
                ],
            }
        )
    output_games.sort(key=lambda x: x["score"], reverse=True)
    return {"generated_at": "TODO: set actual UTC timestamp", "games": output_games}


# ---------------------------------------------------------------------------
# モックデータ(ネットワーク無しで動作確認するため)
# ---------------------------------------------------------------------------

def load_mock_data():
    standings = {
        "LAD": Standing(team_id="LAD", division_rank=1, games_back=0.0, win_streak=3),
        "SD": Standing(team_id="SD", division_rank=2, games_back=1.5, win_streak=-2),
        "NYY": Standing(team_id="NYY", division_rank=1, games_back=0.0, win_streak=1),
        "BOS": Standing(team_id="BOS", division_rank=3, games_back=8.0, win_streak=6),
    }

    games = [
        Game(
            game_id="g1",
            league="MLB",
            home_team_id="LAD",
            away_team_id="SD",
            home_team_name="ドジャース",
            away_team_name="パドレス",
            players=[
                PlayerHighlight(
                    name="大谷翔平",
                    team_id="LAD",
                    is_japanese=True,
                    stat_context="本塁打王争いトップ",
                )
            ],
        ),
        Game(
            game_id="g2",
            league="MLB",
            home_team_id="NYY",
            away_team_id="BOS",
            home_team_name="ヤンキース",
            away_team_name="レッドソックス",
            players=[],
        ),
    ]
    return games, standings


# ---------------------------------------------------------------------------
# 日本人選手リスト(静的リスト・要定期更新)
# ---------------------------------------------------------------------------
# 移籍で頻繁に変わるため、シーズンごと・移籍市場のたびに手動更新が必要。
# name_en は API のレスポンス上の英語表記に一致させること(ローマ字表記の揺れに注意)。

JP_PLAYERS_MLB = [
    {"name_en": "Shohei Ohtani", "name_jp": "大谷翔平"},
    {"name_en": "Yu Darvish", "name_jp": "ダルビッシュ有"},
    {"name_en": "Roki Sasaki", "name_jp": "佐々木朗希"},
    {"name_en": "Yoshinobu Yamamoto", "name_jp": "山本由伸"},
    {"name_en": "Tomoyuki Sugano", "name_jp": "菅野智之"},
    {"name_en": "Yusei Kikuchi", "name_jp": "菊池雄星"},
    {"name_en": "Shota Imanaga", "name_jp": "今永昇太"},
    {"name_en": "Seiya Suzuki", "name_jp": "鈴木誠也"},
    {"name_en": "Kodai Senga", "name_jp": "千賀滉大"},
    {"name_en": "Yuki Matsui", "name_jp": "松井裕樹"},
]

# 2026年7月時点、Web検索で確認できた範囲のみ記載。追加・更新推奨。
JP_PLAYERS_SOCCER = [
    {"name_en": "Kaoru Mitoma", "name_jp": "三笘薫", "team_en": "Brighton"},
    {"name_en": "Ao Tanaka", "name_jp": "田中碧", "team_en": "Leeds United"},
    {"name_en": "Daichi Kamada", "name_jp": "鎌田大地", "team_en": "Crystal Palace"},
    {"name_en": "Tatsuhiro Sakamoto", "name_jp": "坂本達裕", "team_en": "Coventry City"},
]


# ---------------------------------------------------------------------------
# 実データ取得: MLB Stats API
# ---------------------------------------------------------------------------
# エンドポイントはMLB非公式(無料・キー不要だが公式ドキュメントは存在しない)。
# Web検索で実在・広く使われていることは確認済みだが、この環境はネットワーク
# 無効のため実際のレスポンスは未検証。フィールド名などは変わる可能性がある。

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def fetch_mlb_games_and_standings(date_str: str):
    """
    date_str: 'YYYY-MM-DD'
    戻り値: (games: list[Game], standings: dict[str, Standing])
    """
    if requests is None:
        raise RuntimeError("requests がインストールされていません")

    schedule_resp = requests.get(
        f"{MLB_API_BASE}/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "team,probablePitcher"},
        timeout=10,
    )
    schedule_resp.raise_for_status()
    schedule_data = schedule_resp.json()

    standings_resp = requests.get(
        f"{MLB_API_BASE}/standings",
        params={"leagueId": "103,104", "season": date_str[:4]},
        timeout=10,
    )
    standings_resp.raise_for_status()
    standings_data = standings_resp.json()

    standings: dict[str, Standing] = {}
    for record in standings_data.get("records", []):
        for team_record in record.get("teamRecords", []):
            team_id = str(team_record["team"]["id"])
            games_back_raw = team_record.get("gamesBack", "0")
            games_back = 0.0 if games_back_raw in ("-", "0") else float(games_back_raw)
            streak_code = team_record.get("streak", {}).get("streakCode", "")
            # streakCode 例: "W5"(5連勝), "L3"(3連敗)
            win_streak = 0
            if streak_code:
                sign = 1 if streak_code.startswith("W") else -1
                try:
                    win_streak = sign * int(streak_code[1:])
                except ValueError:
                    win_streak = 0
            standings[team_id] = Standing(
                team_id=team_id,
                division_rank=int(team_record.get("divisionRank", 0)),
                games_back=games_back,
                win_streak=win_streak,
            )

    jp_names_en = {p["name_en"] for p in JP_PLAYERS_MLB}
    jp_lookup = {p["name_en"]: p["name_jp"] for p in JP_PLAYERS_MLB}

    games: list[Game] = []
    for date_entry in schedule_data.get("dates", []):
        for g in date_entry.get("games", []):
            home = g["teams"]["home"]["team"]
            away = g["teams"]["away"]["team"]

            players: list[PlayerHighlight] = []
            for side, team in (("home", home), ("away", away)):
                pitcher = g["teams"][side].get("probablePitcher")
                if pitcher and pitcher.get("fullName") in jp_names_en:
                    players.append(
                        PlayerHighlight(
                            name=jp_lookup[pitcher["fullName"]],
                            team_id=str(team["id"]),
                            is_japanese=True,
                            # TODO: 実際の成績文脈(防御率順位など)を別APIから取得して差し替える
                            stat_context="先発予定",
                        )
                    )

            games.append(
                Game(
                    game_id=str(g["gamePk"]),
                    league="MLB",
                    home_team_id=str(home["id"]),
                    away_team_id=str(away["id"]),
                    home_team_name=home["name"],
                    away_team_name=away["name"],
                    players=players,
                )
            )

    return games, standings


# ---------------------------------------------------------------------------
# 実データ取得: football-data.org (欧州5大リーグ)
# ---------------------------------------------------------------------------
# 無料枠: 12競技会・10リクエスト/分・順位表は含まれるがスコアは遅延、選手個別
# 成績(先発メンバー等)は含まれない。要 FOOTBALL_DATA_API_KEY 環境変数。

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
SOCCER_COMPETITIONS = {
    "PL": "プレミアリーグ",
    "PD": "ラ・リーガ",
    "SA": "セリエA",
    "BL1": "ブンデスリーガ",
    "FL1": "リーグ・アン",
}


def _football_data_get(url, headers, params=None, timeout=10, max_retries=3):
    """
    football-data.org は 10リクエスト/分(無料枠)。レスポンスヘッダーの
    X-Requests-Available-Minute を見て残りが少なければ待機し、
    429(レート制限超過)が返ってきた場合は Retry-After に従って再試行する。
    (football-data.org運営者からの助言に基づく実装)
    """
    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            print(f"[warn] football-data.org レート制限に到達。{retry_after}秒待機してリトライします")
            time.sleep(retry_after)
            continue

        resp.raise_for_status()

        remaining = resp.headers.get("X-Requests-Available-Minute")
        if remaining is not None:
            try:
                if int(remaining) <= 1:
                    print("[info] football-data.org 残りリクエスト数が少ないため1秒待機します")
                    time.sleep(1)
            except ValueError:
                pass

        return resp

    raise RuntimeError("football-data.org: リトライ上限に達しました(レート制限が解消しません)")


def fetch_soccer_games_and_standings(date_str: str, api_key: str):
    """
    date_str: 'YYYY-MM-DD'
    無料枠のレート制限(10req/分)に注意。5リーグ分の順位表取得だけで5リクエスト
    消費するので、間隔を空けるかキャッシュを検討すること。
    """
    if requests is None:
        raise RuntimeError("requests がインストールされていません")

    headers = {"X-Auth-Token": api_key}
    games: list[Game] = []
    standings: dict[str, Standing] = {}

    jp_team_names = {p["team_en"] for p in JP_PLAYERS_SOCCER}

    for code, league_name in SOCCER_COMPETITIONS.items():
        matches_resp = _football_data_get(
            f"{FOOTBALL_DATA_BASE}/competitions/{code}/matches",
            headers=headers,
            params={"dateFrom": date_str, "dateTo": date_str},
        )
        matches_data = matches_resp.json()

        standings_resp = _football_data_get(
            f"{FOOTBALL_DATA_BASE}/competitions/{code}/standings",
            headers=headers,
        )
        standings_data = standings_resp.json()

        # 順位表(TOTALテーブルのみ利用)
        for table_group in standings_data.get("standings", []):
            if table_group.get("type") != "TOTAL":
                continue
            table = table_group.get("table", [])
            top_points = table[0]["points"] if table else 0
            for row in table:
                team_id = f"{code}-{row['team']['id']}"
                games_back = round((top_points - row["points"]) / 3, 1)  # 簡易換算
                standings[team_id] = Standing(
                    team_id=team_id,
                    division_rank=row["position"],
                    games_back=games_back,
                    win_streak=0,  # 無料枠にフォームデータが無いため未実装
                )

        for m in matches_data.get("matches", []):
            home = m["homeTeam"]
            away = m["awayTeam"]

            players: list[PlayerHighlight] = []
            for team in (home, away):
                if team.get("name") in jp_team_names:
                    jp_player = next(
                        p for p in JP_PLAYERS_SOCCER if p["team_en"] == team["name"]
                    )
                    players.append(
                        PlayerHighlight(
                            name=jp_player["name_jp"],
                            team_id=f"{code}-{team['id']}",
                            is_japanese=True,
                            # 無料枠では出場の有無(スタメンかどうか)は分からないため
                            # 「所属チームの試合」であることのみを理由にする
                            stat_context="所属チームの試合",
                        )
                    )

            games.append(
                Game(
                    game_id=str(m["id"]),
                    league=league_name,
                    home_team_id=f"{code}-{home['id']}",
                    away_team_id=f"{code}-{away['id']}",
                    home_team_name=home["name"],
                    away_team_name=away["name"],
                    players=players,
                )
            )

    return games, standings


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    import datetime
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mock",
        action="store_true",
        help="モックデータでロジック部分だけ確認する(ネットワーク不要)",
    )
    parser.add_argument(
        "--source",
        choices=["mlb", "soccer", "all"],
        default="all",
        help="実データ取得時のデータソース(--mock指定時は無視される)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="対象日(YYYY-MM-DD)。省略時は実行日(UTC)",
    )
    parser.add_argument(
        "--out",
        default="notable_games.json",
        help="出力先JSONファイルパス",
    )
    args = parser.parse_args()

    if args.mock:
        games, standings = load_mock_data()
    else:
        date_str = args.date or datetime.date.today().isoformat()
        games, standings = [], {}

        if args.source in ("mlb", "all"):
            try:
                g, s = fetch_mlb_games_and_standings(date_str)
                games.extend(g)
                standings.update(s)
            except Exception as e:
                if args.source == "mlb":
                    raise
                print(f"[warn] MLBデータ取得に失敗、スキップします: {e}")

        if args.source in ("soccer", "all"):
            api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
            if not api_key:
                if args.source == "soccer":
                    raise SystemExit(
                        "FOOTBALL_DATA_API_KEY が設定されていません"
                        "(football-data.org で無料登録して取得してください)"
                    )
                print(
                    "[warn] FOOTBALL_DATA_API_KEY 未設定のため、サッカーの"
                    "データ取得をスキップします(MLBのみで続行)"
                )
            else:
                try:
                    g, s = fetch_soccer_games_and_standings(date_str, api_key)
                    games.extend(g)
                    standings.update(s)
                except Exception as e:
                    if args.source == "soccer":
                        raise
                    print(f"[warn] サッカーデータ取得に失敗、スキップします: {e}")

        if not games:
            print("[warn] 取得できた試合が0件でした。notable_games.jsonは空で出力します。")

    result = build_output(games, standings)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
