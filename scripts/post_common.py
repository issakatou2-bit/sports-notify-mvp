"""
SNSへ投稿する本文の組み立て。送信先に依存しない部分だけを集めてある。

なぜ切り出したのか:
  これまで本文の作り方が post_bluesky.py の中に埋まっていた。
  Threads や Mastodon を足すときに、同じ組み立てをもう一度書くことになり、
  文面を直すたびに全部を直して回る必要が出る(そして必ずどれかが古くなる)。

  「何を書くか」をここに、「どこへ送るか」を各 post_*.py に分ける。
  投稿先が増えても、増えるのは送信部分だけになる。

文字数の上限は送信先ごとに違う(Blueskyは300グラフェム、Threadsは500文字)。
上限を引数で受け取り、収まるまで試合を1件ずつ減らす。
"""

import json
import os
from datetime import datetime, timedelta, timezone

SITE_URL = os.environ.get("SITE_URL", "https://collespo.com/")

# ハッシュタグにする選手名の上限。多すぎるとスパム的に見えるため絞る。
MAX_PLAYER_TAGS = 3


def load_notable_games(path: str, limit: int = 3) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return [g for g in data.get("games", []) if g.get("is_notable")][:limit]


def load_news(path: str = "public/news.json", limit: int = 2) -> list:
    """検証を通ったニュース。無ければ空(投稿は試合情報のみになる)。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return (json.load(f).get("news") or [])[:limit]
    except (json.JSONDecodeError, OSError):
        return []


def collect_hashtags(games: list) -> list:
    """
    ハッシュタグにする値を集める。

      1. 球団名 … 先頭(最注目)の試合の両チームのみ。全試合分を入れると
         6個になりタグだらけになる
      2. 日本人選手名 … 上限3人。本文でも名前に触れている以上、
         タグにしても誤情報にはならない(所属を示すだけで出場は保証しない)
      3. リーグ名 … 重複を除いて全部

    球団名は日本語表記を使う。読者が日本語話者中心で、
    日本語圏で実際に検索されているタグに合わせるため。
    """
    tags: list = []
    if not games:
        return tags

    top = games[0]
    for key in ("home_team_name", "away_team_name"):
        name = top.get(key)
        if name and name not in tags:
            tags.append(name)

    names: list = []
    for g in games:
        for name in g.get("jp_players") or []:
            if name and name not in names:
                names.append(name)
        for p in g.get("jp_starters") or []:
            name = p.get("name")
            if name and name not in names:
                names.append(name)
    tags.extend(n for n in names[:MAX_PLAYER_TAGS] if n not in tags)

    for g in games:
        league = g.get("league")
        if league and league not in tags:
            tags.append(league)
    return tags


def build_rule_based_hook(game: dict) -> str:
    """AIのフック文が無い場合のフォールバック。"""
    jp_starters = game.get("jp_starters") or []
    if jp_starters:
        return "・".join(p["name"] for p in jp_starters) + "が先発予定"
    if game.get("rivalry_type") == "historic":
        return "伝統の好カード"
    if game.get("rivalry_type") == "city":
        return "同都市対決"
    if game.get("same_division"):
        return "同地区対決の一戦"
    for r in game.get("reasons", []):
        if r.get("tag") == "streak":
            return r["text"]
    reasons = game.get("reasons", [])
    if reasons:
        return reasons[0]["text"]
    return "詳細はサイトで確認してください"


def game_line(game: dict) -> str:
    """1試合分の1行。'23:10 CWS vs HOU 村上の一発は出るか' の形。"""
    matchup = game.get("abbr_matchup") or game.get("matchup", "")
    hook = game.get("notification_hook") or build_rule_based_hook(game)
    # 解説文の要点強調に使う【】が混ざることがあるので取り除く。
    # ライバル関係の理由文は「見出し — 由来」の形なので見出しだけ使う。
    hook = hook.replace("【", "").replace("】", "").split(" — ")[0]
    start = game.get("start_time_jst")
    time_part = start.split(" ")[1] + " " if start and " " in start else ""
    return f"{time_part}{matchup} {hook}"


def today_or_tomorrow_label(top_game: dict) -> str:
    """投稿時点のJST日付と試合日を比べ、「今日」か「明日」かを決める。"""
    start = top_game.get("start_time_jst")
    if not start:
        return "注目試合"
    try:
        month, day = start.split(" ")[0].split("/")
        now = datetime.now(timezone(timedelta(hours=9)))
        if int(month) == now.month and int(day) == now.day:
            return "今日の注目試合"
        return "明日の注目試合"
    except (ValueError, IndexError):
        return "注目試合"


def sort_for_display(games: list) -> list:
    """どれを載せるかはスコア順で決め、見せる順だけ時系列に並べ替える。"""
    return sorted(games, key=lambda g: g.get("start_time_jst") or "99/99 99:99")


def build_post_body(games: list, hashtags_display: str, max_chars: int) -> str:
    """
    本文を組み立てる。ハッシュタグとURLの分も差し引いて上限に収める。
    収まらなければ試合を1件ずつ減らす(それでも1件は必ず残す)。
    間引きはスコアの低い末尾から行い、表示順だけ最後に時系列へ直す。
    """
    if not games:
        return ""
    label = today_or_tomorrow_label(games[0])
    kept = list(games)
    reserved = len(hashtags_display) + len(SITE_URL) + 4
    while True:
        text = "\n".join([label] + [game_line(g) for g in kept])
        if len(text) + reserved <= max_chars or len(kept) <= 1:
            break
        kept = kept[:-1]
    return "\n".join([label] + [game_line(g) for g in sort_for_display(kept)])


def build_post(games: list, max_chars: int, news_path: str = "public/news.json"):
    """
    投稿1件ぶんの材料をまとめて返す。

    戻り値: (本文, ハッシュタグのリスト, サイトURL)
    送信先ごとにタグやリンクの付け方が違うので、組み立て済みの
    1つの文字列ではなく、部品のまま渡す。
    """
    hashtags = collect_hashtags(games)
    display = " ".join(f"#{t}" for t in hashtags)
    body = build_post_body(games, display, max_chars)

    # 検証済みのニュースがあれば1件添える。文字数に収まる場合のみ。
    news = load_news(news_path)
    if news:
        candidate = body + "\n" + news[0]["text"]
        reserved = len(display) + len(SITE_URL) + 4
        if len(candidate) + reserved <= max_chars:
            body = candidate

    return body, hashtags, SITE_URL
