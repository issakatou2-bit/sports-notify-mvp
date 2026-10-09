"""欧州サッカー結果のv4ショート。本番と保存材料の試作で同じ描画/声/尺を使う。"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from PIL import ImageDraw
import soccer_results as results
import soccer_v4_cards as cards
import review_render_v3 as r3
import short_v4_cards as v4
import video_common as vc
import v3_rules as rules

ROOT=Path(__file__).resolve().parents[1]
FPS=30
ROWS_PER_PAGE=7
CREDIT='音声: VOICEVOX:四国めたん　出典: '+results.SOURCE


def resolve_clubs(data):
    """色表の既存名/Japanese aliasで一意に解決。未知の色を推測しない。"""
    clubs=cards.load_clubs();unique={c['team_en']:c for c in clubs.values()}
    for game in data['games']:
        for side in ('home','away'):
            team=game[side];jp=team['name_jp']
            hits=[c for c in unique.values() if c['league']==game['league'] and (
                results.club_key(c['team_en'])==results.club_key(team['name_en']) or c.get('name_jp')==jp)]
            if len(hits)==1:
                club=dict(hits[0],name_jp=jp)
            else:
                club={'team_en':team['name_en'],'name_jp':jp,'abbr':team['abbr'],'primary':None,'secondary':None,'league':game['league'],'sources':[]}
            clubs[jp]=club;clubs[team['name_en']]=club
    return clubs


def spoken_minute(minute):
    """「90+5」→「後半のアディショナルタイム」。ふつうの分は「79分」。"""
    base,_,extra=str(minute).partition('+')
    if extra:return ('前半' if int(base)<=45 else '後半')+'のアディショナルタイム'
    return f'{base}分'


def roster_pages(data):
    """一覧は出場した選手だけ（得点・アシストの多い順。7人まで）。出場なしは名前を1行に。"""
    played=[p for p in data['players'] if p['status']!='none']
    absent=[p['name'] for p in data['players'] if p['status']=='none']
    return [dict(start=0,count=min(len(played),ROWS_PER_PAGE),more=max(0,len(played)-ROWS_PER_PAGE),absent=absent)]


def narration(data):
    if not data.get('can_make'):return {'label':data['date_jst'],'segments':[],'duration_budget':{'limit':40,'grace':0}}
    lead=next(p for p in data['players'] if p['status']!='none')
    game=next(g for g in data['games'] if g['id']==lead['event_id'])
    intro=f"{lead['name']}{results.action(lead)}。{game['home']['name_jp']}対{game['away']['name_jp']}は、{game['score']['home']}対{game['score']['away']}。"
    segments=[{'kind':'intro','text':intro,'speaker':2,'meta':{'event_id':game['id']}}]
    by_side={side:[g for g in game['goals'] if g['side']==side] for side in ('home','away')}
    pages=max(1,max(math.ceil(len(rows)/4) for rows in by_side.values()))
    for page in range(pages):
        goals=[g for side in ('home','away') for g in by_side[side][page*4:page*4+4]]
        jp_goals=[g for g in goals if g['japanese_goal']]
        result_text=''.join(f"{g['scorer']}は{spoken_minute(g['minute'])}にゴール。" for g in jp_goals)
        if not result_text:result_text='得点経過は画面のとおりです。' if game['goals_complete'] else '確認できた得点経過です。'
        segments.append({'kind':'result','text':result_text,'speaker':2,'meta':{'event_id':game['id'],'goals':goals,'page':page+1}})
    for meta in roster_pages(data):
        rows=[p for p in data['players'] if p['status']!='none'][:meta['count']]
        said=[p for p in rows if p['name']!=lead['name'] and (p.get('goals') or p.get('assists'))][:2]
        text=''.join(p['name']+('が'+str(p['goals'])+'得点' if p.get('goals') else 'が'+str(p['assists'])+'アシスト')+'。' for p in said)
        if not said:text+=f"日本人選手は{len(rows)+meta['more']}人が出場しました。"
        # 出場なしの選手は画面の1行だけ。読み上げで名前を出さない（クラブの結果を本人のことと読ませない）
        segments.append({'kind':'roster','text':text,'speaker':2,'meta':dict(meta,page=1)})
    segments.append({'kind':'outro','text':r3.OUTRO_TEXT,'speaker':2,'meta':{}})
    return {'label':data['date_jst'],'segments':segments,'duration_budget':{'limit':40,'grace':0}}


def program_spec(data):
    day=results.date.fromisoformat(data['date_jst'])
    return {'source':CREDIT,'ticker':f"日本時間{day.month}月{day.day}日終了　欧州の日本人選手の結果",'label':'欧州サッカー　結果'}


def cover(t,data,game,clubs,spec):
    lead=next(p for p in data['players'] if p['status']!='none')
    im=cards.canvas(t,clubs,spec['label']);v4.panel(im,(cards.L,258,cards.R,1120))
    cards.plain(im,cards.L+28,282,lead['name']+results.action(lead),64,r3.GOLD,width=cards.R-cards.L-56)
    cards.club_name(im,cards.L+28,390,clubs[lead['club']],42,width=cards.R-cards.L-56)
    value=lead['goals'] if lead.get('goals') else lead['assists'] if lead.get('assists') else None
    if value is not None:
        v4.stat(im,cards.L+28,470,value,'得点' if lead.get('goals') else 'アシスト',250,width=cards.R-cards.L-70,unit_size=62)
    else:
        cards.plain(im,cards.L+28,520,results.STATUS[lead['status']],100,r3.GOLD,width=cards.R-cards.L-56)
    for side,y in (('home',816),('away',938)):
        v4.panel(im,(cards.L+24,y-14,cards.R-24,y+98))
        cards.club_name(im,cards.L+44,y+12,clubs[game[side]['name_jp']],44,width=cards.R-cards.L-220)
        v4.text(im,cards.R-148,y,game['score'][side],102,r3.GOLD,width=98,number=True)
    return cards.finish(im,t,spec)


def timeline(t,game,clubs,spec,goals):
    im=cards.canvas(t,clubs,spec['label']);v4.panel(im,(cards.L,258,cards.R,1128))
    cards.plain(im,cards.L+28,282,game['league_jp']+'　試合終了',34,r3.GOLD,width=cards.R-cards.L-56)
    for side,y in (('home',352),('away',450)):
        cards.club_name(im,cards.L+28,y,clubs[game[side]['name_jp']],44,width=cards.R-cards.L-240)
        v4.text(im,cards.R-150,y-16,game['score'][side],106,r3.GOLD,width=110,number=True)
    left,right=cards.L+60,cards.R-60;mid=800;half=(left+right)/2;d=ImageDraw.Draw(im)
    d.line((left,mid,right,mid),fill=(196,206,212),width=4)
    d.line((half,mid-20,half,mid+20),fill=r3.GOLD,width=3)
    cards.plain(im,left,mid+30,'前半',24,width=80);cards.plain(im,half+12,mid+30,'後半',24,width=80)
    groups={side:[g for g in goals if g['side']==side] for side in ('home','away')}
    width=220
    for side,rows in groups.items():
        placed=[]
        for g in sorted(rows,key=lambda g:int(g['minute'].split('+')[0])):
            minute=int(g['minute'].split('+')[0]);x=left+(right-left)*min(minute,90)/90
            lx=min(max(x-width/2,left-30),right+30-width)
            # 近い時間の得点は段をずらす（重ならないところまで外へ）
            lane=0
            while any(abs(px-lx)<width+10 and pl==lane for px,pl in placed):lane+=1
            placed.append((lx,lane))
            y=(mid-150-lane*96) if side=='home' else (mid+70+lane*96)
            color=r3.GOLD if g['japanese_goal'] or g['japanese_assists'] else r3.INK
            d.line((x,mid,x,y+82 if side=='home' else y-6),fill=color,width=2)
            d.ellipse((x-7,mid-7,x+7,mid+7),fill=color)
            label=g['minute']+'分'+('　OG' if g['own_goal'] else '')
            cards.plain(im,lx,y,label,32,color,width=width,number=False)
            if g['japanese_goal']:
                cards.plain(im,lx,y+40,g['scorer'],26,color,width=width)
            elif g['japanese_assists']:
                cards.plain(im,lx,y+40,'・'.join(g['japanese_assists'])+' A',26,color,width=width)
            else:
                cards.club_name(im,lx,y+40,clubs[game[side]['name_jp']],26,color,width=width)
    if not goals:
        cards.plain(im,left,650,'得点なし' if game['goals_complete'] else '得点経過は未取得',36,width=right-left)
    cards.plain(im,cards.L+28,1090,'OG＝オウンゴール　A＝アシスト' if any(g['own_goal'] or g['japanese_assists'] for g in goals) else '金色＝日本人選手の得点・アシスト',22,width=cards.R-cards.L-56)
    im.info['soccer_goals']=goals
    return cards.finish(im,t,spec)


def roster_screen(t,data,meta,clubs,spec):
    im=cards.canvas(t,clubs,spec['label'])
    rows=[p for p in data['players'] if p['status']!='none'][:meta['count']]
    foot=bool(meta.get('absent') or meta.get('more'))
    v4.panel(im,(cards.L,258,cards.R,258+108+len(rows)*100+(52 if foot else 0)))
    cards.plain(im,cards.L+22,276,'日本人選手の結果',44,width=cards.R-cards.L-44)
    cards.plain(im,cards.L+22,330,'A＝アシスト',22,width=cards.R-cards.L-44)
    for i,p in enumerate(rows):
        y=362+i*100
        v4.panel(im,(cards.L+14,y,cards.R-14,y+90))
        cards.plain(im,cards.L+36,y+12,p['name'],36,width=310)
        cards.club_name(im,cards.L+36,y+54,clubs[p['club']],24,r3.colors(None)[1],width=310)
        # Reserve right-hand portrait space on the low rows as well as source/caption.
        cards.plain(im,cards.L+336,y+56,results.STATUS[p['status']],26,(255,170,160) if p['status']=='none' else r3.INK,width=200)
        if p['status']=='none':continue
        x=cards.L+336
        for key,unit in (('goals','得点'),('assists','A')):
            if p.get(key) is None:continue
            v4.text(im,x,y+5,p[key],50,r3.GOLD,width=70,number=True)
            cards.plain(im,x+66,y+21,unit,24,width=74)
            x+=154
    if foot:
        y=362+len(rows)*100+8;parts=[]
        if meta.get('more'):parts.append(f"ほか{meta['more']}人が出場")
        if meta.get('absent'):parts.append('出場なし：'+'・'.join(meta['absent'][:4])+('ほか' if len(meta['absent'])>4 else ''))
        cards.plain(im,cards.L+22,y,'　'.join(parts),24,(196,206,212),width=cards.R-cards.L-44)
    im.info['soccer_roster']=rows
    return cards.finish(im,t,spec)


def frame(t,seg,data,clubs=None):
    if r3.LOOK!='v4':raise ValueError('サッカー結果の新設枠はv4専用')
    clubs=clubs or resolve_clubs(data);spec=program_spec(data);kind=seg['kind'];meta=seg['meta']
    if kind=='outro':return r3.outro(t,{},'soccer_results',CREDIT,tagline='欧州の日本人選手とMLBを、毎日数字で')
    if kind=='roster':return roster_screen(t,data,meta,clubs,spec)
    game=next(g for g in data['games'] if g['id']==meta['event_id'])
    if kind=='intro':return cover(t,data,game,clubs,spec)
    # Each page has at most four goals per side. No information is piled beyond the safe region.
    goals=meta.get('goals',game['goals'])
    return timeline(t,game,clubs,spec,goals)


def numeric_material(data):
    values=set()
    for g in data['games']:
        values.update(str(v) for v in g['score'].values())
        for event in g['goals']:values.update(re.findall(r'\d+',event['minute']))
    for p in data['players']:
        for key in ('goals','assists','yellow_cards','red_cards'):
            if p.get(key) is not None:values.add(str(p[key]))
    # 一覧の「ほかN人」「N人が出場」は材料の名簿を数えた数
    for meta in roster_pages(data):values.update({str(meta['more']),str(meta['count']+meta['more'])})
    # Date is explicitly supplied material, not a guessed match day.
    values.update(re.findall(r'\d+',data['date_jst']))
    return values


def validate_frame(im,data,clubs):
    problems=rules.check_layout(im)+cards.check_club_badges(im,clubs)+rules.check_spacing(im)
    if not im.info.get('v3_outro'):
        extra=set(cards.drawn_numbers(im))-numeric_material(data)
        if extra:problems.append({'numbers_missing_from_material':sorted(extra)})
    return problems


def durations(segments,audio):
    if len(segments)!=len(audio):raise ValueError('音声の区間数が原稿と違う')
    times=[]
    import synthesize_narration as sn
    for seg,voice in zip(segments,audio):
        if (seg['text'],seg['speaker'],seg['kind'],seg['meta'])!=(voice.get('text'),voice.get('speaker'),voice.get('kind'),voice.get('meta')):raise ValueError('音声の文/話者/画面が原稿と違う')
        path=Path(voice.get('file') or '')
        if not path.is_file():raise ValueError('実音声がありません')
        actual=sn.audio_duration(path)
        if actual<=0 or abs(actual-float(voice.get('duration') or 0))>.05:raise ValueError('音声の尺が実測と違う')
        times.append(max(actual,3.0 if seg['kind']=='roster' else 2.6 if seg['kind']=='outro' else 2.0))
    if sum(times)>results.LIMIT:raise ValueError(f'40秒を超えます: {sum(times):.3f}。声の設定は変えず原稿を短くしてください')
    return times


def ensure_ffmpeg(out):
    if shutil.which('ffmpeg'):return
    import imageio_ffmpeg
    directory=out/'bin';directory.mkdir(exist_ok=True)
    shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),directory/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg'))
    os.environ['PATH']=str(directory)+os.pathsep+os.environ.get('PATH','')


def render_video(data,narr,audio,out):
    results.validate_data(data)
    times=durations(narr['segments'],audio);out.mkdir(parents=True,exist_ok=True);ensure_ffmpeg(out)
    # Ceil to complete frames; the resulting actual movie remains inside the strict budget.
    times=[math.ceil(t*FPS)/FPS for t in times]
    if sum(times)>40:raise ValueError('フレームの丸め後に40秒を超える')
    track=vc.build_narration_track(audio,times,out)
    if not track:raise ValueError('声つきの動画だけを作る枠です')
    video=out/'collespo_soccer_results.mp4';clubs=resolve_clubs(data);images=[];layouts=[];previous=None;clock=0
    command=['ffmpeg','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r',str(FPS),'-i','-',
             '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',
             '-t',str(sum(times)),'-movflags','+faststart',str(video)]
    with (out/'ffmpeg-render.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for i,(seg,duration) in enumerate(zip(narr['segments'],times)):
                r3.set_program_clock(clock);r3.set_caption(seg['text'],duration,sum(times),speaker=2,duo=False,hide_caption=seg['kind']=='outro')
                snap=min(3,duration*.6) if seg['kind']=='outro' else min(1.4,duration*.6)
                r3.set_program_clock(clock+snap);im=frame(snap,seg,data,clubs)
                errors=validate_frame(im,data,clubs)
                if errors:raise ValueError(f'画面{i}: {errors}')
                im.save(out/f'{i+1:02d}.png');images.append(im);layouts.append(im.info)
                for k in range(round(duration*FPS)):
                    r3.set_program_clock(clock+k/FPS);im=frame(k/FPS,seg,data,clubs)
                    raw=vc.short_transition(previous,im,k,FPS,True);proc.stdin.write(raw)
                previous=im.tobytes();clock+=duration
        finally:
            proc.stdin.close();code=proc.wait();r3.set_program_clock(None)
    if code:raise ValueError('ffmpegの動画生成が失敗。ffmpeg-render.logを確認')
    from preview_unified_v3 import sheet
    sheet(images,[s['kind'] for s in narr['segments']],out/'all-screens.png',columns=4)
    probe=subprocess.run(['ffmpeg','-hide_banner','-i',str(video)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    match=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
    if not match:raise ValueError('実動画の尺が読めません')
    seconds=int(match[1])*3600+int(match[2])*60+float(match[3])
    if seconds>40:raise ValueError('実動画が40秒を超える')
    verification={'date_jst':data['date_jst'],'title':results.title(data),'video_seconds':seconds,
                  'voice_seconds':sum(float(s['duration']) for s in audio),'video':str(video),
                  'layout_club_badges_numbers':'PASS','frames':layouts,'voice_settings':'既存設定不変',
                  'publication':'not performed'}
    (out/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in verification.items() if k!='frames'},ensure_ascii=False))
    return verification


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data',type=Path,default=ROOT/'data/soccer_results.json')
    ap.add_argument('--narration-out',type=Path)
    ap.add_argument('--audio-dir',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_results')
    args=ap.parse_args();data=json.loads(args.data.read_text(encoding='utf-8'));narr=narration(data)
    results.validate_data(data)
    if args.narration_out:
        args.narration_out.parent.mkdir(parents=True,exist_ok=True)
        args.narration_out.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not narr['segments']:print('出場した日本人選手がいないため作りません');return
    if args.audio_dir:
        audio=json.loads((args.audio_dir/'manifest.json').read_text(encoding='utf-8'))['segments']
        render_video(data,narr,audio,args.out)


if __name__=='__main__':main()
