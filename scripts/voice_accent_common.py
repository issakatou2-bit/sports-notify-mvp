"""APSCの共通高低関数の写し。出所/更新方法はNAME_ACCENT_2026-10-12.md。"""

import re

import unicodedata

def mora_count(reading):
    # リリィのィは独立のイ。VOICEVOXのモーラ定義に合わせる。
    joined = re.findall(r"[イキギシジチヂニヒビピミリ][ャュョェ]|[ウクグスズツヅトドフヴ][ァィェォャュョ]|[テデ][ィュ]|[ァ-ヴー]", reading)
    if "".join(joined) != reading:
        raise ValueError(f"カタカナ読みが不正: {reading}")
    return len(joined)

def pattern_to_accent(pattern):
    """単一の下がり目とVOICEVOXの句頭の上昇で表せる型だけ変換。"""
    if not pattern or set(pattern) - {"L", "H"}:
        return None
    if pattern == "H" + "L" * (len(pattern) - 1):
        return 1
    if pattern == "L" + "H" * (len(pattern) - 1) and len(pattern) > 1:
        return 0
    for accent in range(2, len(pattern)):
        if pattern == "L" + "H" * (accent - 1) + "L" * (len(pattern) - accent):
            return accent
    return None

def katakana(text):
    text = unicodedata.normalize('NFKC', text)
    return ''.join(chr(ord(c) + 96) if 'ぁ' <= c <= 'ゖ' else c for c in text)

def moras(text):
    # 長音は1モーラ。拗音・外来音の小書きだけを前の文字と結ぶ。
    return re.findall(r'[イキギシジチヂニヒビピミリ][ャュョェ]|[ウクグスズツヅトドフヴ][ァィェォャュョ]|[テデ][ィュ]|[ァ-ヴー]', katakana(text))

def pattern(n, a):
    if not n:
        return ''
    if a == 1:
        return 'H' + 'L' * (n - 1)
    return 'L' + 'H' * ((a or n) - 1) + 'L' * (n - (a or n))

def phrase_pattern(size, accent):

    # audio_queryには平板の0がない。句末のaccentは句内では平板と同形。

    if not 1 <= accent <= size:

        raise ValueError(f"句のaccentが範囲外: {accent}/{size}")

    if accent == 1:

        return "H" + "L" * (size - 1)

    return "L" + "H" * (accent - 1) + "L" * (size - accent)

def flatten(query):

    flat, phrases = [], []

    for i, phrase in enumerate(query["accent_phrases"]):

        moras = [m["text"] for m in phrase["moras"]]

        if not moras:

            continue

        pat = phrase_pattern(len(moras), phrase["accent"])

        start = len(flat)

        flat.extend(dict(kana=m, highlow=p, phrase=i, offset=j) for j, (m, p) in enumerate(zip(moras, pat)))

        phrases.append(dict(index=i, start=start, end=len(flat), kana="".join(moras), accent=phrase["accent"], pattern=pat))

    return flat, phrases
