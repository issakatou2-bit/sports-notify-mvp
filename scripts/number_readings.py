"""字幕を保ち、音声に渡す分数の読みだけを確定する。"""
import re
import unicodedata

DIGITS = '零一二三四五六七八九'
KANA = ('れい', 'いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう')
NUM = '0-9０-９〇零一二三四五六七八九十百千万億兆'
FRACTION = re.compile(r'([' + NUM + r']+)分の(?=[' + NUM + r'])')


def integer(token):
    token = unicodedata.normalize('NFKC', token).replace('〇', '零')
    if token.isdecimal():
        return int(token)
    if all(c in DIGITS for c in token):
        return int(''.join(str(DIGITS.index(c)) for c in token))
    for char, unit in (('兆', 10**12), ('億', 10**8), ('万', 10**4), ('千', 1000), ('百', 100), ('十', 10)):
        if char in token:
            head, tail = token.split(char, 1)
            return (integer(head) if head else 1) * unit + (integer(tail) if tail else 0)
    raise ValueError('数値を読めません')


def kana(n):
    if n < 10:
        return KANA[n]
    for unit, word in ((10**12, 'ちょう'), (10**8, 'おく'), (10000, 'まん'), (1000, 'せん'), (100, 'ひゃく'), (10, 'じゅう')):
        if n >= unit:
            head, tail = divmod(n, unit)
            prefix = '' if head == 1 and unit <= 1000 else kana(head)
            spoken = {(300): 'さんびゃく', (600): 'ろっぴゃく', (800): 'はっぴゃく',
                      (3000): 'さんぜん', (8000): 'はっせん'}.get(head * unit, prefix + word)
            return spoken + (kana(tail) if tail else '')


def apply(text):
    def fraction(match):
        try:
            return kana(integer(match[1])) + 'ぶんの'
        except (ValueError, RecursionError):
            return match[0]
    return FRACTION.sub(fraction, text)
