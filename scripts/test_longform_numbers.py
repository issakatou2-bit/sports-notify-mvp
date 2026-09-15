#!/usr/bin/env python3
"""長編を数字で組み立てる材料が、嘘を作らないか。

なぜ検査が要るのか:
  この材料を最初に動かしたとき、実データで2つ間違えた。

    1. 投手の行を打者の書式で作った（`type` は "P" だと思っていたが
       実際は "pitcher"）。被安打が安打として出るところだった。
    2. 90勝59敗で地区を走るドジャースに「ワイルドカード最後の枠」と
       書いた。地区首位の球団にはワイルドカードの差が返らないので、
       差が無いことを「最後の枠」と読んでいた。

  どちらも**数字は正しく、意味だけが違う**。三段目の照合は通る。
  ここで止めるしかない。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import generate_dialogue as gd  # noqa: E402
import numbers_material as nm  # noqa: E402
import race_words as rw  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def has(label, got, part):
    global fails
    ok = part in (got or "")
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (%r を含むはず)" % (part,)))


def hasnt(label, got, part):
    global fails
    ok = part not in (got or "")
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (%r を含んではいけない)" % (part,)))


print("--- 投手と打者を取り違えない ---")
check("pitcher は投手", nm.is_pitcher({"type": "pitcher"}), True)
check("P も投手（古い書き方）", nm.is_pitcher({"type": "P"}), True)
check("batter は投手ではない", nm.is_pitcher({"type": "batter"}), False)
check("空は投手ではない", nm.is_pitcher({}), False)

pit = {"type": "pitcher", "ip": "6.0", "hits": 3, "er": 1, "so": 8, "bb": 1,
       "headline": "これは打者の書式"}
has("投手の行に被安打と書く", nm._line(pit), "被安打3")
hasnt("投手の行に「安打」単独を出さない", nm._line(pit).replace("被安打", ""),
      "安打")
check("打者は見出しをそのまま使う",
      nm._line({"type": "batter", "headline": "3打数2安打"}), "3打数2安打")

print()
print("--- 地区首位を「最後の枠」と言わない ---")
# **実データの形。**ドジャースは地区首位で、ワイルドカードの差は返らない。
dodgers = {"team": "ドジャース", "route": "地区首位", "w": 90, "l": 59,
           "magic": 4, "wc_gb": None, "clinched": False}
has("地区首位と書く", rw.phrase(dodgers), "地区首位")
hasnt("最後の枠とは言わない", rw.phrase(dodgers), "最後の枠")
has("マジックも添える", rw.phrase(dodgers), "マジック4")
check("札は短く", rw.short(dodgers), "M4")

padres = {"team": "パドレス", "route": "ワイルドカード", "wc_gb": None,
          "magic": None, "clinched": False}
has("ワイルドカードで差が無いなら最後の枠", rw.phrase(padres), "最後の枠")

print()
print("--- 圏内と圏外は同じ数字で意味が逆 ---")
inside = {"route": "ワイルドカード", "wc_gb": "+1.5"}
outside = {"route": "ワイルドカード", "wc_gb": "1.5"}
has("符号つきは圏内", rw.phrase(inside), "圏内")
hasnt("圏内の文に「あと」は出さない", rw.phrase(inside), "あと")
has("符号なしは圏外", rw.phrase(outside), "圏外")
has("圏外は「あと」で書く", rw.phrase(outside), "あと1.5")
check("札も圏内・圏外を落とさない", rw.short(inside), "圏内 1.5")
check("札の圏外", rw.short(outside), "圏外 1.5")

print()
print("--- 決まったこと・消えたこと ---")
check("進出決定", rw.phrase({"clinched": True, "route": "地区首位"}), "進出決定")
check("敗退", rw.phrase({"wc_gb": "E", "route": "ワイルドカード"}),
      "進出の可能性は消滅")
check("敗退の札", rw.short({"wc_gb": "E"}), "敗退")

print()
print("--- 材料が無い日でも落ちない ---")
empty = nm.load(str(HERE / "no-such-dir"))
check("空の材料が返る", empty["players"], [])
check("話せる材料が無いと分かる", nm.has_enough(empty), False)
check("事実の文は作れる", isinstance(nm.facts(empty), str), True)
check("札は締めだけ残る", sorted(nm.panels(empty)), ["topic"])

print()
print("--- 実データ ---")
real = nm.load(str(HERE.parent / "data"))
check("選手が並ぶ", bool(real["players"]), True)
check("人数を絞る", len(real["players"]) <= nm.MAX_PLAYERS, True)
check("話せる材料がある", nm.has_enough(real), True)
text = nm.facts(real)
hasnt("圏内まで、という曖昧な書き方をしない", text, "圏内まで")
for row in real["rare"]:
    check("同率を拾わない（%s）" % row["stat"], "タイ" in row["rank"], False)
panels = nm.panels(real)
check("札に締めがある", "topic" in panels, True)
for key, panel in panels.items():
    check("%s に説明がある" % key, bool(panel.get("menu")), True)
    check("%s の型が描画にある" % key,
          panel["type"] in ("star", "stat", "group", "topic"), True)

print()
print("--- 二人の口調が混ざらないか ---")
# 9/15の回で、ずんだもんが「じゃあここからは成績表の外の話ね。」と
# **めたんの口調で仕切った。**二人で話す意味は、どちらが言っているかが
# 語尾で分かることにあるので、そこが崩れると形が成り立たない。


def _seg(who, text):
    return {"meta": {"who": who}, "text": text}


check("めたんの口調で話したら見つける",
      [t for _, t in gd.voice_slips(
          [_seg("ずんだもん", "じゃあここからは成績表の外の話ね。")])],
      ["じゃあここからは成績表の外の話ね。"])
check("「のだ」で終われば通す",
      gd.voice_slips([_seg("ずんだもん", "安打1本で3打点なのだ。")]), [])
check("問いかけの「のだ？」も通す",
      gd.voice_slips([_seg("ずんだもん", "1位は誰なのだ？")]), [])
check("前後の挟みは見ない",
      gd.voice_slips([_seg("ずんだもん", "コレスポ")]), [])
check("めたんの行は見ない",
      gd.voice_slips([_seg("めたん", "そうね。")]), [])
check("空の行で落ちない", gd.voice_slips([_seg("ずんだもん", "")]), [])

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
