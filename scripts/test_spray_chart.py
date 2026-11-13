"""本塁打の方向と飛距離の図（scripts/spray_chart.py）の試験。ネットに繋がず、
scripts/fixtures/spray/ の小さな固定材料（大谷翔平の本塁打5本）だけで回る。"""
import copy
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from checks_report import check, section, done  # noqa: E402
import numpy as np  # noqa: E402
import spray_chart as sc  # noqa: E402
import style_v2 as sv  # noqa: E402

FX = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures/spray/ohtani_5.json").read_text(encoding="utf-8"))

section("座標の変換")
check("本塁は原点", sc.to_xy_ft(sc.HOME_X, sc.HOME_Y), (0.0, 0.0))
x, y = sc.to_xy_ft(sc.HOME_X, sc.HOME_Y - 100)
check("真上（座標yが小さい）は中堅方向", (round(x), y > 0), (0, True))
check("中堅方向は0度", round(sc.angle_deg(sc.HOME_X, 50), 3), 0.0)
check("右へ寄ると正の角度", sc.angle_deg(200, 100) > 0, True)
check("左へ寄ると負の角度", sc.angle_deg(50, 100) < 0, True)
px, py = sc.to_px(400, 0)
check("中堅は画面の真上（xが本塁と同じでyが上）", (px == sc.HOME_PX[0], py < sc.HOME_PX[1]), (True, True))
scale, _, _ = sc.fit_scale(FX["homers"])
check("ft の係数は固定材料の実測とほぼ同じ", abs(scale - sc.FT_PER_UNIT) < 0.06, True)
check("メートルは小数1桁で四捨五入", (sc.meters(401), sc.meters(100)), (122.2, 30.5))

section("本数の照合")
check("図5＋座標なし0＝gameLog5", sc.check_counts(FX), 5)
bad = copy.deepcopy(FX)
bad["gamelog_hr"] = 6
try:
    sc.render(bad, "大谷翔平")
    got = "描いた"
except sc.SprayMismatch:
    got = "止めた"
check("合わなければ描かない", got, "止めた")
nc = copy.deepcopy(FX)
nc["homers"] = nc["homers"][:4]
nc["no_coords"] = 1
check("座標なしは数に入れて照合が合う", sc.check_counts(nc), 5)

section("絵")
im, info = sc.render(copy.deepcopy(FX), FX["name_jp"], today="2026-11-13")
check("縦長1080x1920", im.size, (1080, 1920))
check("図の点は5つ", info["plotted"], 5)
check("黄の点は2つ以下", len(info["yellow"]) <= 2, True)
a = np.asarray(im).astype(int)
yel = np.all(np.abs(a - np.array(sv.ACCENT)) <= 6, axis=2)
ys, xs = np.nonzero(yel)
far = [(int(i), int(j)) for i, j in zip(xs, ys)
       if not any(abs(i - cx) <= 20 and abs(j - cy) <= 20 for cx, cy in info["yellow"])
       and not (755 <= j <= 795)]   # 755..795 は黄の点の説明の丸
check("黄は点の周りと説明の丸だけ（ほかに黄の字や線がない）", far, [])
legend = [(int(i), int(j)) for i, j in zip(xs, ys) if 755 <= j <= 795]
check("説明の丸は1つ（幅26px以内）", bool(legend) and max(i for i, _ in legend) - min(i for i, _ in legend) <= 27, True)
x0, y0, x1, y1 = sc.EMPTY_BOX
base = np.asarray(sv._base(sc.W, sc.H).convert("RGB")).astype(int)
diff = np.abs(a[y0:y1, x0:x1] - base[y0:y1, x0:x1]).max()
check("右下（キャラの場所）は地のまま", int(diff), 0)

sys.exit(done())
