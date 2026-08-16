"""
Blueskyへ注目試合を自動投稿するスクリプト。

Blueskyを選ぶ理由: X(旧Twitter) APIは2026年2月に無料枠が完全終了し従量課金制に
なったが、Bluesky(AT Protocol)は審査なし・無料のまま使える。個人開発の
自動投稿にはBlueskyの方が現実的。

本文の組み立ては post_common.py に置いてある。投稿先が増えても、
増えるのはこのファイルのような「送信部分」だけで済むようにしている。

前提:
  - pip install atproto (requirements.txt参照)
  - 環境変数 BLUESKY_HANDLE (例: collespo.bsky.social)
  - 環境変数 BLUESKY_APP_PASSWORD
    (Blueskyの 設定 > プライバシーとセキュリティ > アプリパスワード で発行)

使い方:
  BLUESKY_HANDLE=xxx BLUESKY_APP_PASSWORD=yyy python3 scripts/post_bluesky.py

注意:
  リンクは client_utils.TextBuilder を使い、実際にタップできるリンクとして
  投稿する(単純な文字列でtext=を渡すだけだとURLがクリックできない
  プレーンテキスト扱いになるため)。
"""

import argparse
import os
import sys

import post_common

# Blueskyの投稿上限は300グラフェム。安全マージンを見て280までに収める
MAX_POST_GRAPHEMES = 280


def emit_x_text(games: list) -> None:
    """
    Xへ貼るための本文を、実行ページに出す。

    Blueskyの投稿を手でコピーしてXへ貼る運用だが、Xは日本語を
    1文字2として数えるので、同じ本文はほぼ必ず溢れる(実測354/280)。
    毎日その場で削るのは手間なので、収まる形をここに出しておく。
    Bluesky側は3試合のまま短くしない。読める場所で削る理由が無い。
    """
    text, weight = post_common.build_post_for_x(games)
    if not text:
        return
    print("\n--- X用(そのまま貼れます) ---")
    print(text)
    print(f"--- {weight}/{post_common.X_LIMIT} ---")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Xへ貼る本文\n\n"
                    f"Xの数え方で {weight}/{post_common.X_LIMIT}。"
                    "そのまま貼れます。\n\n"
                    f"```\n{text}\n```\n\n")


def main():
    # 競技ごとに別の投稿にする。MLBは「明日」、欧州サッカーは「今夜」で、
    # 1つにまとめるとどちらかの言い方が必ず嘘になる。
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="notable_games.json")
    args = ap.parse_args()

    # 300グラフェムまで入るので、収まる範囲で複数試合を載せる。
    # (以前Xの文字数に合わせて1試合に固定していたが、Xは手動投稿なので
    #  自動投稿側をXの制限に合わせる必要はなかった)
    games = post_common.load_notable_games(args.games, limit=3)
    if not games:
        print("[info] 今日は注目試合が無いため投稿をスキップします")
        return

    # X用の本文は、Blueskyへ送れるかどうかに関係なく出す。
    # 手で貼るためのものなので、こちらの認証とは無関係。
    emit_x_text(games)

    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        print("[info] BLUESKY_HANDLE/BLUESKY_APP_PASSWORD未設定のためスキップします")
        return

    body, hashtags, site_url = post_common.build_post(games, MAX_POST_GRAPHEMES)

    try:
        from atproto import Client, client_utils

        client = Client()
        client.login(handle, app_password)
        builder = client_utils.TextBuilder().text(body + "\n")
        for t in hashtags:
            builder = builder.tag(f"#{t} ", t)
        builder = builder.link(site_url, site_url)
        client.send_post(builder)
        print("[info] Blueskyに投稿しました")
    except Exception as e:
        print(f"[warn] Bluesky投稿に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
