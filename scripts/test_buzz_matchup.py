#!/usr/bin/env python3
"""
MLB公式ハイライトのタイトルから対戦カードを取り出せているかを検証する。

    python3 scripts/test_buzz_matchup.py

なぜ要るか:
  公式タイトルの書式は一定ではない。実際に取得したデータは
    "RANGERS vs. ANGELS: Official Full Game Highlights (August 10) | 2026 MLB Season"
  で、球団名が全て大文字、対戦カードの後ろに ":" 区切りの但し書きが付いていた。
  日本語への変換は完全一致で探していたため何も置き換わらず、
  「RANGERS 対 ANGELS: Official Full」と読み上げていた。
  同じ理由で、コレスポの選定と現地順位の突き合わせも当たらなくなっていた。

APIキーは要らない。確かめたいのは文字列の処理だけ。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mlb_buzz  # noqa: E402

# (実際に返ってきた/返ってきうるタイトル, 期待する日本語のカード)
CASES = [
    ("RANGERS vs. ANGELS: Official Full Game Highlights (August 10) | 2026 MLB Season",
     "レンジャーズ 対 エンゼルス"),
    ("Angels vs. Dodgers Game Highlights (8/9/26) | MLB Highlights",
     "エンゼルス 対 ドジャース"),
    ("RED SOX vs. WHITE SOX: Official Full Game Highlights (August 7) | 2026 MLB Season",
     "レッドソックス 対 ホワイトソックス"),
    ("Blue Jays vs. Yankees Game Highlights (8/11/26) | MLB Highlights",
     "ブルージェイズ 対 ヤンキース"),
    ("D-backs vs. Rockies Game Highlights (8/12/26)",
     "ダイヤモンドバックス 対 ロッキーズ"),
]

fails = 0
for title, want in CASES:
    got = mlb_buzz.jp_matchup(mlb_buzz.extract_matchup(title))
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {got}" + ("" if ok else f"   (期待 {want})"))
    print(f"    <- {title[:72]}")

# 英字が残っていないこと。残っていれば読み上げが崩れる。
for title, _ in CASES:
    got = mlb_buzz.jp_matchup(mlb_buzz.extract_matchup(title))
    leftover = [c for c in got if c.isascii() and c.isalpha()]
    if leftover:
        fails += 1
        print(f"NG  英字が残っている: {got}")

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
