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
