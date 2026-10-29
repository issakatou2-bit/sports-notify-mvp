"""名簿/材料にある固有名の辞書欠測と、VOICEVOXの実queryの読み違いを止める。"""
import copy
import csv
import functools
import json
from pathlib import Path
import re
import unicodedata

try:
    from . import club_display_names as clubs
except ImportError:
    import club_display_names as clubs
ROOT=Path(__file__).resolve().parents[1]


class NameReadingError(ValueError):
    pass


@functools.lru_cache(maxsize=1)
def player_data():
    return json.loads((ROOT/'data/player_kana.json').read_text(encoding='utf-8'))


@functools.lru_cache(maxsize=1)
def manager_data():
    return json.loads((ROOT/'data/manager_readings.json').read_text(encoding='utf-8'))


def managers():
    return manager_data()['names']


def manager_reading(name):
    return {clubs.normalize(k):v for k,v in managers().items()}.get(clubs.normalize(name))


def player_readings():
    return dict(player_data().get('readings',{}),**player_data().get('short_readings',{}))


def player_reading(name):
    import notability_engine as ne
    aliases=dict(player_data().get('reading_aliases',{}))
    for key in ('JP_PLAYERS_SOCCER','JP_PLAYERS_MLB'):
        aliases.update({p['name_en']:p['name_jp'] for p in getattr(ne,key,[]) if p.get('name_en')})
    canonical={clubs.normalize(k):v for k,v in aliases.items()}.get(clubs.normalize(name),name)
    return {clubs.normalize(k):v for k,v in player_readings().items()}.get(clubs.normalize(canonical))


@functools.lru_cache(maxsize=1)
def shared_readings():
    path=ROOT/'data/yomi_shared.csv'
    with path.open(encoding='utf-8-sig',newline='') as stream:
        rows=csv.reader(stream);next(rows)
        return {r[0]:r[1] for r in rows if len(r)>=2 and r[0] and r[1]}


@functools.lru_cache(maxsize=4096)
def pattern(name):
    if re.search(r'[一-龯ぁ-んァ-ヶ]',name) and not re.search(r'[A-Za-z]',name):
        return re.compile(r'[・\s]*'.join(r'[・\s]*' if c=='・' else re.escape(c) for c in name))
    return re.compile(r'(?<![A-Za-z0-9])'+re.escape(name)+r'(?![A-Za-z0-9])',re.I)


def entries():
    import notability_engine as ne
    live=[p for key in ('JP_PLAYERS_SOCCER','JP_PLAYERS_MLB') for p in getattr(ne,key,[])]
    known=set(player_data()['japanese_players'])|{p['name_jp'] for p in live}
    out={name:('player',player_readings().get(name,'')) for name in known}
    out.update({name:('player',reading) for name,reading in player_readings().items()})
    out.update({name:('player',reading) for name,reading in player_data().get('short_readings',{}).items()})
    out.update({p['name_en']:('player',player_readings().get(p['name_jp'],'')) for p in live if p.get('name_en')})
    out.update({alias:('player',player_readings().get(name,''))
                for alias,name in player_data().get('reading_aliases',{}).items()})
    out.update({name:('club',reading) for name,reading in clubs.readings().items()})
    out.update({name:('manager',reading) for name,reading in managers().items()})
    # 共通CSVの一般語（例: 山路）は人物の姓にもなり得る。
    # 固有名の検査へ無条件に混ぜず、確認時の参照だけに使う。
    return out


def occurrences(text):
    used=[];found=[]
    for name,(kind,reading) in sorted(entries().items(),key=lambda x:len(x[0]),reverse=True):
        for match in pattern(name).finditer(text or ''):
            if any(match.start()<b and match.end()>a for a,b in used):continue
            used.append(match.span());found.append(dict(name=name,kind=kind,reading=reading,start=match.start(),end=match.end()))
    return sorted(found,key=lambda row:row['start'])


def assert_known(text, entities=()):
    found=occurrences(text)
    for row in found:
        if not row['reading']:raise NameReadingError('読み辞書にない'+row['kind']+': '+row['name'])
    for kind,name in entities:
        if not name:continue
        if not pattern(name).search(text or ''):continue  # 台詞に出ない背景材料だけで止めない。
        known=(player_reading(name) if kind=='player' else
               (clubs.lookup(name) or {}).get('reading') if kind=='club' else manager_reading(name))
        if not known:raise NameReadingError('材料の'+kind+'の読み辞書が未登録: '+name)
    # 台詞内で役割が明示された監督名。一般語を人名と決めつけない。
    generic={'新','前','現','元','新人','名','臨時','代理','次期','代表','日本代表','日本','日本人','世界','各','球団','チーム','相手','敵','両','同','選手兼','ヘッド','アシスタント','再度','代目'}
    import notability_engine as ne
    team_names=set(ne.MLB_TEAM_NAME_JP.values())
    for match in re.finditer(r'([ァ-ヶー・]{2,30}|[一-龯々]{2,6}|[A-Z][a-z]+(?: [A-Z][a-z]+){0,3})監督',text or ''):
        name=match[1]
        if name not in generic and name not in team_names and not clubs.lookup(name) and not manager_reading(name):
            raise NameReadingError('監督名の読み辞書が未登録: '+name)
    generic_players={'日本人','日本代表','代表','若手','新人','新','前','現','元','同','各','両','全','他','主力','所属','一部','当該','注目','期待','現地','海外','登録','欠場','出場','先発','救援','中継','中継ぎ','左腕','右腕','二刀流','歴代','支配下','育成','契約','控え','対戦相手','外国人','内野','外野','現役','親子','両先発','実力派','野球','伝説的','位置','中核','複数','日本人複数','好調','主軸','月間最優秀','先発両','最速','奪三振','人気','構成','著名'}
    for match in re.finditer(r'(?<![一-龯﨑々])([一-龯﨑々]{2,6})(?:選手|投手)',text or ''):
        name=match[1]
        if name not in generic_players and not player_reading(name):
            raise NameReadingError('日本人選手名の読み辞書が未登録: '+name)
    return found


def dialogue_entities(dialogue):
    out=[]
    for seg in dialogue.get('segments',[]):
        meta=seg.get('meta') or {}
        if seg.get('kind') in ('jp_player','cover'):out.append(('player',meta.get('name')))
        if meta.get('player_detail'):out.append(('player',meta['player_detail']))
        if meta.get('expectation_name'):out.append(('player',meta['expectation_name']))
        for key in ('club','home','away','manager','coach'):
            if isinstance(meta.get(key),str):out.append(('manager' if key in ('manager','coach') else 'club',meta[key]))
        for key in ('jp','jp_players','absent'):
            values=meta.get(key) or []
            if isinstance(values,dict):values=[name for names in values.values() for name in names]
            if isinstance(values,list):out.extend(('player',name) for name in values if isinstance(name,str))
    return out


def validate_dialogue(dialogue):
    return assert_known('\n'.join(s.get('text','') for s in dialogue.get('segments',[])),dialogue_entities(dialogue))


def apply(text):
    found=assert_known(text)
    for row in reversed(found):
        club=clubs.lookup(row['name']) if row['kind']=='club' else None
        spoken=((club or {}).get('spoken') or
                manager_data().get('speech_overrides',{}).get(row['name']) or row['reading'])
        text=text[:row['start']]+spoken+text[row['end']:]
    return text


def normalized_kana(value):
    value=unicodedata.normalize('NFKC',value or '')
    value=''.join(chr(ord(c)+0x60) if 'ぁ'<=c<='ゖ' else c for c in value)
    value=re.sub(r'[^ァ-ヶー]','',value)
    groups=[('アカサタナハマヤラワガザダバパァャ','ア'),('イキシチニヒミリギジヂビピィ','イ'),
            ('ウクスツヌフムユルグズヅブプゥュヴ','ウ'),('エケセテネヘメレゲゼデベペェ','エ'),('オコソトノホモヨロヲゴゾドボポォョ','オ')]
    out=''
    for c in value:
        if c=='ー':c=next((vowel for chars,vowel in groups if out and out[-1] in chars),'ー')
        elif c=='ウ' and out and out[-1] in groups[-1][0]:c='オ'
        elif c=='イ' and out and out[-1] in groups[-2][0]:c='エ'
        out+=c
    return out


def japanese_readings():
    """フルネームだけ。短名・外国人・監督は氏名結合の対象にしない。"""
    import notability_engine as ne
    names=set(player_data()['japanese_players'])
    names.update(p['name_jp'] for key in ('JP_PLAYERS_MLB','JP_PLAYERS_SOCCER')
                 for p in getattr(ne,key,[]))
    return {normalized_kana(player_readings().get(name,'')) for name in names}


def query_name_locations(original,query):
    """候補の氏名範囲の中だけで長音を照合し、前の語の母音を持ち込まない。"""
    raw='';owners=[];boundaries={0}
    for pi,phrase in enumerate(query.get('accent_phrases',[])):
        for mi,mora in enumerate(phrase.get('moras',[])):
            text=unicodedata.normalize('NFKC',mora['text'])
            text=''.join(chr(ord(c)+0x60) if 'ぁ'<=c<='ゖ' else c for c in text)
            text=re.sub(r'[^ァ-ヶー]','',text)
            raw+=text;owners.extend([(pi,mi)]*len(text));boundaries.add(len(raw))
    used={};out=[]
    for row in assert_known(original):
        kana=normalized_kana(row['reading'])
        if not kana:continue
        start=next((i for i in range(used.get(kana,0),len(raw)-len(kana)+1)
                    if i in boundaries and i+len(kana) in boundaries and
                    normalized_kana(raw[i:i+len(kana)])==kana),None)
        if start is None:
            raise NameReadingError('VOICEVOX queryの読み不一致: '+kana+' / 実際 '+normalized_kana(raw)+' / 元の読み '+raw)
        end=start+len(kana);used[kana]=end
        out.append(dict(row,first=owners[start],last=owners[end-1],query_reading=raw[start:end]))
    return out


def name_phrase_spans(original, query):
    """読み照合後、氏名がまたぐqueryの句番号を返す。長音表記も同一視。"""
    out=[];full=japanese_readings()
    for row in query_name_locations(original,query):
        kana=normalized_kana(row['reading'])
        if row['kind']!='player' or not kana or kana not in full:continue
        out.append(dict(name=row['name'],first=row['first'][0],last=row['last'][0]))
    return out


def prepare_query(original, query, speaker, url):
    """日本人氏名内の境界だけ結合。変更した句のみVOICEVOXで高低/長さを再計算。"""
    import requests
    # 修正で読み違いを隠さない。ここでは既存の読み検査だけ先に行う。
    validate_query(original,query,check_phrases=False)
    spans=name_phrase_spans(original,query)
    joins={i for s in spans for i in range(s['first'],s['last'])}
    import name_accent_guard
    if not joins:
        result=name_accent_guard.prepare(original,query,speaker,url)
        validate_query(original,result)
        return result
    result=copy.deepcopy(query);phrases=result['accent_phrases'];merged=[];changed=[]
    index=0
    while index<len(phrases):
        phrase=phrases[index];last=index
        while last in joins:
            last+=1
            phrase['moras'].extend(phrases[last]['moras'])
            phrase['pause_mora']=phrases[last].get('pause_mora')
            phrase['is_interrogative']=phrases[last].get('is_interrogative',False)
        if last>index:changed.append(len(merged))
        merged.append(phrase);index=last+1
    response=requests.post(url.rstrip('/')+'/mora_data',params={'speaker':speaker},
                           json=[merged[i] for i in changed],timeout=30)
    response.raise_for_status();recomputed=response.json()
    if len(recomputed)!=len(changed):raise NameReadingError('氏名の句の再計算に失敗')
    for i,phrase in zip(changed,recomputed):merged[i]=phrase
    result['accent_phrases']=merged
    # kanaは元queryの区切り文字を含むため補正後の証拠として使わない。
    result['kana']=''
    result=name_accent_guard.prepare(original,result,speaker,url)
    validate_query(original,result)
    return result


def validate_query(original, query, check_phrases=True):
    actual=''.join(m['text'] for phrase in query.get('accent_phrases',[]) for m in phrase.get('moras',[]))
    actual=normalized_kana(actual);details=[]
    for row in query_name_locations(original,query):
        kana=normalized_kana(row['reading'])
        details.append(dict(name=row['name'],kind=row['kind'],expected=kana,actual=normalized_kana(row['query_reading'])))
    spans=name_phrase_spans(original,query) if check_phrases else []
    for span in spans:
        if span['first']!=span['last']:
            raise NameReadingError('VOICEVOX queryの氏名が複数句/内部の間: '+span['name'])
    import name_accent_guard
    accent_checks=name_accent_guard.inspect(original,query) if check_phrases else []
    return dict(status='PASS',names=details,actual_kana=actual,name_phrases=spans,
                name_accents=accent_checks,unverified_accents=[r['name'] for r in accent_checks if r['status']=='UNVERIFIED'])
