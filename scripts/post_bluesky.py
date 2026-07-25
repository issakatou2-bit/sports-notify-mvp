"""
Blueskyへ今日の注目試合を自動投稿するスクリプト。

Blueskyを選ぶ理由: X(旧Twitter) APIは2026年2月に無料枠が完全終了し従量課金制に
なったが、Bluesky(AT Protocol)は審査なし・無料のまま使える。個人開発の
自動投稿にはBlueskyの方が現実的。

前提:
  - pip install atproto (requirements.txt参照)
  - 環境変数 BLUESKY_HANDLE (例: yourname.bsky.social)
  - 環境変数 BLUESKY_APP_PASSWORD
    (Blueskyの 設定 > プライバシーとセキュリティ > アプリパスワード で発行)

使い方:
  BLUESKY_HANDLE=xxx BLUESKY_APP_PASSWORD=yyy python3 scripts/post_bluesky.py
"""

import json
import os
import sys


SITE_URL = os.environ.get(
    "SITE_URL", "https://REPLACE_WITH_YOUR_USERNAME.github.io/REPLACE_WITH_YOUR_REPO/"
)

# Blueskyの投稿上限は300文字(グラフェム単位)。URL分の余裕を残して切り詰める
MAX_POST_CHARS = 260


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def build_post_text(top_game: dict) -> str:
    body = top_game.get("ai_summary") or (
        top_game.get("reasons", [{}])[0].get("text", "")
    )
    header = f"今日の注目試合: {top_game['matchup']}\n"
    # URL分(約25文字)を差し引いた長さに切り詰めてから、末尾にURLを付ける
    # (BlueskyはURLをテキスト内に書くと自動的にリンクとして認識する)
    reserved_for_url = len(SITE_URL) + 2
    truncated = truncate(header + body, MAX_POST_CHARS - reserved_for_url)
    return f"{truncated}\n{SITE_URL}"


def main():
    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        print("[info] BLUESKY_HANDLE/BLUESKY_APP_PASSWORD未設定のためスキップします")
        return

    with open("notable_games.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    games = data.get("games", [])
    top_game = next((g for g in games if g.get("is_notable")), None)
    if not top_game:
        print("[info] 今日は注目試合が無いため投稿をスキップします")
        return

    post_text = build_post_text(top_game)

    try:
        from atproto import Client

        client = Client()
        client.login(handle, app_password)
        client.send_post(text=post_text)
        print("[info] Blueskyに投稿しました")
    except Exception as e:
        print(f"[warn] Bluesky投稿に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
