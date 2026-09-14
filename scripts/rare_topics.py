#!/usr/bin/env python3
"""名前のある指標から、資産動画のトピックを作る。

なぜ要るのか:
  資産動画の在庫が残り3件になっていた（76件のうち51件を投稿済み、
  見られていない種類を外すと3件）。毎日1本出しているので、
  このままだと3日で止まる。

  そして外したのは用語(平均8再生)と球場(4再生)とNPB(4再生)で、
  これは**承認済みの「入れ替え」の片側だけ**。替わりが要る。

  `rarity.py` が毎日、日本人選手の今季の指標と、規定到達者の中での
  順位を出している。村上宗隆のアダム・ダン率58.3%は137人中1位で、
  アダム・ダン本人の最高（2012年 56.7%）を上回っていた。
  **これは常緑もの向きの材料。**その日の勝敗と違って、
  あとから検索しても意味が変わらない。

出すもの:
  data/rare_topics.json に `{"topics": [...]}` の形で書く。
  generated_topics.SOURCES がこれを読むと、資産動画の在庫になる。
  1選手1本。**順位が取れた指標だけ**を並べる。

使い方:
  python3 scripts/rare_topics.py
  python3 scripts/rare_topics.py --rarity data/rarity.json --out data/rare_topics.json
"""

import argparse
import json
import pathlib

# 1項目でも出す。説明（指標の意味・順位・由来）がそれぞれ長いので
# 尺は持つし、**規定に届く日本人選手はそもそも少ない。**
# 2つ以上を条件にすると、在庫が1人ぶんしか残らなかった。
MIN_ITEMS = 1
MAX_ITEMS = 6       # 画面に並ぶ数の上限
TOP_AT = 3          # 何位までを「上位」と呼ぶか


def _rank_text(item: dict, min_pa, min_ip) -> str:
    """順位の書き方。**同率は「タイ」と書く。**

    全員が同じ値の指標で「1位」と言ったことがある。
    `ties` が1より大きいなら、単独ではない。
    """
    at, of = item.get("at"), item.get("of")
    if not at or not of:
        return ""
    gate = ("%d打席以上" % min_pa if item.get("group") == "hitting"
            else "%d回以上" % min_ip)
    tie = "タイ" if (item.get("ties") or 1) > 1 else ""
    side = "下から" if item.get("side") == "bottom" else ""
    return "%s%d人の中で%s%d位%s" % (gate, of, side, at, tie)


def _item(item: dict, min_pa, min_ip):
    """1項目。（見出し, 説明）のタプル。"""
    head = "%s %s" % (item.get("label") or "", item.get("shown") or "")
    bits = []
    if item.get("note"):
        bits.append(item["note"])
    rank = _rank_text(item, min_pa, min_ip)
    if rank:
        bits.append(rank)
    if item.get("namesake"):
        bits.append(item["namesake"])
    return (head.strip(), "。".join(bits))


def build(rarity: dict) -> list:
    """{"topics": [...]} に入れる中身。材料が無ければ空。"""
    min_pa = rarity.get("min_pa") or 300
    min_ip = rarity.get("min_ip") or 60
    out = []
    for name, row in (rarity.get("players") or {}).items():
        items = [i for i in (row.get("items") or []) if i.get("label")]
        if len(items) < MIN_ITEMS:
            continue
        pid = str(row.get("player_id") or "")
        if not pid:
            continue
        # いちばん上の順位を見出しに使う。**単独のものだけ。**
        best = min((i for i in items if (i.get("ties") or 1) == 1
                    and i.get("at")),
                   key=lambda i: i["at"], default=None)
        if best and best["at"] <= TOP_AT:
            hook = "%s %s、%d人中%d位" % (best.get("label"), best.get("shown"),
                                       best.get("of"), best["at"])
        else:
            hook = "%s の今季を数字で" % name
        out.append({
            "key": "rare_%s" % pid,
            "label": "%s 今季の指標" % name,
            "hook": hook,
            "heading": "%s、今季の数字" % name,
            "intro": "%s の今季を、名前のある指標で見ます。"
                     "順位はいずれも今季の規定到達者の中でのものです。"
                     % name,
            "items": [_item(i, min_pa, min_ip) for i in items[:MAX_ITEMS]],
        })
    out.sort(key=lambda t: t["key"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rarity", default="data/rarity.json")
    ap.add_argument("--out", default="data/rare_topics.json")
    args = ap.parse_args()

    try:
        rarity = json.loads(pathlib.Path(args.rarity).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print("[info] 指標を読めません(%s)。何も作りません" % e)
        return 0

    topics = build(rarity)
    if not topics:
        print("[info] 動画にできる選手がいません")
        return 0

    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": rarity.get("updated_at"),
         "season": rarity.get("season"), "topics": topics},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("%d人ぶんのトピックを書きました -> %s" % (len(topics), args.out))
    for t in topics:
        print("  %-16s %s" % (t["key"], t["hook"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
