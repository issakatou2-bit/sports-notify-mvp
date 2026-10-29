"""材料やAIの記憶を使わず、原稿の中だけで確定する矛盾。"""
from decimal import Decimal
import re


def check(documents):
    errors = []
    for doc in documents:
        for index, segment in enumerate(doc.get('segments') or [], 1):
            text = segment.get('text') or ''
            # 同じ一人の連続した成績表記だけ。別人・別文の数を混ぜない。
            for match in re.finditer(r'(?<![\d,万])([0-9]+)打数\s*([0-9]+)安打', text):
                if int(match[2]) > int(match[1]):
                    errors.append(f'行{index}: {match[0]}は安打が打数より多い')
            for match in re.finditer(r'(?<![\d.,])([0-9]+(?:\.[0-9]+)?)\s*([+＋×*−-])\s*'
                                     r'([0-9]+(?:\.[0-9]+)?)\s*[=＝]\s*'
                                     r'([0-9]+(?:\.[0-9]+)?)(?![\d.])', text):
                a, b, claimed = (Decimal(match[n]) for n in (1, 3, 4))
                actual = a+b if match[2] in '+＋' else a*b if match[2] in '×*' else a-b
                if actual != claimed:
                    errors.append(f'行{index}: 計算{match[0]}が不一致（正しくは{actual}）')
    return errors
