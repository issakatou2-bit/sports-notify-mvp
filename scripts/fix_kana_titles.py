#!/usr/bin/env python3
"""公開済みの題に残っているカナ表記を、漢字に直す。

なぜ要るのか:
  ハイライトの題を訳すとき「選手名はカタカナにする」と頼んでいた。
  外国人選手にはそれでよいが、日本人選手まで
  「ムネタカ・ムラカミが歴史的快挙を達成し」になっていた。
  その訳がそのまま動画の題になり、公開されている。

  題に日本人選手の名前があるかどうかで、8/11〜9/8の実測では
  再生が2.8倍(395対192)、登録者が12人対0人。だが
  **「ムネタカ・ムラカミ」では、検索にも記憶にも届かない。**

  作り方は9/7に直した(`mentioned.to_kanji`)。すでに出たものは
  古い題のまま残るので、同じ変換をかけて揃える。

どこまでやるか:
  **題だけ。**説明欄もタグも触らない。動画そのものも触らない。
  既定は下読み。実行ページに「いま」と「こう」を並べて出すので、
  見てから --write でもう一度動かす。

  記録に残っていない動画は `--video` で名指しする。
  9/7の長編がこれに当たる（同じ日に2本上がって記録が上書きされた）。
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import mentioned  # noqa: E402
from retitle import client  # noqa: E402

VIDEOS = "data/published_videos.json"


def targets(path: str = VIDEOS) -> list:
    """記録の中から、題が変わるものを拾う。"""
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for kind, days in d.items():
        if not isinstance(days, dict):
            continue
        for day, v in sorted(days.items()):
            if not isinstance(v, dict) or not v.get("video_id"):
                continue
            now = v.get("title") or ""
            fixed = mentioned.to_kanji(now)
            if fixed != now:
                out.append({"id": v["video_id"], "kind": kind, "day": day,
                            "now": now, "fixed": fixed})
    return out


def one(yt, vid: str) -> dict:
    """名指しの1本。記録に無い動画のため、YouTubeから題を引く。"""
    r = yt.videos().list(part="snippet", id=vid).execute()
    items = r.get("items") or []
    if not items:
        print(f"[warn] 動画が見つかりません: {vid}")
        return {}
    sn = items[0].get("snippet") or {}
    now = sn.get("title") or ""
    fixed = mentioned.to_kanji(now)
    if fixed == now:
        print(f"[info] {vid} は直すところがありません")
        return {}
    return {"id": vid, "kind": "(名指し)", "day": "-",
            "now": now, "fixed": fixed, "snippet": sn}


def apply(yt, row: dict) -> bool:
    """題だけ差し替える。説明欄もタグも、いまのものを引き継ぐ。"""
    sn = row.get("snippet")
    if sn is None:
        r = yt.videos().list(part="snippet", id=row["id"]).execute()
        items = r.get("items") or []
        if not items:
            print(f"[warn] 動画が見つかりません: {row['id']}")
            return False
        sn = items[0].get("snippet") or {}
    body = dict(sn)
    body["title"] = row["fixed"]
    yt.videos().update(part="snippet",
                       body={"id": row["id"], "snippet": body}).execute()
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="付けないと、下読みだけ")
    ap.add_argument("--video", action="append", default=[],
                    help="記録に無い動画を名指しで足す（何度でも）")
    args = ap.parse_args()

    yt = client()
    rows = targets()
    if args.video:
        if not yt:
            print("[info] 名指しの分は、YouTubeに繋がらないと引けません")
        else:
            have = {r["id"] for r in rows}
            for vid in args.video:
                if vid in have:
                    continue
                r = one(yt, vid)
                if r:
                    rows.append(r)

    print("--- 題のカナ表記 ---")
    if not rows:
        print("  直すところはありません")
        return 0
    for r in rows:
        print("%s %-18s %s" % (r["day"], r["kind"], r["id"]))
        print("   いま: " + r["now"][:76])
        print("   こう: " + r["fixed"][:76])
    print()
    print("対象: %d本" % len(rows))
    if not args.write:
        print("下読みだけです。実際に変えるには --write を付けてください")
        return 0
    if not yt:
        return 1

    done = 0
    for r in rows:
        if apply(yt, r):
            done += 1
            print(f"[info] 直しました: {r['id']}")
    print(f"[info] {done}本の題を直しました")

    # 記録の側も揃える。次に見たとき差分が出ないように。
    try:
        p = pathlib.Path(VIDEOS)
        d = json.loads(p.read_text(encoding="utf-8"))
        for r in rows:
            v = (d.get(r["kind"]) or {}).get(r["day"])
            if isinstance(v, dict) and v.get("video_id") == r["id"]:
                v["title"] = r["fixed"]
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + chr(10),
                     encoding="utf-8")
        print("[info] 記録も揃えました")
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] 記録を直せませんでした: {e}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
