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

import json
import pathlib
import subprocess
import sys
import tempfile

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
for text in (
    "そうね。再生回数はおよそ6万7000回ね。",
    "およそ6万7000回ね。",
    "再生回数は67000回ね。",
    "視聴回数は約67000回です。",
    "67000回再生されました。",
    "67,000回視聴されました。",
    "1億2345万6789回再生されました。",
    "再生回数は7回です。",
):
    check("再生/視聴の回数を投球回と読まない: " + text,
          sanity.parse_line(text), {})
check("再生回数と同じ文の本当の投球回は残す",
      sanity.parse_line("再生回数は67000回で、20回を投げた。"), {"回": 20.0})
check("投球回が先でも、再生回数だけ除く",
      sanity.parse_line("7回を投げて8奪三振、67000回再生された。"),
      {"回": 7.0, "奪三振": 8.0})
check("再生という語があるだけで文全体を除外しない",
      sanity.parse_line("再生すると、20回を投げたと分かる。"), {"回": 20.0})
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
check("今季の打数（9/7に成績の回を止めた）",
      sanity.check_line("X", "今季 550打数　160安打"), [])
check("通算の投球回", sanity.check_line("X", "通算 3000回　4000奪三振"), [])

# 一試合の幅は、原稿ではなく**データ行**のほうで見る。
# 行には「今季」「通算」が書いてあるので、文脈で切り替えられる。
print("\n--- 一試合の行は、引き続き一試合の幅で見る ---")
check("一試合で40回はありえない",
      len(sanity.check_line("X", "40.0回　3奪三振")) > 0, True)
check("一試合で24打数はありえない",
      len(sanity.check_line("X", "24打数5安打")) > 0, True)

# 実際の --strict の終了コードを確認。外部API・本番データは使わない。
print("\n--- 長編の停止判定 ---")
with tempfile.TemporaryDirectory() as tmp:
    folder = pathlib.Path(tmp)
    narration, result = folder / "dialogue.json", folder / "result.json"
    for label, text, code in (
        ("長編#16の再生回数で停止しない", "そうね。再生回数はおよそ6万7000回ね。", 0),
        # ここで見たいのは「再生回数の除外が、文を丸ごと飛ばしていないか」。
        # 9/7に「回」の幅を今季ぶんまで広げたので、20回は原稿では
        # 通るようになった（「ここ7日で20回」なら正しいため）。
        # 除外が広すぎないことは、桁違いの値で確かめる。
        # 通算7,356回が歴代最多なので、原稿に当てる幅は8,000まで。
        ("再生回数に続く桁違いの投球回は停止",
         "再生回数は67000回で、10000回を投げた。", 1),
        ("異常な打率は引き続き停止", "打率1.5です。", 1),
        # 9/7、これで**成績の回が丸ごと出なかった**。
        #
        # 「ここ7日」の合計を読み上げる画面を9/6に足した。24打数は
        # 7日ぶんなので正しい。だが原稿を見る側は「打数」の幅を
        # 一試合ぶん(0〜12)しか知らず、期間の数字を止めた。
        # 検算が正しい動画を止めたのは、これで4度目。
        ("ここ7日の合計で停止しない",
         "ここ7日では、スズキ・セイヤは24打数5安打　1本塁打　1打点。", 0),
        ("今季の投球回で停止しない", "今季は180回を投げて210奪三振です。", 0),
        ("今季の四球と三振で停止しない", "今季100四球　150三振です。", 0),

    ):
        narration.write_text(json.dumps({"segments": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE / "sanity.py"), "--strict",
             "--narration", str(narration), "--out", str(result)],
            cwd=folder, capture_output=True, text=True, encoding="utf-8")
        check(label, proc.returncode, code)
        check(label + "（出力JSON）", bool(json.loads(result.read_text(encoding="utf-8"))["impossible"]), bool(code))

print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
sys.exit(1 if fails else 0)
