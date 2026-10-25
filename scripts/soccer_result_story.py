"""昨夜の注目試合→期待選手→日本人→順位→次戦。既存の部品を使う。"""
import re
import argparse
import json
import math
from pathlib import Path
import soccer_results as results
import club_display_names as names
import soccer_result_facts as facts


def clubs_for(data):
    import soccer_slots_v4
    clubs=[g[s]['name_en'] for g in data['games'] for s in ('home','away')]
    for row in (data.get('preview_followup') or {}).get('games',[]):
        if row.get('next_game'):clubs.extend(row['next_game'][s] for s in ('home','away'))
    resolved=soccer_slots_v4.clubs_for(clubs)
    # 保存当時の日本語名も同じ試合の英語名に結び、別名表更新後も再制作できる。
    import soccer_results_render
    resolved.update(soccer_results_render.resolve_clubs(data))
    return resolved


def narration(data):
    import soccer_results_render as render
    followup=data.get('preview_followup')
    if not data.get('can_make'):return dict(label=data['date_jst'],segments=[],duration_budget=dict(limit=results.LIMIT,grace=0))
    rows=followup['games'] if followup else [dict(event_id=g['id']) for g in data['games']]
    segments=[]
    for row in rows:
        g=next(g for g in data['games'] if g['id']==row['event_id'])
        text=f"{g['home']['name_jp']}対{g['away']['name_jp']}は、{g['score']['home']}対{g['score']['away']}。"
        import soccer_look
        import soccer_stats
        if soccer_look.readable():
            segments.append(dict(kind='followup',text=text,speaker=2,caption_units=[text],meta=dict(event_id=g['id'],score_only=True)))
            goals=sorted(g['goals'],key=lambda goal:tuple(int(v) for v in (goal['minute'].split('+')+['0'])[:2]))
            for start in range(0,max(1,len(goals)),3):
                shown=goals[start:start+3]
                detail=[facts.goal_line(goal,g) for goal in shown] or ['得点なし。' if g['goals_complete'] else '得点経過は未取得です。']
                segments.append(dict(kind='followup-detail',text=''.join(detail),speaker=2,caption_units=detail,
                    meta=dict(event_id=g['id'],details=facts.display_details(g,row),goals=shown,required=True)))
            comment=soccer_stats.commentary(g)
            if comment:segments.append(dict(kind='team-stats',text=comment,speaker=2,meta=dict(event_id=g['id'])))
            people=[p for p in g['players'] if p['status']!='none']
            for start,p in enumerate(people):
                line=soccer_stats.result_narration(p)
                segments.append(dict(kind='player-stats',text=line,speaker=2,caption_units=[line],
                    meta=dict(event_id=g['id'],start=start,count=1)))
        else:
            units=[text];answer=row.get('answer')
            if answer:
                units.append(facts.player_line(answer,expected=True))
            units.extend(facts.player_line(p) for p in g['players'] if p['status']!='none' and (not answer or p['name']!=answer['name']))
            import soccer_look
            import soccer_stats
            if soccer_look.readable() and soccer_stats.commentary(g):units.append(soccer_stats.commentary(g))
            segments.append(dict(kind='followup',text=''.join(units),speaker=2,caption_units=units,meta=dict(event_id=g['id'])))
            if soccer_look.readable() and soccer_stats.has_personal(g):
                people=[p for p in g['players'] if p['status']!='none']
                for start in range(0,len(people),2):
                    shown=people[start:start+2]
                    text=''.join(p['name']+'は'+soccer_stats.personal_narration(p)+'。' for p in shown if soccer_stats.personal_narration(p))
                    if not text:continue
                    segments.append(dict(kind='player-stats',text=text,speaker=2,
                                         meta=dict(event_id=g['id'],start=start)))
            detail=facts.supplements(g,row)
            segments.append(dict(kind='followup-detail',text=''.join(detail),speaker=2,caption_units=detail,
                                 meta=dict(event_id=g['id'],details=facts.display_details(g,row),goals=g['goals'])))
    played=[p for p in data['players'] if p['status']!='none']
    if played:
        answer_names={r['answer']['name'] for r in rows if r.get('answer')}
        answer_names.update(p['name'] for g in data['games'] if g['id'] in {r['event_id'] for r in rows} for p in g['players'])
        said=[p for p in played if p['name'] not in answer_names][:2]
        units=[facts.player_line(p) for p in said] or ['日本人選手の結果です。']
        segments.append(dict(kind='roster',text=''.join(units),speaker=2,caption_units=units,meta=dict(render.roster_pages(data)[0],page=1)))
    changes=[c for r in rows for c in r.get('rank_changes',[])][:2]
    if changes:
        text=''.join(f"{c['club']}の順位は{c['before']}位から{c['after']}位。" for c in changes)
        segments.append(dict(kind='followup-change',text=text,speaker=2,meta=dict(rows=changes)))
    upcoming=next((r['next_game'] for r in rows if r.get('next_game')),None)
    if upcoming:
        at=results.utc(upcoming['start_utc']).astimezone(results.JST)
        text=f"次は日本時間{at.month}月{at.day}日{at.hour}時"+(f'{at.minute}分' if at.minute else '')+f"、{names.display(upcoming['home'])}対{names.display(upcoming['away'])}。"
        segments.append(dict(kind='followup-next',text=text,speaker=2,meta=dict(row=upcoming)))
    segments.append(dict(kind='outro',text=render.r3.OUTRO_TEXT,speaker=2,meta={}))
    import sanity_sources
    return sanity_sources.attach(dict(label=data['date_jst'],segments=segments,
        duration_budget=dict(limit=results.LIMIT,grace=0)), data, sport='soccer')


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
            values.update((f'{at.hour:02d}',f'{at.minute:02d}'))
    return values


def frame(t,seg,data,clubs):
    import soccer_results_render as render
    c=render.cards
    if not hasattr(c,'panel'):
        from types import SimpleNamespace
        c=SimpleNamespace(**vars(c),panel=render.v4.panel)
    if render.soccer_look.v5():
        import soccer_v5_cards as c
    spec=render.program_spec(data);im=c.canvas(t,clubs,spec['label'])
    plain=c.text if render.soccer_look.v5() else c.plain
    if seg['kind'] in ('followup','followup-detail'):
        g=next(g for g in data['games'] if g['id']==seg['meta']['event_id'])
        row=next((r for r in (data.get('preview_followup') or {}).get('games',[]) if r['event_id']==g['id']),{})
        answer=row.get('answer')
        if seg['kind']=='followup-detail':
            plain(im,c.L,270,facts.competition(g),38,width=c.R-c.L)
            details=seg['meta']['details'][1:]
            # 保存材料にある得点者と時刻をすべて表示する。密度に合わせて字と行を調整。
            # 辞書に無い得点はクラブ名の札を先に描き、その続きに時刻と得点を置く。
            size=44
            while True:
                body=[]
                for line in details:
                    # クラブ名つきの行は club_name が幅に合わせる。文だけの行は折り返す。
                    body.append((line,[] if line.get('club') else render.v4.lines(line['text'],size,c.R-c.L-70)))
                rows=sum(max(1,len(texts)) for _,texts in body)
                if rows*(size+14)<=720:break
                if size<=22:raise ValueError('得点経過が1画面に入りません')
                size-=1
            height=60+rows*(size+14);top=round((320+render.r3.CONTENT_BOTTOM-height)/2)
            c.panel(im,(c.L,top,c.R,top+height))
            y=top+30
            for line,texts in body:
                if line.get('club'):
                    c.club_name(im,c.L+30,y,clubs[line['club']],size,suffix='　'+line['text'],width=c.R-c.L-70)
                    y+=size+14
                else:
                    for text in texts:
                        plain(im,c.L+30,y,text,size,width=c.R-c.L-70)
                        y+=size+14
            im.info['soccer_followup']=seg['meta']
            return c.finish(im,t,spec)
        plain(im,c.L,270,'昨夜の注目試合の結果',48,width=c.R-c.L)
        plain(im,c.L,330,facts.competition(g),26,width=c.R-c.L)
        people=([answer] if answer else [])+[p for p in g['players'] if p['status']!='none' and (not answer or p['name']!=answer['name'])]
        for i,side in enumerate(('home','away')):
            y=380+i*180 if people else 600+i*300
            c.panel(im,(c.L,y,c.R,y+148))
            plain(im,c.L+24,y+8,'ホーム' if side=='home' else 'アウェー',22,width=560)
            c.club_name(im,c.L+24,y+62,clubs[g[side]['name_jp']],38,width=650)
            plain(im,c.R-150,y+20,g['score'][side],100,width=120,number=True)
        if people:
            size=42
            while True:
                body=[line for person in people for line in render.v4.lines(facts.player_line(person,expected=person==answer).rstrip('。'),size,c.R-c.L-54)]
                if len(body)*(size+10)<=190:break
                if size<=22:raise ValueError('選手成績が1画面に入りません')
                size-=1
            c.panel(im,(c.L,840,c.R,1070))
            for i,line in enumerate(body):plain(im,c.L+22,860+i*(size+10),line,size,width=c.R-c.L-54)
    elif seg['kind']=='followup-change':
        plain(im,c.L,270,'順位の動き',48,width=c.R-c.L)
        for i,row in enumerate(seg['meta']['rows']):
            single=len(seg['meta']['rows'])==1
            y=500 if single else 400+i*330
            c.panel(im,(c.L,y,c.R,y+(500 if single else 306)))
            c.club_name(im,c.L+72,y+(110 if single else 40),clubs[row['club']],44,width=720)
            plain(im,c.L+72,y+(260 if single else 160),f"{row['before']}位 → {row['after']}位",80,width=720)
    else:
        row=seg['meta']['row'];at=results.utc(row['start_utc']).astimezone(results.JST)
        plain(im,c.L,270,'次の試合',48,width=c.R-c.L)
        c.panel(im,(c.L,400,c.R,1090))
        plain(im,c.L+72,480,f'{at.month}月{at.day}日 {at.hour:02d}:{at.minute:02d}',54,width=744)
        c.club_name(im,c.L+72,700,clubs[names.display(row['home'])],44,width=744)
        plain(im,c.L+72,820,'対',36,width=744)
        c.club_name(im,c.L+72,940,clubs[names.display(row['away'])],44,width=744)
    im.info['soccer_followup']=seg['meta']
    return c.finish(im,t,spec)


def fit_to_audio(narration,audio):
    """実音声とフレーム丸めで60秒を超えたら、後ろの試合の補足から省く。"""
    import soccer_results_render as render
    import copy
    narr=copy.deepcopy(narration);voices=copy.deepcopy(audio)
    while True:
        try:
            times=render.durations(narr['segments'],voices)
            if render.soccer_look.readable():
                from soccer_readable import minimum_seconds
                times=[max(t,minimum_seconds(s)) for s,t in zip(narr['segments'],times)]
            if sum(math.ceil(t*render.FPS)/render.FPS for t in times)<=results.LIMIT:return narr,voices
        except ValueError as error:
            if '60秒' not in str(error):raise
        index=next((i for i in reversed(range(len(narr['segments']))) if narr['segments'][i]['kind']=='followup-detail' and not narr['segments'][i]['meta'].get('required')),None)
        if index is None:index=next((i for kind in ('team-stats','followup-next','followup-change') for i,s in enumerate(narr['segments']) if s['kind']==kind),None)
        if index is None:raise ValueError('必須の結果/期待選手/日本人選手の実音声が60秒を超えます')
        omitted=narr['segments'][index]
        narr.setdefault('results_length_adjustment',[]).append(dict(kind=omitted['kind'],event_id=omitted['meta'].get('event_id')))
        print('[omit] 実測60秒に収めるため補足を省きます:',omitted['kind'],omitted['meta'].get('event_id',''))
        narr['segments'].pop(index);voices.pop(index)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--narration',type=Path,required=True);ap.add_argument('--audio-dir',type=Path,required=True)
    args=ap.parse_args();narr=json.loads(args.narration.read_text(encoding='utf8'));manifest=args.audio_dir/'manifest.json';voices=json.loads(manifest.read_text(encoding='utf8'))
    if not any(s['kind']=='followup' for s in narr['segments']):return
    narr,audio=fit_to_audio(narr,voices['segments']);voices['segments']=audio
    args.narration.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    manifest.write_text(json.dumps(voices,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
