"""保存材料の欧州3枠を、本番と同じ原稿・声・描画で試作する。投稿なし。"""
import argparse
import json
import os
import shutil
from pathlib import Path


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=Path('build/soccer-v4-previews'))
    ap.add_argument('--mode',choices=('preview','race','week','all'),default='all')
    args=ap.parse_args();os.environ['COLLESPO_SHORT_LOOK']='v4'
    if not shutil.which('ffmpeg'):
        import imageio_ffmpeg
        directory=args.out/'bin';directory.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),directory/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg'))
        os.environ['PATH']=str(directory.resolve())+os.pathsep+os.environ.get('PATH','')
    import soccer_slots_v4 as slots
    import synthesize_narration as sn
    reports=[]
    for mode in (('preview','race','week') if args.mode=='all' else (args.mode,)):
        data=json.loads((slots.ROOT/'scripts/fixtures/soccer-slots'/f'{mode}.json').read_text(encoding='utf-8'))
        plan=slots.program(mode,data);narr=plan['narration'];out=args.out/mode;out.mkdir(parents=True,exist_ok=True)
        (out/'material.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (out/'narration.json').write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        directory=out/'audio';directory.mkdir(exist_ok=True);manifest=directory/'manifest.json'
        old=json.loads(manifest.read_text(encoding='utf-8')).get('segments',[]) if manifest.exists() else []
        audio=[]
        for i,seg in enumerate(narr['segments']):
            path=directory/f'{i:02d}.wav'
            reuse=i<len(old) and path.exists() and (seg['text'],seg['speaker'])==(old[i].get('text'),old[i].get('speaker'))
            if not reuse and not sn.synth_one(seg['text'],seg['speaker'],path):raise ValueError('声を作れませんでした')
            audio.append(dict(seg,file=str(path.resolve()),duration=sn.audio_duration(path)))
        manifest.write_text(json.dumps(dict(segments=audio),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        reports.append(slots.render_video(plan,audio,out))
    (args.out/'confirmation.json').write_text(json.dumps(dict(previews=reports,published=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
