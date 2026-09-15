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
    """打率から安打数を割り出して、対比型の1件を作る。"""
    def hits(ab, avg):
        try:
            return round(int(ab) * float(avg or 0))
        except (TypeError, ValueError):
            return 0      # 壊れた材料を渡す検査があるので落ちない形で
    return [{"kind": "d_n", "why": "検査",
             "a": {"label": "昼", "atBats": ab_a, "ops": ops_a, "avg": avg_a,
                   "hits": hits(ab_a, avg_a)},
             "b": {"label": "夜", "atBats": ab_b, "ops": ops_b, "avg": avg_b,
                   "hits": hits(ab_b, avg_b)}}]


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
# 村上の実データ: ホーム .194（206打数）/ ビジター .215（205打数）。
check("打率差.021は言わない",
      ins.from_splits(split(206, ".800", ".194", 205, ".820", ".215"), "X"),
      [])
# 実データ: 昼 .149（161打数）/ 夜 .240（250打数）。
check("打率差.091は言う",
      len(ins.from_splits(split(161, ".635", ".149", 250, ".921", ".240"),
                          "X")), 1)

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
print("--- 偶然でそうなる確率 ---")
# ユーザーの問い:「満塁で強いって情報、何がだめ？」への答えがここ。
# 今季.204の打者が、その場面でそれ以上打つ確率を計算する。
check("満塁5打数2安打(.400)は、偶然でも27%起きる",
      round(ins.chance(5, 2, 0.204) * 100), 27)
check("初球29打数10安打(.345)は6%",
      round(ins.chance(29, 10, 0.204) * 100), 6)
check("終盤の接戦42打数9安打(.214)は50%",
      round(ins.chance(42, 9, 0.204) * 100), 50)
check("先頭88打数24安打(.273)は7%",
      round(ins.chance(88, 24, 0.204) * 100), 7)
# 27%は「4人に1人はそう見える」。30球団の主力を並べれば8人が
# 「満塁に強い」ことになる。**情報量がほぼ無い。**
# **打席数では先に切らない。**5打数と29打数の区別がつかなくなるため。
# 落とすのは確率の側（満塁27% > FACT_P で落ちる）。
check("5打数でも計算はする", ins.chance(5, 2, 0.204) < 1.0, True)
check("2打数は計算しない", ins.chance(2, 2, 0.204), 1.0)
check("下限は3打数", ins.MIN_AB_ANY, 3)

print()
print("--- 確率で切る ---")
season = {"ops": ".810", "avg": ".204", "atBats": 411, "hits": 84}


def scene(code, label, ab, hits, ops, avg):
    return [{"kind": code, "label": label, "why": "検査", "atBats": ab,
             "hits": hits, "ops": ops, "avg": avg}]


check("満塁5打数は出さない（27%）",
      ins.from_scenes(scene("r123", "満塁", 5, 2, "1.771", ".400"),
                      season, "X"), [])
check("終盤の接戦42打数も出さない（50%）",
      ins.from_scenes(scene("lc", "終盤の接戦", 42, 9, ".925", ".214"),
                      season, "X"), [])
# **初球は拾う。**下限打数で切っていたときは落としていた。
got = ins.from_scenes(scene("fp", "初球", 29, 10, "1.229", ".345"),
                      season, "X")
check("初球29打数は拾う（5%）", len(got), 1)
check("打数と安打をそのまま置く", "29打数10安打" in got[0]["text"], True)
check("確率を添える", "確率" in got[0]["detail"], True)
# 確率が十分に小さければ「傾向」として語る。
got = ins.from_scenes(scene("risp", "得点圏", 300, 30, ".500", ".100"),
                      season, "X")
check("300打数で.100なら傾向として語る", got[0]["sure"], "high")
check("下を向いていると分かる", got[0]["tone"], "negative")

print()
print("--- 対比型も確率で見る ---")
# 村上の昼夜: 昼161打数24安打(.149) / 夜250打数60安打(.240)
check("昼夜の差は偶然では出にくい",
      round(ins.gap_chance(161, 24, 250, 60) * 100) <= 5, True)
# 対左右: 118打数22安打(.186) / 293打数62安打(.212)
check("対左右の差は偶然の範囲",
      ins.gap_chance(118, 22, 293, 62) > ins.FACT_P, True)
# 片方が5打数なら、差が大きく見えても偶然で説明がつく。
check("片方が薄ければ差として出ない",
      ins.gap_chance(5, 2, 300, 60) > ins.FACT_P, True)

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
