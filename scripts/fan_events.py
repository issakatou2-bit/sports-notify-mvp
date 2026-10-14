"""日本人選手の事実→表情/出来事の音/数字。判断はこの1か所。"""
import json
import logging
import os
from pathlib import Path
import re

TRACK = []
FPS = 24
LOG = logging.getLogger(__name__)


def enabled():
    return os.environ.get('COLLESPO_EXPR') == 'fan'


def rows(data):
    if isinstance(data, dict):
        if data.get('name') or data.get('name_jp'):
            yield data
        for key in ('players','games','results','items','expectation','probable_pitchers','segments','meta','card'):
            value = data.get(key)
            if isinstance(value, (dict,list)):
                yield from rows(value)
        for key in ('home_probable','away_probable'):
            p=data.get(key) or {}
            if p.get('player_id') and p.get('name'):
                yield dict(name=p['name'],type='pitcher',starter_confirmed=True,source=key)
        for key in ('home_pitcher','away_pitcher'):
            p=data.get(key) or {}
            if p.get('id') and p.get('display'):
                yield dict(name=p['display'],type='pitcher',starter_confirmed=True,source=key)
    elif isinstance(data, list):
        for value in data:yield from rows(value)


def decision(line, material):
    import characters
    if not enabled():return None
    for p in rows(material):
        name = str(p.get('name') or p.get('name_jp') or '')
        if not name or not any(n in name for n in characters.fan_names()):continue
        aliases = [name]
        import press_names
        aliases += [press_names.SURNAME.get(name, name)]
        if not any(n in line for n in aliases):continue
        typ = p.get('type')
        evidence = {'player':name,'type':typ}
        def pick(face,effect,event,key,value,unit=''):
            evidence.update(field=key,value=value)
            highlights=[f'{value}{unit}'] if unit else []
            if typ=='pitcher' and (p.get('so') or 0)>0:
                highlights.append(f'{p["so"]}奪三振')
            return dict(face=face,effect=effect,event=event,
                        reason=f'{name}・材料の{key}={value}', evidence=evidence,
                        highlights=highlights)
        if p.get('record_confirmed') is True and p.get('record_source'):
            return pick('surprise','burst','record','record_value',p.get('record_value'))
        if typ == 'pitcher':
            if (p.get('losses') or 0)>0:
                return pick('sad',None,None,'losses',p['losses'])
            if (p.get('wins') or 0)>0:
                return pick('pose-smile','sparkle','win','wins',p['wins'])
            if p.get('er') == 0 and float(p.get('ip') or 0)>0:
                return pick('pose-smile','sparkle',None,'er',0,'自責')
            if (p.get('er') or 0)>0:
                return pick('sad',None,None,'er',p['er'],'自責')
        elif typ == 'batter':
            if (p.get('hr') or 0)>0:
                return pick('pose-smile','sparkle','home_run','hr',p['hr'],'本塁打')
            if (p.get('hits') or 0)>=2:
                return pick('pose-smile','sparkle',None,'hits',p['hits'],'安打')
            if p.get('hits') == 0 and (p.get('ab') or 0)>0:
                return pick('sad',None,None,'hits',0,'安打')
        if (p.get('goals') or 0)>0:
            return pick('pose-smile','sparkle','goal','goals',p['goals'],'ゴール')
        if p.get('starter_confirmed') is True:
            return pick('smile','sparkle',None,'starter_confirmed',True)
        # 材料があるのに表情の根拠がない場合は、台詞から喜怒を捏造しない。
        if typ in ('pitcher','batter'):
            return pick('base','none',None,'type',typ)
    return None


def prepare(material, segments, durations, out_dir, fps=FPS):
    TRACK.clear()
    if not enabled():return
    start = 0.
    for seg,duration in zip(segments,durations):
        text = seg.get('text') or ''
        fact = decision(text, material)
        if not fact:
            import characters
            fallback = characters.fan_mood(text)
            fact = dict(face=fallback[0],effect=fallback[1],reason=fallback[2],event=None,
                        highlights=[],evidence=None) if fallback else None
        row = dict(start=start,end=start+int(duration*fps)/fps,text=text,
                   speech=float(seg.get('duration') or duration),decision=fact)
        TRACK.append(row)
        LOG.info('fan_expr %s', json.dumps(row,ensure_ascii=False))
        print('[fan_expr]', fact['reason'] if fact else 'この画面に表情の根拠なし')
        start=row['end']
    Path(out_dir,'fan-confirmation.json').write_text(json.dumps(
        dict(segments=TRACK,cues=event_cues(),timing='字幕と同じ文字数比。音素単位の時刻ではない',
             sound_source='scripts/sfx.py 数式による既存自作音',event_extra_db=-24),
        ensure_ascii=False,indent=2),encoding='utf-8')


def current():
    if not enabled():return None
    import review_render_v3 as r3
    clock=r3._PROGRAM_CLOCK[0]
    if clock is None:return None
    return next((r for r in TRACK if r['start']<=clock<r['end']),None)


def mood():
    row=current()
    d=row.get('decision') if row else None
    return (d['face'],d['effect'],d['reason']) if d else None


def number_focus(part):
    row=current()
    d=row.get('decision') if row else None
    if not d:return False
    import review_render_v3 as r3
    for target in d['highlights']:
        match=re.search(r'\d+(?:\.\d+)?',target)
        if not match or match[0]!=part:continue
        index=row['text'].find(target)
        if index<0:continue
        at=row['start']+index/max(1,len(row['text']))*row['speech']
        if at-.12<=r3._PROGRAM_CLOCK[0]<=at+.5:return True
    return False


def event_cues():
    if not enabled():return []
    kinds={'home_run':'impact','goal':'impact','win':'notify','record':'rise'}
    out=[]
    for row in TRACK:
        d=row['decision']
        if d and d.get('event') in kinds:
            out.append((row['start']+.18,kinds[d['event']],'a',-24))
    return out
