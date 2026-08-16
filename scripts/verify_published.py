#!/usr/bin/env python3
"""
その回で出るはずだった動画が、本当に出たかを確かめる。

なぜ要るのか:
  配信の各ステップは continue-on-error にしてある。1つの失敗で
  その日の成果物すべてを落とさないためで、これは正しい。
  ただし副作用として、動画が1本も出ていない回も実行は緑になる。

  実際、8/16の再実行は緑で終わったのに動画は上がっていなかった。
  気付いたのは翌朝の健康診断ではなく、こちらが手で調べたときだった。

  そこで、最後にここを通す。作れなかったのなら赤くする。
  途中は止めない、最後に落とす。順序はそのままで、結果だけ正直になる。

使い方:
  python3 scripts/verify_published.py --kind daily
  python3 scripts/verify_published.py --kind daily_soccer --allow-missing
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

RECORD = "data/published_videos.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True,
                    help="published_videos.json の区分 (daily / daily_soccer など)")
    ap.add_argument("--record", default=RECORD)
    ap.add_argument("--allow-missing", action="store_true",
                    help="出ていなくても赤くしない(記録だけ残す)")
    args = ap.parse_args()

    day = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    try:
        rec = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] {args.record} を読めませんでした: {e}")
        rec = {}

    entry = (rec.get(args.kind) or {}).get(day)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")

    if entry and entry.get("video_id"):
        line = (f"{day} の {args.kind}: 出ました "
                f"https://www.youtube.com/watch?v={entry['video_id']}")
        print(f"[info] {line}")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"## 動画\n\n{line}\n\n{entry.get('title','')}\n\n")
        return 0

    line = f"{day} の {args.kind} が出ていません。"
    print(f"[error] {line}")
    print("       上のステップのどれかが失敗しています。"
          "音声(VOICEVOX)・ナレーション・アップロードの順に見てください。")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## 動画が出ていません\n\n{line}\n\n"
                    "配信の各ステップは失敗しても止まらない作りなので、"
                    "この実行自体は緑に見えることがあります。"
                    "上のステップの警告を確認してください。\n\n")
    return 0 if args.allow_missing else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
