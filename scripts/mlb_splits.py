#!/usr/bin/env python3
"""MLB APIの成績行から、正しい1行を選ぶ。

なぜ要るのか:
  シーズン途中に移籍した選手は、APIが**合計と球団ごとの両方**を返す。

    team=(なし)              numTeams=2  28本  ← 合計
    team=Washington Nationals            23本
    team=New York Yankees                 5本

  全部足すと56本になる。9/7の長編で実際にそう出た——
  「ルイス・ガルシア56本、ベン・ライス36本」。176打点は歴代最多に迫る
  数字で、それが台本にも入っていた。

  足さずに「最初の1行」を採っているところも多い。**そちらは
  たまたま合計が先頭に来ているから合っているだけ**で、
  APIが順番を変えたらその日から静かにずれる。

  どちらの読み方も、選ぶ意図がコードに書かれていなかった。
  ここに1つ置いて、全部そこを通す。

試合ログ(gameLog)には使わない:
  あちらは1行が1試合で、合計の行は返らない。誤って通しても
  `numTeams` が無いので素通りするが、意味が違うので混ぜない。
"""


def prefer_total(splits):
    """合計の行があれば、それだけを返す。無ければそのまま。

    移籍していない選手は1行しか返らないので、この関数は何もしない。
    """
    rows = list(splits or [])
    total = [s for s in rows if isinstance(s, dict) and s.get("numTeams")]
    return total if total else rows


def season_stat(splits) -> dict:
    """今季（または通算）の1行ぶんの数字。無ければ空。

    「最初の1行」を採っていたところは、これに置き換える。
    移籍した選手の日だけ、球団ごとの数字ではなく合計を見るようになる。
    """
    rows = prefer_total(splits)
    if not rows:
        return {}
    return rows[0].get("stat") or {}
