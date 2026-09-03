#!/usr/bin/env python3
"""
まだ出していない資産動画のトピックを1つ選ぶ。

なぜ要るのか:
  資産動画は実測で維持率76.3%。日次の倍以上まで見られている。
  ところが手で書いた24本を出し終えて在庫がゼロになり、
  いちばんよく見られている種類が止まっていた。

  球場のトピックは venue_topics.py が公式APIから作るので、
  玉は増え続ける。あとは毎日1本ずつ出せばよい。

選び方:
  **実測でよく見られている種類から先に出す。**

  キーの順（アルファベット）で出していた。そのせいで
  mlb_* → npb_* → soccer_* → team_* → venue_* の順になり、
  いちばん見られている球団ものが後回しになっていた。
  28日の実測（40本中、再生の取れた35本）:

      球団もの   16本  平均 207回
      サッカー    5本  平均  99回
      用語       11本  平均   8回
      球場        5本  平均   2回
      その他      3本  平均   3回

  26倍の差がついている。順番を変えるだけで、同じ本数から
  取れる再生が変わる。

  平均は毎日 data/analytics.json から数え直す。表に書き写すと
  古くなるし、書き写した時点の判断がコードに固定される。
  測れない種類（まだ1本も出していない）は、真ん中に置いて試す。

  同じ種類の中はキーの順。乱数を使わないのは、同じ日に2回
  走らせても同じ答えになるようにするため。
  投稿の記録は data/published_assets.json を見る。

  在庫が尽きたら空文字を返す。空を出したまま動画を作ると、
  何も無い動画が上がるので、呼ぶ側は必ず中身を見ること。

使い方:
  python3 scripts/next_asset.py            # 次に出すトピック名だけを表示
  python3 scripts/next_asset.py --report   # 残りの本数も出す
"""

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def published(path: str) -> set:
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set((d.get("assets") or {}).keys())


def kind_of(key: str) -> str:
    """トピックの種類。キーの頭で決まる（team_ana → team）。"""
    return (key or "").split("_")[0] or "?"


def measured(published_path: str, analytics_path: str) -> dict:
    """種類ごとの、実測の平均再生数。測れない種類は入らない。

    投稿の記録（トピック名→動画ID）と、再生数の記録（動画ID→再生）を
    突き合わせるだけ。**数えるのは毎日やり直す。**
    表に書き写すと、書き写した時点の判断がコードに固定される。
    """
    try:
        pub = (json.loads(pathlib.Path(published_path).read_text(
            encoding="utf-8")).get("assets") or {})
        days = json.loads(pathlib.Path(analytics_path).read_text(
            encoding="utf-8")).get("days") or {}
    except (OSError, json.JSONDecodeError):
        return {}
    if not days:
        return {}
    views = {v.get("video"): (v.get("views") or 0)
             for v in (days[sorted(days)[-1]].get("videos") or [])}
    got = {}
    for key, rec in pub.items():
        v = views.get((rec or {}).get("video_id"))
        if v is None:
            continue                 # まだ集計に入っていない（出したて）
        got.setdefault(kind_of(key), []).append(v)
    return {k: sum(g) / len(g) for k, g in got.items() if g}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--published", default="data/published_assets.json")
    ap.add_argument("--analytics", default="data/analytics.json")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    import generate_asset_video as gav

    done = published(args.published)
    todo = sorted(k for k in gav.LIST_TOPICS if k not in done)

    # よく見られている種類から先に。まだ測れない種類は真ん中に置く
    # （後回しにすると永久に測れないままになる）。
    avg = measured(args.published, args.analytics)
    mid = (sum(avg.values()) / len(avg)) if avg else 0.0
    todo.sort(key=lambda k: (-avg.get(kind_of(k), mid), k))

    if args.report:
        print(f"トピック {len(gav.LIST_TOPICS)}件 / 投稿済み {len(done)}件 / "
              f"残り {len(todo)}件")
        if avg:
            print("種類ごとの実測（28日）:")
            for k, v in sorted(avg.items(), key=lambda x: -x[1]):
                print(f"  {k:10s} 平均{v:6.0f}回")
        for k in todo[:10]:
            label = (gav.LIST_TOPICS[k].get("label") or k)
            print(f"  {k:28s} {label}")
        if len(todo) > 10:
            print(f"  … ほか{len(todo) - 10}件")

    nxt = todo[0] if todo else ""
    if not nxt:
        print("[info] 未投稿の資産動画はありません", file=sys.stderr)

    # ワークフローの次のステップへ渡す。
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"topic={nxt}\n")
            f.write(f"remaining={len(todo)}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## 今日の資産動画\n\n- トピック: `{nxt or '(在庫なし)'}`\n"
                    f"- 残り: {len(todo)}件\n\n")
    if not args.report:
        print(nxt)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
