"""
Web Push通知を送信するスクリプト。GitHub Actionsから毎日19時(JST)に実行する想定。

前提(このサンドボックス環境はネットワーク無効のため未検証。GitHub Actionsの
実行環境はネットワークが使えるので、そちらで requirements.txt 経由の
pip install により動作する見込み):

  - pip install -r scripts/requirements.txt 済みであること
  - 以下の環境変数(GitHub Secrets)が設定されていること
      PUSH_SUBSCRIPTION : index.html で表示されたsubscription JSONそのもの
      VAPID_PRIVATE_KEY : generate_vapid_keys.py で生成した秘密鍵
      VAPID_SUBJECT     : mailto:自分のメールアドレス、またはhttps://のURL
  - notable_games.json (notability_engine.py の出力) が同じ作業ディレクトリにあること
"""

import json
import os
import sys

from pywebpush import webpush, WebPushException


SITE_URL = os.environ.get(
    "SITE_URL", "https://REPLACE_WITH_YOUR_USERNAME.github.io/REPLACE_WITH_YOUR_REPO/"
)


def load_top_game(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    games = data.get("games", [])
    if not games:
        return None
    top = games[0]
    # 全試合が含まれるようになったため、スコア0(理由なし)の試合が
    # 先頭に来てしまう場合は「注目試合が無い日」として扱う
    if not top.get("is_notable"):
        return None
    return top


def main():
    required_env = ["PUSH_SUBSCRIPTION", "VAPID_PRIVATE_KEY"]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        print(f"必要な環境変数が設定されていません: {missing}", file=sys.stderr)
        sys.exit(1)

    subscription_info = json.loads(os.environ["PUSH_SUBSCRIPTION"])
    vapid_private_key = os.environ["VAPID_PRIVATE_KEY"]
    vapid_subject = os.environ.get("VAPID_SUBJECT", "mailto:example@example.com")

    top_game = load_top_game("notable_games.json")
    if top_game is None:
        print("今日は通知対象の試合がありません。送信をスキップします。")
        return

    reasons = top_game.get("reasons", [])
    body_text = (
        top_game.get("ai_summary")
        or " / ".join(r["text"] for r in reasons[:2])
        or "詳細はアプリで確認してください"
    )
    title_matchup = top_game.get("abbr_matchup") or top_game["matchup"]

    payload = json.dumps(
        {
            "title": f"今日の注目: {title_matchup}",
            "body": body_text,
            "url": SITE_URL,
        },
        ensure_ascii=False,
    )

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": vapid_subject},
        )
        print("通知を送信しました:", top_game["matchup"])
    except WebPushException as ex:
        print("通知の送信に失敗しました:", repr(ex), file=sys.stderr)
        # 購読が失効している場合(410 Gone)などがここに来る。
        # 失効時は index.html で再購読が必要になる。
        sys.exit(1)


if __name__ == "__main__":
    main()
