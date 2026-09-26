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
from checks_report import check, has, hasnt, section, done  # noqa: E402

section("投手と打者を取り違えない")
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

section("地区首位を「最後の枠」と言わない")
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

section("圏内と圏外は同じ数字で意味が逆")
inside = {"route": "ワイルドカード", "wc_gb": "+1.5"}
outside = {"route": "ワイルドカード", "wc_gb": "1.5"}
has("符号つきは圏内", rw.phrase(inside), "圏内")
hasnt("圏内の文に「あと」は出さない", rw.phrase(inside), "あと")
has("符号なしは圏外", rw.phrase(outside), "圏外")
has("圏外は「あと」で書く", rw.phrase(outside), "あと1.5")
check("札も圏内・圏外を落とさない", rw.short(inside), "圏内 1.5")
check("札の圏外", rw.short(outside), "圏外 1.5")

section("決まったこと・消えたこと")
check("進出決定", rw.phrase({"clinched": True, "route": "地区首位"}), "進出決定")
check("敗退", rw.phrase({"wc_gb": "E", "route": "ワイルドカード"}),
      "進出の可能性は消滅")
check("敗退の札", rw.short({"wc_gb": "E"}), "敗退")

section("材料が無い日でも落ちない")
empty = nm.load(str(HERE / "no-such-dir"))
check("空の材料が返る", empty["players"], [])
check("話せる材料が無いと分かる", nm.has_enough(empty), False)
check("事実の文は作れる", isinstance(nm.facts(empty), str), True)
check("札は締めだけ残る", sorted(nm.panels(empty)), ["topic"])

section("欧州サッカーの材料（固定の形）")
# **実データ頼みにしない。**
#
# サッカーは節の合間だと `ready` が立たず、材料が空のまま通ってしまう。
# 9/21と9/22は材料が出た日で、そこで初めて `clubs` を一覧だと思って
# 添字で切っていたことが露見した（`clubs` は 20 という数）。
# 材料が出た日にだけ落ちる作りだったので、形を固定して押さえる。
SOCCER = {
    "code": "PL", "round": 5, "round_complete": True,
    "name_jp": "プレミアリーグ", "played": 5, "clubs": 20, "ready": True,
    "jp": [
        {"name": "三笘薫", "club_jp": "ブライトン", "position": 3, "points": 10,
         "out": True, "out_note": "Hamstring injury - Expected back 10 Oct",
         "lines": [{"line": 4, "side": "inside", "label": "CL圏内",
                    "text": "CL圏内。落ちるまで勝点1"}]},
        {"name": "田中碧", "club_jp": "リーズ", "position": 5, "points": 9,
         "out": False, "out_note": "",
         "lines": [{"line": 4, "side": "outside", "label": "CL圏内",
                    "text": "CL圏内と勝点で並んでいる"}]},
    ],
    "lines": [{"at": 4, "label": "CL圏内", "diff": 1, "moved": False,
               "inside": [{"position": 3, "team": "ブライトン", "points": 10}],
               "outside": [{"position": 5, "team": "リーズ", "points": 9}]}],
}
mix = nm.load(str(HERE / "no-such-dir"))
mix["soccer"] = SOCCER
sp = nm.panels(mix)
check("クラブ数が数でも落ちない", "soccer" in sp, True)
check("並ぶのは日本人選手", [r["name"] for r in sp["soccer"]["rows"]],
      ["三笘薫（ブライトン）", "田中碧（リーズ）"])
check("順位を添える", sp["soccer"]["rows"][0]["value"], "3位")
has("札の見出しは短く", sp["soccer"]["head"], "第5節")

sf = nm.facts(mix)
has("選手の現在地を渡す", sf, "CL圏内。落ちるまで勝点1")
has("離脱は離脱と書く", sf, "負傷などで離脱中")
hasnt("英語のまま渡さない", sf, "Hamstring")
hasnt("材料の辞書を生で出さない", sf, "'at':")
has("終わった節はそう書く", sf, "第5節終了時点")

# 次の節が始まっている日。**順位表は第5節までの姿のまま。**
mid = dict(SOCCER)
mid["round_complete"] = False
mix["soccer"] = mid
sf2 = nm.facts(mix)
hasnt("進行中を「終わった」と書かない", sf2, "第5節終了時点")
has("進行中と分かるように書く", sf2, "第6節は進行中")
has("札は進行中でも短いまま", nm.panels(mix)["soccer"]["head"], "第5節")

section("実データ")
# **その日の中身は検査しない。**
#
# 「選手が並ぶ」「話せる材料がある」を求めていたら、9/20に落ちた。
# 日本人選手が出ていない日・オールスター・シーズンオフには必ず落ちる。
# **コードが何も変わっていないのに日が変わって赤くなる検査**は、
# 9/15に別の場所でも直したばかりの型（test_soccer_rules）。
#
# ここで見たいのは「実データを通しても壊れないか」であって、
# その日に選手が何人いたかではない。
real = nm.load(str(HERE.parent / "data"))
check("実データで落ちない", isinstance(real, dict), True)
check("人数を絞る", len(real["players"]) <= nm.MAX_PLAYERS, True)
check("材料の有無を答えられる", isinstance(nm.has_enough(real), bool), True)
if not real["players"]:
    print("    （きょうは出場した選手がいないので、中身の検査は飛ばします）")
text = nm.facts(real)
# 禁じたいのは「圏内まで+1.5」という**符号付きの曖昧な形**。
# 9/15にこう書いて、圏内なのか圏内を目指しているのか読めなかった。
# 「進出圏内まであと3.0ゲーム」は圏外の球団について正しい表現なので、
# こちらは通す。
hasnt("圏内まで＋符号、という書き方をしない", text, "圏内まで+")
hasnt("圏内で＋符号も書かない", text, "圏内で+")
for row in real["rare"]:
    check("同率を拾わない（%s）" % row["stat"], "タイ" in row["rank"], False)
# 実データに同率が無い日もあるので、作り物でも押さえておく。
check("ties>1 は出さない",
      [r for r in nm.load(str(HERE / "no-such-dir"))["rare"]], [])
panels = nm.panels(real)
check("札に締めがある", "topic" in panels, True)
for key, panel in panels.items():
    check("%s に説明がある" % key, bool(panel.get("menu")), True)
    check("%s の型が描画にある" % key,
          panel["type"] in ("star", "stat", "group", "topic"), True)

section("二人の口調が混ざらないか")
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

sys.exit(done())
