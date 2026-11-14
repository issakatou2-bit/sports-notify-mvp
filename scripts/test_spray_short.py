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
check("35本の点は約9秒で置き終わる", 8.0 <= PB["dots_end"] - ss.T_DOTS <= 10.0, True)
check("置き終わってから札", PB["cards_t"] > PB["dots_end"], True)
check("最後の約5秒はまとめ", PB["total"] - PB["cards_t"] >= 4.95, True)

section("点の数が時刻とともに増える")
ts = [0.5, 1.9, 2.4, 3.3, 4.5, 5.5, P["dots_end"] + 0.1, P["total"] - 0.05]
placed = [ss.frame(P, t)[1]["placed"] for t in ts]
check("1枚目では0", placed[:2], [0, 0])
check("増えるだけで減らない", placed == sorted(placed), True)
check("途中は全数より少ない", 0 < placed[3] < 5, True)
check("最後に全数", placed[-1], 5)
check("右上の表示は k/N", ss.frame(P, P["dots_end"] + 0.1)[1]["count_text"], "5/5")
check("まとめでは右上の表示なし", ss.frame(P, P["total"] - 0.05)[1]["count_text"], None)
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

section("黄は記念の点＋説明の丸だけ（まとめ）")
check("途中は黄が無い", ss.frame(P, P["dots_end"] - 0.01)[1]["yellow"], [])
im, info = ss.frame(P, P["total"] - 0.05)
check("最後の黄の点は記念の本数", sorted(info["yellow"]), sorted((round(m["h"]["px"][0]), round(m["h"]["px"][1])) for m in P["mem"]))
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
check("1枚目の句は記念の札の短い形", P["phrases"], [l["short"] for l in sorted((l for m in P["mem"] for l in m["labels"]), key=lambda l: ss.PRIORITY.index(l["key"]))][:2])
check("方向の句の本数は集計と同じ", str(max(P["cnt"].values())) in P["side_phrase"], True)

section("本数が合わなければ描かない")
bad = copy.deepcopy(FX)
bad["gamelog_hr"] = 6
try:
    ss.plan(bad, "大谷翔平")
    got = "作った"
except ss.sc.SprayMismatch:
    got = "止めた"
check("合わなければ止める", got, "止めた")

# ================= 記念の1本 =================
def H(date, **kw):
    base = dict(date=date, at_bat=0, game_pk=1, x=125.0, y=100.0, dist=380.0, ls=100.0, la=30.0, traj='fly_ball',
                pitch_mph=90.0, rbi=1, inning=3, top=True, home_after=0, away_after=1)
    base.update(kw)
    return base


def keys(ms):
    return [(m["h"]["date"], [l["key"] for l in m["labels"]]) for m in ms]


section("優先順・まとめ・繰り上げ・None・同値")
a = H("2026-04-01", dist=430.0, ls=105.0, la=20.0, traj='line_drive', pitch_mph=95.0)
b = H("2026-04-02", dist=400.0, ls=110.0, la=35.0, rbi=4, away_after=4)
c = H("2026-04-03", dist=390.0, ls=108.0, la=25.0, traj='line_drive', pitch_mph=99.0)
d4 = H("2026-04-04", dist=380.0, ls=90.0, la=40.0, pitch_mph=95.0)
ms = ss.memorials([a, b, c, d4])
check("満塁＋最速の打球が1本にまとまり、最長＋弾丸ライナーも1本、3本目は最速の球",
      keys(ms), [("2026-04-02", ["grand_slam", "hardest"]), ("2026-04-01", ["longest", "liner"]), ("2026-04-03", ["fastest_pitch"])])
check("最大3本", len(ms) <= 3, True)
check("札は1本につき2枚まで", all(len(m["labels"]) <= 2 for m in ms), True)
e = H("2026-04-05", dist=440.0, ls=95.0, la=15.0, traj='line_drive', pitch_mph=70.0)
check("まとまった分だけ次の鍵から3本目を取る",
      keys(ss.memorials([b, e, d4])), [("2026-04-02", ["grand_slam", "hardest"]), ("2026-04-05", ["longest", "liner"]), ("2026-04-04", ["fastest_pitch"])])
nn = [H("2026-05-01", dist=400.0, ls=None, la=None, pitch_mph=None, traj=None), H("2026-05-02", dist=390.0, ls=None, la=None, pitch_mph=None, traj=None)]
check("None の鍵は飛ばす", keys(ss.memorials(nn)), [("2026-05-01", ["longest"])])
tie = [H("2026-06-02", dist=420.0), H("2026-06-01", dist=420.0)]
check("同値は日付の早い方", ss.memorials(tie)[0]["h"]["date"], "2026-06-01")
low = ss.memorials([H("2026-07-01", la=30.0), H("2026-07-02", la=22.0, dist=300.0)])
check("line_drive が無ければ最も低い弾道", [l["name"] for m in low for l in m["labels"] if l["key"] == "liner"], ["最も低い弾道"])
lm = ss.memorials([H("2026-07-01", la=30.0), H("2026-07-02", la=22.0, traj='line_drive', dist=300.0)])
check("line_drive があれば弾丸ライナー（la 最小）", [l["name"] for m in lm for l in m["labels"] if l["key"] == "liner"], ["弾丸ライナー"])
av = ss.memorials([H("2026-07-01", la=30.0), H("2026-07-02", la=None), H("2026-07-03", la=20.0, dist=300.0)])
check("liner の平均角度は la のある本塁打だけ", [l["avg_la"] for m in av for l in m["labels"] if l["key"] == "liner"], [25.0])

section("サヨナラ・満塁・勝ち越し・逆転")
wo = dict(top=False, inning=9, rbi=1, home_after=5, away_after=4)   # 打つ前 4-4 → 5-4
check("裏9回・同点から勝ち越しはサヨナラ", ss.is_walkoff(H("2026-04-01", **wo)), True)
check("表9回は偽", ss.is_walkoff(H("2026-04-01", **dict(wo, top=True, home_after=4, away_after=5))), False)
check("裏8回は偽", ss.is_walkoff(H("2026-04-01", **dict(wo, inning=8))), False)
check("裏9回でも負けたままは偽", ss.is_walkoff(H("2026-04-01", **dict(wo, home_after=3, away_after=4))), False)
check("材料が足りなければ偽", ss.is_walkoff(H("2026-04-01", top=None)), False)
check("サヨナラが最優先", keys(ss.memorials([H("2026-04-01", **wo), b, a]))[0][1][0], "walkoff")
check("満塁は rbi 4", [m["labels"][0]["key"] for m in ss.memorials([H("2026-04-02", rbi=4, away_after=4)])], ["grand_slam"])
check("同点から勝ち越し", ss.lead_kind(H("x", top=True, rbi=1, away_after=3, home_after=2)), "勝ち越し")
check("負けから逆転", ss.lead_kind(H("x", top=True, rbi=3, away_after=4, home_after=2)), "逆転")
check("追いつくだけは数えない", ss.lead_kind(H("x", top=True, rbi=2, away_after=2, home_after=2)), None)
check("もともと勝っていれば数えない", ss.lead_kind(H("x", top=True, rbi=1, away_after=5, home_after=2)), None)
check("勝ち越し・逆転の本数",
      ss.lead_count([H("1", top=True, rbi=1, away_after=3, home_after=2), H("2", top=True, rbi=3, away_after=4, home_after=2),
                     H("3", top=True, rbi=1, away_after=5, home_after=2), H("4", away_after=5, home_after=2)]), 2)
check("mph→km/h の四捨五入", [ss.kmh(114.6), ss.kmh(99.1), ss.kmh(114.1), ss.kmh(111.7)], [184, 159, 184, 180])
check("0.5 は切り上げ", ss.rhu(18.5), 19)

section("記念の場面（frame の記録）")
RICH = copy.deepcopy(FX)
hs = RICH["homers"]
hs[0].update(wo, traj='fly_ball', pitch_mph=90.0)
hs[1].update(rbi=4, top=True, inning=5, home_after=1, away_after=6, traj='fly_ball', pitch_mph=99.0)
hs[2].update(traj='line_drive', la=18.0, rbi=1, top=True, inning=2, home_after=0, away_after=1, pitch_mph=88.0)
PR = ss.plan(RICH, "大谷翔平")
check("サヨナラ・満塁が選ばれる", sorted(l["key"] for m in PR["mem"] for l in m["labels"] if l["key"] in ("walkoff", "grand_slam")), ["grand_slam", "walkoff"])
check("場面は優先順（1枚目の句と同じ順）", [m["labels"][0]["key"] for m in PR["mem"]],
      sorted((m["labels"][0]["key"] for m in PR["mem"]), key=ss.PRIORITY.index))
check("1枚目の1行目は最初の場面", PR["phrases"][0], PR["mem"][0]["labels"][0]["short"])
noliner = [H("2026-05-01", dist=450.0, la=20.0), H("2026-05-02", ls=115.0, la=25.0), H("2026-05-03", pitch_mph=101.0, la=28.0),
           H("2026-05-04", la=15.0)]
check("ライナーが無いと最も低い弾道は最速の球より後ろ", keys(ss.memorials(noliner)), [("2026-05-01", ["longest"]), ("2026-05-02", ["hardest"]), ("2026-05-03", ["fastest_pitch"])])
check("25〜35秒", 25.0 <= PR["total"] <= 35.0, True)
x0, y0, x1, y1 = ss.EMPTY_BOX
for pl in (P, PR):
    for m in pl["mem"]:
        t = m["start"] + 2.0
        im, info = ss.frame(pl, t)
        tag = f"場面{m['idx']}"
        check(tag + "の番号", info["scene"], m["idx"])
        check(tag + "の黄の点は選んだ本塁打の位置", info["yellow"], [(round(m["h"]["px"][0]), round(m["h"]["px"][1]))])
        check(tag + "の札の名", info["scene_labels"], [l["name"] for l in m["labels"]])
        lab, h = m["labels"][0], m["h"]
        want = {"longest": lambda: str(round(h["dist"])), "hardest": lambda: f'{h["ls"]:.1f}', "liner": lambda: str(ss.rhu(h["la"])),
                "walkoff": lambda: str(h.get("inning")), "grand_slam": lambda: "4",
                "fastest_pitch": lambda: f'{h["pitch_mph"]:.1f}'}[lab["key"]]()
        check(tag + "の札の数字は材料の値", info["scene_bigs"][0], want)
        check(tag + "の右上", info["count_text"], f'記念の1本 {m["idx"]}/{len(pl["mem"])}')
        a_ = np.asarray(im).astype(int)
        bg = np.asarray(sv.background(t, ss.W, ss.H).convert("RGB")).astype(int)
        check(tag + "の右下は地のまま", int(np.abs(a_[y0:y1, x0:x1] - bg[y0:y1, x0:x1]).max()), 0)
        check(tag + "の黄の点は札（y 700）より下", m["h"]["px"][1] > 760, True)
check("場面の前は場面なし", ss.frame(P, P["ms_t0"] - 0.5)[1]["scene"], None)
check("まとめは場面なし", ss.frame(P, P["cards_t"] + 1.0)[1]["scene"], None)
for t in [m["start"] + d_ for m in PR["mem"] for d_ in (0.1, 0.7, 3.5)] + [PR["cards_t"] + 0.2, PR["cards_t"] + 2.0, PR["total"] - 0.03]:
    im, _ = ss.frame(PR, t)
    a_ = np.asarray(im).astype(int)
    bg = np.asarray(sv.background(t, ss.W, ss.H).convert("RGB")).astype(int)
    check(f"{t:.2f}秒の右下は地のまま", int(np.abs(a_[y0:y1, x0:x1] - bg[y0:y1, x0:x1]).max()), 0)
m0 = PR["mem"][0]
im, _ = ss.frame(PR, m0["start"] + 2.0)
a_ = np.asarray(im).astype(int)
hx, hy = ss.sc.HOME_PX
px, py = m0["h"]["px"]
mx, my = round((hx + px) / 2), round((hy + py) / 2)
check("本塁から点への黄の線がある", bool(np.any(np.all(np.abs(a_[my - 4:my + 5, mx - 4:mx + 5] - np.array(sv.ACCENT)) <= 8, axis=2))), True)
other = next(h for h in PR["homers"] if all(h is not m["h"] for m in PR["mem"]))
oy, ox = round(other["px"][1]), round(other["px"][0])
before = int(np.asarray(ss.frame(PR, PR["dots_end"] + 0.1)[0]).astype(int)[oy, ox].sum())
after = int(a_[oy, ox].sum())
back = int(np.asarray(ss.frame(PR, PR["total"] - 0.03)[0]).astype(int)[oy, ox].sum())
check("記念の場面ではほかの点が薄い", after < before, True)
check("まとめでは点が戻る", back > after, True)
txt = ss.script_text(PR)
check("台本に勝ち越し・逆転の本数", f'{PR["lead"]}本' in txt, True)
check("台本に記念の1本ごとの文", all(f'（記念の1本 {m["idx"]}/{len(PR["mem"])}' in txt for m in PR["mem"]), True)

section("取得材料の新しい欄（キャッシュがあるときだけ）")
import spray_chart as sc_  # noqa: E402
RAWD = sc_.RAW
if all((RAWD / f"{pid}_gamelog.json").exists() for pid in ("808959", "672960", "660271")):
    exp = {
        "808959": ([("2026-04-17", "grand_slam"), ("2026-04-17", "hardest"), ("2026-04-22", "longest"), ("2026-08-08", "fastest_pitch")], 8, "451", "114.1", None),
        "672960": ([("2026-07-08", "grand_slam"), ("2026-05-02", "longest"), ("2026-05-02", "hardest"), ("2026-06-13", "liner")], 8, "453", "111.7", "21"),
        "660271": ([("2026-08-17", "longest"), ("2026-04-05", "hardest"), ("2026-07-07", "liner")], 17, "452", "114.6", "19"),
    }
    for pid, (want, nlead, ft, mph, la) in exp.items():
        pp = ss.plan(ss.attach_opponents(sc_.fetch_player(pid, log=lambda *_: None)), pid)
        got = [(m["h"]["date"], l["key"]) for m in pp["mem"] for l in m["labels"]]
        check(f"{pid} の記念の鍵と日付", sorted(got), sorted(want))
        labs = {l["key"]: l for m in pp["mem"] for l in m["labels"]}
        check(f"{pid} の最長・最速の打球・角度", (labs["longest"]["big"], labs["hardest"]["big"], labs.get("liner", {}).get("big")), (ft, mph, la))
        check(f"{pid} の勝ち越し・逆転の本数", pp["lead"], nlead)
else:
    print("skip: build/spray/raw が無いので数字の照合は飛ばす")

sys.exit(done())
