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


# 日付が変わってから明け方までは、暦の上では翌日でも生活の感覚では
# 「今夜」の続き。欧州の試合は日本時間の深夜〜早朝に集中するので、
# ここを暦どおり「明日」と言うと、20時に見た人には遠い先の話に聞こえる。
# 日本のスポーツ報道も「あす未明」と呼ぶ。
#
# 6時にしている理由:
#   最初は9時にしていたが、それではMLBまで飲み込んだ。MLBの開始は
#   JST 01時〜11時で、07〜08時台に最も多い(実測94試合)。9時を境にすると
#   08:15開始の試合が「今夜」になり、19時に見た人に翌朝の試合を
#   「今夜」と言うことになる。実際、日次の見出しが全て「今夜の注目試合」
#   になっていた。
#   欧州の試合は21時〜翌6時なので、6時ならそちらは取りこぼさない。
LATE_NIGHT_UNTIL = 6  # この時刻より前は「未明」として扱う


def kickoff_parts(start_time_jst: str):
    """"08/23 04:00" を (月, 日, 時) に分解する。読めなければ None。"""
    try:
        date_part, time_part = str(start_time_jst).split(" ", 1)
        month, day = (int(x) for x in date_part.split("/"))
        hour = int(time_part.split(":")[0])
        return month, day, hour
    except (ValueError, IndexError, AttributeError):
        return None


def is_late_night(start_time_jst: str) -> bool:
    """その試合が日本時間の未明に始まるか。"""
    parts = kickoff_parts(start_time_jst)
    return bool(parts) and parts[2] < LATE_NIGHT_UNTIL


def when_label(start_time_jst: str) -> str:
    """
    投稿時点から見て、その試合がいつなのか。

    画面・読み上げ・SNS・サイトが別々にこれを決めると、同じ試合が
    片方で「今夜」もう片方で「明日」になる。必ずここを通す。
    """
    parts = kickoff_parts(start_time_jst)
    if not parts:
        return ""
    month, day, hour = parts
    now = datetime.now(timezone(timedelta(hours=9)))
    if month == now.month and day == now.day:
        return "今夜" if hour >= 18 else "今日"

    tomorrow = now + timedelta(days=1)
    if month == tomorrow.month and day == tomorrow.day:
        # 20時に見ている人にとって、翌4時は「今夜」の続き
        return "今夜" if hour < LATE_NIGHT_UNTIL else "明日"
    return ""


def overall_label(games) -> str:
    """
    その回の見出しに使う「いつ」。試合ごとではなく、まとまりで決める。

    1本の動画に、未明の試合と翌朝の試合が混ざることがある。
    上位1試合だけで決めると、たまたま深夜の試合が1位だった日に
    見出しが「今夜」に振れて、毎日の呼び方が安定しない。
    多数決にすれば、その回が実際どちらの塊なのかで決まる。
    """
    labels = [when_label(g.get("start_time_jst") or "") for g in (games or [])]
    labels = [x for x in labels if x]
    if not labels:
        return ""
    return max(set(labels), key=labels.count)


def today_or_tomorrow_label(games) -> str:
    """
    投稿時点から見た見出し。「今夜の注目試合」など。

    1試合でもリストでも受ける(呼び出し側が両方ある)。
    """
    if isinstance(games, dict):
        games = [games]
    label = overall_label(games)
    return f"{label}の注目試合" if label else "注目試合"


def kickoff_display(start_time_jst: str) -> str:
    """
    画面に出す時刻。未明の試合はそう書き添える。

    「8/23 4:00」だけだと、20時に見た人には翌日の昼と区別がつかない。
    """
    if not start_time_jst:
        return ""
    return (f"{start_time_jst}（未明）" if is_late_night(start_time_jst)
            else str(start_time_jst))


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
    label = today_or_tomorrow_label(games)
    kept = list(games)
    reserved = len(hashtags_display) + len(SITE_URL) + 4
    while True:
        text = "\n".join([label] + [game_line(g) for g in kept])
        if len(text) + reserved <= max_chars or len(kept) <= 1:
            break
        kept = kept[:-1]
    return "\n".join([label] + [game_line(g) for g in sort_for_display(kept)])


# Xの文字数の数え方。
#
# Xは280文字までだが、日本語は1文字を2として数えるので、日本語だけなら
# 実質140文字になる。Blueskyは300グラフェムで、日本語でもそのまま300。
# 同じ本文を手で貼り替えると毎回溢れるのはこのため。
#
# 1として数えられる範囲(それ以外は2):
#   U+0000-U+10FF / U+2000-U+200D / U+2010-U+201F / U+2032-U+2037
# URLは実際の長さに関係なく23として数えられる。
X_LIMIT = 280
X_URL_WEIGHT = 23
_X_SINGLE_RANGES = ((0x0000, 0x10FF), (0x2000, 0x200D),
                    (0x2010, 0x201F), (0x2032, 0x2037))


def x_weight(text: str) -> int:
    """Xでの文字数。日本語は1文字を2として数える。"""
    total = 0
    for ch in text or "":
        c = ord(ch)
        total += 1 if any(lo <= c <= hi for lo, hi in _X_SINGLE_RANGES) else 2
    return total


def build_post_for_x(games: list, news_path: str = "public/news.json"):
    """
    Xへ貼るための本文。収まるまで試合を1件ずつ減らす。

    Bluesky向けを手で削って貼る運用だったが、Xの数え方だと日本語の
    本文はほぼ必ず溢れる。削る作業を毎日やる意味が無いので、
    最初から収まる形を別に用意する。
    """
    kept = list(games)
    while kept:
        hashtags = collect_hashtags(kept)
        display = " ".join(f"#{t}" for t in hashtags)
        body = build_post_body(kept, display, 1000)
        text = f"{body}\n{display}\n{SITE_URL}"
        # URLは23として数えられるので、実文字数との差を引く
        weight = x_weight(text) - x_weight(SITE_URL) + X_URL_WEIGHT
        if weight <= X_LIMIT or len(kept) == 1:
            return text, weight
        kept = kept[:-1]
    return "", 0


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
