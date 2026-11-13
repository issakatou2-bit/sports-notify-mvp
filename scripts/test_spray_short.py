"""本塁打の図の短い動画（scripts/spray_short.py）の試験。ネットに繋がず、
scripts/fixtures/spray/ の固定材料（大谷翔平の本塁打5本）だけで回る。"""
import copy
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from checks_report import check, section, done  # noqa: E402
import numpy as np  # noqa: E402
import spray_short as ss  # noqa: E402
import style_v2 as sv  # noqa: E402

FX = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures/spray/ohtani_5.json").read_text(encoding="utf-8"))
P = ss.plan(copy.deepcopy(FX), FX["name_jp"])

section("長さとコマ数")
check("コマ数＝秒×30", P["frames"], round(P["total"] * 30))
check("秒×30は整数", abs(P["total"] * 30 - P["frames"]) < 1e-6, True)
check("25〜35秒", 25.0 <= P["total"] <= 35.0, True)
big = copy.deepcopy(FX)
base = big["homers"][0]
big["homers"] = [dict(base, at_bat=i, date=f"2026-04-{(i % 28) + 1:02d}") for i in range(35)]
big["gamelog_hr"] = 35
PB = ss.plan(big, "村上宗隆")
check("35本でも25〜35秒", 25.0 <= PB["total"] <= 35.0, True)
check("点の間隔は一定", len({round(b["t"] - a["t"], 6) for a, b in zip(PB["homers"], PB["homers"][1:])}), 1)
check("35本の点は約12〜15秒で置き終わる", 12.0 <= PB["dots_end"] - ss.T_DOTS <= 15.0, True)
check("置き終わってから札", PB["cards_t"] > PB["dots_end"], True)
check("最後の8秒ほどは札", PB["total"] - PB["cards_t"] >= 7.5, True)

section("点の数が時刻とともに増える")
ts = [0.5, 1.9, 2.4, 3.3, 4.5, 5.5, P["dots_end"] + 0.1, P["total"] - 0.05]
placed = [ss.frame(P, t)[1]["placed"] for t in ts]
check("1枚目では0", placed[:2], [0, 0])
check("増えるだけで減らない", placed == sorted(placed), True)
check("途中は全数より少ない", 0 < placed[3] < 5, True)
check("最後に全数", placed[-1], 5)
check("右上の表示は k/N", ss.frame(P, P["total"] - 0.05)[1]["count_text"], "5/5")
check("1枚目に点の数の表示はない", ss.frame(P, 1.0)[1]["count_text"], None)
im_before, _ = ss.frame(P, P["homers"][-1]["t"] - 0.01)
im_after, _ = ss.frame(P, P["homers"][-1]["t"] + 0.4)
px, py = (round(v) for v in P["homers"][-1]["px"])
check("最後の点は出る前は無く、出た後はある",
      (im_before.getpixel((px, py)) != im_after.getpixel((px, py)), min(im_after.getpixel((px, py))) > 150), (True, True))

section("右下（キャラの場所）は空き")
x0, y0, x1, y1 = ss.EMPTY_BOX
for t in (1.0, 3.0, 8.0, P["total"] - 0.05):
    im, _ = ss.frame(P, t)
    a = np.asarray(im).astype(int)
    bg = np.asarray(sv.background(t, ss.W, ss.H).convert("RGB")).astype(int)
    check(f"{t:.1f}秒の右下は地のまま", int(np.abs(a[y0:y1, x0:x1] - bg[y0:y1, x0:x1]).max()), 0)

section("黄は2点＋説明の丸だけ")
check("途中は黄が無い", ss.frame(P, P["dots_end"] - 0.01)[1]["yellow"], [])
im, info = ss.frame(P, P["total"] - 0.05)
check("最後の黄の点は2つ以下", 1 <= len(info["yellow"]) <= 2, True)
a = np.asarray(im).astype(int)
yel = np.all(np.abs(a - np.array(sv.ACCENT)) <= 6, axis=2)
ys, xs = np.nonzero(yel)
lo, hi = ss.LEGEND_Y - 14, ss.LEGEND_Y + 14
far = [(int(i), int(j)) for i, j in zip(xs, ys)
       if not any(abs(i - cx) <= 20 and abs(j - cy) <= 20 for cx, cy in info["yellow"]) and not (lo <= j <= hi)]
check("黄は点の周りと説明の丸だけ", far, [])
legend = [int(i) for i, j in zip(xs, ys) if lo <= j <= hi]
check("説明の丸は1つ（幅26px以内）", bool(legend) and max(legend) - min(legend) <= 27, True)
early = np.asarray(ss.frame(P, 1.0)[0]).astype(int)
check("1枚目に黄は無い", int(np.all(np.abs(early - np.array(sv.ACCENT)) <= 6, axis=2).sum()), 0)

section("句は材料の値")
check("結論の句に最長の飛距離", f'{round(P["longest"]["dist"])}ft' in P["phrases"][1], True)
check("方向の句の本数は集計と同じ", str(max(P["cnt"].values())) in P["phrases"][0], True)

section("本数が合わなければ描かない")
bad = copy.deepcopy(FX)
bad["gamelog_hr"] = 6
try:
    ss.plan(bad, "大谷翔平")
    got = "作った"
except ss.sc.SprayMismatch:
    got = "止めた"
check("合わなければ止める", got, "止めた")

sys.exit(done())
