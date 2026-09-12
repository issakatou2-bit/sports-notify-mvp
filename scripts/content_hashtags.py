"""Small, relevant hashtag sets from the actual editorial text. No network/LLM.

Limits are our editorial policy, not a claim of optimal reach. Platform tagging
metadata and public hashtags are different; never read a whole unrelated roster
or a promotional footer as evidence of the episode's subject.
"""
from functools import lru_cache
from pathlib import Path
import re
import sys
import unicodedata

LIMITS = {'twitter': 2, 'bluesky': 3, 'instagram': 5, 'tiktok': 5,
          'youtube': 3, 'threads': 1}
LEAGUES = {'MLB': 'MLB', 'PL': 'プレミアリーグ', 'PD': 'ラリーガ',
           'SA': 'セリエA', 'BL1': 'ブンデスリーガ', 'FL1': 'リーグアン',
           'CL': 'チャンピオンズリーグ'}
TERMS = {
    'プレミアリーグ': ('プレミアリーグ', 'プレミア'),
    'ラリーガ': ('ラリーガ', 'ラ・リーガ'),
    'セリエA': ('セリエA',), 'ブンデスリーガ': ('ブンデスリーガ',),
    'リーグアン': ('リーグアン', 'リーグ・アン'),
    'チャンピオンズリーグ': ('チャンピオンズリーグ',),
    'ポストシーズン': ('ポストシーズン', '進出争い'),
    'ワイルドカード': ('ワイルドカード',),
    '野球初心者': ('野球初心者', '野球のルール', '2安打'),
    'サッカー初心者': ('サッカー初心者', 'CLと国内リーグ'),
    'OPS': ('OPS',), 'xG': ('xG', '期待ゴール'),
}


def clean(value):
    text = unicodedata.normalize('NFKC', str(value or '')).lstrip('#')
    tag = ''.join(c for c in text if c == '_' or c.isalnum())
    return tag if tag and not tag.isdigit() and len(tag) <= 40 else ''


@lru_cache(maxsize=1)
def entities():
    # Reuse the existing name registry, but select only names found in the text.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from notability_engine import JP_PLAYERS_MLB, JP_PLAYERS_SOCCER, MLB_TEAM_NAME_JP
    names = [(p['name_jp'], (p['name_jp'], p['name_en']))
             for p in JP_PLAYERS_MLB + JP_PLAYERS_SOCCER]
    return names + [(n, (n,)) for n in MLB_TEAM_NAME_JP.values()]


def present(alias, text):
    # Latin keywords need boundaries (e.g. xG must not match an unrelated word).
    if re.fullmatch(r'[A-Za-z0-9 ]+', alias):
        return re.search(r'(?<![A-Za-z0-9])' + re.escape(alias) + r'(?![A-Za-z0-9])', text, re.I) is not None
    return alias in text


def select(text, platform, *, sport='', subjects=(), leagues=(), shorts=False):
    limit = LIMITS[platform]
    text = unicodedata.normalize('NFKC', text)
    league_tags = list(dict.fromkeys(LEAGUES.get(x, x) for x in leagues if x))
    soccer = sport == 'soccer' or (not sport and (
        'サッカー' in text or any(any(a in text for a in TERMS[k]) for k in list(TERMS)[:6])))
    baseball = sport == 'mlb' or (not sport and not soccer and any(w in text for w in ('MLB', '野球', '大リーグ', 'メジャーリーグ')))
    base = 'サッカー' if soccer else ('MLB' if baseball and ('MLB' in text or sport == 'mlb') else '野球' if baseball else '')
    mentions = []
    for tag, aliases in entities():
        found = [text.find(a) for a in aliases if a in text]
        if found:
            mentions.append((min(found), tag))
    # Editorial subject hints still require an actual mention in this content.
    for tag in subjects:
        if tag and present(tag, text):
            mentions.append((text.find(tag), tag))
    mentions.sort(key=lambda row: row[0])
    topics = [tag for tag, aliases in TERMS.items() if any(present(a, text) for a in aliases)]
    candidates = [base] + [n for _, n in mentions] + league_tags + topics + ['コレスポ']
    result = []
    for value in candidates:
        tag = clean(value)
        if tag and tag not in result and tag.lower() not in ('shorts', 'fyp', 'viral'):
            result.append(tag)
    if shorts and platform == 'youtube':
        return result[:limit - 1] + ['Shorts']
    return result[:limit]


def display(tags):
    return ' '.join('#' + tag for tag in tags)


def strip_tags(text):
    return re.sub(r'(?<!\w)#[\w]+', '', text).strip()
