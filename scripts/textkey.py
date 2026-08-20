#!/usr/bin/env python3
"""
名前を照合するときの、キーの作り方を1か所に置く。

なぜ要るのか:
  Edwin Díaz を "iaz" で検索して見つけられず、いないと言い切った。
  それは調べ方の粗さだが、同じ粗さがコードの中にもあった。

  現役に Díaz は6人いる。アクセントを落とさずに数えていたので
  Diaz(1人) と Díaz(5人) に割れ、前者だけが「同姓なし＝一意」として
  残った。ファンが書く "diaz" に、無関係な選手の成績が付くところだった。

  怖いのは、壊れても壊れたと分からないこと。照合が外れれば
  「該当なし」で静かに済むが、割れて一意に見えると別人を出す。

  同じことが読み上げ側でも起きていた。Wikidataから学んだ姓の表は
  キーにアクセントが残っていて、"Diaz" では引けない。たまたま
  手書きの表に "Diaz" があったので気付かなかった。

決めごと:
  名前を辞書のキーにするときは、必ずここを通す。
  照合用のキーと、画面に出す表記は別。表記は元のまま残す。
"""

import re
import unicodedata

# 名前の後ろに付く、人を区別しない語。
SUFFIXES = ("Jr", "Sr", "II", "III", "IV", "V")


def fold(s: str) -> str:
    """アクセントと合字を落とす。Díaz -> Diaz、Muñoz -> Munoz。"""
    if not s:
        return ""
    for a, b in (("ø", "o"), ("Ø", "O"), ("æ", "ae"), ("Æ", "AE"),
                 ("ß", "ss"), ("đ", "d"), ("Đ", "D"), ("ł", "l"),
                 ("Ł", "L")):
        s = s.replace(a, b)
    d = unicodedata.normalize("NFKD", s)
    return "".join(c for c in d if not unicodedata.combining(c))


def key(s: str) -> str:
    """辞書のキーにする形。アクセントを落として小文字にする。"""
    return fold(s).lower().strip()


def surname(name: str) -> str:
    """
    照合に使う姓。無ければ空。

    Jr. や III は落とす。人を区別しないうえ、付ける人と付けない人がいる。
    """
    parts = [x for x in fold(name).replace(".", "").split()
             if x and x not in SUFFIXES]
    return parts[-1] if len(parts) >= 2 else ""


def words(text: str, min_len: int = 3) -> list:
    """文から、名前になりうる語を拾う。大文字小文字は見ない。"""
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", fold(text))
            if len(w) >= min_len]


def unique_by(rows: list, get_key) -> dict:
    """
    キーが1人に決まるものだけを返す。

    2人以上が同じキーになったら、そのキーは捨てる。
    誰のことか決められないまま片方を出すと、そのまま嘘になる。
    """
    grouped = {}
    for row in rows:
        k = get_key(row)
        if k:
            grouped.setdefault(k, []).append(row)
    return {k: v[0] for k, v in grouped.items() if len(v) == 1}
