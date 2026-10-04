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
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
except ImportError:
    build = Credentials = None

TOKEN_URI = "https://oauth2.googleapis.com/token"


def target_status(current, release=False, publish_at=None):
    """確認済み非公開動画だけを未来の明示日時へ予約する。"""
    st = dict(current)
    if publish_at:
        if release or st.get("privacyStatus") != "private":
            raise ValueError("予約は非公開動画に限ります。releaseとは併用不可")
        at = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        if not at.tzinfo or at <= datetime.now(timezone.utc):
            raise ValueError("予約日時はタイムゾーン付きの未来時刻が必要です")
        if st.get("publishAt"):
            if datetime.fromisoformat(st["publishAt"].replace("Z", "+00:00")) != at:
                raise ValueError("既存の予約日時は変更しません")
            return st
        st["publishAt"] = at.astimezone(timezone.utc).isoformat()
    else:
        st["privacyStatus"] = "public" if release else "private"
        st.pop("publishAt", None)
    return st


def status_matches(saved, desired):
    if saved.get("privacyStatus") != desired.get("privacyStatus"):
        return False
    if bool(saved.get("publishAt")) != bool(desired.get("publishAt")):
        return False
    return not desired.get("publishAt") or (
        datetime.fromisoformat(saved["publishAt"].replace("Z", "+00:00")) ==
        datetime.fromisoformat(desired["publishAt"].replace("Z", "+00:00")))


def verify_status(yt, video_id, desired):
    """保存は繰り返さず、読み取りだけを最大4回照合する。"""
    saved = {}
    for attempt in range(4):
        if attempt:
            time.sleep(2)
        items = yt.videos().list(part="status", id=video_id).execute().get("items") or []
        saved = (items[0].get("status") or {}) if items else {}
        if status_matches(saved, desired):
            return saved
    raise ValueError("保存後の公開設定が一致しません: "
                     f"privacyStatus={saved.get('privacyStatus')}, publishAt={saved.get('publishAt')}")


def record_schedule(path, video_id, saved):
    """確認後の予約日時だけを同じ動画の台帳へ反映する。"""
    path = pathlib.Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    matching = [entry for dates in data.values() if isinstance(dates, dict)
                for entry in dates.values() if isinstance(entry, dict)
                and entry.get("video_id") == video_id]
    if not matching:
        raise ValueError("予約動画が配信台帳にありません。YouTubeの設定と台帳を個別確認してください")
    for entry in matching:
        entry["publish_at"] = saved["publishAt"]
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


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
    ap.add_argument("--publish-at", help="確認済み非公開動画の予約日時（タイムゾーン付きISO日時）")
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

    desired = target_status(st, args.release, args.publish_at)
    want = desired["privacyStatus"]
    if desired == st:
        if args.write and args.publish_at:
            record_schedule("data/published_videos.json", args.video, st)
            print(f"[info] 確認済み予約 {st['publishAt']} を台帳へ反映しました。YouTubeの再保存はありません")
            return 0
        print(f"[info] すでに {want} です。何もしません")
        return 0
    print(f"こう  : {want}" + (f" / 予約 {desired['publishAt']}" if args.publish_at else
                              ("" if args.release else "（予約は取り消し）")))
    if not args.write:
        print()
        print("下読みだけです。実際に変えるには --write を付けてください")
        return 0

    # status を丸ごと置き換える。いま入っているものを土台にして、
    # 予約(publishAt)だけを外す。ここで body を空から組み立てると、
    # 子ども向け表示などの設定まで消える。
    yt.videos().update(part="status",
                       body={"id": args.video, "status": desired}).execute()
    saved = verify_status(yt, args.video, desired)
    if args.publish_at:
        record_schedule("data/published_videos.json", args.video, saved)
    print(f"[info] {args.video} の保存後の設定を照合しました: {want}" +
          (f" / 予約 {saved['publishAt']}" if saved.get("publishAt") else ""))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
