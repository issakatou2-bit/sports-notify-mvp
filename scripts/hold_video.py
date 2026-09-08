#!/usr/bin/env python3
"""予約公開を取り消して、非公開に戻す。

なぜ要るのか:
  出した後に中身の誤りが分かった日に、**公開を止める手が無かった。**

  9/8、18:30公開予定の長編に「カブスは20本以上が5人」と入っていた。
  正しくは4人。移籍した選手の成績を二重に数えていたため
  (`mlb_splits` の説明を参照)。公開の1時間前に気づけたのに、
  止める道具が無いので、そのまま出すか作り直すかしか選べなかった。

  **消さない。**非公開に戻すだけなので、直したものと見比べられるし、
  取り違えて止めてしまってもすぐ戻せる。

使い方:
  python3 scripts/hold_video.py --video 7VMEC9txt0k          # 下読み
  python3 scripts/hold_video.py --video 7VMEC9txt0k --write  # 実際に止める
  python3 scripts/hold_video.py --video ... --release --write  # 公開に戻す
"""

import argparse
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
except ImportError:
    build = Credentials = None

TOKEN_URI = "https://oauth2.googleapis.com/token"


def client():
    if not build:
        print("[info] google-api-python-client がありません")
        return None
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="動画ID")
    ap.add_argument("--write", action="store_true",
                    help="付けないと、いまの状態を見るだけ")
    ap.add_argument("--release", action="store_true",
                    help="非公開を解いて、いますぐ公開する")
    args = ap.parse_args()

    yt = client()
    if not yt:
        return 1
    r = yt.videos().list(part="status,snippet", id=args.video).execute()
    items = r.get("items") or []
    if not items:
        print(f"[error] 動画が見つかりません: {args.video}")
        return 1
    v = items[0]
    st = dict(v.get("status") or {})
    title = (v.get("snippet") or {}).get("title") or ""
    print(f"題    : {title[:60]}")
    print(f"いま  : {st.get('privacyStatus')}"
          + (f" / 予約 {st.get('publishAt')}" if st.get("publishAt") else ""))

    want = "public" if args.release else "private"
    if st.get("privacyStatus") == want and not st.get("publishAt"):
        print(f"[info] すでに {want} です。何もしません")
        return 0
    print(f"こう  : {want}" + ("" if args.release else "（予約は取り消し）"))
    if not args.write:
        print()
        print("下読みだけです。実際に変えるには --write を付けてください")
        return 0

    # status を丸ごと置き換える。いま入っているものを土台にして、
    # 予約(publishAt)だけを外す。ここで body を空から組み立てると、
    # 子ども向け表示などの設定まで消える。
    st["privacyStatus"] = want
    st.pop("publishAt", None)
    yt.videos().update(part="status",
                       body={"id": args.video, "status": st}).execute()
    print(f"[info] {args.video} を {want} にしました")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
