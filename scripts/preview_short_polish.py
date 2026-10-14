"""短尺3修正の保存材料による試作。新規取得・公開・投稿器の呼び出しなし。"""
import argparse
import ast
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BASE='843637b4134ec286cf691cb17aadaed7fcba628f'


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def voices(segments,out):
    import synthesize_narration as sn
    out.mkdir(parents=True,exist_ok=True);manifest=out/'manifest.json'
    previous=json.loads(manifest.read_text(encoding='utf8'))['segments'] if manifest.exists() else []
    audio=[]
    for i,seg in enumerate(segments):
        target=out/f'{i:02d}.wav'
        old=previous[i] if i<len(previous) else {}
        if not target.exists() or (old.get('text'),old.get('speaker'))!=(seg['text'],seg['speaker']):
            if not sn.synth_one(seg['text'],seg['speaker'],target):raise ValueError('音声合成に失敗')
        audio.append(dict(seg,file=str(target.resolve()),duration=sn.audio_duration(target)))
    write(manifest,dict(segments=audio))
    return audio


def ps_cues(program,audio):
    import ps_unified_v3 as ps
    import video_common as vc
    focus=ps.lead_card(program);events=[];start=0.
    for i,(seg,voice) in enumerate(zip(program['segments'],audio)):
        duration=max(3.,voice['duration']+vc.SEGMENT_TAIL)
        events.extend((start+at,kind,var,db) for at,kind,var,db in ps.cues(seg['meta']['card'],focus,cover=i==0,duration=duration) if at<duration)
        start+=duration
    return events


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',choices=('soccer','ps','sfx','all'),default='all')
    ap.add_argument('--games',type=Path,default=ROOT/'data/soccer_games.json')
    ap.add_argument('--out',type=Path,default=ROOT/'build/short-polish')
    args=ap.parse_args();out=args.out.resolve()
    os.environ.update(COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v5',COLLESPO_PS_DESIGN='v3',COLLESPO_EXPR='',COLLESPO_MOTION='')
    if not shutil.which('ffmpeg'):
        import imageio_ffmpeg
        directory=out/'bin';directory.mkdir(parents=True,exist_ok=True)
        executable=directory/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')
        if not executable.exists():shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),executable)
        os.environ['PATH']=str(directory)+os.pathsep+os.environ.get('PATH','')
    if args.mode in ('soccer','all'):
        import soccer_selection as selection
        import soccer_slots_v4 as slots
        material=json.loads(args.games.read_text(encoding='utf8'))
        plan=slots.program('preview',selection.select(material,availability={}))
        destination=out/'soccer';write(destination/'narration.json',plan['narration'])
        audio=voices(plan['narration']['segments'],destination/'audio')
        print(json.dumps(dict(soccer_audio_seconds=[round(a['duration'],3) for a in audio]),ensure_ascii=False),flush=True)
        slots.render_video(plan,audio,destination)
    if args.mode in ('ps','sfx','all'):
        import ps_program as p
        import review_render_v3 as r3
        saved=p.read(ROOT/'scripts/fixtures/ps-design/2026-10-07.json')
        now=datetime.fromisoformat(saved['evidence']['retrieved_at'])
        program=p.prepare(saved['snapshot'],saved['evidence'],'forecast',now,saved['ledger'])
        program['rehearsal']=True
        destination=out/'ps';write(destination/'program.json',program)
        audio=voices(program['segments'],destination/'audio')
        # 修正前の音の関数だけを隔離して同じ画面/同じ尺へ適用する。
        source=subprocess.run(['git','show',BASE+':scripts/review_render_v3.py'],cwd=ROOT,capture_output=True,text=True,encoding='utf8',check=True).stdout
        scope=dict(vars(r3))
        for node in ast.parse(source).body:
            if isinstance(node,ast.FunctionDef) and node.name in ('cues','outro_cues'):
                exec(compile(ast.get_source_segment(source,node),'saved-cues','exec'),scope)
        import ps_unified_v3 as ps
        old_ps=subprocess.run(['git','show',BASE+':scripts/ps_unified_v3.py'],cwd=ROOT,capture_output=True,text=True,encoding='utf8',check=True).stdout
        ps_scope=dict(vars(ps))
        node=next(n for n in ast.parse(old_ps).body if isinstance(n,ast.FunctionDef) and n.name=='cues')
        exec(compile(ast.get_source_segment(old_ps,node),'saved-ps-cues','exec'),ps_scope)
        with patch.object(r3,'cues',scope['cues']),patch.object(r3,'outro_cues',scope['outro_cues']),patch.object(ps,'cues',ps_scope['cues']):
            before=ps_cues(program,audio)
        after=ps_cues(program,audio)
        report=dict(material_date='2026-10-07',base_commit=BASE,before=len(before),after=len(after),before_types=dict(Counter(e[1] for e in before)),after_types=dict(Counter(e[1] for e in after)),events_before=before,events_after=after,published=False)
        write(destination/'sfx-comparison.json',report)
        print(json.dumps({k:v for k,v in report.items() if not k.startswith('events_')},ensure_ascii=False),flush=True)
        if args.mode!='sfx':p.movie(program,destination/'audio',destination)


if __name__=='__main__':main()
