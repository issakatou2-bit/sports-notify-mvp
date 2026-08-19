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
import pathlib
import argparse
import time
import unicodedata
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
    # 直近10試合の成績(例: "7-3")。連勝連敗より実際の勢いを表しやすい。
    # 取得できなかった場合はNone。
    last_ten: Optional[str] = None
    # 首位との勝ち点差。サッカーでのみ入る。
    # games_back には互換のため3で割った値を入れているが、
    # 「ゲーム差」は野球の概念で、サッカーの画面にそのまま出すと嘘になる。
    points_back: Optional[float] = None
    # 消化試合数。順位表を語ってよいかの判断に使う。
    # 開幕直後は全チームが勝ち点0で並び、APIは得失点差などの
    # タイブレークで順位を付けて返す。それを実力の順位として読むと
    # 「ラシン・サンタンデールが3位、ビジャレアルが3位の上位対決」
    # 「首位争い、勝ち点差は0」のような、事実でない文が出る(実際に出た)。
    played: Optional[int] = None


@dataclass
class ProbablePitcher:
    """先発予定投手。今季成績はAI要約対象の試合についてのみ後から取得する。"""
    player_id: str
    name_en: str
    name_jp: Optional[str] = None
    era: Optional[str] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    strikeouts: Optional[int] = None


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
    home_probable: Optional[ProbablePitcher] = None
    away_probable: Optional[ProbablePitcher] = None
    venue_name: Optional[str] = None  # MLB Stats APIが返す英語の球場名


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
    # 戦力外・移籍済みの選手が誤って残り続けることはない。
    #
    # 重みは所属人数に応じて変える。以前は何人いても一律+2だったため、
    # 大谷・山本・佐々木の3人が所属するドジャースと、1人だけの球団が
    # 同点になってしまい、日本の視聴者にとって明らかに注目度が違う試合を
    # 正しく順位付けできていなかった(実データで確認済み)。
    # 人数はAPIから取得した客観的な事実なので、球団の人気を主観で
    # ランク付けするより、根拠が明確で自動追従もする。
    for team_id, team_name in (
        (game.home_team_id, game.home_team_name),
        (game.away_team_id, game.away_team_name),
    ):
        if team_id in jp_team_map and team_id not in covered_team_ids:
            names = jp_team_map[team_id]
            names_str = "・".join(names)
            reasons.append(
                Reason(
                    tag="jp_team",
                    text=f"{team_name}には{names_str}が所属",
                    weight=jp_roster_weight(len(names)),
                )
            )
            covered_team_ids.add(team_id)

    return reasons


def jp_roster_weight(count: int) -> int:
    """
    チームに所属する日本人選手の人数から、注目理由の重みを求める。
    1人=2, 2人=3, 3人以上=4。人数が増えるほど「その試合を見る理由」が
    増えるのは確かだが、比例させると1球団だけで他の全要素を押し流して
    しまうため、頭打ちにしている。
    """
    if count <= 1:
        return 2
    if count == 2:
        return 3
    return 4


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


def lookup_venue(venue_en: str):
    """
    球場名から登録済みの情報を引く。

    完全一致で見つからない場合は部分一致でも探す。命名権によって
    APIが返す名前が変わることがあり、実際に MLB Stats API は
    ドジャー・スタジアムを "UNIQLO Field at Dodger Stadium" として
    返していた。そのため、これまでドジャースの本拠地では球場の説明が
    一切出ていなかった(ドジャースは日本人選手が多く、最も頻繁に
    取り上げる球場の一つなので影響が大きい)。
    """
    if not venue_en:
        return None
    if venue_en in MLB_VENUE_NOTES:
        return MLB_VENUE_NOTES[venue_en]
    for key, value in MLB_VENUE_NOTES.items():
        if key in venue_en or venue_en in key:
            return value
    return None


_VENUE_STATS_CACHE = None


def _venue_runs_note(venue_en: str):
    """
    その球場で実際に何点入っているか。scripts/venue_stats.py の集計を読む。

    「打者有利とされる」という言い伝えだけでなく、実際の数字まで書けるようにする。
    集計を取ってみると、言われていることと実測が食い違う球場が実際にあった
    (フェンウェイ・パークは打者天国のイメージだが30球場中25位)。

    ファイルが無ければ None を返し、従来どおり特徴の説明だけになる。
    """
    global _VENUE_STATS_CACHE
    if not venue_en:
        return None
    if _VENUE_STATS_CACHE is None:
        import pathlib

        p = pathlib.Path("data/venue_stats.json")
        try:
            _VENUE_STATS_CACHE = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            _VENUE_STATS_CACHE = {}

    venues = _VENUE_STATS_CACHE.get("venues") or {}
    v = venues.get(venue_en)
    if not v:
        # 命名権による表記ゆれを吸収する(lookup_venue と同じ考え方)
        for key, value in venues.items():
            if key in venue_en or venue_en in key:
                v = value
                break
    if not v:
        return None
    season = _VENUE_STATS_CACHE.get("season", "")
    return (f"この球場の{season}年シーズンの1試合平均得点は"
            f"{v['avg_runs']}点で、MLB{v['total']}球場中{v['rank']}位")


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
    # 「なぜ因縁のカードなのか」まで書く。種別だけでは、初めて見る人に
    # 何が特別なのかが伝わらない。
    note = MLB_RIVALRY_NOTES.get(pair)
    if note:
        text = f"{text} — {note}"
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


# --- サッカー用のルール -----------------------------------------------------
#
# MLB用のルールはどれもチームIDでMLBの地区表や名簿を引くため、サッカーの
# 試合では1つも発火しない。実際、開幕節を模した試合を通したところ両方とも
# 0点・注目試合ゼロになり、そのままなら8/21に動画が1本も出なかった。
#
# 材料が違うので、判定もサッカーの材料で書く。
#   日本人選手 … クラブ名で名簿を引く(MLBのようなIDの対応表が無いため)
#   順位       … 勝ち点表。ゲーム差ではなく勝ち点差で語る
#   ビッグクラブ … 日本での知名度が高く、中継も立つクラブ

# 日本で名前が通っていて、試合単体で見られるクラブ。
# MLB_MARQUEE_TEAM_IDS と同じ役割。クラブ名の正規化キーで持つ。
# 今季の順位表を語ってよくなる消化試合数。
# 5節あれば勝ち点が10前後まで開き、順位が並び順ではなく実態になる。
SOCCER_TABLE_MIN_MATCHES = 5

SOCCER_MARQUEE_CLUBS = {
    "fcbarcelona", "realmadrid", "manchesterunited", "manchestercity",
    "liverpool", "arsenal", "chelsea", "tottenham", "juventus",
    "acmilan", "internazionale", "bayernmunchen", "borussiadortmund",
    "parissaintgermain", "atleticomadrid",
}

# 同じ都市・地域の対戦。背景があると1試合の重みが変わる。
SOCCER_DERBIES = [
    ({"manchesterunited", "manchestercity"}, "マンチェスター・ダービー"),
    ({"liverpool", "everton"}, "マージーサイド・ダービー"),
    ({"arsenal", "tottenham"}, "ノース・ロンドン・ダービー"),
    ({"fcbarcelona", "realmadrid"}, "エル・クラシコ"),
    ({"acmilan", "internazionale"}, "ミラノ・ダービー"),
    ({"juventus", "internazionale"}, "イタリア・ダービー"),
    ({"borussiadortmund", "fcschalke04"}, "レヴィアダービー"),
    ({"bayernmunchen", "borussiadortmund"}, "デア・クラシカー"),
]


# 競技会の見分けに使う値。コードと日本語名の両方を入れる。
#
# 取得側は Game.league に日本語のリーグ名("ラ・リーガ")を入れるが、
# SOCCER_COMPETITIONS のキーはコード("PD")。コードだけで見ていたため、
# サッカー用のルールが本番で1つも発火していなかった。
# テストがコードを渡していたので、テストは通っていた。
# SOCCER_COMPETITIONS はこの下で定義されるので、初回に組み立てる。
_SOCCER_LEAGUE_KEYS = None


def is_soccer_league(league) -> bool:
    """リーグ名またはコードが、対象のサッカー競技会かどうか。"""
    global _SOCCER_LEAGUE_KEYS
    if _SOCCER_LEAGUE_KEYS is None:
        _SOCCER_LEAGUE_KEYS = (set(SOCCER_COMPETITIONS)
                               | set(SOCCER_COMPETITIONS.values()))
    return bool(league) and league in _SOCCER_LEAGUE_KEYS


def is_soccer(game: Game) -> bool:
    return is_soccer_league(game.league)


def _club_key(name: str, keys) -> str:
    """
    クラブ名に含まれる識別子を返す。無ければ空。

    APIは "FC Internazionale Milano" のような正式名称を返すので、
    完全一致では引けない。名簿と同じ部分一致にする。
    長いキーから見るのは "barcelona" が "RCD Espanyol de Barcelona" に
    当たるような取り違えを避けるため。
    """
    norm = normalize_club(name)
    if not norm:
        return ""
    for key in sorted(keys, key=len, reverse=True):
        if key in norm:
            return key
    return ""


def rule_soccer_japanese_player(game: Game) -> list[Reason]:
    """
    クラブ名から日本人選手を引く。

    MLBはチームIDで名簿を引けるが、サッカーはIDの対応表が無い。
    クラブ名の表記揺れは normalize_club が吸収する。
    """
    reasons = []
    for name in (game.home_team_name, game.away_team_name):
        # 名簿の league はコード。日本語名で来た場合は絞り込みを外す
        # (絞ると1件も一致しなくなる)。
        code = game.league if game.league in SOCCER_COMPETITIONS else None
        players = jp_players_for_club(name, code)
        if not players:
            continue
        names = "・".join(p["name_jp"] for p in players)
        reasons.append(Reason(
            tag="jp_team",
            text=f"{club_name_jp(name)}には{names}が所属",
            weight=jp_roster_weight(len(players)),
        ))
    return reasons


def rule_soccer_marquee(game: Game) -> list[Reason]:
    clubs = []
    for name in (game.home_team_name, game.away_team_name):
        if _club_key(name, SOCCER_MARQUEE_CLUBS):
            clubs.append(club_name_jp(name))
    if not clubs:
        return []
    if len(clubs) == 2:
        return [Reason(tag="quality",
                       text=f"{clubs[0]} と {clubs[1]} の対戦",
                       weight=3)]
    return [Reason(tag="quality", text=f"{clubs[0]} の試合", weight=1)]


def rule_soccer_derby(game: Game) -> list[Reason]:
    all_keys = {k for clubs, _ in SOCCER_DERBIES for k in clubs}
    pair = {_club_key(game.home_team_name, all_keys),
            _club_key(game.away_team_name, all_keys)}
    for clubs, label in SOCCER_DERBIES:
        if pair == clubs:
            return [Reason(tag="rivalry", text=f"{label}", weight=3)]
    return []


def rule_soccer_table(game: Game, standings: dict) -> list[Reason]:
    """
    順位表から。ただし順位表が意味を持つようになってからだけ。

    「開幕直後は何も言わない」と書いてありながら、そう書いてあるだけで
    実際には何も見ていなかった。ラ・リーガ開幕節で全チームが勝ち点0のとき、
    APIは得失点差などのタイブレークで順位を返す。それを実力順として読み、
    「ラシン・サンタンデールが3位、ビジャレアルが3位の上位対決」
    「首位争い、勝ち点差は0」という、どちらも事実でない文が出ていた。

    「ゲーム差」は野球の言い方なので使わない。サッカーは勝ち点差で語る。
    """
    home = standings.get(game.home_team_id)
    away = standings.get(game.away_team_id)
    if not (home and away):
        return []

    # 消化が少ないうちの順位は、並び順であって順位ではない。
    # この時期は rule_soccer_last_season(昨季の順位)が受け持つ。
    played = min(home.played or 0, away.played or 0)
    if played < SOCCER_TABLE_MIN_MATCHES:
        return []

    reasons = []
    # 上位対決。順位そのもので判定する(勝ち点差はリーグの拮抗度に左右される)
    if home.division_rank and away.division_rank:
        worst = max(home.division_rank, away.division_rank)
        if worst <= 4:
            reasons.append(Reason(
                tag="quality",
                text=(f"{club_name_jp(game.home_team_name)}が"
                      f"{home.division_rank}位、"
                      f"{club_name_jp(game.away_team_name)}が"
                      f"{away.division_rank}位の上位対決"),
                weight=3))
        elif worst <= 8:
            reasons.append(Reason(
                tag="quality",
                text=(f"{club_name_jp(game.home_team_name)}"
                      f"{home.division_rank}位 と "
                      f"{club_name_jp(game.away_team_name)}"
                      f"{away.division_rank}位"),
                weight=1))

    # 首位争い。points_back が取れている場合だけ、勝ち点差で述べる。
    hb, ab = home.points_back, away.points_back
    if hb is not None and ab is not None and min(hb, ab) <= 3:
        diff = abs(hb - ab)
        if diff <= 3:
            reasons.append(Reason(
                tag="div",
                text=f"首位争い、勝ち点差は{diff:.0f}",
                weight=2))
    return reasons


def _last_season_ranks(path: str = "data/soccer_preview.json") -> dict:
    """
    昨季の最終順位。クラブ名の正規化キーで引けるようにして返す。

    開幕直後は今季の順位表が全チーム横並びで、順位のルールが何も返さない。
    実際、ラ・リーガ開幕日の2試合はどちらも0点になり、動画が作られなかった。
    昨季の順位は soccer_preview.py が既に取っているので、それを使う。
    """
    global _LAST_SEASON_CACHE
    if _LAST_SEASON_CACHE is not None:
        return _LAST_SEASON_CACHE
    ranks: dict = {}
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # 握り潰さない。ここが空だと開幕直後に全試合0点になるが、
        # 静かに0件を返すと「試合が地味だった」のと見分けが付かない。
        print(f"[warn] {path} を読めませんでした: {e}")
        _LAST_SEASON_CACHE = ranks
        return ranks
    for comp in data.get("competitions", []):
        for row in comp.get("last_season", []):
            team, pos = row.get("team"), row.get("position")
            if team and pos:
                ranks[normalize_club(team)] = int(pos)
    _LAST_SEASON_CACHE = ranks
    return ranks


_LAST_SEASON_CACHE = None


def rule_soccer_last_season(game: Game) -> list[Reason]:
    """
    昨季の順位。今季の順位が意味を持つまでの数節を、これで埋める。

    今季の順位が付いている時期には rule_soccer_table の方が実態に近いので、
    こちらは上位同士のときだけ、控えめな重みで足す。
    """
    ranks = _last_season_ranks()
    if not ranks:
        return []
    hr = ranks.get(_club_key(game.home_team_name, ranks) or "")
    ar = ranks.get(_club_key(game.away_team_name, ranks) or "")
    if not (hr and ar):
        return []
    worst = max(hr, ar)
    if worst <= 6:
        # 単独で注目扱いになる重み。MLBの「日本人投手が先発」に相当する。
        # 開幕直後はこれ以外に 材料 が無く、重み2だと閾値3に届かず、
        # 昨季3位と5位の対戦が対象外になっていた。
        return [Reason(tag="quality",
                       text=(f"昨季{hr}位の{club_name_jp(game.home_team_name)}と"
                             f"{ar}位の{club_name_jp(game.away_team_name)}"),
                       weight=3)]
    if worst <= 10:
        return [Reason(tag="quality",
                       text=f"昨季{hr}位と{ar}位の対戦", weight=1)]
    # 中位・下位同士でも、昨季の位置は語れる材料になる。
    # 点は付けない(注目度は上がらない)が、その日にこの試合しか無ければ
    # ナレーションが何も言えなくなるので、文面だけは残す。
    return [Reason(tag="quality",
                   text=f"昨季{hr}位と{ar}位の対戦", weight=0)]


SOCCER_GAME_RULES = [rule_soccer_japanese_player, rule_soccer_marquee,
                     rule_soccer_derby, rule_soccer_last_season]
SOCCER_STANDINGS_RULES = [rule_soccer_table]

STANDINGS_RULES = [rule_division_race, rule_quality_matchup, rule_win_streak]
GAME_ONLY_RULES = [rule_marquee_team, rule_rivalry]  # jp_team_mapもstandingsも不要なルール


def generate_reasons(game: Game, standings: dict, jp_team_map: dict) -> list[Reason]:
    reasons: list[Reason] = []
    # MLBのルールはチームIDでMLBの地区表・名簿を引くので、サッカーでは
    # 1つも発火しない。競技で分ける。
    if is_soccer(game):
        for rule in SOCCER_GAME_RULES:
            reasons.extend(rule(game))
        for rule in SOCCER_STANDINGS_RULES:
            reasons.extend(rule(game, standings))
        return reasons

    reasons.extend(rule_japanese_player(game, jp_team_map))
    for rule in GAME_ONLY_RULES:
        reasons.extend(rule(game))
    for rule in STANDINGS_RULES:
        reasons.extend(rule(game, standings))
    return reasons


# 加点理由を、視聴者に見せるための短いラベルにする。
#
# なぜ見せるのか:
#   コレスポは「なぜこの試合を選んだか」を理由つきで出すことを軸にしている。
#   その選定は実際には点数で決まっているのに、点数自体は今まで内部に隠れていた。
#   何にどれだけ加点したかまで見せれば、選定基準そのものが読み物になる。
#   独自の指標なので、他所には出せない内容でもある。
REASON_TAG_LABELS = {
    "JP": "日本人投手が先発予定",
    "jp_team": "日本人選手が所属",
    "streak": "連勝・連敗中",
    "div": "首位攻防戦",
    "quality": "上位チーム同士",
    "rivalry": "伝統の一戦",
    "venue": "球場の特徴",
    "manual": "編集部メモ",
}


def reason_label(tag: str) -> str:
    return REASON_TAG_LABELS.get(tag or "", "その他の理由")


def score_game(reasons: list[Reason]) -> int:
    """全理由(非表示分も含む)の合計。ソートのタイブレークに使う"""
    return sum(r.weight for r in reasons)


def visible_score_game(reasons: list[Reason]) -> int:
    """ユーザーに見える理由だけの合計。注目試合(is_notable)の判定に使う"""
    return sum(r.weight for r in reasons if r.visible)


# 「注目試合」とみなす最低スコア。同地区対決や連勝のような単発の軽い理由
# (重みweight=2)1つだけでは注目扱いにせず、JP先発(weight=3)クラス1つか、
# 複数の理由が重なった試合だけをハイライトする(以前は0点超えで即注目扱い
# だったため、盤面の半分以上に色が付いてしまい、目印としての意味が薄れて
# いた)。
NOTABLE_SCORE_THRESHOLD = 3

# サッカーで、その日にある試合から最低限残す本数。build_output で使う。
# 試合数がMLBの15に対して0〜10と幅があるため、絶対値の閾値だけでは
# 「開催はあるのに0件」という日が出る。理由は build_output に書いてある。
# 3にしてあるのは日次動画がMLBと同じ3試合構成だから。既に3試合以上が
# 閾値を超えている日は、この下限では何も変わらない。
SOCCER_MIN_NOTABLE = 3


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

        # UI側で「日本人選手が所属している球団に国旗を付ける」ために、
        # チームごとの有無だけを単純な真偽値で持たせる。
        starter_names_set = {s["name"] for s in jp_starters}
        home_has_jp = bool(jp_team_map.get(g.home_team_id)) or any(
            p.name in starter_names_set for p in g.players if p.team_id == g.home_team_id
        )
        away_has_jp = bool(jp_team_map.get(g.away_team_id)) or any(
            p.name in starter_names_set for p in g.players if p.team_id == g.away_team_id
        )

        def _probable_dict(p):
            if not p:
                return None
            return {
                "name": p.name_jp or p.name_en,
                "name_en": p.name_en,
                "player_id": p.player_id,
                "era": p.era,
                "wins": p.wins,
                "losses": p.losses,
                "strikeouts": p.strikeouts,
            }

        # サッカーのAPIは "FC Internazionale Milano" のような正式名称を返す。
        # そのまま出すとタイトルも画面も英語になり、VOICEVOXも読めない。
        # 理由の文面は既に日本語表記なので、ここも揃える。
        if is_soccer(g):
            home_name = club_name_jp(g.home_team_name)
            away_name = club_name_jp(g.away_team_name)
        else:
            home_name = g.home_team_name
            away_name = g.away_team_name

        output_games.append(
            {
                "game_id": g.game_id,
                "league": g.league,
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "home_team_name": home_name,
                "away_team_name": away_name,
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "home_color": MLB_TEAM_COLOR.get(g.home_team_id),
                "away_color": MLB_TEAM_COLOR.get(g.away_team_id),
                "matchup": f"{home_name} vs {away_name}",
                "abbr_matchup": abbr_matchup,
                "start_time_jst": _to_jst_str(g.start_time_utc),
                "home_division": home_division,
                "away_division": away_division,
                "same_division": same_division,
                "rivalry_type": rivalry_type,  # "historic" / "city" / None
                "jp_starters": jp_starters,
                "jp_players": jp_players,
                "home_probable": _probable_dict(g.home_probable),
                "away_probable": _probable_dict(g.away_probable),
                "venue_name": g.venue_name,
                "venue_jp": (lookup_venue(g.venue_name) or (None, None))[0],
                "venue_note": (lookup_venue(g.venue_name) or (None, None))[1],
                # 球場ごとの実測(1試合平均得点)。data/venue_stats.json があれば入る
                "venue_runs_note": _venue_runs_note(g.venue_name),
                "home_has_jp": home_has_jp,
                "away_has_jp": away_has_jp,
                "score": visible_score,
                "_sort_score": total_score,
                "is_notable": visible_score >= NOTABLE_SCORE_THRESHOLD,
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
    # サッカーは、その日にある試合の中で上位を必ず残す。
    #
    # MLBは1日15試合あるので「3点以上」という絶対値で絞れば3試合残る。
    # サッカーは開催が2試合しかない日がある。そこへ同じ閾値を当てると、
    # 「今夜やる試合のうちどれを見るか」に答える前に0件になる。
    # 実際、ラ・リーガ開幕週はアラベス対ヘタフェとセビージャ対ラージョの
    # 2試合しか無く、どちらも昨季14位・15位を含むため0点になり、
    # サッカーの日次動画は1本も出ていなかった。
    #
    # 毎日必ず出ることがこのチャンネルの value なので、試合がある日は出す。
    # 点が低い日は見出しが控えめになるだけで、事実と食い違うわけではない。
    soccer = [g for g in output_games if is_soccer_league(g["league"])]
    for g in _spread_across_leagues(soccer, SOCCER_MIN_NOTABLE):
        g["is_notable"] = True

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
# type は資産動画で投手・野手に分けて紹介するために持つ。
# 大谷翔平は両方だが、打者としての出場が続いているため "batter" にしている。
JP_PLAYERS_MLB = [
    {"name_en": "Shohei Ohtani", "name_jp": "大谷翔平", "type": "batter"},
    {"name_en": "Yu Darvish", "name_jp": "ダルビッシュ有", "type": "pitcher"},
    {"name_en": "Roki Sasaki", "name_jp": "佐々木朗希", "type": "pitcher"},
    {"name_en": "Yoshinobu Yamamoto", "name_jp": "山本由伸", "type": "pitcher"},
    {"name_en": "Tomoyuki Sugano", "name_jp": "菅野智之", "type": "pitcher"},
    {"name_en": "Yusei Kikuchi", "name_jp": "菊池雄星", "type": "pitcher"},
    {"name_en": "Shota Imanaga", "name_jp": "今永昇太", "type": "pitcher"},
    {"name_en": "Seiya Suzuki", "name_jp": "鈴木誠也", "type": "batter"},
    {"name_en": "Kodai Senga", "name_jp": "千賀滉大", "type": "pitcher"},
    {"name_en": "Yuki Matsui", "name_jp": "松井裕樹", "type": "pitcher"},
    # 2026/7時点で判明した見落とし分。2026年在籍16名のうち欠けていた6名を追加
    {"name_en": "Masataka Yoshida", "name_jp": "吉田正尚", "type": "batter"},
    {"name_en": "Kazuma Okamoto", "name_jp": "岡本和真", "type": "batter"},
    {"name_en": "Munetaka Murakami", "name_jp": "村上宗隆", "type": "batter"},
    {"name_en": "Shinnosuke Ogasawara", "name_jp": "小笠原慎之介", "type": "pitcher"},
    {"name_en": "Tatsuya Imai", "name_jp": "今井達也", "type": "pitcher"},
    {"name_en": "Lars Nootbaar", "name_jp": "ヌートバー", "type": "batter"},
]

# 音声合成に渡すときの読み。
#
# なぜ必要か:
#   VOICEVOXは漢字の人名を読み仮名まで正しく推定できず、
#   「朗希」「滉大」「宗隆」あたりは実際に誤読される。動画とポッドキャストの
#   両方で名前が違って聞こえるのは、選手を扱うサービスとして致命的なので、
#   読み上げ直前にここのカナへ置き換える。
#
#   画面に出る文字は漢字のままにする(表記はメディアに合わせる必要がある)。
#   置き換えるのは音声に渡すテキストだけ。
#
# 姓と名の間に読点を入れているのは、続けて読ませると
# アクセントがつながって一語のように聞こえるため。
JP_PLAYER_READINGS = {
    "大谷翔平": "オオタニ、ショウヘイ",
    "ダルビッシュ有": "ダルビッシュ、ユウ",
    "佐々木朗希": "ササキ、ロウキ",
    "山本由伸": "ヤマモト、ヨシノブ",
    "菅野智之": "スガノ、トモユキ",
    "菊池雄星": "キクチ、ユウセイ",
    "今永昇太": "イマナガ、ショウタ",
    "鈴木誠也": "スズキ、セイヤ",
    "千賀滉大": "センガ、コウダイ",
    "松井裕樹": "マツイ、ユウキ",
    "吉田正尚": "ヨシダ、マサタカ",
    "岡本和真": "オカモト、カズマ",
    "村上宗隆": "ムラカミ、ムネタカ",
    "小笠原慎之介": "オガサワラ、シンノスケ",
    "今井達也": "イマイ、タツヤ",
    "ヌートバー": "ヌートバー",
}


# 外国人選手の姓の読み。
#
# なぜ要るのか:
#   VOICEVOXにアルファベットを渡すと、辞書に無いものは1文字ずつ読む。
#   「Crow-Armstrong」は「シーアールオーダブリュー…」になる。
#   これまで名前が出るのは冒頭のフックだけだったので姓に削って凌いでいたが、
#   「今日の1人」で外国人選手を扱うようになり、1本まるごと同じ名前を
#   何度も読むことになった。読めない名前で1分喋ることになる。
#
#   全選手ぶんは持てない(毎日変わる)。日本の中継や記事で普段そう書かれて
#   いる読みだけを置く。無い名前は、これまで通り姓のアルファベットに落ちる。
MLB_NAME_READINGS = {
    "Crow-Armstrong": "クロウ、アームストロング",
    "Ohtani": "オオタニ",
    "Judge": "ジャッジ",
    "Soto": "ソト",
    "Betts": "ベッツ",
    "Freeman": "フリーマン",
    "Harper": "ハーパー",
    "Acuna": "アクーニャ",
    "Witt": "ウィット",
    "Tucker": "タッカー",
    "Alonso": "アロンソ",
    "Devers": "デバース",
    "Ramirez": "ラミレス",
    "Guerrero": "ゲレーロ",
    "Bichette": "ビシェット",
    "Turang": "トゥラング",
    "Carroll": "キャロル",
    "Rutschman": "ラッチマン",
    "Henderson": "ヘンダーソン",
    "Skubal": "スクーバル",
    "Wheeler": "ウィーラー",
    "Snell": "スネル",
    "Burnes": "バーンズ",
    "Gausman": "ガウスマン",
    "Cease": "シース",
    "Sale": "セール",
    "Skenes": "スキーンズ",
    "Buehler": "ビューラー",
    "Glasnow": "グラスノー",
    "Kershaw": "カーショウ",
    "Verlander": "バーランダー",
    "Scherzer": "シャーザー",
    "Cole": "コール",
    "Nola": "ノラ",
    "Webb": "ウェッブ",
    "Gilbert": "ギルバート",
    "Castillo": "カスティーヨ",
    "Diaz": "ディアス",
    "Contreras": "コントレラス",
    "Realmuto": "リアルミュート",
    "Machado": "マチャド",
    "Arenado": "アレナド",
    "Goldschmidt": "ゴールドシュミット",
    "Olson": "オルソン",
    "Riley": "ライリー",
    "Albies": "アルビーズ",
    "Bregman": "ブレグマン",
    "Altuve": "アルトゥーベ",
    "Alvarez": "アルバレス",
    "Rodriguez": "ロドリゲス",
    "Raleigh": "ローリー",
    "Kwan": "クワン",
    "Robert": "ロバート",
    "Langford": "ラングフォード",
    "Marte": "マーテ",
    "Nootbaar": "ヌートバー",
    "Imanaga": "イマナガ",
    "Yamamoto": "ヤマモト",
    "Sasaki": "ササキ",
    "Suzuki": "スズキ",
    "Yoshida": "ヨシダ",
    "Senga": "センガ",
    "Sugano": "スガノ",
    "Kikuchi": "キクチ",
    "Matsui": "マツイ",
    "Murakami": "ムラカミ",
    "Okamoto": "オカモト",
    "Lee": "リー",
    "Muncy": "マンシー",
    "Encarnacion-Strand": "エンカーナシオン、ストランド",
}


def apply_readings(text: str) -> str:
    """
    音声合成へ渡す直前に、選手名を読み仮名へ置き換える。

    長い名前から先に置換する。「大谷翔平」より先に「大谷」のような
    短い項目を処理すると、部分的にだけ置き換わって読みが壊れるため。
    """
    if not text:
        return text
    for kanji in sorted(JP_PLAYER_READINGS, key=len, reverse=True):
        text = text.replace(kanji, JP_PLAYER_READINGS[kanji])
    return text


# 全米的に注目度・話題性が高いとされる伝統的な人気球団(市場規模・ファン数などが根拠)
MLB_MARQUEE_TEAM_IDS = {"147", "119", "111", "112", "144"}  # ヤンキース/ドジャース/レッドソックス/カブス/ブレーブス

# 伝統の好カード(ライバル関係)。フロズンセット化して両方向マッチできるようにする
# 球場ごとの特徴。「大きな注目理由(カード)」に対する「小さな見どころ」として、
# AIが要約の締めに使えるようにするためのメモ。キーはMLB Stats APIが返す
# 英語の球場名。内容は広く知られている事実(標高・フェンスの形状・気候)に
# 限定し、パークファクターのような数値的な断定は避けている。
# 3・4番目の要素は「本拠地球団のteam_id」と「所在地」。
# 球場の特徴だけを聞いても、それがどのチームの本拠地でどこにあるのかが
# 分からないと頭に残らないため、後から追加した。
# 既存の参照は [0][1] しか見ていないので、要素が増えても影響しない。
MLB_VENUE_NOTES = {
    "Coors Field": ("クアーズ・フィールド", "標高約1600mの高地にあり、空気が薄いぶん打球が伸びやすい、MLBで最も打者有利とされる球場", "115", "コロラド州デンバー"),
    "Fenway Park": ("フェンウェイ・パーク", "左翼に高さ約11mの「グリーンモンスター」がそびえ、打球の行方が読みにくい独特の形状", "111", "マサチューセッツ州ボストン"),
    "Wrigley Field": ("リグレー・フィールド", "風向きによって球場の性格が変わり、外野へ吹く日は打撃戦になりやすいことで知られる", "112", "イリノイ州シカゴ"),
    "Oracle Park": ("オラクル・パーク", "右中間が非常に深く、海風の影響もあって本塁打が出にくい、投手有利とされる球場", "137", "カリフォルニア州サンフランシスコ"),
    "Yankee Stadium": ("ヤンキー・スタジアム", "右翼が浅く、左打者の本塁打が出やすい形状", "147", "ニューヨーク州ニューヨーク"),
    "Great American Ball Park": ("グレート・アメリカン・ボール・パーク", "両翼が狭く、本塁打が出やすい球場として知られる", "113", "オハイオ州シンシナティ"),
    "Dodger Stadium": ("ドジャー・スタジアム", "1962年開場、MLBで3番目に古い現役球場", "119", "カリフォルニア州ロサンゼルス"),
    "Petco Park": ("ペトコ・パーク", "広い外野と海沿いの気候により、投手有利とされる球場", "135", "カリフォルニア州サンディエゴ"),
    "Tropicana Field": ("トロピカーナ・フィールド", "MLBで数少ないドーム球場。天候に左右されない", "139", "フロリダ州セントピーターズバーグ"),
    "Citi Field": ("シティ・フィールド", "2009年開場。開場当初は外野が広く投手有利とされ、その後フェンスが調整された", "121", "ニューヨーク州ニューヨーク"),
    "Truist Park": ("トゥルーイスト・パーク", "2017年開場。球場の外に商業施設が一体で作られた、比較的新しい形の球場", "144", "ジョージア州アトランタ"),
    "Busch Stadium": ("ブッシュ・スタジアム", "外野が広く、本塁打より打球が転がる展開になりやすいとされる球場", "138", "ミズーリ州セントルイス"),
    "T-Mobile Park": ("Tモバイル・パーク", "開閉式屋根を持ち、海沿いの湿った空気の影響で投手有利とされる球場", "136", "ワシントン州シアトル"),
    "Rogers Centre": ("ロジャーズ・センター", "MLBで唯一カナダにある球場。開閉式屋根を持つ", "141", "カナダ・トロント"),
    "Progressive Field": ("プログレッシブ・フィールド", "湖からの風の影響を受けやすく、季節によって球場の性格が変わる", "114", "オハイオ州クリーブランド"),
    "Comerica Park": ("コメリカ・パーク", "中堅が非常に深く、本塁打が出にくい投手有利の球場とされる", "116", "ミシガン州デトロイト"),
    "Chase Field": ("チェイス・フィールド", "砂漠気候のため開閉式屋根を備える。屋根を閉じると打球が伸びにくくなる", "109", "アリゾナ州フェニックス"),
    "Oriole Park at Camden Yards": ("カムデン・ヤーズ", "1992年開場。街並みに溶け込む設計で、以降の新球場の手本になった", "110", "メリーランド州ボルチモア"),
    # ミニッツメイド・パークは2025年にダイキン・パークへ改称。
    # 過去のアーカイブが旧名で残っているため、両方の表記を引けるようにしておく。
    "Daikin Park": ("ダイキン・パーク", "左翼が浅く、開閉式屋根を持つ球場", "117", "テキサス州ヒューストン"),
    "Minute Maid Park": ("ミニッツメイド・パーク", "左翼が浅く、開閉式屋根を持つ球場", "117", "テキサス州ヒューストン"),
    # 残り11球場。これが無いと、その球場での試合は球場の説明が一切出ない。
    # 実測値(venue_stats)は30球場すべてで取れるので、説明側も揃えておく。
    "Rate Field": ("レート・フィールド", "ホワイトソックスの本拠地。旧称ギャランティード・レート・フィールド", "145", "イリノイ州シカゴ"),
    "American Family Field": ("アメリカン・ファミリー・フィールド", "開閉式屋根を持ち、天候に左右されにくい球場", "158", "ウィスコンシン州ミルウォーキー"),
    "Citizens Bank Park": ("シチズンズ・バンク・パーク", "両翼が比較的浅く、本塁打が出やすい球場として知られる", "143", "ペンシルベニア州フィラデルフィア"),
    "Kauffman Stadium": ("カウフマン・スタジアム", "外野が広く、長打が転がりやすい構造", "118", "ミズーリ州カンザスシティ"),
    "PNC Park": ("PNCパーク", "川越しに街並みを望む景観で知られる球場", "134", "ペンシルベニア州ピッツバーグ"),
    "Target Field": ("ターゲット・フィールド", "寒暖差が大きく、季節によって打球の飛び方が変わる", "142", "ミネソタ州ミネアポリス"),
    "Angel Stadium": ("エンゼル・スタジアム", "1966年開場。MLBでは古い部類に入る球場", "108", "カリフォルニア州アナハイム"),
    "Globe Life Field": ("グローブライフ・フィールド", "2020年開場。夏の暑さに対応した開閉式屋根を持つ", "140", "テキサス州アーリントン"),
    "loanDepot park": ("ローンデポ・パーク", "開閉式屋根を持ち、湿度の高い気候の影響を抑えている", "146", "フロリダ州マイアミ"),
    "Nationals Park": ("ナショナルズ・パーク", "2008年開場。連邦議会議事堂を望む立地", "120", "ワシントンD.C."),
    "Sutter Health Park": ("サッター・ヘルス・パーク", "アスレチックスが本拠地移転までの間、暫定的に使用している球場", "133", "カリフォルニア州サクラメント"),
}

MLB_DIVISION_NAME_JP = {
    "ALE": "ア・リーグ東地区",
    "ALC": "ア・リーグ中地区",
    "ALW": "ア・リーグ西地区",
    "NLE": "ナ・リーグ東地区",
    "NLC": "ナ・リーグ中地区",
    "NLW": "ナ・リーグ西地区",
}

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

# ライバル関係の「由来」。なぜ因縁のカードなのかが分からないと、
# 「伝統の好カード」と書かれても初めて見る人には意味が伝わらない。
#
# ここに載せるのは、今季の成績とは無関係で、かつ広く知られている
# 歴史的経緯だけに限る(シリーズの通算成績のような、都度APIで確認しないと
# 正しさを保証できない数字は書かない)。
MLB_RIVALRY_NOTES = {
    frozenset({"147", "111"}):
        "1919年のベーブ・ルース移籍に端を発する、MLBで最も長く続くライバル関係",
    frozenset({"119", "137"}):
        "ニューヨーク時代から続く因縁で、1958年に両球団そろって西海岸へ移転した後も続いている",
    frozenset({"112", "138"}):
        "ナ・リーグ中地区を代表する、中西部の伝統の一戦",
    frozenset({"119", "135"}):
        "近年のナ・リーグ西地区の優勝争いを二分してきたカード",
    frozenset({"147", "121"}):
        "ニューヨーク市を二分する「サブウェイ・シリーズ」",
    frozenset({"112", "145"}):
        "シカゴ市内を二分する「クロスタウン・クラシック」",
    frozenset({"108", "119"}):
        "ロサンゼルス近郊の2球団による「フリーウェイ・シリーズ」",
}

# 2026年7月時点、Web検索で確認できた範囲のみ記載。追加・更新推奨。
JP_PLAYERS_SOCCER = [
    # 2026-27シーズン、欧州主要リーグ所属の日本人選手。
    # 大半は5大リーグだが、イングランド2部・ドイツ2部の選手も含む。
    # 2026年8月4日に外部の一覧記事と突き合わせて更新。
    # 欧州の移籍市場は9月2日早朝(日本時間)まで開いているため、
    # 閉幕後にもう一度確認すること。
    #
    # チーム名(team_en)はfootball-data.orgのAPIが返す表記と
    # 突き合わせるので、表記が合わないと検出できない点に注意。
    #
    # league / team_jp は表示と読み上げのために持つ。
    # 所属リーグをコメントだけで表していた頃は、リーグ単位で選手をまとめる
    # 処理が書けなかった。team_jp が要るのは、読み上げ(VOICEVOX)が
    # "Borussia Monchengladbach" のような英字を正しく読めないため。

    # --- プレミアリーグ(イングランド) ---
    {"name_en": "Wataru Endo", "name_jp": "遠藤航", "team_en": "Liverpool",
     "team_jp": "リバプール", "league": "PL", "match": "liverpool"},
    {"name_en": "Kaoru Mitoma", "name_jp": "三笘薫", "team_en": "Brighton",
     "team_jp": "ブライトン", "league": "PL", "match": "brighton"},
    {"name_en": "Daichi Kamada", "name_jp": "鎌田大地", "team_en": "Crystal Palace",
     "team_jp": "クリスタル・パレス", "league": "PL", "match": "crystalpalace"},
    {"name_en": "Kota Takai", "name_jp": "高井幸大", "team_en": "Tottenham",
     "team_jp": "トッテナム", "league": "PL", "match": "tottenham"},
    {"name_en": "Ao Tanaka", "name_jp": "田中碧", "team_en": "Leeds United",
     "team_jp": "リーズ", "league": "PL", "match": "leeds"},
    {"name_en": "Tatsuhiro Sakamoto", "name_jp": "坂元達裕", "team_en": "Coventry City",
     "team_jp": "コベントリー", "league": "ELC", "match": "coventry"},
    {"name_en": "Daizen Maeda", "name_jp": "前田大然", "team_en": "Ipswich Town",
     "team_jp": "イプスウィッチ", "league": "ELC", "match": "ipswich"},
    {"name_en": "Hidemasa Morita", "name_jp": "守田英正", "team_en": "Hull City",
     "team_jp": "ハル・シティ", "league": "ELC", "match": "hullcity"},

    # --- ラ・リーガ(スペイン) ---
    {"name_en": "Takefusa Kubo", "name_jp": "久保建英", "team_en": "Real Sociedad",
     "team_jp": "レアル・ソシエダ", "league": "PD", "match": "sociedad"},
    {"name_en": "Ryunosuke Sato", "name_jp": "佐藤龍之介", "team_en": "Valencia",
     "team_jp": "バレンシア", "league": "PD", "match": "valencia"},

    # --- ブンデスリーガ(ドイツ) ---
    # "bayern" 単体だと Bayer Leverkusen とは別物なので衝突しない
    # (bayer と bayern で綴りが違う)。
    {"name_en": "Hiroki Ito", "name_jp": "伊藤洋輝", "team_en": "Bayern Munich",
     "team_jp": "バイエルン", "league": "BL1", "match": "bayern"},
    {"name_en": "Koki Machida", "name_jp": "町田浩樹", "team_en": "Hoffenheim",
     "team_jp": "ホッフェンハイム", "league": "BL1", "match": "hoffenheim"},
    {"name_en": "Yuito Suzuki", "name_jp": "鈴木唯人", "team_en": "Freiburg",
     "team_jp": "フライブルク", "league": "BL1", "match": "freiburg"},
    {"name_en": "Ritsu Doan", "name_jp": "堂安律", "team_en": "Eintracht Frankfurt",
     "team_jp": "フランクフルト", "league": "BL1", "match": "eintrachtfrankfurt"},
    {"name_en": "Kaishu Sano", "name_jp": "佐野海舟", "team_en": "Mainz",
     "team_jp": "マインツ", "league": "BL1", "match": "mainz"},
    {"name_en": "Sota Kawasaki", "name_jp": "川﨑颯太", "team_en": "Mainz",
     "team_jp": "マインツ", "league": "BL1", "match": "mainz"},
    # "borussia" はドルトムントとぶつかるので地名側を使う
    {"name_en": "Shuto Machino", "name_jp": "町野修斗",
     "team_en": "Borussia Monchengladbach", "team_jp": "ボルシアMG",
     "league": "BL1", "match": "monchengladbach"},
    {"name_en": "Zento Uno", "name_jp": "宇野禅斗",
     "team_en": "Borussia Monchengladbach", "team_jp": "ボルシアMG",
     "league": "BL1", "match": "monchengladbach"},
    {"name_en": "Daiki Hashioka", "name_jp": "橋岡大樹",
     "team_en": "Borussia Monchengladbach", "team_jp": "ボルシアMG",
     "league": "BL1", "match": "monchengladbach"},
    {"name_en": "Satoshi Tanaka", "name_jp": "田中聡", "team_en": "Schalke",
     "team_jp": "シャルケ", "league": "BL2", "match": "schalke"},

    # --- セリエA(イタリア) ---
    {"name_en": "Zion Suzuki", "name_jp": "鈴木ザイオン", "team_en": "Parma",
     "team_jp": "パルマ", "league": "SA", "match": "parma"},

    # --- リーグ・アン(フランス) ---
    {"name_en": "Takumi Minamino", "name_jp": "南野拓実", "team_en": "Monaco",
     "team_jp": "モナコ", "league": "FL1", "match": "monaco"},
    {"name_en": "Ayumu Seko", "name_jp": "瀬古歩夢", "team_en": "Le Havre",
     "team_jp": "ル・アーブル", "league": "FL1", "match": "havre"},
    {"name_en": "Sota Nakamura", "name_jp": "中村草太", "team_en": "Le Havre",
     "team_jp": "ル・アーブル", "league": "FL1", "match": "havre"},
    {"name_en": "Kaito Mizuta", "name_jp": "水多海斗", "team_en": "Le Havre",
     "team_jp": "ル・アーブル", "league": "FL1", "match": "havre"},
]

# クラブ名の照合について
# ---------------------------------------------------------------------------
# 上の team_en は人が読むための表記で、APIが返す名前とは一致しない。
# football-data.org の name は正式名称なので、次のように長い:
#
#   "Liverpool"                → "Liverpool FC"
#   "Bayern Munich"            → "FC Bayern München"
#   "Borussia Monchengladbach" → "Borussia Mönchengladbach"
#   "Le Havre"                 → "Le Havre AC"
#   "Real Sociedad"            → "Real Sociedad de Fútbol"
#
# 当初は team.get("name") in {team_en...} という完全一致で照合していた。
# これだと上のどれ1つ当たらない。開幕前で試合が0件だったため
# 疎通確認では表面化せず、開幕後に「日本人選手が1人も検出されない」形で
# 出るところだった。
#
# 対策として、各選手に match(照合キー)を持たせる。
# 正式名称を正規化した文字列に、このキーが含まれるかどうかで判定する。
# キーはリーグ内で一意になる語を選ぶ。"borussia" はドルトムントと
# ぶつかるので使わず、"monchengladbach" を使う。

def normalize_club(name: str) -> str:
    """
    クラブ名を照合用に潰す。

    ウムラウト等を落とし、英数字だけを残して小文字に揃える。
    空白も落とすので "Real Sociedad de Fútbol" は
    "realsociedaddefutbol" になり、"sociedad" が部分一致で当たる。
    """
    if not name:
        return ""
    # NFKDで分解できない文字は個別に置く。ø や ß は「基底文字＋結合記号」では
    # なく独立した文字なので、分解しても素通りしてしまう。
    # 実データで FC København と FK Bodø/Glimt が当たらなかった。
    for a, b in (("ø", "o"), ("Ø", "O"), ("æ", "ae"), ("Æ", "AE"),
                 ("ß", "ss"), ("đ", "d"), ("Đ", "D"), ("ł", "l"), ("Ł", "L")):
        name = name.replace(a, b)
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in ascii_only.lower() if c.isalnum())


def jp_players_for_club(name: str, league: str | None = None) -> list:
    """APIが返したクラブ名に所属する日本人選手を返す。無ければ空。"""
    norm = normalize_club(name)
    if not norm:
        return []
    return [
        p for p in JP_PLAYERS_SOCCER
        if p["match"] in norm and (league is None or p["league"] == league)
    ]


# クラブ名の日本語表記
# ---------------------------------------------------------------------------
# 日本人選手が居るクラブは名簿に team_jp を持っているが、
# 開幕日程や昨季順位にはそれ以外のクラブも出てくる。
# 読み上げ(VOICEVOX)は "Olympique Lyonnais" のような英字を読めないので、
# 主要クラブぶんの表記をここに置く。
#
# 照合は normalize_club() を通した部分一致で、長いキーから順に見る。
# キーの選び方に注意が要る例:
#   internazionale : "FC Internazionale Milano" は "milan" を含むので、
#                    ミランより先に判定しないとインテルがミランになる
#   acmilan        : 上の理由で "milan" ではなく "acmilan" を使う
#   realmadrid     : "Club Atlético de Madrid" と分けるため地名だけでは足りない
#   saintgermain   : "Paris FC" と分けるため
#
# 一覧に無いクラブは英語表記のまま出る(欠けても落ちない)。
SOCCER_CLUB_NAME_JP = {
    # --- プレミアリーグ ---
    "arsenal": "アーセナル",
    "astonvilla": "アストン・ヴィラ",
    "bournemouth": "ボーンマス",
    "brentford": "ブレントフォード",
    "brighton": "ブライトン",
    "burnley": "バーンリー",
    "chelsea": "チェルシー",
    "crystalpalace": "クリスタル・パレス",
    "everton": "エバートン",
    "fulham": "フラム",
    "leeds": "リーズ",
    "liverpool": "リバプール",
    "manchestercity": "マンチェスター・シティ",
    "manchesterunited": "マンチェスター・ユナイテッド",
    "newcastle": "ニューカッスル",
    "nottingham": "ノッティンガム・フォレスト",
    "sunderland": "サンダーランド",
    "tottenham": "トッテナム",
    "westham": "ウェストハム",
    "wolverhampton": "ウルバーハンプトン",

    # --- ラ・リーガ ---
    "realmadrid": "レアル・マドリード",
    # "barcelona" だと "RCD Espanyol de Barcelona" まで拾ってしまう
    # (実データで発覚)。エスパニョールは別クラブなので前置きまで含める。
    "fcbarcelona": "バルセロナ",
    "espanyol": "エスパニョール",
    "atletico": "アトレティコ・マドリード",
    "athletic": "アスレティック・ビルバオ",
    "villarreal": "ビジャレアル",
    "betis": "レアル・ベティス",
    "sevilla": "セビージャ",
    "valencia": "バレンシア",
    "sociedad": "レアル・ソシエダ",
    "girona": "ジローナ",
    "celta": "セルタ",
    "osasuna": "オサスナ",
    "mallorca": "マジョルカ",
    "rayo": "ラージョ・バジェカーノ",
    "getafe": "ヘタフェ",
    "alaves": "アラベス",
    "levante": "レバンテ",
    "elche": "エルチェ",

    # --- セリエA ---
    # インテルを先に見る(下の acmilan より長いので自然に先になる)
    "internazionale": "インテル",
    "acmilan": "ACミラン",
    "juventus": "ユベントス",
    "napoli": "ナポリ",
    "roma": "ローマ",
    "lazio": "ラツィオ",
    "atalanta": "アタランタ",
    "fiorentina": "フィオレンティーナ",
    "bologna": "ボローニャ",
    "torino": "トリノ",
    "udinese": "ウディネーゼ",
    "genoa": "ジェノア",
    "parma": "パルマ",
    "cagliari": "カリアリ",
    "lecce": "レッチェ",
    "verona": "ベローナ",
    "sassuolo": "サッスオーロ",
    "cremonese": "クレモネーゼ",

    # --- ブンデスリーガ ---
    "bayern": "バイエルン",
    "dortmund": "ドルトムント",
    "leverkusen": "レバークーゼン",
    "leipzig": "ライプツィヒ",
    "stuttgart": "シュツットガルト",
    "eintrachtfrankfurt": "フランクフルト",
    "wolfsburg": "ボルフスブルク",
    "freiburg": "フライブルク",
    "mainz": "マインツ",
    "monchengladbach": "ボルシアMG",
    "werder": "ブレーメン",
    "hoffenheim": "ホッフェンハイム",
    "augsburg": "アウクスブルク",
    "unionberlin": "ウニオン・ベルリン",
    "stpauli": "ザンクトパウリ",
    "koln": "ケルン",
    "heidenheim": "ハイデンハイム",
    "hamburger": "ハンブルク",
    "schalke": "シャルケ",

    # --- リーグ・アン ---
    "saintgermain": "パリ・サンジェルマン",
    "marseille": "マルセイユ",
    "lyonnais": "リヨン",
    "monaco": "モナコ",
    "lille": "リール",
    "rennais": "レンヌ",
    "nice": "ニース",
    "lens": "ランス",
    "nantes": "ナント",
    "toulouse": "トゥールーズ",
    "strasbourg": "ストラスブール",
    "brestois": "ブレスト",
    "havre": "ル・アーブル",
    "auxerre": "オセール",
    "angers": "アンジェ",
    "metz": "メス",
    "lorient": "ロリアン",
    "parisfc": "パリFC",

    # --- CLに出てくる5大リーグ以外のクラブ ---
    # 実データ(data/soccer_preview.json)で英語のまま残っていた分を補った。
    # CLの注目カードにこれらが出ると、読み上げが英字を読めない。
    "benfica": "ベンフィカ",
    "sportingclubedeportugal": "スポルティング",
    "porto": "ポルト",
    "ajax": "アヤックス",
    "psv": "PSV",
    "feyenoord": "フェイエノールト",
    "brugge": "クラブ・ブルージュ",
    "unionsaintgilloise": "ユニオン・サンジロワーズ",
    "celtic": "セルティック",
    "galatasaray": "ガラタサライ",
    "salzburg": "ザルツブルク",
    "sturmgraz": "シュツルム・グラーツ",
    "youngboys": "ヤングボーイズ",
    "slaviapraha": "スラビア・プラハ",
    "spartapraha": "スパルタ・プラハ",
    "dinamozagreb": "ディナモ・ザグレブ",
    "crvenazvezda": "レッドスター・ベオグラード",
    "slovanbratislava": "スロバン・ブラチスラバ",
    "shakhtar": "シャフタール",
    "olympiakos": "オリンピアコス",
    "kobenhavn": "コペンハーゲン",
    "bodo": "ボドー／グリムト",
    "qarabag": "カラバフ",
    "kairat": "カイラト",
    "paphos": "パフォス",

    # --- 昇格・降格で出入りするクラブ ---
    "monza": "モンツァ",
    "pisa": "ピサ",
    "como": "コモ",
    "venezia": "ベネチア",
    "frosinone": "フロジノーネ",
    "oviedo": "オビエド",
    "malaga": "マラガ",
    # "deportivo" だと "Deportivo Alavés" を飲み込む(実データで発覚)
    "deportivolacoruna": "デポルティボ",
    "racingclubdesantander": "ラシン・サンタンデール",
    "paderborn": "パーダーボルン",
    "elversberg": "エルバースベルク",
    "troyes": "トロワ",
    "lemans": "ル・マン",
    "auxerre": "オセール",
}

# 長いキーを先に見る。"acmilan" と "milan" のように片方が
# もう片方を含む場合、短い方が先に当たると誤って割り当てられる。
_SOCCER_CLUB_KEYS = sorted(SOCCER_CLUB_NAME_JP, key=len, reverse=True)


def club_name_jp(name: str) -> str:
    """
    APIが返したクラブ名を日本語表記にする。一覧に無ければ元の文字列。

    まず名簿(日本人選手のクラブ)を見るのは、そちらが実際に配信へ
    出る表記だから。両方に載っているクラブで表記が割れないようにする。
    """
    norm = normalize_club(name)
    if not norm:
        return name
    for p in JP_PLAYERS_SOCCER:
        if p["match"] in norm:
            return p["team_jp"]
    for key in _SOCCER_CLUB_KEYS:
        if key in norm:
            return SOCCER_CLUB_NAME_JP[key]
    return name


# 上のleagueコードに対応する日本語名。資産動画などで見出しに使う。
# ELC(イングランド2部)とBL2(ドイツ2部)は5大リーグではないが、
# 日本人選手が在籍しているので名簿には載せ、見出しで区別する。
SOCCER_LEAGUE_NAME_JP = {
    "PL": "プレミアリーグ",
    "ELC": "イングランド2部（チャンピオンシップ）",
    "PD": "ラ・リーガ",
    "SA": "セリエA",
    "BL1": "ブンデスリーガ",
    "BL2": "ブンデスリーガ2部",
    "FL1": "リーグ・アン",
    "CL": "チャンピオンズリーグ",
}

# 移籍市場は9月2日早朝(日本時間)まで開いている。閉幕後に再確認すること。


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

# 球団カラー(公式ロゴ画像そのものではなく、ブランドカラーの色情報のみ)。
# 色そのものは著作物ではないため、球団名の頭に色付きバッジを表示する
# 目的でのみ使用する(実際のエンブレム画像は一切使わない)。
MLB_TEAM_COLOR = {
    "108": "#BA0021", "109": "#A71930", "110": "#DF4601", "111": "#BD3039",
    "112": "#0E3386", "113": "#C6011F", "114": "#00385D", "115": "#333366",
    "116": "#0C2C56", "117": "#002D62", "118": "#004687", "119": "#005A9C",
    "120": "#AB0003", "121": "#002D72", "133": "#003831", "134": "#FDB827",
    "135": "#2F241D", "136": "#0C2C56", "137": "#FD5A1E", "138": "#C41E3A",
    "139": "#092C5C", "140": "#003278", "141": "#134A8E", "142": "#002B5C",
    "143": "#E81828", "144": "#CE1141", "145": "#27251F", "146": "#00A3E0",
    "147": "#003087", "158": "#12284B",
}


# ---------------------------------------------------------------------------
# 実データ取得: MLB Stats API
# ---------------------------------------------------------------------------
# エンドポイントはMLB非公式(無料・キー不要だが公式ドキュメントは存在しない)。
# Web検索で実在・広く使われていることは確認済みだが、この環境はネットワーク
# 無効のため実際のレスポンスは未検証。フィールド名などは変わる可能性がある。

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


# 日本語名 -> {"player_id", "team_id"}。resolve_jp_player_teams が毎回更新する。
JP_PLAYER_LOOKUP: dict = {}


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
    name_to_player_id: dict[str, str] = {}
    for player in data.get("people", []):
        full_name = player.get("fullName")
        current_team = player.get("currentTeam") or {}
        team_id = current_team.get("id")
        if full_name and team_id:
            name_to_team_id[full_name] = str(team_id)
            name_to_player_id[full_name] = str(player.get("id", ""))

    jp_team_map: dict[str, list] = {}
    # 日本語名 -> (player_id, team_id)。打者の試合ログ(連続安打など)を
    # 引くのに選手IDが要るため、ここで一緒に控えておく。
    # 1日1回の解決結果を使い回すので、追加のAPI呼び出しは発生しない。
    JP_PLAYER_LOOKUP.clear()
    for jp in JP_PLAYERS_MLB:
        team_id = name_to_team_id.get(jp["name_en"])
        if team_id:
            jp_team_map.setdefault(team_id, []).append(jp["name_jp"])
            JP_PLAYER_LOOKUP[jp["name_jp"]] = {
                "player_id": name_to_player_id.get(jp["name_en"], ""),
                "team_id": team_id,
            }

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
        params={
            "leagueId": "103,104",
            "season": date_str[:4],
            # splitRecords を含めると直近10試合(lastTen)の成績が取れる
            "hydrate": "team",
        },
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
            # 直近10試合の成績。standingsのsplitRecordsに含まれるが、
            # レスポンスに無い場合もあるため防御的に取得する。
            last_ten = None
            for sr in team_record.get("records", {}).get("splitRecords", []):
                if sr.get("type") == "lastTen":
                    last_ten = f"{sr.get('wins', 0)}勝{sr.get('losses', 0)}敗"
                    break

            standings[team_id] = Standing(
                team_id=team_id,
                division_rank=int(team_record.get("divisionRank", 0)),
                games_back=games_back,
                win_streak=win_streak,
                wins=int(team_record.get("wins", 0)),
                losses=int(team_record.get("losses", 0)),
                last_ten=last_ten,
            )

    jp_names_en = {p["name_en"] for p in JP_PLAYERS_MLB}
    jp_lookup = {p["name_en"]: p["name_jp"] for p in JP_PLAYERS_MLB}

    games: list[Game] = []
    for date_entry in schedule_data.get("dates", []):
        for g in date_entry.get("games", []):
            home = g["teams"]["home"]["team"]
            away = g["teams"]["away"]["team"]

            players: list[PlayerHighlight] = []
            probables: dict = {"home": None, "away": None}
            for side, team in (("home", home), ("away", away)):
                pitcher = g["teams"][side].get("probablePitcher")
                if not pitcher:
                    continue
                name_en = pitcher.get("fullName")
                # 日本人以外の先発投手も記録しておく。AI要約で「誰と誰が投げ合うのか」
                # を語れるようにするため(以前は日本人選手しか拾っていなかった)。
                probables[side] = ProbablePitcher(
                    player_id=str(pitcher.get("id", "")),
                    name_en=name_en or "",
                    name_jp=jp_lookup.get(name_en),
                )
                if name_en in jp_names_en:
                    players.append(
                        PlayerHighlight(
                            name=jp_lookup[name_en],
                            team_id=str(team["id"]),
                            is_japanese=True,
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
                    home_probable=probables["home"],
                    away_probable=probables["away"],
                    venue_name=(g.get("venue") or {}).get("name"),
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
    # CLを含めるのは、5大リーグのリーグ戦が週末に集中し平日がほぼ空白に
    # なるため。CLは火・水開催なので、平日の穴をちょうど埋める形になる。
    # (日本ではWOWOWが独占放送しており、視聴導線とも噛み合う)
    "CL": "チャンピオンズリーグ",
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


# 1つのリーグから取る上限。複数リーグある日に、同じところから続けて取らない。
SOCCER_PER_LEAGUE = 1


def _spread_across_leagues(games: list, want: int) -> list:
    """
    上位から選ぶが、1つのリーグからは1試合までにする。

    足りなければ上限を無視して点数順で埋める。開幕直後はラ・リーガしか
    やっていない日が続き(2026年はラ・リーガ8/16、ブンデス8/28で12日ずれる)、
    そういう日に分散のために枠を空けても仕方がない。

    なぜ要るのか:
      同点が多い。日本人選手の所属で3点、両チームにいれば6点。
      6点が上限で、そこに複数の試合が並ぶ。同点の並びは
      リーグの処理順で決まっていて、選んだ理由が無い。
      同じリーグから続けて取らないだけで、その恣意はかなり減る。

    偏りについて、先に出した数字を訂正しておく:
      5大リーグが同じ日に48試合あると仮定して回したところ、
      36枠中22枠がブンデスリーガになった。だがそれは現実に無い日程で、
      実際の日程(data/soccer_preview.json)で23日ぶんを回すと
      ラ・リーガ16・プレミア10・セリエA10・ブンデス10・リーグアン6で、
      偏ってはいなかった。試合が日にちに散るので、そもそも
      1日に5リーグ揃うことがない。

      つまりこの関数は「偏りを直すため」ではなく、
      「複数リーグある日に、同点から選ぶ理由を1つ与えるため」にある。
    """
    picked, per, taken = [], {}, set()
    for g in games:
        if len(picked) >= want:
            break
        lg = g.get("league") or ""
        if per.get(lg, 0) >= SOCCER_PER_LEAGUE:
            continue
        picked.append(g)
        taken.add(id(g))
        per[lg] = per.get(lg, 0) + 1
    for g in games:            # それでも足りない日は点数順で補う
        if len(picked) >= want:
            break
        # 中身ではなく実体で見る。同点・同リーグの2試合は辞書として
        # 等しくなることがあり、`in` で比べると片方が取りこぼされる。
        # 実際、試合が2つしか無い日に1つしか選ばれていなかった。
        if id(g) not in taken:
            picked.append(g)
            taken.add(id(g))
    return picked


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
                points_back = float(top_points - row["points"])
                games_back = round(points_back / 3, 1)  # 互換のための簡易換算
                standings[team_id] = Standing(
                    team_id=team_id,
                    division_rank=row["position"],
                    games_back=games_back,
                    win_streak=0,  # 無料枠にフォームデータが無いため未実装
                    points_back=points_back,
                    played=row.get("playedGames"),
                )

        for m in matches_data.get("matches", []):
            home = m["homeTeam"]
            away = m["awayTeam"]

            players: list[PlayerHighlight] = []
            for team in (home, away):
                # 同じクラブに複数の日本人選手がいる場合(ボルシアMGは3人)、
                # 以前は next() で最初の1人しか拾えていなかった。
                for jp_player in jp_players_for_club(team.get("name")):
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
#   - 1日1回の実行につき、上位3試合まで(enhance_games_with_ai の count 引数)
#   - max_tokensに上限を設ける(暴走した場合の被害を最小化)
#   - 失敗時にリトライはしない(1回失敗したらルールベースの理由文にフォールバック)
#   - 最も安価なHaiku 4.5を使用
# この関数は ANTHROPIC_API_KEY が設定されている場合のみ main() から呼ばれる。
#
# max_tokensの決め方(2026年8月に320から引き上げ):
#   出力は「解説文 + ---HOOK--- + フック文」の順で、フック文が最後に来る。
#   そのため上限に当たると、真っ先に壊れるのがフック文になる。実際、
#   解説文が300文字を超えた日はフック文が「防御率2.41の投」のように
#   語の途中で切れており、それがそのまま通知・Bluesky・動画へ流れていた。
#   出力トークンは実際に使った分だけの課金なので、上限を上げること自体の
#   コストは無い。上限は「暴走の歯止め」としてだけ機能させ、長さの制御は
#   プロンプト側の文字数指定で行う。

def _division_lead_margin(team_id: str, standings: dict):
    """
    そのチームが地区首位の場合に、2位との差(リード幅)を返す。
    首位でない場合や算出できない場合はNone。
    首位チームのgames_backは常に0.0なので、それだけをAIに渡すと
    「独走中なのか、僅差で追われているのか」が区別できず、10ゲーム差で
    独走していても「首位の座を守る正念場」のような誇張した表現を
    生んでしまうため(実際に発生した)、リード幅を明示的に渡す。
    """
    s = standings.get(team_id)
    if not s or s.division_rank != 1:
        return None
    div = MLB_DIVISIONS.get(team_id)
    if not div:
        return None
    others = [
        o.games_back
        for tid, o in standings.items()
        if tid != team_id and MLB_DIVISIONS.get(tid) == div and o.games_back is not None
    ]
    if not others:
        return None
    return min(others)


def fetch_pitcher_season_stats(player_id: str, season: str) -> dict:
    """
    先発投手の今季成績(防御率・勝敗・奪三振)を取得する。
    AI要約の対象になる上位数試合ぶんだけ呼ぶ想定なので、呼び出し回数は
    1日あたり数回に収まる。取得に失敗しても要約自体は続行できるよう、
    失敗時は空dictを返す。
    """
    if not player_id or requests is None:
        return {}
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "season", "group": "pitching", "season": season},
            timeout=10,
        )
        resp.raise_for_status()
        for st in resp.json().get("stats", []):
            for split in st.get("splits", []):
                s = split.get("stat", {})
                if not s:
                    continue
                return {
                    "era": s.get("era"),
                    "wins": s.get("wins"),
                    "losses": s.get("losses"),
                    "strikeouts": s.get("strikeOuts"),
                }
    except Exception as e:
        print(f"[warn] 投手成績の取得に失敗(player_id={player_id}): {e}")
    return {}


def _team_context_line(team_id: str, team_name: str, standings: dict) -> str:
    """AIに渡すための、1チーム分の順位表コンテキストを組み立てる"""
    s = standings.get(team_id)
    if not s:
        return f"{team_name}: 順位表データなし"
    record = f"{s.wins}勝{s.losses}敗" if (s.wins or s.losses) else "戦績データなし"

    # 1試合勝った/負けただけの状態を「1連勝中」「1連敗中」と書くと日本語として
    # 不自然なうえ、勢いがあるかのような誤った印象を与えるため、2以上のときだけ
    # 連勝・連敗として扱う。
    if s.win_streak >= 2:
        streak = f"{s.win_streak}連勝中"
    elif s.win_streak <= -2:
        streak = f"{abs(s.win_streak)}連敗中"
    else:
        streak = "連勝・連敗はしていない"

    div_name = MLB_DIVISION_NAME_JP.get(MLB_DIVISIONS.get(team_id, ""), "所属地区不明")
    if s.division_rank == 1:
        lead = _division_lead_margin(team_id, standings)
        if lead is not None:
            rank_part = f"{div_name}の1位(2位に{lead}ゲーム差をつけている)"
        else:
            rank_part = f"{div_name}の1位"
    else:
        rank_part = f"{div_name}の{s.division_rank}位(同地区首位との差{s.games_back}ゲーム)"

    parts = f"{team_name}: {record}、{rank_part}、{streak}"
    if s.last_ten:
        parts += f"、直近10試合は{s.last_ten}"
    return parts


def _soccer_context_line(team_id: str, team_name: str, standings: dict) -> str:
    """
    サッカー1チーム分の、AIに渡す状況。

    MLB用をそのまま当てていたので、「所属地区不明」と「ゲーム差」が
    サッカーの試合に出ていた。どちらもサッカーには無い概念で、
    それを見たAIが「同地区内で1.0ゲーム差の3位同士」という、
    どこにも根拠の無い文を書いて公開された。

    開幕直後は順位そのものを渡さない。全チームが勝ち点0で並び、
    APIは得失点差などのタイブレークで順位を付けて返すだけなので、
    それを実力の順位として読ませると必ず作り話になる。
    ルール側(rule_soccer_table)と同じ境目で切る。
    """
    s = standings.get(team_id)
    if not s or (s.played or 0) < SOCCER_TABLE_MIN_MATCHES:
        return (f"{team_name}: 今季の順位表はまだ意味を持つ段階にない"
                "(開幕直後のため順位には触れないこと)")
    if s.division_rank == 1:
        rank_part = "リーグ首位"
    else:
        rank_part = f"リーグ{s.division_rank}位"
        if s.points_back is not None:
            rank_part += f"(首位との勝ち点差{s.points_back:.0f})"
    return f"{team_name}: {rank_part}、{s.played}試合消化"


def _build_ai_prompt(game: dict, standings: dict) -> str:
    line = (_soccer_context_line if is_soccer_league(game.get("league"))
            else _team_context_line)
    home_context = line(
        game["home_team_id"], game["home_team_name"], standings
    )
    away_context = line(
        game["away_team_id"], game["away_team_name"], standings
    )

    structural_notes = []
    soccer = is_soccer_league(game.get("league"))
    if soccer:
        # サッカーには地区が無い。MLB用の地区の話をそのまま通すと、
        # 「同地区内で対峙する」という存在しない構図が書かれる。
        structural_notes.append(
            f"{game['league']}は1部リーグの総当たり戦であり、地区や"
            "カンファレンスの区分は無い。「同地区」「地区首位」といった"
            "言い方はこの競技には存在しないので使わないこと")
        structural_notes.append(
            "順位の差は勝ち点で表す。「ゲーム差」は野球の言い方なので"
            "使わないこと")
    home_div = MLB_DIVISIONS.get(game["home_team_id"]) if not soccer else None
    away_div = MLB_DIVISIONS.get(game["away_team_id"]) if not soccer else None
    if home_div and away_div:
        if home_div == away_div:
            structural_notes.append(
                f"両チームとも{MLB_DIVISION_NAME_JP.get(home_div, '同じ地区')}に所属する"
                "同地区対決であり、順位を直接争う関係にある"
            )
        else:
            # 別地区であることを明示しないと、両チームの順位(1位/2位など)を
            # 見たAIが「同じ地区で首位を争っている」かのような誤った文章を
            # 書いてしまう(実際に発生した)。
            structural_notes.append(
                f"{game['home_team_name']}は"
                f"{MLB_DIVISION_NAME_JP.get(home_div, '不明')}、"
                f"{game['away_team_name']}は"
                f"{MLB_DIVISION_NAME_JP.get(away_div, '不明')}と、"
                "所属地区が異なるため、両チームは地区順位を直接争う関係にはない"
            )
    pair = frozenset({game["home_team_id"], game["away_team_id"]})
    rivalry_type = MLB_RIVALRIES.get(pair)
    if rivalry_type == "historic":
        structural_notes.append("歴史的に有名なライバルカードである")
    elif rivalry_type == "city":
        structural_notes.append("同都市・近郊に本拠地を置くチーム同士の対決である")
    # ライバル関係の由来。AIが自前の知識で歴史を語ると不確かなことを
    # 書きかねないので、書いてよい内容をこちらから渡す。
    rivalry_note = MLB_RIVALRY_NOTES.get(pair)
    if rivalry_note:
        structural_notes.append(f"このカードの由来: {rivalry_note}")

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

    def _pitcher_line(p, team_name):
        if not p or not p.get("name"):
            return None
        bits = [f"{team_name}先発: {p['name']}"]
        detail = []
        if p.get("era") is not None:
            detail.append(f"今季防御率{p['era']}")
        if p.get("wins") is not None and p.get("losses") is not None:
            detail.append(f"{p['wins']}勝{p['losses']}敗")
        if p.get("strikeouts") is not None:
            detail.append(f"{p['strikeouts']}奪三振")
        if detail:
            bits.append("(" + "、".join(detail) + ")")
        return "".join(bits)

    pitcher_lines = [
        line
        for line in (
            _pitcher_line(game.get("home_probable"), game["home_team_name"]),
            _pitcher_line(game.get("away_probable"), game["away_team_name"]),
        )
        if line
    ]
    pitcher_text = (
        "\n【先発予定投手】\n" + "\n".join(f"- {l}" for l in pitcher_lines) + "\n"
        if pitcher_lines
        else ""
    )

    log_notes = game.get("log_notes") or []
    log_text = ""
    if log_notes:
        log_text = (
            "\n【その日ならではの見どころ(試合ログから確認済みの事実)】\n"
            + "\n".join(f"- {n}" for n in log_notes)
            + "\n"
        )

    venue_text = ""
    if game.get("venue_note"):
        venue_text = (
            f"\n【球場の特徴(小さな見どころとして使ってよい)】\n"
            f"- 会場は{game.get('venue_jp')}。{game['venue_note']}\n"
        )
        # その年の全試合から集計した実測値。「打者有利とされる」で終わらせず、
        # 実際どうなのかまで書けるようにする。
        if game.get("venue_runs_note"):
            venue_text += f"- {game['venue_runs_note']}\n"

    return (
        f"以下は「{game['matchup']}」({game['league']})という試合についてのデータです。\n\n"
        f"【チームの状況】\n{home_context}\n{away_context}\n"
        f"{pitcher_text}"
        f"{log_text}"
        f"{venue_text}\n"
        f"【構造的な位置づけ】\n{structural_text}\n\n"
        f"【この試合が注目された理由(ルールベースで抽出)】\n{reasons_text}\n"
        f"{highlight_line}\n"
        # 競技で言い換える。サッカーの試合にも「MLB/野球初心者にも」
        # 「先発投手の投げ合い」「本塁打が出やすい球場」と書かせていた。
        + (f"あなたは{'サッカー' if soccer else 'MLB/野球'}初心者にも"
           "分かりやすく解説するスポーツ記者です。") +
        "以下の2つを、上記のデータだけを根拠に日本語で書いてください。\n\n"
        "【出力1: 解説文】\n"
        f"「シーズン全体・{game['league']}全体で見たときに、"
        "この一戦になぜ注目すべきか」を"
        "3〜4文で説明する文章。250文字から320文字に収めること。\n"
        "この文章はサイト本文として読まれるので、短すぎると物足りない。"
        + ("上に与えたデータのうち、順位・昨季の成績・所属する日本人選手など、"
           "使えるものはできるだけ拾って厚みを出すこと。"
           if soccer else
           "上に与えたデータのうち、順位・連勝連敗・先発投手の成績・"
           "球場の特徴・選手の記録など、使えるものはできるだけ拾って"
           "厚みを出すこと。") +
        "ただし320文字を超えると、続けて書くフック文が書けなくなるので"
        "必ず収めること。\n"
        "構成は「大きな注目理由(順位争い・両チームの立場など、試合全体の意味)」を"
        "先に述べ、最後の1文で「小さな見どころ(試合を見ている間に注目できる"
        "具体的なポイント)」を添えること。"
        + ("" if soccer else
           "先発投手の投げ合いや球場の特徴が提供されている場合は、"
           "それを最後の見どころとして使うと良い"
           "(例:「本塁打が出やすい球場での一戦だけに、"
           "一発が出るかにも注目したい」)。") + "\n"
        "解説文の中で、読者がここだけ読めば要点が掴めるという箇所を1〜2箇所選び、"
        "その部分だけを【】で囲むこと(例: 【首位と2.0ゲーム差】で並ぶ両者が)。"
        "囲むのは10〜20文字程度の短い語句にとどめ、文全体を囲まないこと。\n\n"
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
        # 22日分を数えたら、13本に「〜だろう」「予想される」、5本に
        # 「正念場」「危機一髪」「圧倒的」「絶好調」が残っていた。
        # 出力側でも弾くが(forbidden_wording)、まずここで断っておく。
        "- 結果を言い当てないこと。「〜だろう」「予想される」「必至」"
        "  「間違いなく」は使わない。見どころは「〜に注目したい」"
        "  「〜がどうなるか」のように、問いの形で書くこと\n"
        "- 数字の裏付けなしに良し悪しを断じないこと。「圧倒的」「驚異的」"
        "  「絶好調」「最強」「正念場」「危機一髪」「崖っぷち」は使わない。"
        "  数字を並べれば、読んだ人がそう感じるかどうかは読んだ人が決める\n"
        "- 「有名選手が揃っている」「注目の一戦だ」のような、データを言い換えた"
        "  だけの薄い文章は禁止。必ず具体的な数字や、上記の構造的な位置づけを"
        "  組み込むこと\n"
        "- 所属地区を取り違えないこと。上記【チームの状況】に各チームの所属地区を"
        "  明記してあるので、別々の地区のチーム同士を「同地区で首位を争っている」"
        "  かのように書くことは絶対に禁止\n"
        # 開幕直後のサッカーで、渡していない順位を勝手に書いた実例がある。
        # 「順位表はまだ意味を持つ段階にない」と渡したにもかかわらず、
        # 「同地区内で1.0ゲーム差の3位同士」という文が公開された。
        "- 【チームの状況】に「順位表はまだ意味を持つ段階にない」と書かれている"
        "  場合、今季の順位・勝ち点・勝ち点差・ゲーム差には一切触れないこと。"
        "  昨季の順位など、与えられている材料だけで書くこと\n"
        "- 順位差を誇張しないこと。地区首位のチームについては2位との差を明記して"
        "  あるので、大差をつけて独走している場合に「首位の座が危うい」「正念場」"
        "  のような、事実と食い違う煽り方をしないこと\n"
        "- 連勝・連敗は、上記データに書かれている場合のみ言及すること。"
        "  「連勝・連敗はしていない」と書かれているチームについて、"
        "  勝手に連勝中・連敗中と書かないこと\n"
        "- 選手名を勝手にカタカナへ変換しないこと。上記データで日本語表記に"
        "  なっている選手はその表記をそのまま使い、英語表記(アルファベット)で"
        "  与えられている選手は英語表記のまま書くこと。英語名を自分でカタカナに"
        "  読み替えると、日本のメディアで使われている表記と食い違い"
        "  (例: Skubalを「スカブル」と書いてしまう等)、読者に伝わらなくなる\n"
        "- 出力2のフック文は、体言止めでも構わないが、意味の通る完結した一言に"
        "  すること。単語を並べただけの、途中で切れたように読める書き方は禁止\n"
        "- 出力1の文体は理路整然とした説明口調にすること。「〜だよ！」「〜だね！」の"
        "  ような話し言葉・感嘆符での締めは禁止。「〜である」「〜になる」のような"
        "  落ち着いた書き言葉で書くこと\n"
        + (f"- {'サッカー' if soccer else '野球'}初心者にも伝わるよう、"
           "専門用語を使う場合は軽く説明を添えること\n") +
        "- 見出しや記号(・や「」)は使わず、文章のみを出力すること\n"
        "- 公式ハイライト動画のタイトルが提供されている場合、そこから伝わる"
        "  文脈(注目プレーの内容など)は参考にしてよいが、タイトルの文言を"
        "  そのまま引用せず、必ず自分の言葉で言い換えること\n\n"
        "出力形式(厳守): まず出力1の文章のみを書き、次の行に半角記号で"
        "「---HOOK---」とだけ書いた行を挟み、最後に出力2のフック文を1行で"
        "書くこと。それ以外の見出しや前置き・番号は一切付けないこと。"
    )


# 書いてはいけない語。
#
# 「数えたことしか言わない」がこのチャンネルの立ち位置なので、
# 数字の裏付けなしに良し悪しを断じる語と、結果を言い当てる語は使わない。
# 見どころを述べるのは構わないが、「〜に注目したい」「〜がどうなるか」と
# 問いの形にすれば、事実の記述のまま同じことが言える。
FORBIDDEN_WORDING = [
    # 結果の予測
    "だろう", "予想される", "はずだ", "に違いない", "と思われる",
    "見込まれる", "必至", "間違いなく",
    # 数字を伴わない評価
    "圧倒的", "驚異的", "絶好調", "最強", "正念場", "危機一髪",
    "崖っぷち", "独壇場",
]

# サッカーの文に出てはいけない、野球の語。
FORBIDDEN_SOCCER_WORDS = ["ゲーム差", "地区", "完封", "先発投手",
                          "球場", "本塁打", "打率", "防御率"]


def forbidden_wording(text: str, soccer: bool = False) -> list:
    """その文に含まれる、使ってはいけない語を返す。"""
    if not text:
        return []
    words = list(FORBIDDEN_WORDING)
    if soccer:
        words += FORBIDDEN_SOCCER_WORDS
    return [w for w in words if w in text]


def _call_ai(prompt: str, api_key: str, max_tokens: int = 700):
    """
    1回分のAPI呼び出し。

    戻り値: (text, cost_usd, in_tok, out_tok, truncated)
      truncated … 上限に当たって出力が途中で切れたか。Trueなら文の途中で
      終わっている可能性が高いので、呼び出し側でそのまま公開してはいけない。
    """
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
        truncated = message.stop_reason == "max_tokens"
        if truncated:
            print(
                f"[warn] 出力がmax_tokens({max_tokens})に達して途中で切れました。"
                "壊れた文を公開しないよう、この試合の生成結果は破棄します"
            )
        return ai_text, cost_usd, usage.input_tokens, usage.output_tokens, truncated
    except Exception as e:
        print(f"[warn] AI呼び出しに失敗、この試合はルールベースの理由のみ使用します: {e}")
        return None, 0, 0, 0, False


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


def collect_log_notes(game: dict, season: str) -> list:
    """
    試合ログ由来の見どころを集める。API呼び出しを抑えるため、
    先発予定投手と、その試合に絡む日本人選手だけを対象にする。
    game_log_notes モジュールが読み込めない場合は静かに空を返す。
    """
    import os
    import sys as _sys

    # notability_engine.py はリポジトリ直下、モジュールは scripts/ にあるため
    # 明示的にパスを通す(実行時のカレントディレクトリに依存させない)
    scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    try:
        import game_log_notes as gln
    except ImportError as e:
        print(f"[warn] game_log_notes を読み込めませんでした: {e}")
        return []

    notes = []

    # 先発予定投手
    for key, team_key in (("home_probable", "home_team_id"), ("away_probable", "away_team_id")):
        p = game.get(key)
        if p and p.get("player_id"):
            notes.extend(
                gln.detect_pitching_notes(
                    p["player_id"], p.get("name", ""), game.get(team_key, ""), season
                )
            )

    # この試合に絡む日本人打者。先発投手として既に見た選手は重複するので除く。
    # 対象を絞らないと1試合で何度もAPIを叩くことになるため、上限も設ける。
    seen = {
        (game.get(k) or {}).get("name")
        for k in ("home_probable", "away_probable")
    }
    checked = 0
    for name in (game.get("jp_players") or []):
        if checked >= 2:
            break
        if name in seen:
            continue
        info = JP_PLAYER_LOOKUP.get(name)
        if not info or not info.get("player_id"):
            continue
        checked += 1
        notes.extend(
            gln.detect_hitting_notes(
                info["player_id"], name, info.get("team_id", ""), season
            )
        )

    return notes[:3]


# フック文として短すぎるものの下限。実データ上、正常に生成されたフック文は
# 26〜53文字に収まっていたのに対し、上限で切れたものは9〜14文字だった。
# stop_reasonでの判定が主で、これは念のための二段目の網。
MIN_HOOK_CHARS = 15


def _clean_hook(hook_part: str) -> str:
    """
    フック文を、通知・SNS・動画へそのまま流せる形に整える。

    ここで整えておけば、送信側(send_onesignal / post_bluesky)それぞれで
    同じ処理を書かずに済む。短すぎるものは、途中で切れた残骸である可能性が
    高いので捨て、送信側のルールベースへフォールバックさせる。
    """
    hook = hook_part.strip().strip("「」").strip()
    # 解説文の要点強調に使う【】が、フック文側へ混ざってくることがある
    hook = hook.replace("【", "").replace("】", "")
    # 複数行で返してきた場合は先頭行だけ使う
    hook = hook.splitlines()[0].strip() if hook else ""
    if len(hook) < MIN_HOOK_CHARS:
        if hook:
            print(f"[warn] フック文が短すぎるため破棄します({len(hook)}文字): {hook}")
        return ""
    return hook


def enhance_games_with_ai(
    output: dict, standings: dict, api_key: str, count: int = 3
) -> None:
    """上位N試合(注目試合のみ、理由が空でないもの)にAI要約を追加する"""
    games = output.get("games", [])
    targets = [
        g for g in games if g.get("is_notable") and g.get("reasons")
    ][:count]

    total_cost = 0.0
    succeeded = 0
    season = None
    for game in targets:
        # 先発投手の今季成績を、AI要約を作る試合についてだけ取得する
        # (全試合ぶん取るとAPI呼び出しが1日30回近くに増えるため、
        #  実際に文章化する上位数試合に絞っている)。
        if season is None:
            season = (output.get("generated_at") or "")[:4] or None
        for key in ("home_probable", "away_probable"):
            p = game.get(key)
            if not p or not p.get("player_id") or p.get("era") is not None:
                continue
            stats = fetch_pitcher_season_stats(p["player_id"], season or "")
            if stats:
                p.update(stats)

        # 試合ログから「その日ならではの見どころ」を拾う。
        # 条件を満たさなければ何も返らないので、毎日必ず出るものではない。
        game["log_notes"] = collect_log_notes(game, season or "")

        prompt = _build_ai_prompt(game, standings)
        ai_text, cost_usd, in_tok, out_tok, truncated = _call_ai(prompt, api_key)
        total_cost += cost_usd

        # 書いてはいけない語が入っていたら、1度だけ書き直させる。
        #
        # 禁止事項はプロンプトに並べてあるが、守られたかは誰も見ていなかった。
        # 実際、22日分のうち13本に「〜だろう」「予想される」、5本に
        # 「正念場」「危機一髪」「圧倒的」「絶好調」が残っていた。
        # どれも数字の裏付けが無い評価と予測で、このチャンネルが
        # 「数えたことしか言わない」と名乗る根拠を静かに削っていた。
        #
        # 頼むだけでなく、出力を見て弾く。1回の書き直しで直らなければ
        # AIの文は捨てて、ルールベースの理由文だけで出す。
        bad = forbidden_wording(ai_text, is_soccer_league(game.get("league")))
        if bad and not truncated:
            print(f"[info] 書き直し: {game['matchup']} に "
                  f"{'・'.join(bad)} が入っていました")
            retry = prompt + (
                "\n\n【書き直しの指示】\n"
                f"前回の出力に「{'」「'.join(bad)}」が含まれていました。"
                "これらは数字の裏付けが無い評価・予測なので使えません。"
                "同じ内容を、与えられた数字と事実だけで書き直してください。"
                "見どころは「〜に注目したい」「〜がどうなるか」のように、"
                "結果を言い当てない形で書くこと。")
            ai_text, c2, in_tok, out_tok, truncated = _call_ai(retry, api_key)
            total_cost += c2
            if forbidden_wording(ai_text, is_soccer_league(game.get("league"))):
                print(f"[warn] {game['matchup']}: 書き直しでも直らないため、"
                      "AIの文は使いません")
                continue

        # 途中で切れた出力は、文としても事実としても壊れている可能性がある。
        # 「検証できることしか書かない」以前に「読める文しか出さない」ため、
        # 部分的に使うことはせず丸ごと捨てて、ルールベースへ委ねる。
        if truncated:
            continue
        if not ai_text:
            continue

        # "---HOOK---" を境に、解説文(ai_summary)と通知用フック文
        # (notification_hook)に分割する。AIが区切りを守らなかった場合は
        # 全文をai_summaryとして扱い、フック文は無し(送信側でルール
        # ベースにフォールバックする)扱いにする。
        if "---HOOK---" in ai_text:
            summary_part, _, hook_part = ai_text.partition("---HOOK---")
            game["ai_summary"] = summary_part.strip()
            hook_clean = _clean_hook(hook_part)
            if hook_clean:
                game["notification_hook"] = hook_clean
        else:
            game["ai_summary"] = ai_text.strip()

        succeeded += 1
        print(
            f"[info] AI要約生成: {game['matchup']} "
            f"(入力{in_tok}トークン/出力{out_tok}トークン、概算${cost_usd:.5f}、"
            f"解説{len(game.get('ai_summary') or '')}文字)"
        )

    if targets:
        print(f"[info] 今回のAI要約合計コスト: 概算${total_cost:.5f}"
              f"({succeeded}/{len(targets)}試合成功)")

    # AIが全滅したことに気付けるようにする。
    # 残高切れ・APIキー失効はどれも例外として握り潰されるため、放っておくと
    # 「ワークフローは成功しているのに中身だけ静かに劣化する」状態になる。
    # ワークフローのログにGitHub Actionsの注釈として出し、生成物にも残す。
    output["ai_status"] = {
        "targets": len(targets),
        "succeeded": succeeded,
        "cost_usd": round(total_cost, 5),
    }
    if targets and succeeded == 0:
        print("::error title=AI要約が全滅::"
              "AI要約が1件も生成できませんでした。Anthropicの残高・APIキーを"
              "確認してください(サイトはルールベースの文章で更新されています)")
    elif succeeded < len(targets):
        print(f"::warning title=AI要約が一部失敗::"
              f"{len(targets)}試合中{len(targets) - succeeded}試合でAI要約を"
              "生成できませんでした")


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

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 日次アーカイブ(評価用・将来的な自前データソース化のため蓄積する)
    if not args.mock:
        import pathlib

        archive_dir = pathlib.Path("archive")
        archive_dir.mkdir(exist_ok=True)
        archive_path = archive_dir / f"{date_str}.json"

        # 同じ日に競技ごとに実行するので、上書きではなく足し込む。
        #
        # MLBとサッカーを別々に取るようにした時点で、後から走った方が
        # その日のアーカイブを丸ごと置き換えてしまう状態になっていた。
        # アーカイブはページ・選手ページ・週次・答え合わせの全部が読む
        # 元データなので、消えると1日分がまとめて欠ける。
        #
        # 同じ game_id は新しい方で差し替える(結果の追記で上書きされる)。
        merged = {}
        if archive_path.exists():
            try:
                old = json.loads(archive_path.read_text(encoding="utf-8"))
                for g in old.get("games", []):
                    if g.get("game_id"):
                        merged[g["game_id"]] = g
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] 既存のアーカイブを読めませんでした: {e}")
        for g in result.get("games", []):
            if g.get("game_id"):
                merged[g["game_id"]] = g

        archived = dict(result)
        archived["games"] = sorted(
            merged.values(),
            key=lambda g: (g.get("start_time_jst") or "99/99 99:99"))
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archived, f, ensure_ascii=False, indent=2)
        print(f"[info] アーカイブに保存しました: {archive_path} "
              f"(今回{len(result.get('games', []))}件 / 合計{len(merged)}件)")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
