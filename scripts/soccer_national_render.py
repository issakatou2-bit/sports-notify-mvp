"""代表戦を既存v6 focus・字幕・音声・ショート検査で制作する。"""

import short_common
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess

import soccer_national as national

ROOT=Path(__file__).resolve().parents[1]
FPS=30
VIDEO='collespo_national.mp4'


def clubs_for(data):
    names={'日本':'JPN'}
    for key in ('game','next_game'):
        if data.get(key):names[data[key]['opponent']]=data[key].get('opponent_abbr') or '?'
    for key in ('japan_recent','opponent_recent','japan_previous','opponent_previous','previous','previous_earlier','next_known'):
        if data.get(key):
            names.setdefault(data[key]['team'],data[key].get('team_abbr') or '?')
            names.setdefault(data[key]['opponent'],data[key].get('opponent_abbr') or '?')
    # 国の色をクラブの部分一致で探さない。既存の未確認札だけを使う。
    return {n:dict(team_en=n,name_jp=n,abbr=a,primary=None,secondary=None,league='親善試合') for n,a in names.items()}


def result_board(r):
    at=national.datetime.fromisoformat(r['date_jst'])
    return (f"{at.year}/{at.month}/{at.day} {r['team']}",f"{r['gf']}-{r['ga']} {r['opponent']}")


def frame(t,seg,data,clubs):
    if seg['kind'] == 'outro':
        import review_render_v3 as r3
        return r3.outro(t, credit='音声: VOICEVOX:四国めたん　出典: JFA・ESPN')
    if data.get('squad_style')=='pitch-v1' and (seg.get('meta') or {}).get('panel')=='squad':
        import soccer_national_pitch
        return soccer_national_pitch.frame(t,seg,data,clubs)
    import soccer_readable as readable
    class NationalScreen(readable.Screen):
        def __init__(self,clubs,t):
            self.clubs,self.t=clubs,t
        def text(self,x,y,value,size=44,width=800,color=None,number=False,role='text'):
            # 国名「日本」と時刻の単位「日本時間」をクラブの言及と取り違えない。
            if value=='日本時間':role='supplement'
            return super().text(x,y,value,size,width,color,number,role)
    s=NationalScreen(clubs,t)
    # 背景上部の番組札も代表番組へ。canvasの既存部品から作る。
    import soccer_v5_cards as cards
    s.im=cards.canvas(t,clubs,'日本代表')
    s.im.info.update(soccer_readable=True,semantic_items=[],readable_motion='フェードイン 0.35秒・以後停止')
    spec=dict(source='VOICEVOX:四国めたん / '+('JFA・クラブ成績' if data['mode']=='squad' else '確認一覧・ESPN'),title='日本代表')
    panel=seg['meta']['panel'];g=data.get('game')
    if panel in ('match','next'):
        g=data['next_game'] if panel=='next' else g
        at=national.instant(g['kickoff_jst'])
        reasons=[]
        if panel=='match' and data.get('previous'):
            p=data['previous'];d=national.datetime.fromisoformat(p['date_jst'])
            reasons=[dict(kind='h2h',text=f"前回 {d.year}/{d.month} {p['gf']}-{p['ga']}")]
        row=dict(game_id=g['id'],home='日本',away=g['opponent'],league='親善試合',
            date=f'{at.month}/{at.day}',time=at.strftime('%H:%M'),jp={},interest=dict(reasons=reasons))
        head=('次は日本対'+g['opponent']) if panel=='next' else national.title(data).replace(' #Shorts','')
        return s.focus_preview([row],dict(spec,game_id=g['id'],title_focus=dict(head=head,game_id=g['id'])))
    if panel=='score':
        at=national.instant(g['kickoff_jst']);score=g['score']
        game=dict(home=dict(name_jp='日本'),away=dict(name_jp=g['opponent']),
            score=dict(home=score['japan'],away=score['opponent']),players=[],league_jp=f'{at.month}/{at.day} 親善試合')
        word='勝利' if score['japan']>score['opponent'] else '敗戦' if score['japan']<score['opponent'] else '引き分け'
        return s.score(game,spec,f"{score['japan']}-{score['opponent']}で{word}",score_only=True)
    if panel in ('venue','match-venue'):
        g=g or data['next_game']
        venue=g['venue'].replace('・ナショナル','・\nナショナル').replace('エディオンピース','エディオン\nピース')
        heading='シンガポールで対戦' if panel=='venue' and g['venue_raw']=='Singapore National Stadium' else '開催会場'
        return s.national_facts(heading,[('会場',venue)],spec)
    if panel in ('recent','opponent-recent'):
        side='japan' if panel=='recent' else 'opponent'
        if side=='japan':
            r=data['japan_recent'];rows=[result_board(r)]
            title='キリンカップで優勝' if r.get('stage')=='決勝' and r.get('note')=='優勝' else '代表の直近の結果'
        else:
            rows=[result_board(data['opponent_recent'])];title='相手の対戦結果'
        return s.national_facts(title,rows,spec,sub=data['japan_recent'].get('competition','対戦結果') if side=='japan' else '日付つきの対戦結果')
    if panel=='recent-single':
        return s.national_facts('ひとつ前の試合',[result_board(data['japan_recent'])],spec,sub=data['japan_recent'].get('competition','対戦結果'))
    if panel=='previous':
        rows=[]
        for key in ('previous','previous_earlier'):
            if data.get(key):
                r=data[key];at=national.datetime.fromisoformat(r['date_jst'])
                rows.append((f"{at.year}/{at.month}/{at.day} {r['competition']}"+((' '+r['stage']) if r.get('stage') else ''),f"{r['gf']}-{r['ga']} {r['opponent']}"))
        return s.national_facts('前回とその前の対戦',rows,spec,sub='過去の対戦')
    if panel=='next-known':
        r=data['next_known']
        return s.national_facts('次の代表戦',[(r['date_jst']+' '+r['competition'],r['opponent']+'戦')],spec,sub=r['competition'])
    if panel=='cup-route':
        r=national.cup_route(data)
        return s.national_facts('キリンカップ優勝への道',[(r['date_jst']+' '+r['stage'],r['opponent']+'と0-0'),('PK戦','勝利')],spec,sub='キリンカップ')
    if panel=='halves':
        h=data['halves']
        return s.national_facts('後半に得点を追加',[('前半終了',f"{h['japan'][0]}-{h['opponent'][0]}"),
            ('試合終了',f"{g['score']['japan']}-{g['score']['opponent']}")],spec)
    if panel=='goals':
        story=national.match_story(data)
        rows=[]
        for e in sorted(story['scorers'],key=lambda r:(r['team_id']!=national.JAPAN,-r['goals'])):
            team='日本' if e['team_id']==national.JAPAN else g['opponent']
            who='オウンゴール' if e['own_goal'] else e['name'] or team
            rows.append((team+'の得点',who+' '+str(e['goals'])+'得点'))
        if story['decisive']:rows.append(('決勝点',national.minute_words(story['decisive']['minute'])))
        pages=max(1,(len(rows)+2)//3);page=readable.page_at(t,pages)
        s.im.info.update(readable_page=page,readable_page_count=pages)
        return s.national_facts('逆転勝ちの主役' if story['comeback'] else '得点の主役',rows[page*3:page*3+3],spec)
    if panel=='year-record':
        r=national.history_record(data.get('japan_history') or [],national.instant(g['kickoff_jst']).year)
        rows=[(f"{r['year']}年 全大会 {r['games']}試合",f"{r['wins']}勝 {r['draws']}分 {r['losses']}敗")]
        if data.get('length_level',0)>=2:rows.append(('同じ試合の得失点',f"{r['gf']}得点 {r['ga']}失点"))
        return s.national_facts('今年の全大会成績',rows,spec,sub='全大会・PK戦は引き分け')
    if panel=='squad-count':
        return s.national_facts('招集メンバー',[('招集の人数',f"{data['squad_size']}人")],spec,sub='JFA公式発表')
    if panel=='squad':
        if 'player' not in seg['meta']:
            rows=[(p['position'],p['name']) for p in data['players']]
            return s.national_facts('招集メンバー',rows,spec,sub='JFA公式発表')
        p=data['players'][seg['meta']['player']]
        rows=[(p['position'],p['name']),('所属クラブ',p['club'])]
        stats=p.get('stats')
        if stats:
            units={'goals':'得点','assists':'アシスト','minutes':'分出場','appearances':'試合出場'}
            rows.append((stats['season']+' '+stats['league'],' / '.join(str(v)+units[k] for k,v in stats['values'].items())))
        return s.national_facts('招集メンバー',rows,spec,sub='JFA公式発表')
    raise ValueError('未知の代表画面')


def validate_frame(im,clubs,data=None):
    import soccer_readable
    errors=soccer_readable.check_frame(im,clubs)
    if data:
        lines=im.info.get('bubble_style',{}).get('lines') or []
        names=[g['name'] for g in data.get('goals',[]) if g.get('name')]+[p['name'] for p in data.get('players',[])]
        split=[name for name in names if name in ''.join(lines) and not any(name in line for line in lines)]
        if split:errors.append(dict(player_names_split_across_lines=split))
        import soccer_v4_cards
        derived=[data]
        if data.get('mode')=='result':derived.append(national.match_story(data))
        if data.get('length_level',0)>=1 and data.get('mode')!='squad':derived.append(national.history_record(data.get('japan_history') or [],national.instant(data['game']['kickoff_jst']).year))
        allowed=set(re.findall(r'\d+(?:\.\d+)?',json.dumps(derived,ensure_ascii=False)))
        # ゼロ埋めの時計は日時の整数として比較。1点は各得点イベントの単位。
        allowed={float(v) for v in allowed}|({1.0} if data.get('goals') else set())
        extra={v for v in soccer_v4_cards.drawn_numbers(im) if float(v) not in allowed}
        extra|={v for e in im.info.get('v3_layout',[]) if e['role']=='national_fact'
            for v in re.findall(r'\d+(?:\.\d+)?',str(e['text'])) if float(v) not in allowed}
        if extra:errors.append(dict(numbers_missing_from_material=sorted(extra)))
    return errors


def render(data,narr,audio,out):
    import soccer_results_render as common
    import soccer_look
    import short_content
    import review_render_v3 as r3
    import video_common as vc
    import render_timeline
    import voice_manifest
    if national.check(narr) or narr['national_material']!=data:
        raise ValueError('材料と台本が一致しません')
    if not soccer_look.readable() or not soccer_look.focus():
        raise ValueError('代表番組はv6 focusだけを使います')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);common.ensure_ffmpeg(out)
    times=common.durations(narr['segments'],audio)
    if data.get('squad_style')=='pitch-v1':
        import soccer_national_pitch
        times=soccer_national_pitch.durations(narr,audio,times)
    times=[math.ceil(t*FPS)/FPS for t in times]
    short_content.require(narr,times,out,data,maximum=60,video_name=VIDEO)
    track=vc.build_narration_track(audio,times,out)
    if not track:raise ValueError('実音声なし')
    track=short_common.add_audio(track,audio,times,out)
    clubs=clubs_for(data);video=out/VIDEO;previous=None;clock=0;layouts=[]
    timeline=render_timeline.Recorder(FPS,audio,narr)
    command=['ffmpeg','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r',str(FPS),'-i','-',
        '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',
        '-t',str(sum(times)),'-movflags','+faststart',str(video)]
    with (out/'ffmpeg.log').open('w',encoding='utf8') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for i,(seg,duration) in enumerate(zip(narr['segments'],times)):
                timeline.select(audio[i],i)
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'],duration,sum(times),speaker=2,duo=False,hide_caption=seg['kind']=='outro')
                seen=set()
                for k in range(round(duration*FPS)):
                    t=k/FPS;r3.set_program_clock(clock+t);im=frame(t,seg,data,clubs)
                    signature=json.dumps([im.info.get('readable_page'),im.info.get('bubble_style',{}).get('lines')],ensure_ascii=False)
                    if t>=.35 and signature not in seen:
                        seen.add(signature);errors=validate_frame(im,clubs,data)
                        layouts.append(dict(scene=i,frame=k,errors=errors,layout=im.info.get('v3_layout'),lines=im.info.get('bubble_style',{}).get('lines')))
                        national.save(out/'layout_checks.json',layouts)
                        if errors:raise ValueError(f'画面{i}: {errors}')
                    if k==min(42,round(duration*FPS)-1):im.save(out/f'{i+1:02d}.png')
                    raw=im.tobytes() if data.get('squad_style')=='pitch-v1' else soccer_look.transition(previous,im,k,FPS)
                    timeline.write(proc.stdin,raw,im)
                previous=im.tobytes();clock+=duration
        finally:
            proc.stdin.close();code=proc.wait();r3.set_program_clock(None)
    if code:raise ValueError('ffmpegの制作に失敗')
    timeline.save(video,Path(audio[0]['file']).parent)
    report=short_content.validate_upload(video)
    voice_manifest.save(Path(audio[0]['file']).parent,audio,narr)
    national.save(out/'verification.json',dict(seconds=report['actual_seconds'],information=report['information_count'],
        scenes=len(times),layout_states=len(layouts),voice_seconds=sum(a['duration'] for a in audio),publication='not performed'))
    return report


def fit_to_audio(out):
    """27秒未満だけ当年成績→得失点→当該会場→直前結果。声設定は不変。"""
    import soccer_results_render as common
    import synthesize_narration as synth
    out=Path(out)
    data=national.read(out/'material.json');narr=national.read(out/'narration.json')
    audio=national.read(out/'audio/manifest.json')['segments']
    measured=common.durations(narr['segments'],audio)
    if data.get('squad_style')=='pitch-v1':
        import soccer_national_pitch
        times=soccer_national_pitch.durations(narr,audio,measured)
        import short_content
        gate=short_content.assess(narr,times,data,maximum=60)
        national.save(out/'repaired_duration_gate.json',gate)
        if gate['status']!='passed':raise ValueError(gate['reasons'])
        return False
    seconds=sum(measured)
    if seconds>=27:return False
    repairs=[]
    while seconds<27:
        level=data.get('length_level',0)+1
        if data['mode']=='squad':
            # 招集回は 1 次の試合の会場 → 2 招集の人数 だけ。どちらも発表と日程の確定事実。
            if level==1 and not (data.get('next_game') or {}).get('venue'):level=2
            if level>2 or level==2 and not data.get('squad_size'):
                raise ValueError('尺不足。追加できる未使用の事実がありません')
            data['length_level']=level
            repairs.append(dict(before_seconds=seconds,level=level,added=('次の試合の会場','招集の人数')[level-1]))
            national.save(out/'duration_repair.json',dict(reason='27秒未満',steps=repairs,voice_settings='unchanged'))
            national.save(out/'material.json',data);national.save(out/'narration.json',national.narration(data))
            synth.main(['--narration',str(out/'narration.json'),'--out-dir',str(out/'audio')])
            doc=national.read(out/'narration.json');voices=national.read(out/'audio/manifest.json')['segments']
            times=common.durations(doc['segments'],voices);seconds=sum(times)
            continue
        if data['mode']=='preview' and level==1:level=2
        if level==3 and data['mode']=='result' and not data['game'].get('venue'):level=4
        if level>4 or data['mode'] not in ('preview','result') or not national.record_sentence(data) or (data['mode']=='preview' and (level>3 or level==3 and not national.cup_route(data))) or (level==4 and not data.get('japan_recent')):
            raise ValueError('尺不足。追加できる未使用の事実がありません')
        data['length_level']=level
        added='キリンカップのPK勝利' if data['mode']=='preview' and level==3 else ('当年全大会成績','同じ試合の得失点','当該試合の会場','直前の試合結果')[level-1]
        repairs.append(dict(before_seconds=seconds,level=level,added=added))
        national.save(out/'duration_repair.json',dict(reason='27秒未満',steps=repairs,voice_settings='unchanged'))
        national.save(out/'material.json',data);national.save(out/'narration.json',national.narration(data))
        synth.main(['--narration',str(out/'narration.json'),'--out-dir',str(out/'audio')])
        doc=national.read(out/'narration.json');voices=national.read(out/'audio/manifest.json')['segments']
        times=common.durations(doc['segments'],voices);seconds=sum(times)
    import short_content
    gate=short_content.assess(doc,times,data,maximum=60)
    national.save(out/'repaired_duration_gate.json',gate)
    if gate['status']!='passed':raise ValueError(gate['reasons'])
    return True


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_national')
    ap.add_argument('--fit-audio',action='store_true')
    args=ap.parse_args()
    os.environ.update(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4')
    if args.fit_audio:
        fit_to_audio(args.out);return
    data=national.read(args.out/'material.json');narr=national.read(args.out/'narration.json')
    render(data,narr,national.read(args.out/'audio/manifest.json')['segments'],args.out)


if __name__=='__main__':main()
