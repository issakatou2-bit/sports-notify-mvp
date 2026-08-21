#!/usr/bin/env python3
"""
アナリティクスが取れなくなっていないかを見張る。

なぜ要るのか:
  取得のステップは continue-on-error にしてある。数字が取れない日に
  健康診断ごと落とす理由はないからで、そこは正しい。
  ただしそのぶん、取れていないことに誰も気づけない。

  実際 data/analytics.json は2026-08-19の1回きりで、そのあと2日ぶん
  静かに欠けていた。ワークフローは緑、動画も毎日出ている。
  数字を見ようとした日に初めて分かる。それでは、判断のもとが無い
  ままの期間ができる。

  落ちてもよいが、落ちたことは見えていなければならない。

使い方:
  python3 scripts/analytics_age.py            # 実行ページに書く
  python3 scripts/analytics_age.py --max-age 1
"""

import argparse
import datetime
import json
import os
import pathlib
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="data/analytics.json")
    ap.add_argument("--max-age", type=int, default=1,
                    help="これより古かったら警告する(日)")
    args = ap.parse_args()

    days = []
    p = pathlib.Path(args.path)
    if p.exists():
        try:
            days = sorted(json.loads(
                p.read_text(encoding="utf-8")).get("days") or {})
        except json.JSONDecodeError:
            pass

    today = datetime.date.today()
    if days:
        age = (today - datetime.date.fromisoformat(days[-1])).days
        newest = days[-1]
    else:
        age, newest = 999, "なし"

    msg = "アナリティクスの最新は %s(%d日前)" % (newest, age)
    print(msg)
    if days:
        print("残っている日: " + ", ".join(days[-5:]))

    stale = age > args.max_age
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and stale:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n> **%s。取得が効いていません。**\n" % msg)
    if stale:
        print("::error::" + msg)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
