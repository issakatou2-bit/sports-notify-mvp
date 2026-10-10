"""保存された架空のコメントだけで声つき見本と全画面を作る（投稿なし）。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

# This new slot is explicitly v4; this only affects the preview process.
os.environ['COLLESPO_SHORT_LOOK']='v4'
os.environ['COLLESPO_DUO']='off'
import soccer_voices as sv
import soccer_voices_render as render
import synthesize_narration as sn

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sample',type=Path,default=ROOT/'scripts/fixtures/soccer-voices/fictional.json')
    ap.add_argument('--out',type=Path,default=ROOT/'build/codex/tmp/soccer-voices-preview')
    ap.add_argument('--voicevox-url',default=sn.VOICEVOX_URL)
    ap.add_argument('--screens-only',action='store_true')
    args=ap.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
    data=render.prepare(sv.sample_input(args.sample))
    if not data['can_make']:raise ValueError(data['reason'])
    (out/'material.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    narr=sv.narration(data)
    (out/'narration.json').write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.screens_only:
        from preview_unified_v3 import sheet
        images=[];clubs=render.clubs_for(data)
        for i,s in enumerate(narr['segments']):
            render.r3.set_program_clock(3)
            render.r3.set_caption(s['text'],20,100,speaker=2,hide_caption=s['kind']=='outro')
            im=render.frame(18,s,data,clubs,20)
            errs=render.check_frame(im,data,clubs)
            if errs:raise ValueError(f'画面{i}: {errs}')
            im.save(out/f'{i+1:02d}.png');images.append(im)
        sheet(images,[s['kind'] for s in narr['segments']],out/'all-screens.png',columns=3)
        print('ok fictional screens',len(images));return 0
    if not shutil.which('ffmpeg'):
        # Optional local-only fallback. Production installs the system video tools first.
        import imageio_ffmpeg
        directory=out/'bin';directory.mkdir(exist_ok=True)
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),directory/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg'))
        os.environ['PATH']=str(directory)+os.pathsep+os.environ.get('PATH','')
    sn.VOICEVOX_URL=args.voicevox_url
    if not sn.engine_available():raise ValueError('VOICEVOXが起動していません（無音への置換はしない）')
    audio_dir=out/'audio';audio_dir.mkdir(exist_ok=True);audio=[]
    for i,seg in enumerate(narr['segments']):
        file=audio_dir/f'seg_{i:03d}.wav'
        if not sn.synth_one(seg['text'],seg['speaker'],file):raise ValueError('声の生成失敗')
        audio.append(dict(seg,file=str(file.resolve()),duration=sn.audio_duration(file)))
    (audio_dir/'manifest.json').write_text(json.dumps({'segments':audio},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    render.render_video(data,narr,audio,out)
    return 0


if __name__=='__main__':raise SystemExit(main())
