#!/usr/bin/env python3
"""
検算そのものを検算する。

なぜ要るのか:
  **検算が正しい動画を止めたのが3度ある。**

    8/21 通算成績の幅が今季の幅だったので「今日の1人」が出なかった
    8/29 打率1.000（1打数1安打）で、その日の6本すべてが止まった
    9/2  「257,422回」の「422回」を422イニングと読んで長編が止まった

  どれも、止める側が間違っていた。**止める側が間違っていると、
  正しい日に何も出ない。** 出さない失敗は、間違ったものを出す失敗より
  静かで、気づくのが遅れる。

  だから、検算そのものに試験を置く。
  「これは止めるべき」と「これは通すべき」を両方書く。

使い方:
  python3 scripts/test_sanity.py
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import sanity  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    if got != want:
        fails += 1
        print("NG  %s: %r (期待 %r)" % (label, got, want))
    else:
        print("ok  %s" % label)


# --- 読み取り -------------------------------------------------------------
# 実際に止めてしまった文を、そのまま置く。
print("--- 数字の読み取り ---")
check("桁区切りの中を単位に結び付けない（9/2に長編を止めた）",
      sanity.parse_line("およそ26万回ね。正確には257,422回よ。"), {})
check("高評価の件数を成績と読まない",
      sanity.parse_line("高評価が1,240件、返信18件"), {})
check("ふつうの投球はそのまま読む",
      sanity.parse_line("7回を投げて8奪三振"), {"回": 7.0, "奪三振": 8.0})
check("防御率は小数のまま",
      sanity.parse_line("防御率2.14")["防御率"], 2.14)
check("割・分・厘を打率に直す",
      round(sanity.parse_line("打率2割9分1厘")["打率"], 3), 0.291)

# --- 止めるべきもの -------------------------------------------------------
print("\n--- 止めるべきもの ---")
check("打数より安打が多い",
      len(sanity.check_line("X", "2打数3安打")) > 0, True)
check("安打より本塁打が多い",
      len(sanity.check_line("X", "3打数1安打　2本塁打")) > 0, True)
check("1回で20奪三振",
      len(sanity.check_line("X", "1.0回　20奪三振")) > 0, True)

# --- 通すべきもの ---------------------------------------------------------
# ここが本題。**正しいのに止めた**ものを並べる。
print("\n--- 通すべきもの（過去に誤って止めた） ---")
check("1打数1安打の打率1.000（8/29に6本止めた）",
      sanity.check_line("X", "今季 打率1.000　0本塁打　0打点"), [])
check("通算443安打（8/21に今日の1人を止めた）",
      sanity.check_line("X", "通算 443安打　79本塁打　234打点"), [])
check("再生回数の桁区切り（9/2に長編を止めた）",
      sanity.check_line("X", "およそ26万回。正確には257,422回"), [])
check("ふつうの好投", sanity.check_line("X", "7.0回　8奪三振　自責1"), [])
check("延長15回", sanity.check_line("X", "15.0回　12奪三振"), [])

print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
sys.exit(1 if fails else 0)
