"""クラブの表示名/短名/読みの入口。API名と原文は同一性のため保持する。"""
import functools
import json
from pathlib import Path
import re
import unicodedata

ROOT=Path(__file__).resolve().parents[1]


def normalize(value):
    value=unicodedata.normalize('NFKC',value or '').casefold()
    if not re.search(r'[一-龯ぁ-んァ-ヶ]',value):
        value=''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c))
    return re.sub(r'[\s・.\-_/]+','',value)


@functools.lru_cache(maxsize=1)
def rows():
    data=json.loads((ROOT/'data/club_display_names.json').read_text(encoding='utf-8'))
    return data['clubs']+data.get('extra_clubs',[])


@functools.lru_cache(maxsize=1)
def index():
    result={}
    for row in rows():
        for alias in [row['id'],row['current'],row['display'],row['short'],row['legacy'],*row.get('aliases',[])]:
            key=normalize(alias)
            if key in result and (result[key] is None or result[key]['id']!=row['id']):
                result[key]=None  # BREはBrentford/Bremen双方。略称だけで決めない。
            else:
                result[key]=row
    return result


def lookup(value):
    if isinstance(value,dict):
        value=value.get('team_en') or value.get('name_jp')
    return index().get(normalize(value))


def display(value, *, short=False, legacy=False):
    row=lookup(value)
    if row:return row['legacy'] if legacy else row['short'] if short else row['display']
    return (value.get('name_jp') or value.get('team_en')) if isinstance(value,dict) else value


@functools.lru_cache(maxsize=1)
def text_pairs():
    pairs={}
    for row in rows():
        for alias in [row['current'],row['legacy'],row['display'],row['id'],*row.get('aliases',[])]:
            # 短い英略称・普通名詞を文中で置換しない。
            if re.search(r'[一-龯ぁ-んァ-ヶ]',alias) or alias==row['id']:
                resolved=lookup(alias)
                if resolved and resolved['id']==row['id']:pairs[alias]=row['display']
    return pairs


def display_text(text):
    pairs=text_pairs()
    if not pairs:return str(text or '')
    pattern='|'.join(re.escape(key) for key in sorted(pairs,key=len,reverse=True))
    return re.sub(pattern,lambda m:pairs[m.group()],str(text or ''))


def readings():
    result={}
    for row in rows():
        for alias in [row['id'],row['current'],row['display'],row['short'],*row.get('aliases',[])]:
            resolved=lookup(alias)
            # Nice等の普通の英単語をクラブと決めつけない。正式英名/表示短名だけ。
            speakable=(bool(re.search(r'[一-龯ぁ-んァ-ヶ]',alias))
                       or alias==row['id'] or alias in (row['display'],row['short']))
            if speakable and len(alias)>=3 and resolved and resolved['id']==row['id']:
                result[alias]=row.get('reading','')
    return result
