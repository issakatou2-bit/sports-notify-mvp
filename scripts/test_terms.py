#!/usr/bin/env python3
"""用語の検査が、実際に出た誤りを止めるか。

なぜ検査が要るのか:
  9/16の長編が「HQS」を**「ヒットクオリティスタート」**と読み、
  投手の被打率を「打率」と書いた。ユーザーの言葉:
  「本当に終わってる。公開できませんこれは」。

  **どちらも数字は正しい。**`verify_numbers`（台詞と材料の照合）も
  `sanity`（値の常識）も通る。値ではなく呼び方の問題だから。

  そして「毎日人が見る」では解決しない
  （「わざわざ毎日見てからっていうのは手間すぎます」）。
  辞書で決められるところは機械で止める。**この検査が最後の砦。**
"""

import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import morning_recap as mr  # noqa: E402
import verify_terms as vt  # noqa: E402
from checks_report import check, section, done  # noqa: E402


def run(lines, players=None) -> int:
    """実際に起動して終了コードを見る。"""
    data = {"segments": [{"meta": {"who": "めたん"}, "text": t}
                         for t in lines],
            "material": {"players": players or []}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        path = f.name
    r = subprocess.run([sys.executable, str(HERE / "verify_terms.py"),
                        "--dialogue", path, "--strict"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    pathlib.Path(path).unlink(missing_ok=True)
    return r.returncode


PIT = [{"name": "山本由伸", "type": "pitcher"}]

section("9/16に実際に出た誤り")
check("HQSを「ヒットクオリティスタート」と読む",
      run(["7回1失点、ヒットクオリティスタートの内容ね。"]), 1)
check("投手に「打率」と書く",
      run(["山本由伸は初球で打率.338。"], PIT), 1)
check("投手に「OPS」と書く",
      run(["山本由伸は終盤の接戦でOPS.864よ。"], PIT), 1)

section("正しい書き方は通す")
check("ハイクオリティスタート",
      run(["7回1失点、ハイクオリティスタートと素晴らしい投球だったわ。"]), 0)
check("クオリティスタート", run(["6回2失点でクオリティスタートね。"]), 0)
check("投手には被打率", run(["山本由伸は初球で被打率.338。"], PIT), 0)
check("投手には被OPS", run(["山本由伸は終盤の接戦で被OPS.864よ。"], PIT), 0)
# **打者の行では「打率」でよい。**同じ回に打者も出る。
check("打者の打率は止めない",
      run(["村上宗隆は得点圏で打率.160よ。"], PIT), 0)

section("辞書に無い開き方")
check("ノーヒットノーランの崩れ",
      run(["きょうはパーフェクトヒットノーランね。"]), 1)
check("正しいノーヒットノーランは通す",
      run(["ノーヒットノーランを達成したわ。"]), 0)
check("サイクルヒットの崩れ",
      run(["サイクルグランドヒットを記録したのよ。"]), 1)
check("正しいサイクルヒットは通す",
      run(["サイクルヒットを達成したわ。"]), 0)

section("読み仮名は全部の記録にある")
# ユーザーの提案:「ネームド記録に読み仮名もつければいける？」
# 辞書にあれば、モデルが読み方を作る余地がなくなる。
_names = set()
for group in (mr.PITCHER_BADGES, mr.BATTER_BADGES):
    _names |= (set(group) if isinstance(group, dict)
               else {x[0] for x in group})
for name in sorted(_names):
    check("%s に読み方がある" % name, name in mr.BADGE_SPEECH, True)

section("壊れた材料で落ちない")
check("台本が無い",
      subprocess.run([sys.executable, str(HERE / "verify_terms.py"),
                      "--dialogue", "no-such-file.json", "--strict"],
                     capture_output=True).returncode, 0)
check("台詞が空", run([]), 0)
check("投手が分からなければ、打率を止めない",
      run(["山本由伸は初球で打率.338。"]), 0)
sys.exit(done())
