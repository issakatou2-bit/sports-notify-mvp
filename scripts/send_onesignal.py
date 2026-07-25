"""
OneSignal経由で通知を送信するスクリプト。

これまでのsend_push.py(VAPID+pywebpush)は「1人分の購読情報を手動でSecretsに
登録する」個人利用限定の作りだった。OneSignalは購読者の保存・管理を代わりに
やってくれるサービスなので、これに乗り換えることで「誰でも通知を有効にできる」
状態を実現する。

前提:
  - OneSignalで無料アカウントを作成し、Web Push用のアプリを作成済みであること
  - 環境変数 ONESIGNAL_APP_ID (アプリ作成時に発行されるID)
  - 環境変数 ONESIGNAL_REST_API_KEY (Settings > Keys & IDs で発行)
  - notable_games.json (notability_engine.py の出力) が同じ作業ディレクトリにあること

注意:
  このコード実行環境はネットワーク無効のため、実際にOneSignal APIを叩いた
  検証はできていない。OneSignalの公式ドキュメントに基づく標準的な実装だが、
  実際に動かして初めて分かる差異が残っている前提で扱うこと。
"""

import json
import os
import sys

import requests


SITE_URL = os.environ.get(
    "SITE_URL", "https://REPLACE_WITH_YOUR_USERNAME.github.io/REPLACE_WITH_YOUR_REPO/"
)

ONESIGNAL_API_URL = "https://onesignal.com/api/v1/notifications"


def build_notification_headline(game: dict) -> str:
    """
    通知本文は「フックになる一言」に絞る(send_push.pyと同じロジック)。
    pywebpushへの依存を避けるためこちらにも複製している。
    優先順位: JP先発 > 伝統の好カード > 同都市対決 > 同地区対決 > 連勝/連敗 > その他
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

    return "詳細はアプリで確認してください"


def load_top_game(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    games = data.get("games", [])
    if not games:
        return None
    top = games[0]
    if not top.get("is_notable"):
        return None
    return top


def main():
    app_id = os.environ.get("ONESIGNAL_APP_ID")
    api_key = os.environ.get("ONESIGNAL_REST_API_KEY")
    if not app_id or not api_key:
        print("[info] ONESIGNAL_APP_ID/ONESIGNAL_REST_API_KEY未設定のためスキップします")
        return

    top_game = load_top_game("notable_games.json")
    if top_game is None:
        print("今日は通知対象の試合がありません。送信をスキップします。")
        return

    body_text = build_notification_headline(top_game)
    title_matchup = top_game.get("abbr_matchup") or top_game["matchup"]

    payload = {
        "app_id": app_id,
        "included_segments": ["Subscribed Users"],
        "headings": {"ja": f"今日の注目: {title_matchup}", "en": f"Today's Pick: {title_matchup}"},
        "contents": {"ja": body_text, "en": body_text},
        "url": SITE_URL,
    }

    try:
        resp = requests.post(
            ONESIGNAL_API_URL,
            headers={
                "Authorization": f"Basic {api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        recipients = result.get("recipients", "不明")
        print(f"[info] OneSignal経由で通知を送信しました(配信対象: {recipients}件)")
    except Exception as e:
        print(f"[warn] OneSignal通知の送信に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
