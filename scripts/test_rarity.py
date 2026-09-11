#!/usr/bin/env python3
"""名前のある指標の計算と、リーグの中での位置。

なぜ検査が要るのか:
  **公式の記録ではない数字を出す。**だからこそ、計算を間違えると
  取り返しがつかない。「アダム・ダン率でアダム・ダンを超えた」と
  言うなら、その式と比較が正しくないと嘘になる。

  いちばんありそうな壊れ方は、**投手と打者の項目の取り違え。**
  投手の avg は被打率、hits は被安打、homeRuns は被本塁打。
  実際、作った直後に山本由伸へ「打率.185。メンドーサ・ラインの
  すぐ下」が付いた（被打率.185は良い投球で、意味が逆）。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import rarity as ra  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def near(label, got, want, tol=0.001):
    global fails
    ok = got is not None and abs(got - want) <= tol
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r±%s)" % (want, tol)))


print("--- 指標の計算（村上宗隆 2026の実データ） ---")
# 486打席 31本 82四球 170三振 打率.208 長打率.475
MURAKAMI = {"plateAppearances": 486, "atBats": 400, "hits": 83,
            "homeRuns": 31, "baseOnBalls": 82, "strikeOuts": 170,
            "sacFlies": 1, "avg": ".208", "slg": ".475", "obp": ".346"}
near("アダム・ダン率", ra.tto(MURAKAMI), 0.5823, 0.0005)
near("ISO（長打率-打率）", ra.iso(MURAKAMI), 0.267)
# BABIP = (83-31) / (400-170-31+1) = 52/200 = .260
near("BABIP", ra.babip(MURAKAMI), 0.260)
near("四球三振比", ra.bb_per_k(MURAKAMI), 82 / 170)
near("三振率", ra.k_rate(MURAKAMI), 170 / 486)
near("四球率", ra.bb_rate(MURAKAMI), 82 / 486)

print()
print("--- 投手の指標 ---")
# 7回1失点3被安打1四球10奪三振の登板を、季で 150.1回 に見立てる
PITCHER = {"inningsPitched": "150.1", "strikeOuts": 180, "hits": 120,
           "baseOnBalls": 40, "earnedRuns": 50, "avg": ".185"}
# 150.1回 = 451アウト。180 * 27 / 451 = 10.78
near("9回あたり奪三振", ra.k_per_9(PITCHER), 10.776, 0.01)
near("奪三振四球比", ra.k_per_bb(PITCHER), 4.5)
# (120+40) * 3 / 451 = 1.064
near("WHIP", ra.whip(PITCHER), 1.064, 0.01)
# 投球回の小数は3分の1。150.1 を 150.1 として読むと全部ずれる。
check("回の小数を取り違えない（150.1回は451アウト）",
      ra._outs("150.1"), 451)
check("6.2回は20アウト", ra._outs("6.2"), 20)

print()
print("--- 欠けても落ちない ---")
check("空の成績", ra.tto({}), None)
check("打席0", ra.tto({"plateAppearances": 0}), None)
check("長打率が無い", ra.iso({"avg": ".250"}), None)
check("三振0なら四球三振比は出さない",
      ra.bb_per_k({"baseOnBalls": 10, "strikeOuts": 0}), None)
check("与四球0なら奪三振四球比は出さない",
      ra.k_per_bb({"strikeOuts": 100, "baseOnBalls": 0}), None)
check("回0ならWHIPは出さない",
      ra.whip({"inningsPitched": "0.0", "hits": 1, "baseOnBalls": 1}), None)
check("回が読めない文字列", ra.k_per_9({"inningsPitched": "-",
                                  "strikeOuts": 10}), None)
check("BABIPの分母が0", ra.babip({"atBats": 3, "strikeOuts": 3,
                                "homeRuns": 0, "hits": 0}), None)

print()
print("--- 出し方 ---")
check("割合は小数1桁のパーセント", ra.fmt(0.582, "pct"), "58.2%")
check("打率の形は先頭の0を落とす", ra.fmt(0.267, "avg3"), ".267")
check("比は小数2桁", ra.fmt(1.064, "ratio"), "1.06")
check("計算できない値は空", ra.fmt(None, "pct"), "")

print()
print("--- リーグの中での位置 ---")
ROWS = [
    {"player_id": "1", "name": "A", "stat": {"plateAppearances": 500,
     "homeRuns": 40, "baseOnBalls": 80, "strikeOuts": 180}},   # 60.0%
    {"player_id": "2", "name": "B", "stat": {"plateAppearances": 500,
     "homeRuns": 30, "baseOnBalls": 70, "strikeOuts": 150}},   # 50.0%
    {"player_id": "3", "name": "C", "stat": {"plateAppearances": 500,
     "homeRuns": 10, "baseOnBalls": 40, "strikeOuts": 100}},   # 30.0%
]
M = next(m for m in ra.METRICS if m["key"] == "tto")
r = ra.rank(ROWS, M, "2")
check("順位", (r["at"], r["of"]), (2, 3))
check("値の表示", r["shown"], "50.0%")
check("すぐ上の選手", r["above"]["name"], "A")
check("すぐ下の選手", r["below"]["name"], "C")
check("1位の上は無い", ra.rank(ROWS, M, "1")["above"], None)
check("最下位の下は無い", ra.rank(ROWS, M, "3")["below"], None)
check("いない選手は空", ra.rank(ROWS, M, "9"), {})
# 計算できない選手を並びに入れない（0として最下位に並べない）。
_with_bad = ROWS + [{"player_id": "4", "name": "D",
                     "stat": {"plateAppearances": 0}}]
check("計算できない選手は数に入れない",
      ra.rank(_with_bad, M, "1")["of"], 3)
# 小さいほうが良い指標（WHIP）は、小さい順に並べる。
W = next(m for m in ra.METRICS if m["key"] == "whip")
PROWS = [
    {"player_id": "p1", "name": "P1", "stat": {"inningsPitched": "100.0",
     "hits": 70, "baseOnBalls": 20}},                           # 0.90
    {"player_id": "p2", "name": "P2", "stat": {"inningsPitched": "100.0",
     "hits": 100, "baseOnBalls": 40}},                          # 1.40
]
check("WHIPは小さいほうが1位", ra.rank(PROWS, W, "p1")["at"], 1)

print()
print("--- 話にする価値があるものだけ ---")
# 139人中70位の指標を並べても「ふつう」という意味しかない。
_many = [{"player_id": str(i), "name": "P%d" % i,
          "stat": {"plateAppearances": 500, "homeRuns": 10,
                   "baseOnBalls": 40, "strikeOuts": 100 + i}}
         for i in range(1, 31)]
_mid = ra.notable({"hitting": _many}, "15",
                  {"hitting": _many[14]["stat"]})
check("真ん中の選手は何も出ない", _mid, [])
_top = ra.notable({"hitting": _many}, "30",
                  {"hitting": _many[29]["stat"]})
check("上位の選手は出る", len(_top) > 0, True)
check("上位だと分かる", _top[0]["side"], "top")
# **上位を先に並べる。**「リーグ1位」のほうが「下から1番目」より
# 先に伝わるべきこと。
check("上位の指標が先に来る",
      [x["side"] for x in _top][:1], ["top"])
_bottom = ra.notable({"hitting": _many}, "1",
                     {"hitting": _many[0]["stat"]})
# この選手は三振がいちばん少ないので、三振率では下から1番目だが
# 四球三振比では1位になる。**両側とも拾えていることを見る。**
check("下位の指標も拾う（極端さは両側）",
      "bottom" in [x["side"] for x in _bottom], True)
_sides = [x["side"] for x in _bottom]
check("上位の指標が先、下位が後",
      _sides == ["top"] * _sides.count("top")
      + ["bottom"] * _sides.count("bottom"), True)
check("材料が無ければ空", ra.notable({}, "1", {}), [])


# **同じ値が並ぶ指標は扱わない。**「◯位」と書いても実際は
# 「◯位タイ」で、極端であることの証明にならない。
# 検査データで四球率が全員同じだったとき、それが「下から1番目」
# として拾われて上位の指標より先に並んだ。
print()
print("--- 同じ値が並ぶ指標は扱わない ---")
_same = [{"player_id": str(i), "name": "P%d" % i,
          "stat": {"plateAppearances": 500, "homeRuns": 10,
                   "baseOnBalls": 40, "strikeOuts": 100}}
         for i in range(1, 6)]
_r = ra.rank(_same, next(m for m in ra.METRICS if m["key"] == "bb_rate"), "3")
check("同じ値の人数を返す", _r["ties"], 5)
check("全員同じ値なら何も出さない",
      ra.notable({"hitting": _same}, "3", {"hitting": _same[2]["stat"]}), [])
_r2 = ra.rank(ROWS, M, "1")
check("値がばらけていればタイは1人", _r2["ties"], 1)

print()
print("--- 言い方 ---")
check("上位", ra.phrase({"side": "top", "label": "アダム・ダン率",
                       "shown": "58.2%", "at": 1, "of": 139}),
      "アダム・ダン率 58.2%（139人中1位）")
check("下位は下から何番目かも言う",
      ra.phrase({"side": "bottom", "label": "BABIP", "shown": ".210",
                 "at": 139, "of": 139}),
      "BABIP .210（139人中139位＝下から1番目）")
check("材料が無ければ空", ra.phrase({}), "")

print()
print("--- 呼び名の由来になっている選手との比較 ---")
# **超えたときだけ言う。**比較そのものが話題になるのは、
# 超えたときだけ。
_mine = {"value": 0.582, "shown": "58.2%"}
_theirs = {"value": 0.567, "shown": "56.7%", "season": "2012"}
check("超えていれば言う", ra.namesake_phrase(M, _mine, _theirs),
      "アダム・ダン本人の最高（2012年 56.7%）を上回っている")
check("超えていなければ言わない",
      ra.namesake_phrase(M, {"value": 0.50, "shown": "50.0%"}, _theirs),
      "")
check("由来が無い指標では何も言わない",
      ra.namesake_phrase(next(m for m in ra.METRICS if m["key"] == "iso"),
                         _mine, _theirs), "")
check("材料が欠けていれば空", ra.namesake_phrase(M, {}, _theirs), "")
# WHIPのように小さいほうが良い指標は、下回ったときが「超えた」。
check("小さいほうが良い指標の向き",
      ra.namesake_phrase({**W, "namesake": {"name": "X"}},
                         {"value": 0.90, "shown": "0.90"},
                         {"value": 1.10, "shown": "1.10",
                          "season": "2010"}),
      "X本人の最高（2010年 1.10）を上回っている")

print()
print("--- メンドーサ・ラインは打者だけ ---")
# **投手の avg は被打率。**打率として扱うと意味が逆になる。
# 作った直後に山本由伸へ「打率.185。メンドーサ・ラインのすぐ下」
# が付いた。被打率.185は良い投球。
src = (HERE / "rarity.py").read_text(encoding="utf-8")
check("打者に限る条件が入っている",
      'if group == "hitting" else None' in src, True)
check("線は.200", ra.MENDOZA_LINE, 0.200)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
