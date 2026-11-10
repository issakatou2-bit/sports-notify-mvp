"""代表長編を両相手のfixtureで検証。実通信・実音声・公開は呼ばない。"""
from contextlib import redirect_stderr,redirect_stdout
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]


def main():
    from verify_national_numbers import available
    available(15)
    import soccer_national as n
    import render_soccer_national_long as render
    from test_soccer_national_numbers import AS_OF
    from PIL import Image
    out=ROOT/'build_reports/national_numbers_20261110';out.mkdir(parents=True,exist_ok=True)
    results=[]
    for name in ('test_soccer_national_long.py','test_soccer_national_numbers.py','test_name_reading_guard.py','test_soccer_official_names.py','test_soccer_weekly_long.py'):
        available()
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
        (out/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf8',newline='\n')
        results.append(dict(file=name,exit_code=result.returncode))
    import run_checks
    with (out/'long_static.log').open('w',encoding='utf8',newline='\n') as log,redirect_stdout(log),redirect_stderr(log):
        static=dict(syntax=run_checks.check_syntax(),pyflakes_fatal=run_checks.check_pyflakes(),yaml=run_checks.check_yaml(),test_entry=run_checks.check_test_entry())
    n.save(out/'long_checks.json',dict(tests=results,static=static))
    if any(r['exit_code'] for r in results) or any(static.values()):raise RuntimeError('長編の試験・静的検査に失敗。ログを確認してください')
    days=[]
    with patch.dict(os.environ,COLLESPO_SAMPLE_ONLY='true'):
        for key in ('brazil','paraguay'):
            available(5)
            directory=out/key;directory.mkdir(exist_ok=True)
            command=[sys.executable,str(ROOT/'scripts/soccer_national_long.py'),'--opponent',key,'--as-of',AS_OF,
                     '--fixture',str(ROOT/'scripts/fixtures/soccer_national_numbers.json'),'--out',str(directory)]
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf8')
            (directory/'cli.log').write_text(result.stdout+result.stderr,encoding='utf8',newline='\n')
            if result.returncode:raise RuntimeError('長編CLIで失敗: '+key)
            data=n.read(directory/'material.json');doc=n.read(directory/'dialogue.json')
            render.frames(doc,directory/'frames')
            selected=('opening','position_GK_0','position_MF_FW_0','focus_0','history','kickoff')
            strip=Image.new('RGB',(640*2,360*3))
            for index,name in enumerate(selected):
                im=Image.open(directory/'frames'/(name+'.png')).convert('RGB').resize((640,360))
                strip.paste(im,(index%2*640,index//2*360))
            strip.save(directory/'review.png')
            days.append(dict(key=key,title=doc['title'],planned_publish_at=data['planned_publish_at'],players=len(data['players']),panels=len(doc['panels']),segments=len(doc['segments'])))
    n.save(out/'long_result.json',dict(checks=results,static=static,matches=days,real_audio=False,publication=False))
    print('代表長編: 両相手の台本・全札の描画・検査完了')


if __name__=='__main__':main()
