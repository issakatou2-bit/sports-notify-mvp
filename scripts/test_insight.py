#!/usr/bin/env python3
"""問い合わせエンジンが、偶然を傾向として語らないか。

なぜ検査が要るのか:
  この仕組みの怖いところは、**数字が全部正しいこと**。
  「直近5試合で打率.400」は20打数8安打で、偶然の範囲で普通に起きる。
  それを「上げてきている」と書いても、数字の検算では捕まらない。
  今日直したオフシーズンの穴と同じ型で、止められるのはここだけ。

  同じAPIで曜日別も取れる。村上宗隆の実データ（2026-09-15）は
  1日目 40打数 打率.300、4日目 39打数 打率.103 で、**差は昼夜より
  大きく出る。**それでも言ってはいけない。40打数は偶然の幅が広く、
  7通り試せば1つくらい極端な値が出るのが当たり前だから。

  昼夜が言えて曜日が言えないのは統計ではなく「意味が想像できるか」の
  違いなので、計算では決まらない。**切り口は登録制にする。**
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import insight as ins  # noqa: E402
import mlb_trends as mt  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def split(ab_a, ops_a, avg_a, ab_b, ops_b, avg_b):
    return [{"kind": "d_n", "why": "検査",
             "a": {"label": "昼", "atBats": ab_a, "ops": ops_a, "avg": avg_a},
             "b": {"label": "夜", "atBats": ab_b, "ops": ops_b, "avg": avg_b}}]


print("--- 見てよい切り口は登録制 ---")
codes = {c for pair in mt.SPLITS for c in pair[:2]}
check("昼夜を見る", {"d", "n"} <= codes, True)
check("対左右を見る", {"vl", "vr"} <= codes, True)
check("ホーム/ビジターを見る", {"h", "a"} <= codes, True)
# **曜日別は取れる。それでも持たない。**意味が想像できないため。
check("曜日別は持たない", any("dow" in str(p) for p in mt.SPLITS), False)
check("どの切り口にも理由が書いてある",
      all(len(p) == 5 and p[4] for p in mt.SPLITS), True)

print()
print("--- 差が小さければ黙る ---")
# 村上の実データ: ホーム OPS.800 / ビジター .820。差.020。
check("OPS差.020は言わない",
      ins.from_splits(split(206, ".800", ".194", 205, ".820", ".215"), "X"),
      [])
# 実データ: 昼 .635 / 夜 .921。差.286。
check("OPS差.286は言う",
      len(ins.from_splits(split(161, ".635", ".149", 250, ".921", ".240"),
                          "X")), 1)

print()
print("--- 薄いサンプルでは比べない ---")
# **曜日別と同じ40打数。**差が大きくても、この打数では比べない。
check("40打数では言わない",
      ins.from_splits(split(40, ".505", ".103", 39, "1.066", ".300"), "X"),
      [])
check("下限は定数で持つ", mt.MIN_AB_SPLIT, 80)

print()
print("--- 短い直近は、傾向ではなく事実として置く ---")
season = {"ops": ".810", "avg": ".204", "atBats": 411}
short = ins.from_recent({10: {"atBats": 35, "hits": 4, "avg": ".114",
                              "ops": ".530"}}, season, "X")
check("1件返る", len(short), 1)
check("事実として置くだけ", short[0]["sure"], "low")
check("向きは付けない", short[0]["tone"], "neutral")
check("「上げている」「下げている」とは書かない",
      any(w in short[0]["text"] for w in ("上回", "下回", "上げ", "下げ")),
      False)
check("打数と安打をそのまま置く", "35打数4安打" in short[0]["text"], True)

long = ins.from_recent({30: {"atBats": 108, "hits": 13, "avg": ".120",
                             "ops": ".564"}}, season, "X")
check("108打数なら傾向として言う", long[0]["sure"], "high")
check("下を向いていると分かる", long[0]["tone"], "negative")

print()
print("--- 場面ごとの成績 ---")
season = {"ops": ".810", "avg": ".204", "atBats": 411}


def scene(code, label, ab, ops, avg):
    return [{"kind": code, "label": label, "why": "検査",
             "atBats": ab, "ops": ops, "avg": avg}]


# **村上宗隆の満塁は今季5打数で打率.400・OPS1.771。**
# これを「満塁に強い」と書いたら終わり。打数で落とす。
check("満塁5打数は出さない",
      ins.from_scenes(scene("r123", "満塁", 5, "1.771", ".400"), season, "X"),
      [])
check("初球29打数も出さない",
      ins.from_scenes(scene("fp", "初球", 29, "1.229", ".345"), season, "X"),
      [])
# 得点圏81打数・OPS.707は、今季.810との差.103。言える。
got = ins.from_scenes(scene("risp", "得点圏", 81, ".707", ".160"),
                      season, "X")
check("得点圏81打数は言う", len(got), 1)
check("下を向いていると分かる", got[0]["tone"], "negative")
check("今季全体と並べて書く", "今季全体の.810" in got[0]["text"], True)
got = ins.from_scenes(scene("lo", "イニングの先頭", 88, ".913", ".273"),
                      season, "X")
check("上回っていれば positive", got[0]["tone"], "positive")
check("差が小さければ黙る",
      ins.from_scenes(scene("ig07", "7回以降", 128, ".850", ".211"),
                      season, "X"), [])

print()
print("--- 場面型は対比型より狭い幅で見る ---")
# 対比型は独立した2群の差なので両方の揺れが乗る（√2倍）。
# 場面型は部分と全体の比較なので揺れが小さい。同じ基準だと
# 場面型がほぼ全部落ちる（村上は得点圏.103・2アウト.100・先頭.103で、
# どれも対比型の.120のすぐ下だった）。
check("場面型のほうが狭い", ins.MIN_DIFF_OPS_SCENE < ins.MIN_DIFF_OPS, True)
check("対比型は0.120", ins.MIN_DIFF_OPS, 0.120)
check("場面型は0.085", ins.MIN_DIFF_OPS_SCENE, 0.085)

print()
print("--- 持たないと決めた切り口 ---")
codes = {c for c, _, _ in mt.SITUATIONS}
check("得点圏は持つ", "risp" in codes, True)
check("2アウトは持つ", "o2" in codes, True)
# **曜日別は打数が集まってしまうので、下限では落ちない。**
# 最初から取らないしかない。
check("曜日別は取らない一覧に入っている",
      {"dmo", "dsu"} <= set(mt.NOT_TAKEN), True)
check("曜日別を場面にも入れていない",
      any(c.startswith("d") and len(c) == 3 for c in codes), False)
check("どの場面にも理由が書いてある",
      all(len(s) == 3 and s[2] for s in mt.SITUATIONS), True)

print()
print("--- 向きで絞れる ---")
rows = [{"tone": "positive", "sure": "high", "weight": 90, "text": "上"},
        {"tone": "negative", "sure": "high", "weight": 80, "text": "下"},
        {"tone": "neutral", "sure": "low", "weight": 30, "text": "事実"}]
check("ポジティブな枠から下降を外す",
      [r["text"] for r in ins.pick(rows, tone=("positive", "neutral"))],
      ["上", "事実"])
check("戦略の回では全部渡す", len(ins.pick(rows)), 3)
check("傾向だけ欲しいとき", [r["text"] for r in ins.pick(rows, sure="high")],
      ["上", "下"])
check("件数で切れる", len(ins.pick(rows, limit=2)), 2)

print()
print("--- 返すものに必ず付く ---")
got = ins.from_splits(split(161, ".635", ".149", 250, ".921", ".240"), "X")[0]
for key in ("type", "text", "tone", "sure", "weight", "detail", "why",
            "source"):
    check("%s がある" % key, key in got and got[key] != "", True)
check("向きは3つのどれか", got["tone"] in
      (ins.POSITIVE, ins.NEUTRAL, ins.NEGATIVE), True)
check("確からしさは2つのどれか", got["sure"] in ("high", "low"), True)

print()
print("--- 壊れた材料で落ちない ---")
check("空の切り口", ins.from_splits([], "X"), [])
check("OPSが無い",
      ins.from_splits(split(200, None, ".200", 200, None, ".200"), "X"), [])
check("打数が文字", ins.from_splits(
    split("たくさん", ".600", ".100", 200, ".900", ".300"), "X"), [])
check("月が空", ins.from_months([], season, "X"), [])
check("直近が空", ins.from_recent({}, season, "X"), [])

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
