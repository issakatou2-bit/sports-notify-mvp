"""
Blueskyへ注目試合を自動投稿するスクリプト。

Blueskyを選ぶ理由: X(旧Twitter) APIは2026年2月に無料枠が完全終了し従量課金制に
なったが、Bluesky(AT Protocol)は審査なし・無料のまま使える。個人開発の
自動投稿にはBlueskyの方が現実的。

前提:
  - pip install atproto (requirements.txt参照)
  - 環境変数 BLUESKY_HANDLE (例: collespo.bsky.social)
  - 環境変数 BLUESKY_APP_PASSWORD
    (Blueskyの 設定 > プライバシーとセキュリティ > アプリパスワード で発行)

使い方:
  BLUESKY_HANDLE=xxx BLUESKY_APP_PASSWORD=yyy SITE_URL=https://collespo.com/ python3 scripts/post_bluesky.py

注意:
  send_onesignal.pyと同じ考え方(上位2〜3試合・今日/明日の動的判定・AIの
  短いフック文優先/無ければルールベースにフォールバック)に揃えている。
  リンクは client_utils.TextBuilder を使い、実際にタップできるリンクとして
  投稿する(単純な文字列でtext=を渡すだけだとURLがクリックできない
  プレーンテキスト扱いになるため)。
"""

import json
import os
import sys


SITE_URL = os.environ.get("SITE_URL", "https://collespo.com/")

# Blueskyの投稿上限は300グラフェム。安全マージンを見て280までに収める
MAX_POST_GRAPHEMES = 280


# ハッシュタグにする選手名の上限。多すぎるとスパム的に見えるため絞る。
MAX_PLAYER_TAGS = 3


def collect_hashtags(games: list) -> list:
    """
    表示する試合群から、ハッシュタグにする値を集める。

    含めるのは「先発予定の日本人選手」と「その試合の両チームに所属している
    日本人選手」。所属選手まで含めるのは、本文でも名前に触れている以上、
    タグにしても誤情報にはならないため(タグは『所属している』ことを示すだけで、
    出場・スタメンを保証するものではない)。
    なお打者のスタメン情報は、MLB Stats APIでは試合開始の1〜2時間前にしか
    公表されず、19時JSTの生成時点では存在しないため使えない。

    順序は jp_players 側で「先発予定が先頭」に並べてあるので、上限で切っても
    重要な選手が残るようになっている。
    """
    names: list = []
    for g in games:
        for name in g.get("jp_players") or []:
            if name and name not in names:
                names.append(name)
        # jp_playersが無い古いデータ向けのフォールバック
        for p in g.get("jp_starters") or []:
            name = p.get("name")
            if name and name not in names:
                names.append(name)

    leagues: list = []
    for g in games:
        league = g.get("league")
        if league and league not in leagues:
            leagues.append(league)

    return names[:MAX_PLAYER_TAGS] + leagues


def build_rule_based_hook(game: dict) -> str:
    """
    AIのフック文(notification_hook)が無い場合のフォールバック。
    send_onesignal.pyのbuild_rule_based_hookと同じロジック。
    """
    jp_starters = game.get("jp_starters") or []
    if jp_starters:
        names = "・".join(p["name"] for p in jp_starters)
        return f"{names}が先発予定"

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
    """1試合分の1行。'23:10 CWS vs HOU 村上の一発は出るか、HOUは5連勝中' の形。"""
    matchup = game.get("abbr_matchup") or game["matchup"]
    hook = game.get("notification_hook") or build_rule_based_hook(game)
    start = game.get("start_time_jst")
    time_part = ""
    if start and " " in start:
        time_part = start.split(" ")[1] + " "
    return f"{time_part}{matchup} {hook}"


def today_or_tomorrow_label(top_game: dict) -> str:
    """
    投稿時点のJST日付と、試合のstart_time_jstの日付を比較し、
    「今日」か「明日」かを動的に判定する(send_onesignal.pyと同じ考え方)。
    """
    import datetime

    start = top_game.get("start_time_jst")
    if not start:
        return "注目試合"
    try:
        month, day = start.split(" ")[0].split("/")
        jst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        if int(month) == jst_now.month and int(day) == jst_now.day:
            return "今日の注目試合"
        return "明日の注目試合"
    except (ValueError, IndexError):
        return "注目試合"


def load_notable_games(path: str, limit: int = 3):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    games = data.get("games", [])
    return [g for g in games if g.get("is_notable")][:limit]


def build_post_body(notable_games: list, hashtags_display: str) -> str:
    """
    上位試合を使って本文を組み立てる。ハッシュタグ・URL分の文字数も
    差し引いた上で、300グラフェムを超える場合は試合数を1件ずつ減らして
    収まるまで組み直す(それでも1件だけは必ず残す)。
    """
    label = today_or_tomorrow_label(notable_games[0])
    games = list(notable_games)
    reserved = len(hashtags_display) + len(SITE_URL) + 4  # 改行・スペース分の余裕
    while True:
        lines = [label] + [game_line(g) for g in games]
        text = "\n".join(lines)
        if len(text) + reserved <= MAX_POST_GRAPHEMES or len(games) <= 1:
            return text
        games = games[:-1]


def main():
    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        print("[info] BLUESKY_HANDLE/BLUESKY_APP_PASSWORD未設定のためスキップします")
        return

    notable_games = load_notable_games("notable_games.json", limit=3)
    if not notable_games:
        print("[info] 今日は注目試合が無いため投稿をスキップします")
        return

    hashtags = collect_hashtags(notable_games)
    hashtags_display = " ".join(f"#{t}" for t in hashtags)
    body_text = build_post_body(notable_games, hashtags_display)

    try:
        from atproto import Client, client_utils

        client = Client()
        client.login(handle, app_password)
        builder = client_utils.TextBuilder().text(body_text + "\n")
        for t in hashtags:
            builder = builder.tag(f"#{t} ", t)
        builder = builder.link(SITE_URL, SITE_URL)
        client.send_post(builder)
        print("[info] Blueskyに投稿しました")
    except Exception as e:
        print(f"[warn] Bluesky投稿に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
