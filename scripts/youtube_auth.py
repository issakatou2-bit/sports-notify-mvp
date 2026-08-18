#!/usr/bin/env python3
"""
YouTubeのリフレッシュトークンを取り直す。

なぜリポジトリに置くのか:
  これまで取得用のスクリプトが手元にしか無く、リポジトリに残っていなかった。
  権限を足したいときに「あのファイルはどこか」から始まるうえ、
  どのスコープで取ったのかが記録に残らない。

必要な権限:
  youtube.upload  … 動画の投稿(これまで取っていたのはこれだけ)
  youtube        … 再生リストの作成と追加

  再生リストが要るのは、ショートを見た人にチャンネルとして
  認識してもらうため。53本がバラバラに並ぶより、
  「毎日ここに増えている」が一覧で見える方が残ってもらえる。

事前に:
  pip install google-auth-oauthlib
  Google Cloud Console でOAuthクライアント(デスクトップアプリ)を作り、
  client_secret.json をダウンロードしておく。

使い方:
  py -3 scripts/youtube_auth.py --client-secret path/to/client_secret.json
"""

import argparse
import pathlib
import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    # 動画ごとの維持率と再生数を読むのに要る。
    # これまで Studio の画面から人が書き写していた。自動で残れば、
    # 「1枚目を変えた翌日に数字が動いたか」を機械的に比べられる。
    # 読み取り専用で、投稿や編集はできない。
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-secret", required=True,
                    help="Google Cloud Console から落とした client_secret.json")
    ap.add_argument("--port", type=int, default=8765,
                    help="認可の戻り先に使うローカルのポート")
    args = ap.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[error] google-auth-oauthlib が要ります")
        print("        pip install google-auth-oauthlib")
        return 1

    path = pathlib.Path(args.client_secret)
    if not path.exists():
        print(f"[error] {path} がありません")
        return 1

    print("要求する権限:")
    for s in SCOPES:
        print(f"  {s}")
    print("\nブラウザが開きます。コレスポのアカウントで許可してください。\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    # 再認可でもリフレッシュトークンを必ず返させる。
    # prompt=consent が無いと、2回目以降 refresh_token が空で返り、
    # 「取れたのに使えない」状態になる。
    creds = flow.run_local_server(port=args.port, prompt="consent",
                                  access_type="offline")

    if not creds.refresh_token:
        print("[error] リフレッシュトークンが返りませんでした。"
              "既存の許可を取り消してからやり直してください")
        print("        https://myaccount.google.com/permissions")
        return 1

    print("\n=== 取得できました ===")
    print(f"付与された権限: {' '.join(creds.scopes or [])}")
    print("\n--- GitHub Secrets に登録 ---")
    print(f"YOUTUBE_CLIENT_ID       = {creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET   = {creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN   = {creds.refresh_token}")
    print("--- ここまで ---")
    print("\nCLIENT_ID と CLIENT_SECRET が既に登録済みなら、"
          "REFRESH_TOKEN だけ差し替えれば足ります。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
