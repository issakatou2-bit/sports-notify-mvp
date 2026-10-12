"""保存材料で17時/19時の声つき試作を既存の本番生成器から作る。公開なし。"""
import argparse
from datetime import date,datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def run(command,env,log):
    if command[0]=='ffmpeg':
        executable=shutil.which('ffmpeg',path=env['PATH'])
        if not executable:raise FileNotFoundError('指定したffmpeg-dirにffmpeg.exeがない')
        command=[executable,*command[1:]]
    with log.open('w',encoding='utf8') as stream:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('試作生成が失敗: '+str(log))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path)
    ap.add_argument('--url',default='http://127.0.0.1:50121');ap.add_argument('--ffmpeg-dir',type=Path)
    ap.add_argument('--replay-players',type=Path,help=argparse.SUPPRESS)
    ap.add_argument('--resume',action='store_true',help='同じ保存原稿の完成済み音声/動画を再利用する')
    args=ap.parse_args()
    if args.replay_players:
        import generate_morning_short as g
        import recap_freshness
        folder=args.replay_players;recap=json.loads((folder/'recap.json').read_text(encoding='utf8'))
        # 見本のプロセス内だけ時計を保存日の版へ固定。本番の日付検査は変更しない。
        with patch.object(recap_freshness,'current_day',return_value=date.fromisoformat(recap['date_jst'])),\
             patch.object(sys,'argv',['generate_morning_short','--mode','players','--recap',str(folder/'recap.json'),
                                     '--narration',str(folder/'narration.json'),'--audio-dir',str(folder/'audio'),'--out',str(folder),'--require-audio']):
            return g.main()
    if not args.out or not args.ffmpeg_dir:ap.error('--out と --ffmpeg-dir が必要です')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,COLLESPO_SHORT_LOOK='v4',COLLESPO_MLB_BADGE='pinstripe',COLLESPO_PLAYERS_DESIGN='bignumber',
             COLLESPO_PS_DESIGN='v3',COLLESPO_DUO='off',PYTHONUTF8='1')
    env['PATH']=str(args.ffmpeg_dir.resolve())+os.pathsep+env.get('PATH','')
    os.environ.update({k:env[k] for k in ('COLLESPO_SHORT_LOOK','COLLESPO_MLB_BADGE','COLLESPO_PLAYERS_DESIGN','COLLESPO_PS_DESIGN','COLLESPO_DUO')})
    import generate_morning_short as g
    import bignumber_render as bn
    import ps_program as ps
    import synthesize_narration as sn
    import review_render_v3 as r3
    from preview_unified_v3 import sheet
    import test_v3_rules as fixtures
    sources=[ROOT/'scripts/fixtures/bignumber/morning_recap.json',ROOT/'scripts/fixtures/ps-design/2026-10-07.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    recap=json.loads(sources[0].read_text(encoding='utf8'));recap['players']=g.sort_players(recap['players'])
    with patch.object(g,'week_line',return_value=('',[])):
        narration=g.build_narration(recap,'players')
    if not g.bignumber_scenes(recap,narration,'players'):raise ValueError('本番の成績用場面を準備できません')
    if bn.check_scenes(bn.scenes_from_morning(recap,narration),narration,recap):raise ValueError('成績と原稿が不一致')
    saved=json.loads(sources[1].read_text(encoding='utf8'))
    program=ps.prepare(saved['snapshot'],saved['evidence'],'forecast',datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
    ps.check_program(program)
    plans=[('1700-players',narration,recap),('1900-forecast',ps.script(program),program)]
    summary=[];sn.VOICEVOX_URL=args.url
    for name,nar,data in plans:
        folder=out/name;folder.mkdir(exist_ok=True)
        old_script=folder/'narration.json'
        cached=args.resume and old_script.exists() and json.loads(old_script.read_text(encoding='utf8'))==nar
        write(old_script,nar)
        audio=folder/'audio';audio.mkdir(exist_ok=True)
        # 合成器のmainも同じ原稿・メタ・話者を保存する。
        if not cached or not (audio/'manifest.json').exists():
            with patch.object(sys,'argv',['synthesize_narration','--narration',str(folder/'narration.json'),'--out-dir',str(audio)]):sn.main()
        manifest=json.loads((audio/'manifest.json').read_text(encoding='utf8'))
        if len(manifest['segments'])!=len(nar['segments']) or any(not s.get('file') or not s.get('duration') for s in manifest['segments']):
            raise ValueError('音声が不足')
        if any(any(a.get(k)!=b.get(k) for k in ('text','kind','meta','speaker')) for a,b in zip(manifest['segments'],nar['segments'])):
            raise ValueError('音声と原稿の内容/話者が不一致')
        if name.startswith('1700'):
            write(folder/'recap.json',data)
            source_video=folder/'collespo_morning.mp4'
            if not cached or not source_video.exists():
                run([sys.executable,str(Path(__file__)),'--replay-players',str(folder)],env,folder/'render.log')
        else:
            write(folder/'program.json',data)
            source_video=folder/'collespo_short.mp4'
            if not cached or not source_video.exists() or not (folder/'ps_program_gate.json').exists():
                run([sys.executable,str(ROOT/'scripts/ps_program.py'),'--program',str(folder/'program.json'),
                     '--audio-dir',str(audio),'--out',str(folder)],env,folder/'render.log')
        if not source_video.exists():raise ValueError('MP4がない: '+str(source_video))
        video=out/(name+'.mp4');shutil.copyfile(source_video,video)
        run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],env,folder/'decode-check.log')
        run(['ffmpeg','-y','-v','error','-i',str(video),'-vf','fps=1/4,scale=270:480,tile=4x4','-frames:v','1',str(out/(name+'-contact.png'))],env,folder/'contact.log')
        run(['ffmpeg','-y','-v','error','-ss','5','-i',str(video),'-frames:v','1',str(out/(name+'-poster.png'))],env,folder/'poster.log')
        summary.append(dict(name=name,video=video.name,narration_segments=len(nar['segments']),audio_seconds=sum(s['duration'] for s in manifest['segments']),
                            sample_date=nar.get('date_jst'),audio=True,decode_check='PASS'))
        print(name,'movie complete',flush=True)
    # 基準と比較する静止画。全枠の検査はtest_mlb_pinstripeで実行。
    cases=fixtures.daily_cases();images=[];labels=[]
    for case in cases:
        for i,draw in enumerate(case['frames']):
            if case['name'] not in ('players','forecast'):continue
            r3.set_caption('',0,0);r3.set_program_clock(None)
            os.environ.pop('COLLESPO_MLB_BADGE',None);before=draw(7)
            os.environ['COLLESPO_MLB_BADGE']='pinstripe';after=draw(7)
            images.extend((before,after));labels.extend((f'{case["name"]} {i+1} 現在',f'{case["name"]} {i+1} 縦じま'))
    sheet(images,labels,out/'before-after.png',columns=4)
    if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h for p,h in hashes.items()):raise ValueError('元材料が変わった')
    write(out/'confirmation.json',dict(base='2f86ba3f',source_sha256=hashes,previews=summary,production_flag='COLLESPO_MLB_BADGE=pinstripe',published=False,variable_changed=False))
    html='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MLBの縦じま札</title><style>body{background:#0d171f;color:#eef5f3;font:18px system-ui;max-width:1000px;margin:24px auto;padding:12px}video{width:min(100%,360px)}img{max-width:100%}</style><h1>MLBの縦じま札</h1><p>保存した過去の材料での声つき試作です。当日の情報ではありません。</p>'
    for r in summary:html+=f'<h2>{"17:00 日本人選手の成績" if r["name"].startswith("1700") else "19:00 明日の注目試合"}</h2><video controls playsinline src="{r["video"]}"></video><p><a href="{r["video"]}">MP4</a></p>'
    html+='<h2>現在の札と縦じまの比較</h2><img src="before-after.png"></html>'
    (out/'index.html').write_text(html,encoding='utf8')


if __name__=='__main__':main()
