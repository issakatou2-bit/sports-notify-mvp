"""昨夜の注目試合→期待選手→日本人→順位→次戦。既存の部品を使う。"""
import re
import argparse
import json
import math
from pathlib import Path
import soccer_results as results
import club_display_names as names


def clubs_for(data):
    import soccer_slots_v4
    clubs=[g[s]['name_en'] for g in data['games'] for s in ('home','away')]
    for row in data['preview_followup']['games']:
        if row.get('next_game'):clubs.extend(row['next_game'][s] for s in ('home','away'))
    return soccer_slots_v4.clubs_for(clubs)


def narration(data):
    import soccer_results_render as render
    followup=data.get('preview_followup')
    if not followup:return render.narration(data)
    segments=[]
    for row in followup['games'][:3]:
        g=next(g for g in data['games'] if g['id']==row['event_id'])
        text=f"{g['home']['name_jp']}対{g['away']['name_jp']}は、{g['score']['home']}対{g['score']['away']}。"
        answer=row.get('answer')
        if answer:
            text+=f"期待選手の{answer['name']}は"+results.STATUS[answer['status']]+'。'
            if answer['status']!='none':text+=''.join(f"{answer[k]}{unit}。" for k,unit in (('goals','得点'),('assists','アシスト')) if answer.get(k) is not None)
        segments.append(dict(kind='followup',text=text,speaker=2,meta=dict(event_id=g['id'])))
    played=[p for p in data['players'] if p['status']!='none']
    if played:
        answer_names={r['answer']['name'] for r in followup['games'] if r.get('answer')}
        said=[p for p in played if p['name'] not in answer_names][:2]
        text=''.join(p['name']+results.action(p)+'。' for p in said) or '日本人選手の結果です。'
        segments.append(dict(kind='roster',text=text,speaker=2,meta=dict(render.roster_pages(data)[0],page=1)))
    changes=[c for r in followup['games'] for c in r['rank_changes']][:2]
    if changes:
        text=''.join(f"{c['club']}の順位は{c['before']}位から{c['after']}位。" for c in changes)
        segments.append(dict(kind='followup-change',text=text,speaker=2,meta=dict(rows=changes)))
    upcoming=next((r['next_game'] for r in followup['games'] if r.get('next_game')),None)
    if upcoming:
        at=results.utc(upcoming['start_utc']).astimezone(results.JST)
        text=f"次は日本時間{at.month}月{at.day}日{at.hour}時"+(f'{at.minute}分' if at.minute else '')+f"、{names.display(upcoming['home'])}対{names.display(upcoming['away'])}。"
        segments.append(dict(kind='followup-next',text=text,speaker=2,meta=dict(row=upcoming)))
    segments.append(dict(kind='outro',text=render.r3.OUTRO_TEXT,speaker=2,meta={}))
    return dict(label=data['date_jst'],segments=segments,duration_budget=dict(limit=40,grace=0))


def numeric_material(data):
    values=set()
    def collect(value):
        if isinstance(value,dict):
            for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
        elif value is not None:values.update(re.findall(r'\d+',str(value)))
    collect(data.get('preview_followup',{}))
    for row in (data.get('preview_followup') or {}).get('games',[]):
        if row.get('next_game'):
            at=results.utc(row['next_game']['start_utc']).astimezone(results.JST)
            values.update(str(n) for n in (at.month,at.day,at.hour,at.minute))
    return values


def frame(t,seg,data,clubs):
    import soccer_results_render as render
    c=render.cards
    if render.soccer_look.v5():
        import soccer_v5_cards as c
    spec=render.program_spec(data);im=c.canvas(t,clubs,spec['label'])
    plain=c.text if render.soccer_look.v5() else c.plain
    if seg['kind']=='followup':
        g=next(g for g in data['games'] if g['id']==seg['meta']['event_id'])
        plain(im,c.L,270,'昨夜の注目試合の結果',48,width=c.R-c.L)
        for i,side in enumerate(('home','away')):
            y=380+i*180;c.panel(im,(c.L,y,c.R,y+148))
            plain(im,c.L+24,y+8,'ホーム' if side=='home' else 'アウェー',22,width=560)
            c.club_name(im,c.L+24,y+62,clubs[g[side]['name_jp']],38,width=650)
            plain(im,c.R-150,y+20,g['score'][side],100,width=120,number=True)
        row=next(r for r in data['preview_followup']['games'] if r['event_id']==g['id']);answer=row.get('answer')
        if answer:
            c.panel(im,(c.L,840,c.R,1070))
            plain(im,c.L+22,860,'期待選手 '+answer['name'],36,width=c.R-c.L-44)
            plain(im,c.L+22,914,results.STATUS[answer['status']],32,width=680)
            if answer['status']!='none':
                stats=' / '.join(f'{answer[k]}{unit}' for k,unit in (('goals','得点'),('assists','アシスト')) if answer.get(k) is not None)
                plain(im,c.L+22,972,stats,38,width=680)
    elif seg['kind']=='followup-change':
        plain(im,c.L,270,'順位の動き',48,width=c.R-c.L)
        for i,row in enumerate(seg['meta']['rows']):
            y=380+i*190;c.panel(im,(c.L,y,c.R,y+158))
            plain(im,c.L+24,y+16,row['club'],36,width=800)
            plain(im,c.L+24,y+78,f"{row['before']}位 → {row['after']}位",48,width=800)
    else:
        row=seg['meta']['row'];at=results.utc(row['start_utc']).astimezone(results.JST)
        plain(im,c.L,270,'次の試合',48,width=c.R-c.L)
        plain(im,c.L+24,390,f'{at.month}月{at.day}日 {at.hour:02d}:{at.minute:02d}',54,width=840)
        c.club_name(im,c.L+24,540,clubs[names.display(row['home'])],38,width=840)
        plain(im,c.L+24,620,'対',36,width=840)
        c.club_name(im,c.L+24,700,clubs[names.display(row['away'])],38,width=840)
    im.info['soccer_followup']=seg['meta']
    return c.finish(im,t,spec)


def fit_to_audio(narration,audio):
    """実音声で40秒を超える場合、補足の次戦→順位の順で省く。結果/期待選手は落とさない。"""
    import soccer_results_render as render
    import copy
    narr=copy.deepcopy(narration);voices=copy.deepcopy(audio)
    while True:
        try:
            times=render.durations(narr['segments'],voices)
            if sum(math.ceil(t*render.FPS)/render.FPS for t in times)<=40:return narr,voices
        except ValueError as error:
            if '40秒' not in str(error):raise
        index=next((i for kind in ('followup-next','followup-change') for i,s in enumerate(narr['segments']) if s['kind']==kind),None)
        if index is None:raise ValueError('必須の結果/期待選手/日本人選手の実音声が40秒を超えます')
        print('[omit] 実測40秒に収めるため補足を省きます:',narr['segments'][index]['kind'])
        narr['segments'].pop(index);voices.pop(index)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--narration',type=Path,required=True);ap.add_argument('--audio-dir',type=Path,required=True)
    args=ap.parse_args();narr=json.loads(args.narration.read_text(encoding='utf8'));manifest=args.audio_dir/'manifest.json';voices=json.loads(manifest.read_text(encoding='utf8'))
    if not any(s['kind']=='followup' for s in narr['segments']):return
    narr,audio=fit_to_audio(narr,voices['segments']);voices['segments']=audio
    args.narration.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    manifest.write_text(json.dumps(voices,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
