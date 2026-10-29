"""本人確認済みの高低と、出所を分けて採用した既定の高低を補正。"""
import copy
import csv
import json
from pathlib import Path

import voice_accent_common as common

ROOT=Path(__file__).resolve().parents[1]


def entries():
    import name_reading_guard as guard
    import notability_engine as ne
    names=set(guard.player_data()['japanese_players'])
    names.update(p['name_jp'] for key in ('JP_PLAYERS_MLB','JP_PLAYERS_SOCCER') for p in getattr(ne,key,[]))
    with (ROOT/'data/yomi_shared.csv').open(encoding='utf-8-sig',newline='') as stream:
        shared={r['語']:r for r in csv.DictReader(stream)}
    defaults=json.loads((ROOT/'data/name_accent_defaults.json').read_text(encoding='utf-8'))
    rows=[]
    for name in sorted(names):
        reading=guard.player_readings().get(name,'');row=shared.get(name,{})
        confirmed=bool(row.get('高低の並び'))
        if not confirmed:
            row=defaults.get(name,{})
        pat=row.get('高低の並び','').strip().upper() or None
        if pat:
            if (guard.normalized_kana(reading)!=guard.normalized_kana(row['読み']) or
                    len(pat)!=common.mora_count(reading) or common.pattern_to_accent(pat) is None or not row['どこで分かったか']):
                raise guard.NameReadingError('確認済み高低辞書の読み/型/出所が不正: '+name)
        rows.append(dict(name=name,reading=reading,pattern=pat,
                         source=row.get('どこで分かったか') if pat else None,
                         status=('CONFIRMED' if confirmed else 'DEFAULT_ACCEPTED') if pat else 'UNVERIFIED'))
    return rows


def locations(original,query):
    import name_reading_guard as guard
    table=entries();by_name={r['name']:r for r in table};by_kana={}
    for r in table:by_kana.setdefault(guard.normalized_kana(r['reading']),r)
    out=[]
    for row in guard.query_name_locations(original,query):
        kana=guard.normalized_kana(row['reading'])
        target=by_name.get(row['name']) or by_kana.get(kana)
        if row['kind']!='player' or not target:continue
        out.append(dict(**target,spoken_name=row['name'],first=row['first'],last=row['last']))
    return out


def inspect(original,query,strict=True):
    import name_reading_guard as guard
    checks=[]
    for row in locations(original,query):
        pi,mi=row['first'];pj,mj=row['last'];phrase=query['accent_phrases'][pi]
        actual=None
        if pi==pj and 'accent' in phrase:
            actual=common.phrase_pattern(len(phrase['moras']),phrase['accent'])[mi:mj+1]
        status='UNVERIFIED' if not row['pattern'] else 'PASS' if actual==row['pattern'] else 'FAIL'
        result=dict(name=row['name'],spoken_name=row['spoken_name'],status=status,
                    expected=row['pattern'],actual=actual,source=row['source'])
        checks.append(result)
        if strict and status=='FAIL':
            raise guard.NameReadingError('VOICEVOX queryの氏名高低不一致: '+row['name']+' '+str(actual)+' / '+row['pattern'])
    return checks


def prepare(original,query,speaker,url):
    import requests
    import name_reading_guard as guard
    confirmed=[r for r in locations(original,query) if r['pattern']]
    if not confirmed:return query
    result=copy.deepcopy(query);phrases=result['accent_phrases'];changed=False
    # 後ろから分けることで、それより前の氏名の位置を動かさない。
    for row in sorted(confirmed,key=lambda r:r['first'],reverse=True):
        pi,mi=row['first'];pj,mj=row['last']
        if pi!=pj:raise guard.NameReadingError('高低補正前の氏名が複数句: '+row['name'])
        phrase=phrases[pi]
        # 既定採用は氏名内のL/Hだけを固定する。既に一致していれば、
        # 姓名後の「です」等の下降位置まで平板に変えない。
        if (row['status']=='DEFAULT_ACCEPTED' and
                common.phrase_pattern(len(phrase['moras']),phrase['accent'])[mi:mj+1]==row['pattern']):
            continue
        if mi:
            prefix=copy.deepcopy(phrase);prefix['moras']=prefix['moras'][:mi]
            prefix['accent']=min(prefix['accent'],mi);prefix['pause_mora']=None;prefix['is_interrogative']=False
            prefix['_name_accent']=True
            suffix=copy.deepcopy(phrase);suffix['moras']=suffix['moras'][mi:]
            phrases[pi:pi+1]=[prefix,suffix];phrase=suffix
        a=common.pattern_to_accent(row['pattern'])
        desired=a or len(phrase['moras'])  # 平板は後続助詞も高くする。queryのaccentは1..句長。
        if mi or phrase['accent']!=desired:
            phrase['accent']=desired;phrase['_name_accent']=True;changed=True
    if not changed:return query
    indices=[i for i,p in enumerate(phrases) if p.pop('_name_accent',False)]
    response=requests.post(url.rstrip('/')+'/mora_data',params=dict(speaker=speaker),
                           json=[phrases[i] for i in indices],timeout=30)
    response.raise_for_status();recomputed=response.json()
    if len(recomputed)!=len(indices):raise guard.NameReadingError('氏名高低の再計算件数が不一致')
    for i,p in zip(indices,recomputed):phrases[i]=p
    result['kana']='';inspect(original,result)
    return result
