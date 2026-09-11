#!/usr/bin/env python3
"""順位表の「境目」の切り出しが正しいか。

なぜ検査が要るのか:
  「4位までがCL圏内」を1つずらすと、**圏内のクラブを圏外と言う。**
  進出争いの回では以前それが起きていて、「1.0差ワイルドカード」が
  圏内なのか圏外なのか読めない画面になっていた。

  境目は1から数える(4位までが圏内)。一覧の添字は0から。
  **ここを間違えるのが、いちばんありそうな壊れ方。**
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cutline  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def table(*pts):
    """順位表。上から順に勝点を渡す。"""
    return [{"position": i + 1, "team": chr(65 + i), "points": p}
            for i, p in enumerate(pts)]


T = table(30, 27, 25, 22, 21, 19, 18, 15)

print("--- 線の前後 ---")
a = cutline.around(T, 4, span=2)
check("圏内の下2つ", [r["team"] for r in a["inside"]], ["C", "D"])
check("圏外の上2つ", [r["team"] for r in a["outside"]], ["E", "F"])
check("線の位置", a["line"], 4)

a1 = cutline.around(T, 1, span=2)
check("線が1位のとき、圏内は1つだけ",
      [r["team"] for r in a1["inside"]], ["A"])
check("空の一覧でも落ちない", cutline.around([], 4),
      {"inside": [], "outside": [], "line": 4})
check("線が0以下なら何も返さない", cutline.around(T, 0)["inside"], [])

print()
print("--- 線をまたぐ差 ---")
g = cutline.gap(T, 4)
check("4位22点と5位21点の差", g["diff"], 1)
check("圏内の最後", g["inside"]["team"], "D")
check("圏外の最初", g["outside"]["team"], "E")
check("並んでいる日は0",
      cutline.gap(table(30, 27, 25, 22, 22, 19), 4)["diff"], 0)
check("線が一覧の外なら空", cutline.gap(T, 8), {})
check("空の一覧でも落ちない", cutline.gap([], 4), {})

print()
print("--- 昨日から線をまたいだか ---")
now = table(30, 27, 25, 22, 21)          # A B C D | E
before = table(30, 27, 25, 21, 22)       # 同じ点だが並びが違う
before[3]["team"], before[4]["team"] = "E", "D"   # A B C E | D
m = cutline.moved(now, before, 4)
check("入ったクラブ", m["in"], ["D"])
check("出たクラブ", m["out"], ["E"])
check("動きが無い日は空の一覧",
      cutline.moved(now, now, 4), {"line": 4, "in": [], "out": []})
# **「変化なし」と「分からない」を混ぜない。**
check("昨日の記録が無い日は何も返さない", cutline.moved(now, [], 4), {})

print()
print("--- 同順位があっても、順位で切る ---")
# **これが最初に作ったときの穴。**「上から4件が圏内」と添字で
# 切っていたので、同順位があると全部ずれた。9/11の実データでは
# 6大会のうち5つで同順位が出ていて、プレミアは17位が2クラブ、
# チャンピオンズリーグは36行のうち18行が添字とずれていた。
# その結果「17位のトッテナムは残留圏外」と出ていた。
#
# APIが同勝点・同得失点のクラブに同じ順位を付けて返すのは
# ふつうのことなので、こちらで数え直してはいけない。
TIE = [
    {"position": 1, "team": "A", "points": 9},
    {"position": 2, "team": "B", "points": 7},
    {"position": 2, "team": "C", "points": 7},   # 同順位
    {"position": 4, "team": "D", "points": 5},
    {"position": 5, "team": "E", "points": 4},
    {"position": 6, "team": "F", "points": 3},
]
_in, _out = cutline.split(TIE, 4)
check("4位までが圏内（同順位を含めて4クラブ）",
      [r["team"] for r in _in], ["A", "B", "C", "D"])
check("5位以下が圏外", [r["team"] for r in _out], ["E", "F"])
check("線をまたぐ差は4位と5位", cutline.gap(TIE, 4)["diff"], 1)
check("圏内の最後は4位のD", cutline.gap(TIE, 4)["inside"]["team"], "D")

# 同順位が線そのものにかかる日。4位が2クラブなら両方とも圏内。
TIE_ON = [
    {"position": 1, "team": "A", "points": 9},
    {"position": 2, "team": "B", "points": 7},
    {"position": 3, "team": "C", "points": 6},
    {"position": 4, "team": "D", "points": 5},
    {"position": 4, "team": "E", "points": 5},   # 4位が2クラブ
    {"position": 6, "team": "F", "points": 3},
]
check("4位が2クラブなら5クラブが圏内",
      [r["team"] for r in cutline.split(TIE_ON, 4)[0]],
      ["A", "B", "C", "D", "E"])
check("圏外の先頭は6位", cutline.gap(TIE_ON, 4)["outside"]["team"], "F")

# 9/11に実際に出ていた間違い。17位が2クラブで、17位までが残留。
REL = [{"position": i + 1, "team": "T%d" % (i + 1), "points": 20 - i}
       for i in range(16)]
REL += [{"position": 17, "team": "Villa", "points": 1},
        {"position": 17, "team": "Tottenham", "points": 1},
        {"position": 19, "team": "Fulham", "points": 0},
        {"position": 20, "team": "Coventry", "points": 0}]
_d = cutline.distance_to(REL, 17, "Tottenham")
check("17位のクラブは残留圏内", _d["side"], "inside")
check("順位は position の値", _d["position"], 17)
check("19位は圏外", cutline.distance_to(REL, 17, "Fulham")["side"],
      "outside")
check("圏内からは「落ちるまでの差」", _d["diff"], 1)

# position が無い記録（昔のMLBの形）は、並び順で数える。
NOPOS = [{"team": "A", "points": 9}, {"team": "B", "points": 7},
         {"team": "C", "points": 5}, {"team": "D", "points": 4},
         {"team": "E", "points": 3}]
check("position が無ければ並び順",
      [r["team"] for r in cutline.split(NOPOS, 3)[0]], ["A", "B", "C"])
check("position が無くても差は出る", cutline.gap(NOPOS, 3)["diff"], 1)

print()
print("--- 線までの差 ---")
check("圏外のクラブは「入るまでの差」",
      cutline.distance_to(T, 4, "F"), {"line": 4, "position": 6,
                                       "side": "outside", "diff": 3})
check("圏内のクラブは「落ちるまでの差」",
      cutline.distance_to(T, 4, "D"), {"line": 4, "position": 4,
                                       "side": "inside", "diff": 1})
check("知らないクラブは空", cutline.distance_to(T, 4, "Z"), {})
check("名前が空でも落ちない", cutline.distance_to(T, 4, ""), {})
check("空の一覧でも落ちない", cutline.distance_to([], 4, "A"), {})
# 線が一覧の外にあると、相手側が存在しない。
check("線が一覧の外なら空", cutline.distance_to(T, 20, "A"), {})

print()
print("--- 大会ごとの境目 ---")
check("プレミアはCL4・EL5・残留17",
      cutline.lines_for("PL"), [(4, "CL圏内"), (5, "EL圏内"), (17, "残留")])
check("ブンデスは18クラブなので残留15",
      [n for n, lab in cutline.lines_for("BL1") if lab == "残留"], [15])
check("2部は昇格の線",
      [lab for _, lab in cutline.lines_for("ELC")][0], "自動昇格")
check("知らない大会は空", cutline.lines_for("XX"), [])

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
