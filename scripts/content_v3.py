"""本人確認用の新しい編集順。公開設定を変更しない。"""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def closing(segments,mode):
    choices={'players':('COLLESPO_PLAYERS_DESIGN','bignumber','morning'),
             'voices':('COLLESPO_COMMENTS_DESIGN','comments','morning_voices'),
             'press':('COLLESPO_PRESS_DESIGN','v3','morning_press')}
    choice=choices.get(mode)
    if choice and os.getenv(choice[0],'legacy')==choice[1]:
        import review_render_v3 as r3
        for seg in segments:
            if seg['kind']=='outro':
                seg['text']=r3.OUTRO_TEXT
                seg['meta']=dict(seg.get('meta') or {},lineup_kind=choice[2])
                seg['speaker']=2
    return segments


def players(segments, roster, day):
    if os.getenv('COLLESPO_PLAYERS_DESIGN','legacy') != 'bignumber' or not roster:
        return segments
    import bignumber_render as bn
    import generate_morning_short as g
    import notability_engine as ne
    ranking=[]
    for rank,p in enumerate(roster[:5],1):
        number,unit=bn.pick_big(p.get('headline'),p.get('type'))
        score=number+unit if number else f'勝利貢献{rank}位'
        ranking.append({'rank':rank,'name':p['name'],'abbr':ne.MLB_TEAM_ABBR.get(str(p.get('team_id')),''),
                        'score':score,'team_id':p.get('team_id')})
    cover={'kind':'cover','text':f'{day}、日本人選手{len(roster)}人の成績です。','meta':{'count':len(roster)}}
    table={'kind':'ranking','text':'きょうの勝利貢献順位です。'+''.join(f'{r["rank"]}位、{r["name"]}。{g.yomi_stats(r["score"])}。' for r in ranking),
           'meta':{'ranking':ranking}}
    old=segments[0]['text']
    tail=f'{day}、日本人選手{len(roster)}人の成績です。'
    hero=dict(segments[0],kind='hero',text=old.removesuffix(tail))
    remaining=[]
    for seg in segments[1:]:
        if seg['kind']=='list':
            meta=seg['meta'];start=meta['start'];count=meta['count']
            if start==0:
                start=1;count-=1
            if count<=0:
                continue
            seg=dict(seg,text=g.spoken_list(roster[start:start+count],start),meta=dict(meta,start=start,count=count))
        remaining.append(seg)
    return [cover,table,hero]+remaining


def quotes(segments,data,mode):
    enabled=(mode=='voices' and os.getenv('COLLESPO_COMMENTS_DESIGN')=='comments') or (mode=='press' and os.getenv('COLLESPO_PRESS_DESIGN')=='v3')
    if not enabled:
        return segments
    import comment_render as cr
    import press_v3
    result=[]
    for seg in segments:
        if seg['kind']=='outro':
            result.append(seg);continue
        rows=(cr.voices_for_segment(seg,data.get('voices') or {}) if mode=='voices'
              else press_v3.bubbles(seg,data.get('reporters') or {}))
        if not rows or any(v.get('fact') for v in rows):
            result.append(seg);continue
        history=[];cursor=0
        def add(text,active=None):
            if not text:
                return
            if not text.strip('。！!、. '):
                if result:
                    result[-1]['text']+=text
                return
            shown=[dict(v,read=False) for v in history]
            shown.append(dict(active or {'said':text,'who':'概要','fact':True},read=True,clip=True))
            result.append(dict(seg,text=text,meta=dict(seg.get('meta') or {},quote_rows=shown)))
        for row in rows:
            body=row['said'].strip().rstrip('。！!、.')
            start=seg['text'].find(body,cursor)
            if start<0:
                raise ValueError('引用を原稿内に見つけられません')
            add(seg['text'][cursor:start])
            end=start+len(body)
            while end<len(seg['text']) and seg['text'][end] in '。！!、.':
                end+=1
            add(seg['text'][start:end],row)
            history.append(row);cursor=end
        add(seg['text'][cursor:])
    if ''.join(s['text'] for s in result)!=''.join(s['text'] for s in segments):
        raise ValueError('引用の区間分割で原稿が変わりました')
    return result
