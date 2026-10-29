"""英語字幕の固有名詞表。MLB公式表記は既存の共通名簿を参照する。
出典: https://www.mlb.com/team / https://www.mlb.com/players
名簿の更新元: notability_engine.MLB_TEAM_NAME_EN / JP_PLAYERS_MLB。
"""
import json
import re
import pathlib
import sys
import unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import notability_engine as ne


def names():
    table = {ne.MLB_TEAM_NAME_JP[key]: value for key, value in ne.MLB_TEAM_NAME_EN.items()}
    # Keys originate from MLB Stats API; kana is only an alias, never the English source.
    p = pathlib.Path(__file__).resolve().parents[1]/'data/player_kana.json'
    for english, kana in json.loads(p.read_text(encoding='utf-8')).get('names', {}).items():
        if kana and re.fullmatch(r"[A-Za-z .’'\-]+", english):
            table[kana] = english
    for player in ne.JP_PLAYERS_MLB:
        table[player['name_jp']] = player['name_en']
        if player.get('kana'):
            table[player['kana']] = player['name_en']
    return table


def required(text):
    return {ja: en for ja, en in names().items() if ja in text}


def normalized(text):
    text = unicodedata.normalize('NFKD', text).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def mentions(text):
    """長い日本語名を優先し、姓の省略は共通かな表から引く。"""
    table = {ja: {en} for ja, en in names().items()}
    for ja, en in names().items():
        kana = ja.split('・')
        words = en.split()
        if len(kana) > 1 and len(words) > 1:
            if words[-1].rstrip('.').lower() in {'jr', 'sr', 'ii', 'iii', 'iv'}:
                kana, words = kana[:-1], words[:-1]
            if len(kana) > 1 and len(words) > 1:
                # フルネームが書かれた場合は、フルネームの照合を維持する。
                table.setdefault(kana[-1], set()).add(words[-1])
    # 球団は所在地を省いた名称も、既存の公式名から得る。
    teams = set(ne.MLB_TEAM_NAME_EN.values())
    for ja, values in table.items():
        for value in list(values):
            if value in teams:
                short = ' '.join(value.split()[-2:]) if value.endswith(('White Sox', 'Red Sox', 'Blue Jays')) else value.split()[-1]
                values.add(short)
    used = set()
    out = {}
    for ja in sorted(table, key=len, reverse=True):
        # Leeなど短い姓を「リーグ」の一部と取り違えない。
        pattern = r'(?<![ァ-ヶー])' + re.escape(ja) + r'(?![ァ-ヶー])'
        found = [m for m in re.finditer(pattern, text)
                 if not used.intersection(range(m.start(), m.end()))]
        if found:
            out[ja] = table[ja]
            for match in found:
                used.update(range(match.start(), match.end()))
    return out


def mismatches(original, english):
    """不一致語だけを返す。原稿や翻訳本文を診断ログへ出さない。"""
    actual = ' ' + normalized(english) + ' '
    expected = mentions(original)
    missing = [ja for ja, choices in expected.items()
               if not any(' ' + normalized(name) + ' ' in actual for name in choices)]
    extras = []
    if missing:
        accepted = {normalized(name) for ja, choices in expected.items() if ja not in missing for name in choices}
        candidates = set(names().values())
        candidates.update(name.split()[-1].rstrip('.') for name in names().values() if ' ' in name)
        candidates.update(name.split()[-1] for name in ne.MLB_TEAM_NAME_EN.values())
        # 原文と対応しない、表で確認できる英語の名前だけを報告。
        extras = sorted({name for name in candidates
                         if not any(normalized(name) == match or normalized(name).endswith(' ' + match)
                                    or match.endswith(' ' + normalized(name)) for match in accepted)
                         and ' ' + normalized(name) + ' ' in actual})
        extras = [name for name in extras if not any(name != other and normalized(other).endswith(' ' + normalized(name))
                                                     for other in extras)]
    return missing, extras
