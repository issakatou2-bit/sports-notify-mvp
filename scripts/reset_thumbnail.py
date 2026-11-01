#!/usr/bin/env python3
"""
公開済みの動画にサムネイルを付け直す。

    python scripts/reset_thumbnail.py VIDEO_ID=画像.png [...] [--write]

なぜ要るか:
  投稿のあとのサムネイル設定は、失敗しても動画は出ているので警告で
  終わる。10/27 は使用枠切れで3本が付かないまま残った。
  付け直す手段が無いと、その動画は自動の切り出し絵のままになる。

既定は下読みだけ（どの動画にどの絵を付けるかを出す）。
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from retitle import client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pairs", nargs="+", help="VIDEO_ID=画像のパス")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--quota-warning", action="store_true",
                        help="自動付け直し用。枠切れなら警告で打ち切る")
    args = parser.parse_args()

    pairs = []
    for p in args.pairs:
        vid, _, path = p.partition("=")
        img = pathlib.Path(path)
        if not vid or not img.is_file():
            print(f"[error] 指定が読めないか画像がありません: {p}", file=sys.stderr)
            return 1
        pairs.append((vid, img))

    youtube = client()
    if youtube is None:
        return 1
    from googleapiclient.http import MediaFileUpload
    from thumbnail_pending import quota_exceeded

    # videos.list は他人の公開動画も返すので、存在確認だけでは所有確認にならない。
    try:
        owned = {item["id"] for item in youtube.channels().list(part="id", mine=True).execute().get("items", [])}
    except Exception as error:
        if args.quota_warning and quota_exceeded(error):
            print("[warn] 使用枠切れのため本日の付け直しを終了します。翌日へ持ち越しません")
            return 0
        raise

    failed = 0
    for vid, img in pairs:
        # 自分のチャンネルの動画かを先に確かめる（1単位）。番号の打ち間違いで
        # 他人の動画に向けて送らないため。
        try:
            items = youtube.videos().list(part="snippet", id=vid).execute().get("items", [])
        except Exception as error:
            if args.quota_warning and quota_exceeded(error):
                print("[warn] 使用枠切れのため本日の付け直しを終了します。翌日へ持ち越しません")
                return 0
            raise
        if not items:
            print(f"[error] 動画が見つかりません: {vid}", file=sys.stderr)
            failed += 1
            continue
        if items[0]["snippet"].get("channelId") not in owned:
            print(f"[error] 自分のチャンネルの動画ではありません: {vid}", file=sys.stderr)
            failed += 1
            continue
        title = items[0]["snippet"]["title"]
        print(f"[info] {vid}「{title}」← {img}")
        if not args.write:
            continue
        try:
            youtube.thumbnails().set(
                videoId=vid, media_body=MediaFileUpload(str(img), mimetype="image/png")
            ).execute()
        except Exception as error:
            if args.quota_warning and quota_exceeded(error):
                print("[warn] 使用枠切れのため本日の付け直しを終了します。翌日へ持ち越しません")
                return 0
            raise
        print(f"[info] サムネイルを設定しました: {vid}")
    if not args.write:
        print("[info] 下読みだけです。write を true にすると設定します")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
