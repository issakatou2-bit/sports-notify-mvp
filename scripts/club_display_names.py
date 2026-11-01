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


def candidate_keys(value):
    """候補表示専用。クラブ接辞の省略を登録済み判定へは持ち込まない。"""
    value=unicodedata.normalize('NFKD',value or '').casefold()
    value=''.join(c for c in value if not unicodedata.combining(c))
    tokens=re.findall(r'[^\W_]+',value)
    prefixes={'fc','sv','cf','afc','sc','ac','as','ss','rc','rcd','cd','ca',
              'fk','sk','bk','pfc','gnk','kks','tsg','vfb','vfl','ud','us','club'}
    stripped=''.join(t for t in tokens if t not in prefixes and not t.isdecimal())
    return {key for key in (normalize(value),stripped) if key}


def candidates(value, *, limit=5):
    """正規化一致/包含の近い登録行を返す。勝手に同一クラブとは判定しない。"""
    keys=candidate_keys(value);found=[]
    for row in rows():
        names=[row['id'],row['current'],row['display'],row['short'],row['legacy'],*row.get('aliases',[])]
        other={key for name in names for key in candidate_keys(name)}
        scores=[(0 if a==b else 1,abs(len(a)-len(b))) for a in keys for b in other
                if a==b or (min(len(a),len(b))>=4 and (a in b or b in a))]
        if scores:found.append((min(scores),row['id'],row['display']))
    return [dict(id=ident,display=label) for _,ident,label in sorted(found)[:limit]]


def display(value, *, short=False, legacy=False):
    row=lookup(value)
    if row:return row['legacy'] if legacy else row['short'] if short else row['display']
    return (value.get('name_jp') or value.get('team_en')) if isinstance(value,dict) else value


@functools.lru_cache(maxsize=1)
def text_pairs(include_short=False):
    pairs={}
    for row in rows():
        for alias in [row['current'],row['legacy'],row['display'],row['id'],*row.get('aliases',[]),*([row['short']] if include_short else [])]:
            # 短い英略称・普通名詞を文中で置換しない。
            if re.search(r'[一-龯ぁ-んァ-ヶ]',alias) or alias==row['id'] or (include_short and alias==row['short']):
                resolved=lookup(alias)
                if resolved and resolved['id']==row['id']:pairs[alias]=row['display']
    return pairs


def display_text(text, *, include_short=False):
    pairs=text_pairs(include_short)
    if not pairs:return str(text or '')
    pattern='|'.join(re.escape(key) for key in sorted(pairs,key=len,reverse=True))
    return re.sub(pattern,lambda m:pairs[m.group()],str(text or ''))


def youtube_title(text):
    """表示名を保ち、100字を超えた場合だけ末尾の補足を区切りごと落とす。"""
    title=display_text(text, include_short=True)
    if len(title)<=100:return title
    # 対戦カードを含む補足も途中で切らず、クラブ名が欠けないようにする。
    while '｜' in title:
        title=title.rsplit('｜',1)[0].rstrip()
        if len(title)<=100:return title
    title=re.sub(r'\s+#Shorts$', '', title)
    if len(title)>100:
        raise ValueError('題の本文が100字を超えています。クラブ名を保って題を見直してください')
    return title


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
