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

  州境のほかに、**球場のまわりだけ**の細かい地図も作る。
  州の輪郭は10km単位なので、街まで寄るとただの直線になる。
  1:10m のデータから、30球場の半径55km以内だけを切り出して
  400mまで細かくすれば、街の形も湾の形も出る。全部入れると26MBだが、
  球場のまわりだけなら200KBで済む。

使い方:
  python3 scripts/fetch_map_data.py --out data/us_states.json
  python3 scripts/fetch_map_data.py --places data/us_places.json
"""

import argparse
import json
import math
import pathlib
import sys

import requests

BASE_10M = ("https://raw.githubusercontent.com/nvkelso/"
            "natural-earth-vector/master/geojson/")
URL = BASE_10M + "ne_110m_admin_1_states_provinces.geojson"
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


# 球場のまわりを描くための、細かいほうのデータ。
#
# 1:110m（州境）は10km単位なので、街のスケールへ寄ると直線になる。
# 1:10m は約1kmの精度で、フラッシング湾（幅3km）くらいなら形が出る。
PLACE_URLS = {
    "urban": BASE_10M + "ne_10m_urban_areas.geojson",
    "coast": BASE_10M + "ne_10m_coastline.geojson",
    "airports": BASE_10M + "ne_10m_airports.geojson",
}

# 球場から何km以内を残すか。画面に出るのはせいぜい20km四方だが、
# 端の形が切れていると「そこで陸が終わっている」ように見える。
PLACE_RADIUS_KM = 55

# 間引きの粗さ(度)。0.004度はおよそ400m。
PLACE_TOLERANCE = 0.004


def _km(lat1, lon1, lat2, lon2) -> float:
    """2点の距離。数十kmの範囲で使うので、平面で足りる。"""
    dy = (lat1 - lat2) * 111.0
    dx = (lon1 - lon2) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def ballparks(path: str = "data/team_topics.json") -> list:
    """30球場の座標。team_topics.py が既に取っているものを使う。"""
    try:
        rows = json.loads(pathlib.Path(path).read_text(
            encoding="utf-8")).get("topics") or []
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] {path} を読めません: {e}", file=sys.stderr)
        return []
    return [(t["map"]["lat"], t["map"]["lon"])
            for t in rows if (t.get("map") or {}).get("lat") is not None]


def _rings(geom: dict) -> list:
    """GeoJSON の形から、点の並びだけを取り出す。"""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        return [c[0]]
    if t == "MultiPolygon":
        return [poly[0] for poly in c]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def fetch_places(parks: list, out_path: str) -> int:
    """球場のまわりの、街・海岸線・空港を1つのファイルにまとめる。"""
    def near(lat, lon, r=PLACE_RADIUS_KM):
        return any(_km(lat, lon, a, b) <= r for a, b in parks)

    got = {"urban": [], "coast": [], "airports": []}
    for key, url in PLACE_URLS.items():
        print(f"[info] {key} を取得します")
        try:
            r = requests.get(url, headers=UA, timeout=300)
            r.raise_for_status()
            data = r.json()
        except Exception as e:                   # noqa: BLE001
            print(f"[warn] {key} を取れません: {e}", file=sys.stderr)
            continue
        feats = data.get("features") or []
        if key == "airports":
            for f in feats:
                pr = f.get("properties") or {}
                # 小さな飛行場まで出すと点だらけになる。定期便のある規模だけ。
                if pr.get("type") not in ("major", "mid"):
                    continue
                coords = (f.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 2:
                    continue
                lon, lat = coords[0], coords[1]
                if not near(lat, lon, 80):
                    continue
                got["airports"].append({
                    "name": pr.get("name") or "",
                    "iata": pr.get("iata_code") or "",
                    "lon": round(lon, 4), "lat": round(lat, 4)})
            continue

        closed = key == "urban"
        for f in feats:
            for ring in _rings(f.get("geometry") or {}):
                if closed:
                    # 街は塗るので、形を切ると崩れる。丸ごと残すか捨てるか。
                    if not any(near(pt[1], pt[0]) for pt in ring[::3]):
                        continue
                    line = simplify([[round(pt[0], 4), round(pt[1], 4)]
                                     for pt in ring], PLACE_TOLERANCE)
                    if len(line) >= 3:
                        got[key].append(line)
                else:
                    # 海岸線は長くつながっているので、近いところだけ切り出す。
                    cur = []
                    for pt in ring:
                        if near(pt[1], pt[0]):
                            cur.append([round(pt[0], 4), round(pt[1], 4)])
                        else:
                            if len(cur) >= 3:
                                got[key].append(
                                    simplify(cur, PLACE_TOLERANCE))
                            cur = []
                    if len(cur) >= 3:
                        got[key].append(simplify(cur, PLACE_TOLERANCE))

    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "source": "Natural Earth (public domain) 1:10m",
        "radius_km": PLACE_RADIUS_KM,
        "tolerance_deg": PLACE_TOLERANCE,
        **got,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[info] 街{len(got['urban'])}／海岸線{len(got['coast'])}／"
          f"空港{len(got['airports'])} を書き出しました -> {out} "
          f"({out.stat().st_size / 1024:.0f}KB)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/us_states.json")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE)
    ap.add_argument("--places", default="",
                    help="球場まわりの細かい地図を、このパスへ書き出す")
    ap.add_argument("--teams", default="data/team_topics.json")
    args = ap.parse_args()

    # 球場のまわりだけを取る（--places）。州境とは別のファイルにする。
    # 州境は数年変わらないが、こちらは球場が移転したら取り直す。
    if args.places:
        parks = ballparks(args.teams)
        if not parks:
            print("[error] 球場の座標が読めないので作れません", file=sys.stderr)
            return 1
        print(f"[info] 球場{len(parks)}か所のまわり"
              f"{PLACE_RADIUS_KM}kmを切り出します")
        return fetch_places(parks, args.places)

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
