#!/usr/bin/env python3
"""球団ごとの殿堂入り選手から、資産動画のトピックを作る。

なぜ要るのか:
  資産動画の在庫が5件になっていた。毎日1本出しているので5日で尽きる。
  ユーザーから「以前から言っていたはず」との指摘があった、いちばん古い宿題。

  **いちばん見られている種類は球団もの（28日で平均178再生）。**
  ただし30球団を出し切っていて、同じ材料からもう1本は作れない。

  ところが `data/team_legends.json` に、球団ごとの殿堂入り選手が
  通算成績つきで入っていて、**どこにも使われていなかった。**
  team_topics.json は `legends` を持っているが、動画の items には
  入れていない。27球団ぶんが丸ごと余っている。

  球団ものと同じ系統で、中身は重複しない。在庫が5件から32件になる。

名前について:
  殿堂入り選手は古いので、日本語表記のデータが無い。英語名のまま出す。
  **主役は通算成績の数字**なので、名前が英語でも中身は伝わる。
  日本語の表記が取れるようになったら、ここで差し替える。

使い方:
  python3 scripts/legend_topics.py
"""

import argparse
import json
import pathlib

MIN_PLAYERS = 1     # 1人でも出す。その1人の通算成績で1本ぶんになる
MAX_PLAYERS = 4     # 画面に並ぶ上限（generate_asset_video の描画に合わせる）


def build(legends: dict) -> list:
    """{"topics": [...]} に入れる中身。材料が無ければ空。"""
    out = []
    for team_id, row in (legends.get("teams") or {}).items():
        name = (row or {}).get("team") or ""
        players = [p for p in ((row or {}).get("players") or [])
                   if p.get("name")]
        if not name or len(players) < MIN_PLAYERS:
            continue
        items = []
        for p in players[:MAX_PLAYERS]:
            bits = []
            if p.get("hof_year"):
                bits.append("%s年に殿堂入り" % p["hof_year"])
            if p.get("line"):
                bits.append(p["line"])
            items.append([p["name"], "。".join(bits)])
        out.append({
            "key": "legend_%s" % team_id,
            "label": "%sの殿堂入り選手" % name,
            "hook": ("%sから殿堂入りした%d人" % (name, len(items))
                     if len(items) > 1
                     else "%sの殿堂入り選手" % name),
            "heading": "%s　殿堂入り" % name,
            "intro": "%s でプレーし、アメリカ野球殿堂に選ばれた選手を、"
                     "通算成績で見ます。" % name,
            "items": items,
        })
    out.sort(key=lambda t: t["key"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legends", default="data/team_legends.json")
    ap.add_argument("--out", default="data/legend_topics.json")
    args = ap.parse_args()

    try:
        legends = json.loads(pathlib.Path(args.legends).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print("[info] 殿堂入りの材料を読めません(%s)。何も作りません" % e)
        return 0

    topics = build(legends)
    if not topics:
        print("[info] 動画にできる球団がありません")
        return 0

    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": legends.get("updated_at"),
         "source": legends.get("source"), "topics": topics},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("%d球団ぶんのトピックを書きました -> %s" % (len(topics), args.out))
    for t in topics[:5]:
        print("  %-16s %s" % (t["key"], t["hook"]))
    if len(topics) > 5:
        print("  … ほか%d件" % (len(topics) - 5))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
