#!/usr/bin/env python3
"""言ったことと材料の突き合わせが、正しい日を止めないか。

**ここは誤検知のほうが怖い。**検算(sanity)は正しい動画を4回止めて
いて、そのたびにその日の枠が空いた。数字の誤りは致命的だが、
止める側が間違っているのも同じくらい困る。

だから両方を見る。**捕まえるもの**と、**通すもの**。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_numbers as vn  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def seg(*texts):
    return {"facts": FACTS, "segments": [{"text": t} for t in texts]}


FACTS = {
    "Tyrone Taylor": {"本": 11, "打点": 36},
    "Pete Crow-Armstrong": {"本": 41, "打点": 97},
    "鈴木誠也": {"本": 24, "打点": 80},
    "Jacob Misiorowski": {"勝": 14, "奪三振": 180},
}

print("--- 捕まえるもの ---")
# 9/8に実際に出た誤り。
d = seg("カブスは20本以上打ってる選手が5人いるのよ。"
        "Pete Crow-Armstrongが41本、Tyrone Taylorが22本打ってるわ。")
check("移籍した選手の二重計上", len(vn.check(d)), 1)
check("打点の食い違い", len(vn.check(seg("鈴木誠也は80打点なのだ"))), 0)
check("打点が違えば捕まえる",
      len(vn.check(seg("鈴木誠也は99打点なのだ"))), 1)
check("投手の勝ち星", len(vn.check(seg("Jacob Misiorowskiが20勝してるわ"))), 1)

print(chr(10) + "--- 通すもの（正しい台詞を止めない） ---")
check("材料どおり", vn.check(seg("鈴木誠也が24本打ったのだ")), [])
check("同じ文に何人も並ぶ",
      vn.check(seg("Pete Crow-Armstrongが41本、鈴木誠也が24本なのだ")), [])
check("通算の話は見ない",
      vn.check(seg("鈴木誠也は通算182本塁打なのだ")), [])
check("去年の話は見ない",
      vn.check(seg("鈴木誠也は去年21本だったのよ")), [])
check("目標の話は見ない",
      vn.check(seg("鈴木誠也はあと6本で30本に届くのだ")), [])
check("ペースの話は見ない",
      vn.check(seg("鈴木誠也は162試合ペースで35本なのよ")), [])
check("人数は数えない（単位が違う）",
      vn.check(seg("20本以上が4人いるのだ")), [])
check("材料に無い選手は見ない",
      vn.check(seg("Aaron Judgeが62本打ったのだ")), [])
check("隣の選手の数字を拾わない",
      vn.check(seg("Tyrone Taylorの話をしよう。ところでPete Crow-Armstrongは41本。")), [])
check("材料が無い台本は見ない",
      vn.check({"segments": [{"text": "鈴木誠也が99本なのだ"}]}), [])
check("空でも落ちない", vn.check({}), [])

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
