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


def build_rule_based_hook(game: dict) -> str:
    """
    AIのフック文(notification_hook)が無い場合のフォールバック。
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


def game_hook_line(game: dict) -> str:
    """1試合分の通知本文の1行を組み立てる。'23:10 CWS vs HOU 村上の一発は出るか、HOUは5連勝中' の形。"""
    matchup = game.get("abbr_matchup") or game["matchup"]
    hook = game.get("notification_hook") or build_rule_based_hook(game)
    start = game.get("start_time_jst")
    time_part = ""
    if start and " " in start:
        time_part = start.split(" ")[1] + " "  # 'MM/DD HH:MM' の 'HH:MM ' 部分だけ使う
    return f"{time_part}{matchup} {hook}"


def today_or_tomorrow_label(top_game: dict) -> str:
    """
    通知が実際に送られる(=この関数が呼ばれる)時点のJST日付と、試合の
    start_time_jst('MM/DD HH:MM')の日付を比較し、「今日」か「明日」かを
    動的に判定する。cronの実行遅延で日付を跨いだ場合でも自然な表現になる。
    タイトル行にそのまま使う想定なので、末尾に「の注目試合」まで含める。
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


def load_notable_games(path: str, limit: int = 2):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    games = data.get("games", [])
    notable = [g for g in games if g.get("is_notable")][:limit]
    return notable


def main():
    app_id = os.environ.get("ONESIGNAL_APP_ID")
    api_key = os.environ.get("ONESIGNAL_REST_API_KEY")
    if not app_id or not api_key:
        print("[info] ONESIGNAL_APP_ID/ONESIGNAL_REST_API_KEY未設定のためスキップします")
        return

    notable_games = load_notable_games("notable_games.json", limit=2)
    if not notable_games:
        print("今日は通知対象の試合がありません。送信をスキップします。")
        return

    label = today_or_tomorrow_label(notable_games[0])
    body_text = "\n".join(game_hook_line(g) for g in notable_games)

    payload = {
        "app_id": app_id,
        # 注意: OneSignalアプリの作成時期によって、標準セグメント名が異なる
        # (旧: "Subscribed Users" / 新: "Total Subscriptions")。実際に
        # ダッシュボードのSegments一覧に表示されている名前と一致させること。
        "included_segments": ["Total Subscriptions"],
        "headings": {"ja": f"コレスポ {label}！", "en": "Kollespo Picks"},
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
