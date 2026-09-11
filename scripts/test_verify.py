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

# ------------------------------------------------------------------
# 成績の回。単位が多く、打者と投手で同じ鍵が別のものを指す。
# ------------------------------------------------------------------
print(chr(10) + "--- 成績の回 ---")
RECAP = {
    "岡本和真": {"打数": 4, "安打": 2, "本塁打": 1, "打点": 1, "二塁打": 0},
    "千賀滉大": {"回": 1.0, "奪三振": 2, "自責": 1, "被安打": 2, "セーブ": 1},
    "松井裕樹": {"回": 0.2, "奪三振": 1, "自責": 1, "被安打": 2},
}


def rec(*texts):
    return {"facts": RECAP, "segments": [{"text": t} for t in texts]}


check("その日の打撃はそのまま通る",
      vn.check(rec("岡本和真は4打数2安打　1本塁打　1打点。")), [])
check("安打が違えば捕まえる",
      len(vn.check(rec("岡本和真は4打数3安打　1本塁打　1打点。"))), 1)
check("読点をまたいで読む（一覧の形）",
      vn.check(rec("4位、岡本和真、4打数2安打　1本塁打。")), [])
check("投球回は小数で照合",
      vn.check(rec("千賀滉大は1.0回　2奪三振　自責1　2被安打　セーブ。")), [])
check("投球回が違えば捕まえる",
      len(vn.check(rec("千賀滉大は6.0回　2奪三振。"))), 1)
check("3分の1イニングも通る",
      vn.check(rec("松井裕樹は0.2回　1奪三振　自責1。")), [])
# 投手の「被安打」を打者の「安打」と読み違えないか。
# 何度も踏んでいる罠なので、ここで固定する。
check("被安打を安打として拾わない",
      vn.check(rec("千賀滉大は1.0回　2奪三振　自責1　2被安打。")), [])
check("ここ7日の合計は見ない",
      vn.check(rec("ここ7日では、岡本和真が24打数8安打　2本塁打。")), [])
check("直近3試合も見ない",
      vn.check(rec("岡本和真の直近3試合は10打数3安打です。")), [])
check("スコアの数字は拾わない",
      vn.check(rec("1位は岡本和真。スコア104。")), [])
check("名前だけ読む選手は照合しない",
      vn.check(rec("ほか、ヌートバー、センガ。")), [])

print()
print("--- 1試合の成績は、今季の累計と突き合わせない ---")
# 9/11に**正しい台詞を止めた。**「山本由伸が7回10奪三振」に対して
# 「材料は171奪三振です」と言って長編を落とした。台詞はその日の
# 登板の話で、材料が持っているのは今季の累計。別のものだった。
_season = {"山本由伸": {"勝": 12, "奪三振": 171}}
check("7回10奪三振は通す",
      vn.check({"facts": _season,
                "segments": [{"text": "山本由伸が7回10奪三振の好投だったのだ。"}]}),
      [])
check("6.2回3被安打も通す",
      vn.check({"facts": {"佐々木朗希": {"被安打": 98, "奪三振": 120}},
                "segments": [{"text": "佐々木朗希は6.2回3被安打だったのだ。"}]}),
      [])
# 投球回が付かない文は、これまでどおり照合する。
check("今季の累計は照合する（正しい日）",
      vn.check({"facts": _season,
                "segments": [{"text": "山本由伸は今季171奪三振なのだ。"}]}),
      [])
_bad = vn.check({"facts": _season,
                 "segments": [{"text": "山本由伸は今季200奪三振なのだ。"}]})
check("今季の累計が違えば止める", len(_bad), 1)
# 本塁打は1試合の単位に入れていない（「7回2本」という文はまず無い）。
# 9/8に捕まえた形をそのまま通さないこと。
_bad2 = vn.check({"facts": {"Ben Rice": {"本": 36}},
                  "segments": [{"text": "Ben Riceが56本打っているのだ。"}]})
check("本塁打の誤りは捕まえたまま", len(_bad2), 1)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
