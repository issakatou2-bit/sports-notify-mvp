#!/usr/bin/env python3
"""
アメリカの州境を1度だけ取ってきて、リポジトリに残す。

なぜ取りに行くのか:
  最初は海岸線を手で書いた60点の多角形で持っていた。全体を見せる
  ぶんには足りるが、州へ寄ると輪郭が粗いままで、どこを見ているのか
  分からなくなる。州境があれば、寄っても位置の手がかりが残る。

なぜ1度だけなのか:
  毎日の動画生成で外部へ取りに行くと、その日に相手が落ちていれば
  動画が作れない。州境は変わらないので、取ってコミットしておけば
  以後は通信が要らない。数年に一度、気が向いたら取り直せばよい。

出どころ:
  Natural Earth (naturalearthdata.com)。パブリックドメインで、
  出典表示すら求められていない。地図製作者の団体が公開している、
  この種のデータの定番。

間引きについて:
  縦1080pxの画面に描くので、0.1度(およそ10km)より細かい凹凸は
  1ピクセルにもならない。落としても見た目は変わらず、
  ファイルは10分の1になる。

使い方:
  python3 scripts/fetch_map_data.py --out data/us_states.json
"""

import argparse
import json
import math
import pathlib
import sys

import requests

URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
       "master/geojson/ne_110m_admin_1_states_provinces.geojson")
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# 本土だけ。アラスカとハワイは離れすぎていて、同じ画面に置くと
# 本土が小さくなる。プエルトリコも同じ理由で外す。
SKIP = {"US-AK", "US-HI", "US-PR", "US-VI", "US-GU", "US-MP", "US-AS"}

# 間引きの粗さ(度)。0.1度はおよそ10km。
TOLERANCE = 0.1


def simplify(points: list, tol: float) -> list:
    """
    近すぎる点を落とす。

    Douglas-Peucker ではなく、前の点からの距離で切る素朴なやり方。
    州境は元から粗い(110m縮尺)ので、これで十分に形が残る。
    """
    if len(points) < 3:
        return points
    out = [points[0]]
    for x, y in points[1:-1]:
        px, py = out[-1]
        if math.hypot(x - px, y - py) >= tol:
            out.append((x, y))
    out.append(points[-1])
    return out if len(out) >= 3 else points


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/us_states.json")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = ap.parse_args()

    try:
        r = requests.get(URL, headers=UA, timeout=120)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[error] 取得に失敗しました: {e}", file=sys.stderr)
        return 1

    states, raw_pts, kept_pts = [], 0, 0
    for f in data.get("features", []):
        pr = f.get("properties") or {}
        if (pr.get("adm0_a3") or pr.get("iso_a2")) not in ("US", "USA"):
            continue
        code = pr.get("iso_3166_2") or ""
        if code in SKIP:
            continue
        geom = f.get("geometry") or {}
        polys = (geom.get("coordinates") or [])
        if geom.get("type") == "Polygon":
            polys = [polys]
        rings = []
        for poly in polys:
            if not poly:
                continue
            # 外周だけ。穴(湖など)は描かない。
            ring = [(round(x, 3), round(y, 3)) for x, y in poly[0]]
            raw_pts += len(ring)
            ring = simplify(ring, args.tolerance)
            kept_pts += len(ring)
            if len(ring) >= 3:
                rings.append([[x, y] for x, y in ring])
        if rings:
            states.append({"code": code,
                           "name": pr.get("name") or "",
                           "rings": rings})

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "source": "Natural Earth (public domain) 1:110m admin-1",
        "tolerance_deg": args.tolerance,
        "states": states,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    size = p.stat().st_size / 1024
    print(f"[info] {len(states)}州 / 点 {raw_pts} -> {kept_pts} "
          f"({kept_pts / max(1, raw_pts) * 100:.0f}%) / {size:.0f}KB -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
