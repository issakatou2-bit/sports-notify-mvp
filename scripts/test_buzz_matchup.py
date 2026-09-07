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

# ------------------------------------------------------------------
# 並べ替え。**まとめ動画を先頭に置かない。**
#
# 9/7に、題が "Highlights from ALL GAMES on 9/5 (Munetaka Murakami makes
# history, ...)" という**その日の全試合まとめ**が先頭へ来た。
# 村上の名前が入っているので「日本人選手を先頭へ」の条件には合っていた。
# だが個別の試合ではないので、対戦カードも結果もスコアボードも取れず、
# 再生回数ランキングの画面では3万回が19万回より上に並んでいた。
# ------------------------------------------------------------------
print(chr(10) + "=== 並べ替え ===")


def _v(views, matchup, title):
    return {"views": views, "matchup": matchup, "title": title}


def _check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'ok ' if ok else 'NG '} {label}: {got!r}"
          + ("" if ok else f"   (期待 {want!r})"))


ALL_GAMES = _v(32853, "", "Highlights from ALL GAMES on 9/5 "
                          "(Munetaka Murakami makes history)")
rows = [ALL_GAMES,
        _v(197774, "YANKEES vs. PADRES", "YANKEES vs. PADRES: Official"),
        _v(144508, "BRAVES vs. PHILLIES", "BRAVES vs. PHILLIES: Official"),
        _v(107226, "BLUE JAYS vs. ROYALS", "BLUE JAYS vs. ROYALS: Official")]
got = mlb_buzz.prefer_japanese(list(rows))
_check("先頭が個別の試合", bool(got[0]["matchup"]), True)
_check("まとめ動画は末尾", got[-1]["matchup"], "")
_check("試合どうしは再生順のまま",
       [v["views"] for v in got if v["matchup"]], [197774, 144508, 107226])

# 個別の試合に日本人選手がいる日は、これまで通り先頭へ。
rows2 = [_v(200000, "YANKEES vs. PADRES", "YANKEES vs. PADRES: Official"),
         _v(90000, "TWINS vs. WHITE SOX",
            "TWINS vs. WHITE SOX (Munetaka Murakami homers)")]
_check("日本人選手のいる試合を先頭へ",
       mlb_buzz.prefer_japanese(list(rows2))[0]["matchup"],
       "TWINS vs. WHITE SOX")

# まとめ動画に日本人選手がいても、そちらは選ばない。
_check("まとめ動画は選ばない",
       mlb_buzz.prefer_japanese([ALL_GAMES,
                                 _v(1, "A vs. B", "A vs. B")])[0]["matchup"],
       "A vs. B")

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
