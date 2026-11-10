"""数字入り招集の試験・静的検査・静止画・無音見本を一度に確認（通信なし）。"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]


def available(minutes=0):
    now=datetime.now(timezone(timedelta(hours=9)))
    for start,end in ((440,520),(1155,1330)):
        minute=now.hour*60+now.minute+now.second/60
        if start<=minute<end or minute<start<minute+minutes:
            raise RuntimeError('配信のため試験・描画を始めない時間です: '+now.isoformat())


def main():
    available(15)
    import soccer_national as n
    import soccer_national_numbers as numbers
    import soccer_national_render as render
    import review_render_v3 as r3
    import name_reading_guard as guard
    from test_soccer_national_numbers import fixture_sheet,AS_OF
    from verify_national_pitch import silent_video
    from PIL import Image
    out=ROOT/'build_reports/national_numbers_20261110';out.mkdir(parents=True,exist_ok=True)
    results=[]
    for filename in ('test_soccer_national_numbers.py','test_soccer_national.py','test_soccer_national_squad.py','test_national_pitch.py','test_name_reading_guard.py','test_short_common.py'):
        available()
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/filename)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
        (out/(filename+'.log')).write_text(result.stdout+result.stderr,encoding='utf8',newline='\n')
        results.append(dict(file=filename,exit_code=result.returncode))
    import run_checks
    with (out/'static.log').open('w',encoding='utf8',newline='\n') as log,redirect_stdout(log),redirect_stderr(log):
        static=dict(syntax=run_checks.check_syntax(),pyflakes_fatal=run_checks.check_pyflakes(),yaml=run_checks.check_yaml(),test_entry=run_checks.check_test_entry())
    n.save(out/'checks.json',dict(tests=results,static=static))
    if any(r['exit_code'] for r in results) or any(static.values()):raise RuntimeError('試験または静的検査に失敗。ログを確認してください')
    env=dict(COLLESPO_SAMPLE_ONLY='true',COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan')
    with patch.dict(os.environ,env):
        sheet=fixture_sheet();roster=n.read(ROOT/'data/soccer_national_squad.json')
        data=numbers.attach(n.squad(roster,{},AS_OF,4),sheet)
        doc=n.narration(data);assert n.check(doc)==[];guard.validate_dialogue(doc)
        times=[3.0 if s['meta'].get('intro') else 3.2 if 'player' in s['meta'] else 2.0 for s in doc['segments']]
        n.save(out/'sample_material.json',data);n.save(out/'sample_narration.json',doc);n.save(out/'numbers_fixture.json',sheet)
        cards=[]
        for i,seg in enumerate(doc['segments']):
            r3.set_program_clock(0);r3.set_caption(seg['text'],times[i],sum(times),speaker=2,hide_caption=seg['kind']=='outro')
            r3.set_program_clock(.4);im=render.frame(.4,seg,data,render.clubs_for(data))
            errors=render.validate_frame(im,render.clubs_for(data),data)
            if errors:raise ValueError(errors)
            im.save(out/f'short_{i:02d}.png')
            if 'player' in seg['meta']:cards.append(im.resize((360,640)))
        strip=Image.new('RGB',(360*len(cards),640))
        for i,im in enumerate(cards):strip.paste(im,(360*i,0))
        strip.save(out/'short_cards.png');available(8);silent_video(out,data,doc,times)
        # 依頼された共有の見本位置へ、実績データを使わずコピーする。
        import shutil
        sample=ROOT.parents[1]/'build/codex/tmp/national_numbers_sample.mp4'
        sample.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/'silent_sample.mp4',sample)
        n.save(out/'result.json',dict(tests=results,static=static,video=str(sample),fixture=True,real_audio=False,publication=False))
    print('数字入り招集: 試験・静的検査・描画・無音動画の確認完了')


if __name__=='__main__':main()
