"""招集ピッチの検証を一括で行う。実音声・公開・台帳更新はしない。"""
import argparse
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import subprocess
import sys
import re

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
JST=timezone(timedelta(hours=9))
TESTS=['test_soccer_national.py','test_soccer_national_squad.py','test_national_pitch.py',
       'test_short_common.py','test_short_polish.py','test_name_reading_guard.py','test_name_phrases.py','test_soccer_readable.py']


def available():
    now=datetime.now(JST);minute=now.hour*60+now.minute
    if 7*60+20<=minute<8*60+40 or 19*60+15<=minute<20*60+40 or 20*60+50<=minute<22*60+10:
        raise RuntimeError('試験・描画を始めない時間帯です: '+now.isoformat())


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')


def planned(document):
    import soccer_national_pitch as pitch
    return [2.0 if s['kind']=='outro' or s['meta'].get('intro') else pitch.PLAYER_SECONDS
            if s['meta'].get('panel')=='squad' and 'player' in s['meta'] else 7.0 for s in document['segments']]


def run_tests(out):
    results=[]
    for name in TESTS:
        available()
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
        text=result.stdout+'\n'+result.stderr
        (out/(name+'.log')).write_text(text,encoding='utf8',newline='\n')
        count=re.search(r'Ran (\d+) tests?',text)
        failures=re.search(r'failures=(\d+)',text);errors=re.search(r'errors=(\d+)',text)
        results.append(dict(file=name,tests=int(count[1]) if count else 0,
            failures=int(failures[1]) if failures else 0,errors=int(errors[1]) if errors else int(bool(result.returncode)),exit_code=result.returncode))
    save(out/'tests.json',results)
    return results


def drawings(out,video):
    available()
    from unittest.mock import patch
    import soccer_national as n
    import soccer_national_pitch as pitch
    import soccer_national_render as render
    import review_render_v3 as r3
    import name_reading_guard as guard
    import sanity_material, sanity_sources, short_content
    from PIL import Image
    roster=n.read(ROOT/'data/soccer_national_squad.json')
    source=ROOT.parents[1]/'build/codex/tmp/national_espn'
    games=n.japan_matches([n.read(source/f'scoreboard_202611{day}.json') for day in (14,17)])
    # 実績台帳は使わず、11/5〜8に1ページずつ出た条件だけを模擬する。
    ledger={'soccer_national':{f'2026-11-{day:02d}':{'national_squad_page':day-5} for day in range(5,9)}}
    material=n.read(ROOT/'data/soccer_games.json')
    env=dict(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4',
             COLLESPO_SOLO_HOST='metan',COLLESPO_HOST_SPLIT='off',COLLESPO_DUO='off',COLLESPO_MOTION='on',
             COLLESPO_CAPTION_BREAKS='on')
    results=[];all_frames=[];sample=None
    with patch.dict(os.environ,env):
        for day in range(9,14):
            available()
            now=n.instant(f'2026-11-{day:02d}T10:15:00+09:00')
            def no_fetch(*args):raise AssertionError('結果の取得は行いません')
            data=n.choose(games,{},None,now,ledger,no_fetch,roster,material)
            if data is None:
                results.append(dict(day=now.date().isoformat(),selected=False));continue
            doc=n.narration(data);times=planned(doc)
            assert n.check(doc)==[]
            assert sanity_material.check(doc,sanity_sources.collect([doc]))==[]
            guard.validate_dialogue(doc)
            gate=short_content.assess(doc,times,data,maximum=60)
            assert gate['status']=='passed',gate
            save(out/f'{day:02d}_narration.json',doc)
            save(out/f'{day:02d}_material.json',data)
            if sample is None:sample=(data,doc,times)
            clubs=render.clubs_for(data);portraits=[];frames=[]
            for index,seg in enumerate(doc['segments']):
                duration=times[index]
                r3.set_program_clock(0);r3.set_caption(seg['text'],duration,sum(times),speaker=2,hide_caption=seg['kind']=='outro')
                samples=(0,.15,.3,1,2.8,3.05,3.19) if 'player' in seg['meta'] else (min(.5,duration/2),)
                for t in samples:
                    r3.set_program_clock(t);im=render.frame(t,seg,data,clubs)
                    errors=render.validate_frame(im,clubs,data)
                    assert not errors,(day,index,t,errors)
                    row=dict(day=day,scene=index,time=t,errors=errors,pitch=im.info.get('national_pitch'),
                             subtitles=im.info.get('timeline_subtitles',[]),subtitle_visible=im.info.get('timeline_subtitle_visible',True))
                    frames.append(row)
                    if 'player' in seg['meta']:
                        assert row['pitch']['active']==data['players'][seg['meta']['player']]['name']
                        if t==.3:
                            filename=f'{day:02d}_player_{seg["meta"]["player"]+1}.png'
                            im.save(out/filename);portraits.append(im.resize((360,640)))
                    else:im.save(out/f'{day:02d}_scene_{index:02d}.png')
            sheet=Image.new('RGB',(360*len(portraits),640))
            for i,im in enumerate(portraits):sheet.paste(im,(360*i,0))
            sheet.save(out/f'{day:02d}_cards.png')
            results.append(dict(day=now.date().isoformat(),selected=True,page=data['page']+1,
                names=[p['name'] for p in data['players']],leagues=[p['league'] for p in data['players']],
                lines=[s['text'] for s in doc['segments']],title=doc['title'],sample_seconds=sum(times),gate=gate))
            ledger['soccer_national'][now.date().isoformat()]={'national_squad_page':data['page']}
            all_frames.extend(frames)
        # 未登場のGKのページも見本として保持。実際の次回候補とは区別。
        keeper=n.squad(roster,material,'2026-11-09T10:15:00+09:00',0,upcoming=games)
        keeper_doc=n.narration(keeper)
        for i,seg in enumerate(keeper_doc['segments'][1:4]):
            r3.set_program_clock(0);r3.set_caption(seg['text'],3.2,21,speaker=2)
            r3.set_program_clock(.3);im=render.frame(.3,seg,keeper,render.clubs_for(keeper));im.save(out/f'gk_reference_{i+1}.png')
        if video and sample:
            available()
            silent_video(out,*sample)
        r3.set_program_clock(None);r3.set_caption('',0,0)
    save(out/'frames.json',all_frames)
    save(out/'days.json',results)
    html='<!doctype html><meta charset="utf-8"><title>日本代表 ピッチ見本</title><style>body{background:#081b14;color:#f3f5e8;font:18px sans-serif;max-width:1150px;margin:30px auto}img{max-width:100%}video{max-height:80vh;max-width:100%}</style><h1>日本代表の招集回</h1><p>無音・仮の尺。実音声の確認前。リーグ不明は札なし。</p>'
    if (out/'silent_sample.mp4').exists():html+='<video controls muted src="silent_sample.mp4"></video>'
    for row in results:
        html+='<h2>'+row['day']+'</h2>'
        if row['selected']:
            day=row['day'][-2:];html+=f'<p>{row["title"]}</p><a href="{day}_narration.json">原稿</a><img src="{day}_cards.png">'
        else:html+='<p>招集回なし（翌日が試合）。</p>'
    (out/'index.html').write_text(html,encoding='utf8',newline='\n')
    return results


def silent_video(out,data,doc,times):
    """本番frameを15fps・540x960で確認。音声生成や投稿の経路は呼ばない。"""
    import imageio_ffmpeg
    import soccer_national_render as render
    import review_render_v3 as r3
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe();fps=15
    command=[ffmpeg,'-y','-f','rawvideo','-pix_fmt','rgb24','-s','540x960','-r',str(fps),'-i','-',
             '-an','-c:v','libx264','-preset','ultrafast','-threads','2','-crf','24','-pix_fmt','yuv420p',
             '-movflags','+faststart',str(out/'silent_sample.mp4')]
    with (out/'ffmpeg.log').open('w',encoding='utf8') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for seg,duration in zip(doc['segments'],times):
                r3.set_program_clock(0);r3.set_caption(seg['text'],duration,sum(times),speaker=2,hide_caption=seg['kind']=='outro')
                for k in range(round(duration*fps)):
                    t=k/fps;r3.set_program_clock(t)
                    im=render.frame(t,seg,data,render.clubs_for(data))
                    proc.stdin.write(im.resize((540,960)).convert('RGB').tobytes())
        finally:proc.stdin.close();code=proc.wait()
    if code:raise RuntimeError('無音の見本の書き出し失敗')
    result=subprocess.run([ffmpeg,'-v','error','-i',str(out/'silent_sample.mp4'),'-f','null','-'],capture_output=True)
    if result.returncode:raise RuntimeError('無音の見本を最後まで復号できません')
    # 完成したmp4から切替の直前・途中・直後を取り、字幕との同期を目でも確認する。
    from io import BytesIO
    from PIL import Image,ImageDraw
    from ps_brand_components import font
    samples=[1.93,2.0,2.13,2.33,4.86,5.06,5.2,5.33,5.53,8.73]
    strip=Image.new('RGB',(270*5,510*2),(8,27,20))
    for i,seconds in enumerate(samples):
        result=subprocess.run([ffmpeg,'-v','error','-ss',str(seconds),'-i',str(out/'silent_sample.mp4'),
            '-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True)
        im=Image.open(BytesIO(result.stdout)).convert('RGB').resize((270,480))
        x,y=i%5*270,i//5*510;strip.paste(im,(x,y))
        ImageDraw.Draw(strip).text((x+12,y+482),f'{seconds:.2f}s',fill=(240,246,240),font=font(24))
    strip.save(out/'video_transition_strip.png')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build_reports/national_pitch_20261108')
    parser.add_argument('--part',choices=('all','tests','draw'),default='all')
    parser.add_argument('--no-video',action='store_true')
    args=parser.parse_args();available();args.out.mkdir(parents=True,exist_ok=True)
    errors=0
    if args.part in ('all','tests'):
        results=run_tests(args.out);errors=sum(r['errors']+r['failures'] for r in results)
        import run_checks
        available()
        with (args.out/'static.log').open('w',encoding='utf8',newline='\n') as log,redirect_stdout(log),redirect_stderr(log):
            static={'syntax':run_checks.check_syntax(),'pyflakes_fatal':run_checks.check_pyflakes(),
                    'yaml':run_checks.check_yaml(),'test_entry':run_checks.check_test_entry()}
        save(args.out/'static.json',static);errors+=sum(static.values())
    if args.part in ('all','draw'):
        drawings(args.out,not args.no_video)
    save(args.out/'result.json',dict(errors=errors,time=datetime.now(JST).isoformat(),real_audio=False,publication=False))
    print('national pitch checks:',errors)
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
