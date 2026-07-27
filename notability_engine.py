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
    wins: int = 0
    losses: int = 0


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
    start_time_utc: Optional[str] = None  # ISO8601 (例: '2026-07-21T00:10:00Z')


@dataclass
class Reason:
    tag: str
    text: str
    weight: int
    visible: bool = True  # Falseならスコアには使うが、ユーザーには表示しない


# ---------------------------------------------------------------------------
# 注目理由の判定ルール
# ---------------------------------------------------------------------------
# 判定ルールはここに集約する。新しい注目軸を足したい場合はこの関数群に追加していく。

def rule_japanese_player(game: Game, jp_team_map: dict) -> list[Reason]:
    reasons = []
    covered_team_ids = set()

    # 今日の先発予定として確認できた場合は高めの重み
    for p in game.players:
        if p.is_japanese:
            reasons.append(
                Reason(
                    tag="JP",
                    text=f"{p.name}が{p.stat_context}の中での出場",
                    weight=3,
                )
            )
            covered_team_ids.add(p.team_id)

    # 先発確認は取れなくても、チームに日本人選手が所属していること自体を理由にする
    # (野手や登板日でない投手も対象にするため)。jp_team_mapはMLB Stats APIから
    # 毎回動的に解決した「今シーズン実際に所属している」選手のみを含むので、
    # 戦力外・移籍済みの選手が誤って残り続けることはない
    for team_id, team_name in (
        (game.home_team_id, game.home_team_name),
        (game.away_team_id, game.away_team_name),
    ):
        if team_id in jp_team_map and team_id not in covered_team_ids:
            names_str = "・".join(jp_team_map[team_id])
            reasons.append(
                Reason(
                    tag="jp_team",
                    text=f"{team_name}には{names_str}が所属",
                    weight=2,
                )
            )
            covered_team_ids.add(team_id)

    return reasons


def rule_marquee_team(game: Game) -> list[Reason]:
    """
    全米的に人気・注目度が高いとされる伝統的な球団が出場する場合に加点する。
    ただし「全米的に人気」というテキスト自体は情報として薄いというフィードバックを
    踏まえ、ユーザーには表示せず、注目試合の並び順(スコア)にだけ影響させる。
    """
    reasons = []
    for team_id, team_name in (
        (game.home_team_id, game.home_team_name),
        (game.away_team_id, game.away_team_name),
    ):
        if team_id in MLB_MARQUEE_TEAM_IDS:
            reasons.append(
                Reason(
                    tag="marquee",
                    text=f"{team_name}は全米的に注目度の高い人気球団",
                    weight=1,
                    visible=False,
                )
            )
    return reasons


def rule_rivalry(game: Game) -> list[Reason]:
    """伝統的なライバルカード・同都市対決に加点する"""
    pair = frozenset({game.home_team_id, game.away_team_id})
    rivalry_type = MLB_RIVALRIES.get(pair)
    if rivalry_type == "historic":
        text = f"{game.home_team_name} vs {game.away_team_name} は伝統の好カード"
    elif rivalry_type == "city":
        text = f"{game.home_team_name} vs {game.away_team_name} は同都市対決"
    else:
        return []
    return [Reason(tag="rivalry", text=text, weight=2)]


def rule_division_race(game: Game, standings: dict) -> list[Reason]:
    reasons = []
    home = standings.get(game.home_team_id)
    away = standings.get(game.away_team_id)
    home_div = MLB_DIVISIONS.get(game.home_team_id)
    away_div = MLB_DIVISIONS.get(game.away_team_id)
    # 「首位攻防戦」は同一地区内の順位争いを指す表現。ここでの
    # home_div == away_div チェックが無いと、たまたま両チームとも
    # (別々の地区で)首位と僅差、というだけで「首位攻防戦」という、
    # あたかも同じ地区で直接争っているかのような誤解を招く文章が
    # 生成されてしまう(実際に発生していたバグ)。
    if home and away and home_div and away_div and home_div == away_div:
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


def load_manual_notes(date_str: str, path: str = "manual_notes.json") -> list:
    """
    manual_notes.json から、指定日付分の手動追加情報を読み込む。

    このファイルは「APIやAIでは自動的に集められない情報」(例: 放送予定の
    確定情報、直前の怪我・移籍の一報など)を、コードを書かずにJSONへ直接
    書き足すだけで注目理由に反映させるための仕組み。

    ファイルが存在しない/該当日付の記載が無い場合は、空リストを返して
    通常通り(自動データのみ)で動作する。つまりこの機能は「無くても動く・
    あれば上乗せされる」という前提で設計している。

    フォーマット例:
      {
        "2026-07-27": [
          {"teams": ["ホワイトソックス", "アストロズ"], "text": "地上波でも中継決定", "weight": 2}
        ]
      }
    "teams" は、その試合のhome_team_name/away_team_nameに一致させる
    (両方の名前が含まれる試合にだけ適用される)。
    """
    import pathlib

    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            all_notes = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] manual_notes.jsonの読み込みに失敗、スキップします: {e}")
        return []
    return all_notes.get(date_str, [])


def apply_manual_notes(games: list, notes: list) -> dict:
    """
    manual_notesの内容を、該当する試合のgame_idごとの追加Reasonリストに変換する。
    戻り値: {game_id: [Reason, ...]}
    """
    extra: dict = {}
    for note in notes:
        team_names = note.get("teams", [])
        text = note.get("text")
        if not team_names or not text:
            print(f"[warn] manual_notesの記載が不正なためスキップします: {note}")
            continue
        weight = note.get("weight", 2)
        visible = note.get("visible", True)
        matched = False
        for g in games:
            game_team_names = {g.home_team_name, g.away_team_name}
            if all(name in game_team_names for name in team_names):
                extra.setdefault(g.game_id, []).append(
                    Reason(tag="manual", text=text, weight=weight, visible=visible)
                )
                matched = True
        if not matched:
            print(
                f"[warn] manual_notesのteams={team_names}に一致する試合が"
                "見つかりませんでした(チーム名の表記揺れの可能性)"
            )
    return extra


def rule_quality_matchup(game: Game, standings: dict) -> list[Reason]:
    """
    同地区でなくても、両チームがそれぞれ自分の地区で1位か2位に位置している
    場合に加点する(=インターリーグ等では貴重な、強豪同士の対戦)。
    「ゲーム差が僅か」ではなく「実際の順位そのもの」で判定する。理由は、
    ゲーム差だと地区のレベル差(激戦区か否か)に左右されて基準が曖昧になるが、
    順位そのものなら「1位or2位」という基準が明確で分かりやすいため。

    rule_division_raceとの違い: あちらは「同じ地区で直接争っている」ことが
    前提の表現(首位攻防戦)。こちらは地区が違っても成立する、あくまで
    「両チームとも自分の地区の上位」という事実だけを述べる表現にして、
    同地区で争っているかのような誤解を生まないようにしている。
    """
    reasons = []
    home = standings.get(game.home_team_id)
    away = standings.get(game.away_team_id)
    home_div = MLB_DIVISIONS.get(game.home_team_id)
    away_div = MLB_DIVISIONS.get(game.away_team_id)
    if not (home and away and home_div and away_div):
        return reasons
    if home_div == away_div:
        return reasons  # 同地区はrule_division_race側の担当

    if home.division_rank in (1, 2) and away.division_rank in (1, 2):
        reasons.append(
            Reason(
                tag="quality",
                text=(
                    f"{game.home_team_name}は自地区{home.division_rank}位、"
                    f"{game.away_team_name}は自地区{away.division_rank}位"
                    "同士の好カード"
                ),
                weight=2,
            )
        )
    return reasons


STANDINGS_RULES = [rule_division_race, rule_quality_matchup, rule_win_streak]
GAME_ONLY_RULES = [rule_marquee_team, rule_rivalry]  # jp_team_mapもstandingsも不要なルール


def generate_reasons(game: Game, standings: dict, jp_team_map: dict) -> list[Reason]:
    reasons: list[Reason] = []
    reasons.extend(rule_japanese_player(game, jp_team_map))
    for rule in GAME_ONLY_RULES:
        reasons.extend(rule(game))
    for rule in STANDINGS_RULES:
        reasons.extend(rule(game, standings))
    return reasons


def score_game(reasons: list[Reason]) -> int:
    """全理由(非表示分も含む)の合計。ソートのタイブレークに使う"""
    return sum(r.weight for r in reasons)


def visible_score_game(reasons: list[Reason]) -> int:
    """ユーザーに見える理由だけの合計。注目試合(is_notable)の判定に使う"""
    return sum(r.weight for r in reasons if r.visible)


# ---------------------------------------------------------------------------
# 出力JSON組み立て
# ---------------------------------------------------------------------------

def _to_jst_str(start_time_utc: Optional[str]) -> Optional[str]:
    """'2026-07-21T00:10:00Z' のようなUTC文字列をJST(UTC+9)の'HH:MM'に変換する"""
    if not start_time_utc:
        return None
    import datetime as _datetime

    try:
        s = start_time_utc.replace("Z", "+00:00")
        dt_utc = _datetime.datetime.fromisoformat(s)
        dt_jst = dt_utc.astimezone(_datetime.timezone(_datetime.timedelta(hours=9)))
        return dt_jst.strftime("%m/%d %H:%M")
    except (ValueError, TypeError):
        return None


def build_output(
    games: list[Game], standings: dict, jp_team_map: dict, manual_reasons: dict = None
) -> dict:
    manual_reasons = manual_reasons or {}
    output_games = []
    for g in games:
        reasons = generate_reasons(g, standings, jp_team_map)
        reasons.extend(manual_reasons.get(g.game_id, []))
        visible_score = visible_score_game(reasons)
        total_score = score_game(reasons)

        home_abbr = MLB_TEAM_ABBR.get(g.home_team_id)
        away_abbr = MLB_TEAM_ABBR.get(g.away_team_id)
        abbr_matchup = (
            f"{home_abbr} vs {away_abbr}" if home_abbr and away_abbr else None
        )

        home_division = MLB_DIVISIONS.get(g.home_team_id)
        away_division = MLB_DIVISIONS.get(g.away_team_id)
        same_division = bool(
            home_division and away_division and home_division == away_division
        )
        rivalry_type = MLB_RIVALRIES.get(frozenset({g.home_team_id, g.away_team_id}))

        jp_starters = [
            {"name": p.name, "context": p.stat_context}
            for p in g.players
            if p.is_japanese
        ]

        # 「先発かどうかに関わらず、この試合の両チームに所属している日本人選手」の
        # 一覧。ハッシュタグ生成などで、本文テキストを正規表現で解析するような
        # 壊れやすいやり方を避けるために、構造化した形でも持たせておく。
        # 先発予定(jp_starters)を先頭に、それ以外の所属選手を後ろに並べる。
        starter_names = [s["name"] for s in jp_starters]
        jp_players = list(starter_names)
        for team_id in (g.home_team_id, g.away_team_id):
            for name in jp_team_map.get(team_id, []):
                if name not in jp_players:
                    jp_players.append(name)

        output_games.append(
            {
                "game_id": g.game_id,
                "league": g.league,
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "home_team_name": g.home_team_name,
                "away_team_name": g.away_team_name,
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "matchup": f"{g.home_team_name} vs {g.away_team_name}",
                "abbr_matchup": abbr_matchup,
                "start_time_jst": _to_jst_str(g.start_time_utc),
                "home_division": home_division,
                "away_division": away_division,
                "same_division": same_division,
                "rivalry_type": rivalry_type,  # "historic" / "city" / None
                "jp_starters": jp_starters,
                "jp_players": jp_players,
                "score": visible_score,
                "_sort_score": total_score,
                "is_notable": visible_score > 0,
                "reasons": [
                    {"tag": r.tag, "text": r.text, "weight": r.weight}
                    for r in reasons
                    if r.visible
                ],
            }
        )
    # 注目度が高い順、同点なら開始時刻順に並べる
    output_games.sort(
        key=lambda x: (-x["score"], -x["_sort_score"], x["start_time_jst"] or "99/99 99:99")
    )
    for g in output_games:
        del g["_sort_score"]  # 内部のタイブレーク用なので出力には含めない
    import datetime as _datetime
    generated_at = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    return {"generated_at": generated_at, "games": output_games}


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

# 2026年7月時点、Web検索で確認した所属先。移籍が多いので毎シーズン要更新。
# team_id は MLB_TEAM_NAME_JP / MLB_TEAM_ABBR のキーと対応
# 所属チームはハードコードしない(移籍・戦力外が多く、すぐ古くなるため)。
# 実際に青柳晃洋は2025年7月にフィリーズを自由契約になっており、静的な所属情報の
# 限界が実証された。所属チームは resolve_jp_player_teams() でMLB Stats APIから
# 毎回動的に解決する。ここは「誰が対象の日本人選手か」の名前リストのみを持つ。
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
    # 2026/7時点で判明した見落とし分。2026年在籍16名のうち欠けていた6名を追加
    {"name_en": "Masataka Yoshida", "name_jp": "吉田正尚"},
    {"name_en": "Kazuma Okamoto", "name_jp": "岡本和真"},
    {"name_en": "Munetaka Murakami", "name_jp": "村上宗隆"},
    {"name_en": "Shinnosuke Ogasawara", "name_jp": "小笠原慎之介"},
    {"name_en": "Tatsuya Imai", "name_jp": "今井達也"},
    {"name_en": "Lars Nootbaar", "name_jp": "ヌートバー"},
]

# 全米的に注目度・話題性が高いとされる伝統的な人気球団(市場規模・ファン数などが根拠)
MLB_MARQUEE_TEAM_IDS = {"147", "119", "111", "112", "144"}  # ヤンキース/ドジャース/レッドソックス/カブス/ブレーブス

# 伝統の好カード(ライバル関係)。フロズンセット化して両方向マッチできるようにする
MLB_DIVISIONS = {
    # AL East
    "110": "ALE", "111": "ALE", "147": "ALE", "139": "ALE", "141": "ALE",
    # AL Central
    "145": "ALC", "114": "ALC", "116": "ALC", "118": "ALC", "142": "ALC",
    # AL West
    "117": "ALW", "108": "ALW", "133": "ALW", "136": "ALW", "140": "ALW",
    # NL East
    "144": "NLE", "146": "NLE", "121": "NLE", "143": "NLE", "120": "NLE",
    # NL Central
    "112": "NLC", "113": "NLC", "158": "NLC", "134": "NLC", "138": "NLC",
    # NL West
    "109": "NLW", "119": "NLW", "135": "NLW", "137": "NLW", "115": "NLW",
}

# 歴史的なライバル関係("historic")と、同都市・近郊対決("city")を区別して持つ。
# AIへのコンテキストとして渡し、文章に「同地区」「同都市」の文脈を含められるようにする
MLB_RIVALRIES = {
    frozenset({"147", "111"}): "historic",  # ヤンキース vs レッドソックス
    frozenset({"119", "137"}): "historic",  # ドジャース vs ジャイアンツ
    frozenset({"112", "138"}): "historic",  # カブス vs カージナルス
    frozenset({"119", "135"}): "historic",  # ドジャース vs パドレス
    frozenset({"147", "121"}): "city",       # ヤンキース vs メッツ(subway series)
    frozenset({"112", "145"}): "city",       # カブス vs ホワイトソックス(crosstown classic)
    frozenset({"108", "119"}): "city",       # エンゼルス vs ドジャース(freeway series)
}

# 2026年7月時点、Web検索で確認できた範囲のみ記載。追加・更新推奨。
JP_PLAYERS_SOCCER = [
    {"name_en": "Kaoru Mitoma", "name_jp": "三笘薫", "team_en": "Brighton"},
    # 2026年7月時点で退団報道多数(マンU/ニューカッスル/エヴァートン等に興味報道)。
    # 開幕直前(8月中旬)に必ず再確認すること
    {"name_en": "Ao Tanaka", "name_jp": "田中碧", "team_en": "Leeds United"},
    {"name_en": "Daichi Kamada", "name_jp": "鎌田大地", "team_en": "Crystal Palace"},
    {"name_en": "Tatsuhiro Sakamoto", "name_jp": "坂元達裕", "team_en": "Coventry City"},
    {"name_en": "Wataru Endo", "name_jp": "遠藤航", "team_en": "Liverpool"},
]

# 2026年7月時点、Web検索で確認できた範囲。移籍市場が動いている選手がいるため
# 8月中旬(開幕直前)に必ず再確認すること


# MLB Stats API のチームIDは実行結果で確認済みの値と一致(108=エンゼルス等)
MLB_TEAM_NAME_JP = {
    "108": "エンゼルス",
    "109": "ダイヤモンドバックス",
    "110": "オリオールズ",
    "111": "レッドソックス",
    "112": "カブス",
    "113": "レッズ",
    "114": "ガーディアンズ",
    "115": "ロッキーズ",
    "116": "タイガース",
    "117": "アストロズ",
    "118": "ロイヤルズ",
    "119": "ドジャース",
    "120": "ナショナルズ",
    "121": "メッツ",
    "133": "アスレチックス",
    "134": "パイレーツ",
    "135": "パドレス",
    "136": "マリナーズ",
    "137": "ジャイアンツ",
    "138": "カージナルス",
    "139": "レイズ",
    "140": "レンジャーズ",
    "141": "ブルージェイズ",
    "142": "ツインズ",
    "143": "フィリーズ",
    "144": "ブレーブス",
    "145": "ホワイトソックス",
    "146": "マーリンズ",
    "147": "ヤンキース",
    "158": "ブリュワーズ",
}

# YouTube検索用(公式英語名)。翻訳前のAPIレスポンスの名前と揃えてある
MLB_TEAM_NAME_EN = {
    "108": "Los Angeles Angels", "109": "Arizona Diamondbacks",
    "110": "Baltimore Orioles", "111": "Boston Red Sox", "112": "Chicago Cubs",
    "113": "Cincinnati Reds", "114": "Cleveland Guardians", "115": "Colorado Rockies",
    "116": "Detroit Tigers", "117": "Houston Astros", "118": "Kansas City Royals",
    "119": "Los Angeles Dodgers", "120": "Washington Nationals", "121": "New York Mets",
    "133": "Athletics", "134": "Pittsburgh Pirates", "135": "San Diego Padres",
    "136": "Seattle Mariners", "137": "San Francisco Giants", "138": "St. Louis Cardinals",
    "139": "Tampa Bay Rays", "140": "Texas Rangers", "141": "Toronto Blue Jays",
    "142": "Minnesota Twins", "143": "Philadelphia Phillies", "144": "Atlanta Braves",
    "145": "Chicago White Sox", "146": "Miami Marlins", "147": "New York Yankees",
    "158": "Milwaukee Brewers",
}

# 短縮表記(通知の文字数節約・略称に慣れてもらう目的で使用)
MLB_TEAM_ABBR = {
    "108": "LAA", "109": "ARI", "110": "BAL", "111": "BOS", "112": "CHC",
    "113": "CIN", "114": "CLE", "115": "COL", "116": "DET", "117": "HOU",
    "118": "KC", "119": "LAD", "120": "WSH", "121": "NYM", "133": "ATH",
    "134": "PIT", "135": "SD", "136": "SEA", "137": "SF", "138": "STL",
    "139": "TB", "140": "TEX", "141": "TOR", "142": "MIN", "143": "PHI",
    "144": "ATL", "145": "CWS", "146": "MIA", "147": "NYY", "158": "MIL",
}


# ---------------------------------------------------------------------------
# 実データ取得: MLB Stats API
# ---------------------------------------------------------------------------
# エンドポイントはMLB非公式(無料・キー不要だが公式ドキュメントは存在しない)。
# Web検索で実在・広く使われていることは確認済みだが、この環境はネットワーク
# 無効のため実際のレスポンスは未検証。フィールド名などは変わる可能性がある。

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def resolve_jp_player_teams(date_str: str) -> dict:
    """
    日本人選手の「現在の所属チーム」をMLB Stats APIから動的に解決する。
    戻り値: team_id -> [name_jp, ...] のdict

    見つからなかった選手(戦力外・引退・マイナー降格などでシーズンの選手名鑑に
    載っていない)は単純に対象から外れる。誤って古い所属を表示し続けるより、
    何も表示しない方が安全という判断。
    """
    if requests is None:
        return {}

    season = date_str[:4]
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/sports/1/players", params={"season": season}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[warn] 日本人選手の所属解決に失敗、この日はJP所属チーム加点をスキップします: {e}")
        return {}

    name_to_team_id: dict[str, str] = {}
    for player in data.get("people", []):
        full_name = player.get("fullName")
        current_team = player.get("currentTeam") or {}
        team_id = current_team.get("id")
        if full_name and team_id:
            name_to_team_id[full_name] = str(team_id)

    jp_team_map: dict[str, list] = {}
    for jp in JP_PLAYERS_MLB:
        team_id = name_to_team_id.get(jp["name_en"])
        if team_id:
            jp_team_map.setdefault(team_id, []).append(jp["name_jp"])

    return jp_team_map


def fetch_series_context(home_team_id: str, away_team_id: str, date_str: str) -> dict | None:
    """
    同じ2チームの直近の対戦成績・シリーズ内の位置づけを取得する。
    MLB Stats APIのスケジュールに含まれる seriesGameNumber/gamesInSeries を使う。
    この項目が無い/取得失敗の場合はNoneを返し、呼び出し側は無視すればよい設計。
    """
    if requests is None:
        return None

    import datetime as _datetime

    try:
        end = _datetime.date.fromisoformat(date_str)
        start = end - _datetime.timedelta(days=5)
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={
                "sportId": 1,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "teamId": home_team_id,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        past_results = []  # (date, home_wins: bool)
        series_game_number = None
        games_in_series = None

        for date_entry in data.get("dates", []):
            for g in date_entry.get("games", []):
                home_id = str(g["teams"]["home"]["team"]["id"])
                away_id = str(g["teams"]["away"]["team"]["id"])
                pair = {home_id, away_id}
                if pair != {home_team_id, away_team_id}:
                    continue

                if g.get("gameDate", "").startswith(date_str):
                    series_game_number = g.get("seriesGameNumber")
                    games_in_series = g.get("gamesInSeries")

                if g.get("status", {}).get("abstractGameCode") == "F":
                    home_score = g["teams"]["home"].get("score")
                    away_score = g["teams"]["away"].get("score")
                    if home_score is None or away_score is None:
                        continue
                    this_game_home_won = home_score > away_score
                    # この関数の呼び出し元から見た home_team_id が勝ったかどうかに正規化
                    normalized_home_won = (
                        this_game_home_won if home_id == home_team_id else not this_game_home_won
                    )
                    past_results.append(normalized_home_won)

        if not past_results and series_game_number is None:
            return None

        return {
            "series_game_number": series_game_number,
            "games_in_series": games_in_series,
            "home_wins_in_stretch": sum(1 for r in past_results if r),
            "away_wins_in_stretch": sum(1 for r in past_results if not r),
        }
    except Exception as e:
        print(f"[warn] シリーズ文脈の取得に失敗、この試合はスキップします: {e}")
        return None


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
                wins=int(team_record.get("wins", 0)),
                losses=int(team_record.get("losses", 0)),
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
                    home_team_name=MLB_TEAM_NAME_JP.get(str(home["id"]), home["name"]),
                    away_team_name=MLB_TEAM_NAME_JP.get(str(away["id"]), away["name"]),
                    players=players,
                    start_time_utc=g.get("gameDate"),
                )
            )

    return games, standings, resolve_jp_player_teams(date_str)


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
                    start_time_utc=m.get("utcDate"),
                )
            )

    return games, standings


# ---------------------------------------------------------------------------
# AIによる注目理由の要約(任意機能)
# ---------------------------------------------------------------------------
# コスト暴走を防ぐための設計上の制約:
#   - 1日1回の実行につき、最大1試合分・1回のAPI呼び出しのみ(ループでの複数回
#     呼び出しはしない)
#   - max_tokensを150に固定(暴走した場合の被害を最小化)
#   - 失敗時にリトライはしない(1回失敗したらルールベースの理由文にフォールバック)
#   - 最も安価なHaiku 4.5を使用
# この関数は ANTHROPIC_API_KEY が設定されている場合のみ main() から呼ばれる。

def _team_context_line(team_id: str, team_name: str, standings: dict) -> str:
    """AIに渡すための、1チーム分の順位表コンテキストを組み立てる"""
    s = standings.get(team_id)
    if not s:
        return f"{team_name}: 順位表データなし"
    record = f"{s.wins}勝{s.losses}敗" if (s.wins or s.losses) else "戦績データなし"
    streak = f"{abs(s.win_streak)}連勝中" if s.win_streak > 0 else (
        f"{abs(s.win_streak)}連敗中" if s.win_streak < 0 else "連勝連敗なし"
    )
    return (
        f"{team_name}: {record}、地区{s.division_rank}位"
        f"(首位との差{s.games_back}ゲーム)、{streak}"
    )


def _build_ai_prompt(game: dict, standings: dict) -> str:
    home_context = _team_context_line(
        game["home_team_id"], game["home_team_name"], standings
    )
    away_context = _team_context_line(
        game["away_team_id"], game["away_team_name"], standings
    )

    structural_notes = []
    home_div = MLB_DIVISIONS.get(game["home_team_id"])
    away_div = MLB_DIVISIONS.get(game["away_team_id"])
    if home_div and away_div and home_div == away_div:
        structural_notes.append("同地区対決である")
    pair = frozenset({game["home_team_id"], game["away_team_id"]})
    rivalry_type = MLB_RIVALRIES.get(pair)
    if rivalry_type == "historic":
        structural_notes.append("歴史的に有名なライバルカードである")
    elif rivalry_type == "city":
        structural_notes.append("同都市・近郊に本拠地を置くチーム同士の対決である")

    series_context = game.get("series_context")
    if series_context:
        sgn = series_context.get("series_game_number")
        gis = series_context.get("games_in_series")
        if sgn and gis:
            structural_notes.append(f"今シリーズの第{sgn}戦(全{gis}戦)である")
        home_w = series_context.get("home_wins_in_stretch", 0)
        away_w = series_context.get("away_wins_in_stretch", 0)
        if home_w or away_w:
            structural_notes.append(
                f"直近の対戦成績は{game['home_team_name']}{home_w}勝"
                f"{game['away_team_name']}{away_w}勝である"
            )

    structural_text = "\n".join(f"- {n}" for n in structural_notes) or "- 特記事項なし"

    reasons_text = "\n".join(f"- {r['text']}" for r in game.get("reasons", []))

    highlight_line = ""
    if game.get("highlight_title"):
        highlight_line = (
            f"\n【MLB公式ハイライト動画のタイトル(参考情報)】\n{game['highlight_title']}\n"
        )

    return (
        f"以下は「{game['matchup']}」({game['league']})という試合についてのデータです。\n\n"
        f"【チームの状況】\n{home_context}\n{away_context}\n\n"
        f"【構造的な位置づけ】\n{structural_text}\n\n"
        f"【この試合が注目された理由(ルールベースで抽出)】\n{reasons_text}\n"
        f"{highlight_line}\n"
        "あなたはMLB/野球初心者にも分かりやすく解説するスポーツ記者です。"
        "以下の2つを、上記のデータだけを根拠に日本語で書いてください。\n\n"
        "【出力1: 解説文】\n"
        "「シーズン全体・MLB全体で見たときに、この一戦になぜ注目すべきか」を"
        "2〜3文で説明する文章。\n\n"
        "【出力2: 通知用フック文】\n"
        "スマホのプッシュ通知に使う、15〜25文字程度の短い一言。見た人が"
        "「試合を見てみよう」と思うような、具体的な選手名や数字を絡めた"
        "煽り文句にすること。「〜か」「〜なるか」のような体言止め・疑問形は"
        "使ってよい(こちらは解説文と違い、キャッチーな見出し口調でよい)。\n\n"
        "厳守してほしいこと(出力1・出力2共通):\n"
        "- 今シーズンの具体的な数字(順位・ゲーム差・連勝数など)は、必ず上記の"
        "  データに書かれているものだけを使うこと。データに無い今季の数字は"
        "  絶対に書かないこと\n"
        "- ただし、球団の歴史的背景・伝統的なライバル関係の由来など、今季の"
        "  数字を伴わない一般的な知識は、事実として広く知られている範囲でのみ"
        "  補足として使ってよい(不確かな場合は使わないこと)\n"
        "- 「有名選手が揃っている」「注目の一戦だ」のような、データを言い換えた"
        "  だけの薄い文章は禁止。必ず具体的な数字や、上記の構造的な位置づけを"
        "  組み込むこと\n"
        "- 出力1の文体は理路整然とした説明口調にすること。「〜だよ！」「〜だね！」の"
        "  ような話し言葉・感嘆符での締めは禁止。「〜である」「〜になる」のような"
        "  落ち着いた書き言葉で書くこと\n"
        "- 野球初心者にも伝わるよう、専門用語を使う場合は軽く説明を添えること\n"
        "- 見出しや記号(・や「」)は使わず、文章のみを出力すること\n"
        "- MLB公式ハイライト動画のタイトルが提供されている場合、そこから伝わる"
        "  文脈(注目プレーの内容など)は参考にしてよいが、タイトルの文言を"
        "  そのまま引用せず、必ず自分の言葉で言い換えること\n\n"
        "出力形式(厳守): まず出力1の文章のみを書き、次の行に半角記号で"
        "「---HOOK---」とだけ書いた行を挟み、最後に出力2のフック文を1行で"
        "書くこと。それ以外の見出しや前置き・番号は一切付けないこと。"
    )


def _call_ai(prompt: str, api_key: str, max_tokens: int = 320):
    """1回分のAPI呼び出し。戻り値: (text, cost_usd) または (None, 0)"""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,  # 暴走時の被害を抑えるための上限
            messages=[{"role": "user", "content": prompt}],
        )
        ai_text = "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()
        usage = message.usage
        # Haiku 4.5の料金: 入力$1/出力$5 per 1M tokens (2026年7月時点)
        cost_usd = (usage.input_tokens / 1_000_000 * 1) + (
            usage.output_tokens / 1_000_000 * 5
        )
        return ai_text, cost_usd, usage.input_tokens, usage.output_tokens
    except Exception as e:
        print(f"[warn] AI呼び出しに失敗、この試合はルールベースの理由のみ使用します: {e}")
        return None, 0, 0, 0


def fetch_mlb_highlight(
    home_team_id: str, away_team_id: str, date_str: str, api_key: str
):
    """
    MLB公式YouTubeチャンネル(channelTitleが完全一致で"MLB"のもの)から、
    該当試合のハイライト動画を検索する。公式チャンネル以外の結果は除外する。
    戻り値: (title, video_id) または (None, None)
    """
    if requests is None:
        return None, None

    home_en = MLB_TEAM_NAME_EN.get(home_team_id)
    away_en = MLB_TEAM_NAME_EN.get(away_team_id)
    if not home_en or not away_en:
        return None, None

    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": api_key,
                "part": "snippet",  # これが無いとレスポンスにsnippetが含まれずKeyErrorになる
                "q": f"{away_en} {home_en} Highlights",
                "type": "video",
                "order": "date",
                "maxResults": 5,
                "publishedAfter": f"{date_str}T00:00:00Z",
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        for item in items:
            snippet = item.get("snippet") or {}
            video_id = item.get("id", {}).get("videoId")
            if snippet.get("channelTitle") == "MLB" and video_id:
                return snippet.get("title"), video_id
    except Exception as e:
        print(f"[warn] MLBハイライト動画の検索に失敗: {e}")

    return None, None


def enhance_games_with_ai(
    output: dict, standings: dict, api_key: str, count: int = 3
) -> None:
    """上位N試合(注目試合のみ、理由が空でないもの)にAI要約を追加する"""
    games = output.get("games", [])
    targets = [
        g for g in games if g.get("is_notable") and g.get("reasons")
    ][:count]

    total_cost = 0.0
    for game in targets:
        prompt = _build_ai_prompt(game, standings)
        ai_text, cost_usd, in_tok, out_tok = _call_ai(prompt, api_key)
        if ai_text:
            # "---HOOK---" を境に、解説文(ai_summary)と通知用フック文
            # (notification_hook)に分割する。AIが区切りを守らなかった場合は
            # 全文をai_summaryとして扱い、フック文は無し(送信側でルール
            # ベースにフォールバックする)扱いにする。
            if "---HOOK---" in ai_text:
                summary_part, _, hook_part = ai_text.partition("---HOOK---")
                game["ai_summary"] = summary_part.strip()
                hook_clean = hook_part.strip().strip("「」")
                if hook_clean:
                    game["notification_hook"] = hook_clean
            else:
                game["ai_summary"] = ai_text.strip()
            total_cost += cost_usd
            print(
                f"[info] AI要約生成: {game['matchup']} "
                f"(入力{in_tok}トークン/出力{out_tok}トークン、概算${cost_usd:.5f})"
            )

    if targets:
        print(f"[info] 今回のAI要約合計コスト: 概算${total_cost:.5f}")


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
        jp_team_map = {}
    else:
        date_str = args.date or datetime.date.today().isoformat()
        games, standings, jp_team_map = [], {}, {}

        if args.source in ("mlb", "all"):
            try:
                g, s, jtm = fetch_mlb_games_and_standings(date_str)
                games.extend(g)
                standings.update(s)
                jp_team_map.update(jtm)
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

    manual_reasons = {}
    if not args.mock:
        manual_notes = load_manual_notes(date_str)
        if manual_notes:
            manual_reasons = apply_manual_notes(games, manual_notes)
            print(f"[info] manual_notes.jsonから{len(manual_notes)}件の手動情報を反映しました")

    result = build_output(games, standings, jp_team_map, manual_reasons)

    # シリーズ文脈(前の試合結果・第何戦か)を取得
    if not args.mock:
        for game in [g for g in result["games"] if g.get("is_notable")][:3]:
            if game["league"] != "MLB":
                continue
            series_context = fetch_series_context(
                game["home_team_id"], game["away_team_id"], date_str
            )
            if series_context:
                game["series_context"] = series_context
                print(f"[info] シリーズ文脈を取得: {game['matchup']} -> {series_context}")

    # MLB公式ハイライト動画のタイトルを取得(AIのコンテキスト強化・埋め込み表示用)
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")
    if youtube_api_key and not args.mock:
        for game in [g for g in result["games"] if g.get("is_notable")][:3]:
            if game["league"] != "MLB":
                continue
            title, video_id = fetch_mlb_highlight(
                game["home_team_id"], game["away_team_id"], date_str, youtube_api_key
            )
            if title:
                game["highlight_title"] = title
                game["highlight_video_id"] = video_id
                print(f"[info] ハイライト動画を発見: {title}")

    ai_key = os.environ.get("ANTHROPIC_API_KEY")
    if ai_key:
        enhance_games_with_ai(result, standings, ai_key, count=3)

    # 明日のMLB注目候補プレビュー(失敗しても本体の結果には影響させない)
    if not args.mock and args.source in ("mlb", "all"):
        try:
            tomorrow_str = (
                datetime.date.fromisoformat(date_str) + datetime.timedelta(days=1)
            ).isoformat()
            t_games, t_standings, t_jp_map = fetch_mlb_games_and_standings(tomorrow_str)
            t_result = build_output(t_games, t_standings, t_jp_map)
            t_top = t_result["games"][0] if t_result["games"] else None
            if t_top and t_top["is_notable"] and t_top["reasons"]:
                result["tomorrow_preview"] = {
                    "matchup": t_top["matchup"],
                    "start_time_jst": t_top["start_time_jst"],
                    "reason_text": t_top["reasons"][0]["text"],
                }
                print(f"[info] 明日のプレビュー生成: {t_top['matchup']}")
        except Exception as e:
            print(f"[warn] 明日のプレビュー生成に失敗、スキップします: {e}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 日次アーカイブ(評価用・将来的な自前データソース化のため蓄積する)
    if not args.mock:
        import pathlib

        archive_dir = pathlib.Path("archive")
        archive_dir.mkdir(exist_ok=True)
        archive_path = archive_dir / f"{date_str}.json"
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[info] アーカイブに保存しました: {archive_path}")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
