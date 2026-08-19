#!/usr/bin/env python3
"""
アメリカ本土の地図を線で描く。球団の場所を示すために使う。

なぜ自前で持つのか:
  地図の画像を使うと、出どころと利用条件を毎回確かめることになる。
  外部のGeoJSONを取りに行くと、その日にサービスが落ちていれば
  動画が作れない。ここでやりたいのは「だいたいどのあたりか」を
  伝えることだけなので、輪郭を粗い多角形で持てば足りる。

  海岸線の形そのものには著作権が無い。ここに書いてあるのは
  地図から読み取れる公知の座標で、誰が作っても同じものになる。

精度について:
  州境も五大湖も描かない。60点ほどの多角形で、
  「西海岸・南部・東海岸・五大湖のあたり」が分かればよい。
  縮尺を上げても輪郭は粗いままなので、寄ったときは
  輪郭を薄くして、球場の点の方を見せる。
"""

import math

# 本土のおおまかな輪郭。(緯度, 経度) を反時計回りに並べる。
OUTLINE = [
    # 西海岸(北から南へ)
    (48.4, -124.7), (46.3, -124.1), (43.3, -124.4), (40.4, -124.4),
    (38.9, -123.7), (37.8, -122.5), (36.3, -121.9), (34.4, -120.5),
    (33.7, -118.4), (32.5, -117.1),
    # 南の国境
    (32.7, -114.7), (31.3, -111.1), (31.3, -108.2), (31.8, -106.5),
    (29.8, -101.4), (28.0, -99.5), (25.9, -97.4),
    # メキシコ湾岸
    (27.8, -97.4), (29.7, -95.0), (29.6, -92.0), (29.2, -89.0),
    (30.4, -88.0), (30.4, -86.5), (30.1, -84.3), (29.1, -83.0),
    (27.8, -82.8), (26.0, -81.8), (25.1, -80.4),
    # 東海岸(南から北へ)
    (26.8, -80.0), (28.5, -80.5), (30.7, -81.5), (32.8, -79.9),
    (34.7, -76.5), (35.2, -75.5), (36.9, -76.0), (38.0, -75.2),
    (38.9, -74.9), (40.5, -74.0), (41.3, -71.9), (41.7, -70.0),
    (42.7, -70.8), (43.7, -70.0), (44.5, -67.9), (44.8, -67.0),
    # 北の国境(東から西へ)
    (45.3, -71.0), (45.0, -73.3), (44.0, -76.5), (43.3, -79.0),
    (42.3, -83.0), (43.6, -82.5), (45.0, -83.4), (45.9, -84.7),
    (46.5, -84.4), (46.9, -89.0), (46.7, -92.1), (48.0, -94.0),
    (49.0, -95.2), (49.0, -123.0),
]

# 画面へ落とすときの基準。本土がだいたい収まる範囲。
LAT_RANGE = (24.0, 50.0)
LON_RANGE = (-125.5, -66.5)


def project(lat: float, lon: float, w: int, h: int,
            center=None, zoom: float = 1.0) -> tuple:
    """
    緯度経度を画面の座標へ。zoom を上げると center を中心に寄る。

    経度の幅を cos(緯度) で縮めるのは、高い緯度ほど経度1度あたりの
    実距離が短いため。これをしないと北側が横に伸びて見える。
    """
    lat0 = (LAT_RANGE[0] + LAT_RANGE[1]) / 2
    k = math.cos(math.radians(lat0))
    cx = center[1] if center else (LON_RANGE[0] + LON_RANGE[1]) / 2
    cy = center[0] if center else lat0
    span_lon = (LON_RANGE[1] - LON_RANGE[0]) / zoom
    span_lat = span_lon * k * h / w
    x = (lon - cx) / span_lon * w + w / 2
    y = -(lat - cy) / span_lat * h + h / 2
    return x, y


def outline_points(w: int, h: int, center=None, zoom: float = 1.0) -> list:
    return [project(la, lo, w, h, center, zoom) for la, lo in OUTLINE]


# ---------------------------------------------------------------------------
# 州境。fetch_map_data.py が Natural Earth から取ってきたもの。
# 手書きの OUTLINE と違い、州の形が入っているので寄っても崩れない。
# ---------------------------------------------------------------------------

import functools
import json
import pathlib

STATES_PATH = "data/us_states.json"


@functools.lru_cache(maxsize=1)
def states(path: str = STATES_PATH) -> list:
    """[{"code","name","rings":[[[lon,lat],...],...]}, ...]。無ければ空。"""
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return d.get("states") or []


def state_polygons(w: int, h: int, center=None, zoom: float = 1.0,
                   margin: int = 400) -> list:
    """
    画面に落とした州の輪郭。画面から大きく外れたものは省く。

    寄ると49州のうち数州しか映らないので、全部を描き直すのは無駄。
    画面の外側 margin ピクセルまでを残す。
    """
    out = []
    for st in states():
        for ring in st["rings"]:
            pts = [project(lat, lon, w, h, center, zoom) for lon, lat in ring]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if (max(xs) < -margin or min(xs) > w + margin
                    or max(ys) < -margin or min(ys) > h + margin):
                continue
            out.append(pts)
    return out
