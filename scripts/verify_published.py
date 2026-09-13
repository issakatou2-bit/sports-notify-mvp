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

# 前日の記録を「この実行で出したもの」とみなす時間の幅。
#
# 19時の枠がJST 0時台に走ることがある（GitHubのscheduleは2〜4時間
# 遅れる）。5時間あれば、その遅れを吸収できる。
# **これ以上広げない。**前日の朝に出したものまで拾うと、
# 今日1本も出ていない日を緑にしてしまう。
RECENT_HOURS = 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True,
                    help="published_videos.json の区分 (daily / daily_soccer など)")
    ap.add_argument("--record", default=RECORD)
    ap.add_argument("--allow-missing", action="store_true",
                    help="出ていなくても赤くしない(記録だけ残す)")
    args = ap.parse_args()

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    day = now.strftime("%Y-%m-%d")
    try:
        rec = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] {args.record} を読めませんでした: {e}")
        rec = {}

    rows = rec.get(args.kind) or {}
    entry = rows.get(day)

    # **日をまたいだ実行を、欠けと数えない。**
    #
    # 9/13の19時の枠が、GitHubのscheduleの遅れでJST 00:30に走った。
    # 動画は9/13の日付で作られて投稿されたのに、確認はJST 00:42に
    # 「9/14のdailyはあるか」と探して、無いので赤くした。
    # その回は**9本すべて出ていた。**
    #
    # 日付ではなく、**記録された時刻がこの実行の少し前か**で見る。
    # 前日の記録でも、いま投稿したばかりなら「出た」でよい。
    # 逆に前日の朝に出したものは拾わない（RECENT_HOURSで切る）。
    if not (entry and entry.get("video_id")):
        prev = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        cand = rows.get(prev) or {}
        at = cand.get("published_at") or ""
        try:
            posted = datetime.fromisoformat(at.replace("Z", "+00:00"))
            hours = (now - posted.astimezone(jst)).total_seconds() / 3600
        except (ValueError, TypeError):
            hours = None
        if cand.get("video_id") and hours is not None                 and 0 <= hours <= RECENT_HOURS:
            print(f"[info] {day} の記録はありませんが、{prev} の分を"
                  f"{hours:.1f}時間前に出しています。"
                  "実行が日をまたいだものとして扱います。")
            entry, day = cand, prev

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
