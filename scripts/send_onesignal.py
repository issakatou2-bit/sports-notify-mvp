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

import argparse
import pathlib
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
    # 解説文の要点強調に使う【】がフック文へ混ざることがあるため、
    # プレーンテキストで表示される通知・SNS投稿では取り除く。
    hook = hook.replace("【", "").replace("】", "")
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


def _time_sort_key(g: dict) -> str:
    return g.get("start_time_jst") or "99/99 99:99"


def sort_for_display(games: list) -> list:
    """
    「どの試合を選ぶか」はスコア順のまま行い、この関数は選出済みの試合群を
    「どの順に見せるか」だけ時系列に並べ替える(見せ方の問題であって、
    選出ロジックには影響させない)。
    """
    return sorted(games, key=_time_sort_key)


def split_by_league(games: list) -> tuple:
    """試合群をMLBとそれ以外(5大リーグ)に分ける。"""
    mlb = [g for g in games if g.get("league") == "MLB"]
    soccer = [g for g in games if g.get("league") != "MLB"]
    return mlb, soccer


def send_one(app_id: str, api_key: str, tag_key: str, games: list, heading_suffix: str) -> bool:
    """
    指定したタグ(mlb/soccer)が'1'の購読者にだけ、その競技の上位試合を送る。
    そのタグが一度も設定されていない(=この機能追加前からの古い購読者で、
    まだページを再訪問していない)人には、この絞り込みでは届かない。
    再訪問時にindex.html側で自動的にタグが補完されるため、時間が経てば
    解消される想定。
    戻り値: 成功したらTrue(対象0件でスキップした場合もTrue扱い)、
    送信自体に失敗した場合のみFalse。
    """
    if not games:
        print(f"[info] {tag_key}: 今回は通知対象の試合が無いためスキップします")
        return True

    label = today_or_tomorrow_label(games[0])
    display_games = sort_for_display(games)
    body_text = "\n".join(game_hook_line(g) for g in display_games)

    payload = {
        "app_id": app_id,
        "filters": [{"field": "tag", "key": tag_key, "relation": "=", "value": "1"}],
        "headings": {"ja": f"コレスポ {label}({heading_suffix})！", "en": "Kollespo Picks"},
        "contents": {"ja": body_text, "en": body_text},
        "url": SITE_URL,
    }

    print(f"[info] {tag_key}: {len(games)}試合を、タグ {tag_key}=1 の購読者へ送信します")

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

        # 成否の判定は「通知IDが返ったか」で行う。
        # filtersを使った送信では、配信数(recipients)がその場では返らず、
        # IDだけが返ることがある。recipientsの有無で判定すると、
        # 正常に送れているのに失敗扱いしてしまう(実際に発生した)。
        errors = result.get("errors")
        notification_id = result.get("id")

        if errors:
            print(f"[warn] {tag_key}: OneSignalがエラーを返しました -> {errors}",
                  file=sys.stderr)
            return False

        if not notification_id:
            print(f"[warn] {tag_key}: 通知IDが返りませんでした。"
                  f"応答: {result}", file=sys.stderr)
            return False

        recipients = result.get("recipients")
        if recipients is None:
            # 配信数は後から確定するため、この時点では分からないことがある。
            # 実際に何人へ届いたかはOneSignalのDelivery画面で確認できる。
            print(f"[info] {tag_key}向けに通知を作成しました"
                  f"(ID: {notification_id} / 配信数は集計中)")
        elif recipients == 0:
            print(f"[warn] {tag_key}: 条件に一致する購読者が0人でした。"
                  f"タグ({tag_key}=1)が付いているか確認してください。")
        else:
            print(f"[info] {tag_key}向けに通知を送信しました(配信対象: {recipients}件)")
        return True
    except Exception as e:
        print(f"[warn] {tag_key}向けの通知送信に失敗しました: {e}", file=sys.stderr)
        return False


def main():
    # 競技ごとに別ファイルへ分かれたので、両方を読む。
    # 片方だけ渡すと、その競技のタグを付けている購読者には何も届かない。
    # 通知そのものは send_one がタグごとに分けて送るので、
    # ここで混ざっても購読者の受け取りは分かれたままになる。
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", action="append", default=None,
                    help="注目試合のJSON。複数回指定できる")
    args = ap.parse_args()

    app_id = os.environ.get("ONESIGNAL_APP_ID")
    api_key = os.environ.get("ONESIGNAL_REST_API_KEY")
    if not app_id or not api_key:
        print("[info] ONESIGNAL_APP_ID/ONESIGNAL_REST_API_KEY未設定のためスキップします")
        return

    notable_games = []
    for path in (args.games or ["notable_games.json"]):
        if pathlib.Path(path).exists():
            notable_games.extend(load_notable_games(path, limit=4))
        else:
            print(f"[info] {path} が無いため飛ばします")
    if not notable_games:
        print("今日は通知対象の試合がありません。送信をスキップします。")
        return

    mlb_games, soccer_games = split_by_league(notable_games)
    ok1 = send_one(app_id, api_key, "mlb", mlb_games[:2], "MLB")
    ok2 = send_one(app_id, api_key, "soccer", soccer_games[:2], "5大リーグ")
    if not (ok1 and ok2):
        sys.exit(1)


if __name__ == "__main__":
    main()
