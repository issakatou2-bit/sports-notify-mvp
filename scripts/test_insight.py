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
