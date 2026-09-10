#!/usr/bin/env python3
"""サッカーのハイライトから、対戦カードと日本人選手を取れるか。

なぜ検査が要るのか:
  題の形が大会ごとに違う。区切りが "vs" のことも "2-1" のことも
  " - " のこともある。**推測で切っているので、外れ方を固定しておく。**

  そして**取れないときに空を返すこと**が同じくらい大事。
  記者会見や特集を試合として扱うと、「◯◯対◯◯のコメント欄」と
  言いながら中身が別のものになる。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import soccer_buzz as sb  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


print("--- 対戦カードの取り出し ---")
check("スコア区切り", sb.clubs("Liverpool 2-1 Atletico Madrid | Highlights"),
      ["Liverpool", "Atletico Madrid"])
check("vs 区切り", sb.clubs("Real Madrid vs Barcelona | LaLiga Highlights"),
      ["Real Madrid", "Barcelona"])
# 略記は正式名に読み替えて返す（canon）。名簿との照合も
# club_name_jp も、正式名のほうが当たる。
check("ハイフン区切り", sb.clubs("Bayern - Dortmund | Highlights"),
      ["FC Bayern Munchen", "Borussia Dortmund"])
check("全角の縦棒でも切れる",
      sb.clubs("Arsenal vs Napoli ｜ Champions League"),
      ["Arsenal", "Napoli"])
check("括弧の前で切る",
      sb.clubs("Inter vs Milan (Serie A Highlights)"),
      ["FC Internazionale Milano", "AC Milan"])

print()
print("--- 取れないときは空 ---")
check("記者会見", sb.clubs("Press conference: Guardiola on the derby"), [])
check("特集", sb.clubs("Top 10 goals of the month"), [])
check("空文字", sb.clubs(""), [])
check("クラブが3つ以上に割れる形",
      sb.clubs("A vs B vs C | Highlights"), [])

print()
print("--- 日本人選手（名簿から引く） ---")
check("リバプールの試合", sb.jp_in("Liverpool 2-1 Atletico Madrid | Highlights"),
      ["遠藤航"])
check("2クラブに日本人がいる試合",
      sb.jp_in("Crystal Palace 1-0 Brighton | Highlights"),
      ["鎌田大地", "冨安健洋", "三笘薫"])
check("いない試合", sb.jp_in("Real Madrid vs Barcelona | Highlights"), [])
check("カードが取れない題", sb.jp_in("Press conference"), [])

print()
print("--- ハイライトかどうか ---")
# recent() の中で使っている語。ここが緩すぎると記者会見を拾い、
# 厳しすぎるとリーグごとの言い回しを落とす。
for title, want in (
        ("Liverpool 2-1 Atletico | Highlights", True),
        ("Real Madrid vs Barca | Extended Highlights", True),
        ("Bayern - Dortmund | All Goals", True),
        ("Resumen: Real Madrid 2-0 Sevilla", True),
        ("Press conference: Guardiola", False),
        ("Player of the Month award", False)):
    got = any(w in title.lower() for w in sb.HIGHLIGHT_WORDS)
    check(title[:40], got, want)

print()
print("--- 公式チャンネルの一覧 ---")
check("大会が5つある", len(sb.OFFICIAL), 5)
# ハンドル名は候補を順に試す形にしてある。1つ書いて外すと、
# その大会が丸ごと消えたまま毎日「0本」と出る（9/10のCLがそれ）。
_handles = [h for hs, _ in sb.OFFICIAL for h in hs]
check("ハンドル名が重なっていない", len(set(_handles)), len(_handles))
check("チャンピオンズリーグに候補が2つ以上ある",
      len(sb.OFFICIAL[0][0]) >= 2, True)
# プレミアリーグは公式がフルハイライトを出していないので入れていない。
# 入れると毎日「0本」と出るだけになる。
check("プレミアリーグは入れていない",
      any("premier" in h.lower() for h in _handles), False)

print()
print("--- 試合以外を外す ---")
# 9/10に実際に拾ったもの。公式はトップチームの試合以外もたくさん出す。
for title, want in (
        ("Ordenamos los 15 GOLES de AUBAMEYANG en LaLiga", True),
        ("ALL ROUND 3 HIGHLIGHTS | PRIMAVERA 1 2026/27", True),
        ("Top 10 goals of the month", True),
        ("Real Madrid Femenino vs Barcelona | Highlights", True),
        ("Liverpool 2-1 Atletico Madrid | Highlights", False),
        ("Resumen: Real Madrid 2-0 Sevilla", False)):
    got = any(w in title.lower() for w in sb.NOT_MATCH)
    check(title[:44], got, want)

print()
print("--- セリエAの形（9/10に11本落とした） ---")
# 公式の題は「見出し | 対戦カード | HIGHLIGHTS」の順で、
# しかもハイフンにスペースが無い。先頭だけ見ていたので1本も
# 拾えなかった。
check("スペース無しの大文字ハイフン",
      sb.clubs("JUVENTUS-MILAN 1-1 | EXTENDED HIGHLIGHTS"),
      ["JUVENTUS", "AC Milan"])
check("見出しが先に来る形",
      sb.clubs("Gattuso Vince Ancora | UDINESE-LAZIO | HIGHLIGHTS"),
      ["UDINESE", "LAZIO"])
check("前置き(MAXI SINTESI)を落とす",
      sb.clubs("MAXI SINTESI ROMA-ATALANTA 2-1 | EXTENDED HIGHLIGHTS"),
      ["ROMA", "ATALANTA"])
# ハイフンを含むクラブ名を割らないこと。**両側が大文字のときだけ切る。**
check("Saint-Etienne を割らない",
      sb.clubs("AS Saint-Etienne vs Lyon | Highlights"),
      ["AS Saint-Etienne", "Lyon"])

print()
print("--- 略記の読み替え ---")
# club_name_jp は "milan" を意図して持っていない（"Inter Milan" と
# 部分一致するため "acmilan" で登録してある）。公式は MILAN と書く。
check("MILAN は ACミラン", sb.canon("MILAN"), "AC Milan")
check("INTER はインテル", sb.canon("INTER"), "FC Internazionale Milano")
check("知らない名前はそのまま", sb.canon("Sevilla"), "Sevilla")

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
