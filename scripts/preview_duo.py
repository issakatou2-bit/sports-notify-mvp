"""保存した公式由来の材料を、本番の台本/合成/描画で声つき確認する。投稿なし。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--material',type=Path,default=ROOT/'scripts/fixtures/v3-rules/game-v4.json')
    ap.add_argument('--topic',default='season_game_849826')
    ap.add_argument('--out',type=Path,default=ROOT/'build/duo-preview')
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    os.environ['COLLESPO_SHORT_LOOK']='v4'
    os.environ['COLLESPO_DUO']='game'
    import generate_asset_video as asset
    import duo
    import review_render_v3 as r3
    import synthesize_narration as sn
    from preview_unified_v3 import sheet
    import v3_rules as rules
    if not shutil.which('ffmpeg'):
        import imageio_ffmpeg
        bin_dir=args.out/'bin';bin_dir.mkdir(exist_ok=True)
        name='ffmpeg.exe' if os.name=='nt' else 'ffmpeg'
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),bin_dir/name)
        os.environ['PATH']=str(bin_dir)+os.pathsep+os.environ.get('PATH','')
    material=json.loads(args.material.read_text(encoding='utf-8'))
    spec=next(s for s in material['topics'] if s['key']==args.topic)
    with patch.dict(asset.LIST_TOPICS,{args.topic:spec}):
        narration=asset.build_narration(args.topic)
        narration_path=args.out/'narration.json'
        narration_path.write_text(json.dumps(narration,ensure_ascii=False,indent=2),encoding='utf-8')
        audio_dir=args.out/'audio';audio_dir.mkdir(exist_ok=True)
        audio=[]
        prior_path=audio_dir/'manifest.json'
        prior=json.loads(prior_path.read_text(encoding='utf-8')).get('segments',[]) if prior_path.exists() else []
        for i,seg in enumerate(narration['segments']):
            path=audio_dir/f'{i:02d}.wav'
            reusable=i<len(prior) and path.exists() and (prior[i].get('text'),prior[i].get('speaker'))==(seg['text'],seg['speaker'])
            if not reusable and not sn.synth_one(seg['text'],seg['speaker'],path):
                raise ValueError('VOICEVOXの合成に失敗: '+str(i))
            audio.append(dict(seg,file=str(path.resolve()),duration=sn.audio_duration(path)))
        durations=duo.durations(audio)
        errors=duo.check(audio,durations)
        if errors:raise ValueError('実音声の掛け合い検査: '+str(errors))
        (audio_dir/'manifest.json').write_text(json.dumps({'segments':audio},ensure_ascii=False,indent=2),encoding='utf-8')
        asset.VOICE_CREDIT=duo.credit(audio)
        images=[];labels=[];layouts=[];clock=0
        for i,(seg,dur) in enumerate(zip(audio,durations)):
            t=min(3 if seg['kind']=='outro' else 1.4,dur*.55)
            r3.set_program_clock(clock)
            r3.set_caption('' if seg['kind']=='outro' else seg['text'],dur,sum(durations),speaker=seg['speaker'],duo=True)
            r3.set_program_clock(clock+t)
            image=asset.render_v3(t,seg['kind'],seg['meta'],spec,args.topic)
            errors=rules.check_layout(image)+rules.check_team_badges(image)+rules.check_spacing(image)
            if errors:raise ValueError(f'配置 {i}: {errors}')
            image.save(args.out/f'{i+1:02d}.png');images.append(image)
            labels.append(('ずんだもん' if seg['speaker']==3 else 'めたん')+' '+seg['kind'])
            layouts.append(image.info)
            clock+=dur
        sheet(images,labels,args.out/'all-screens.png',columns=4)
        r3.set_program_clock(None)
        argv=['generate_asset_video.py','--topic',args.topic,'--narration',str(narration_path),
              '--audio-dir',str(audio_dir),'--out',str(args.out)]
        with patch.object(sys,'argv',argv):asset.main()
        video=args.out/f'collespo_asset_{args.topic}.mp4'
        import subprocess
        probe=subprocess.run(['ffmpeg','-hide_banner','-i',str(video)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        import re
        duration_text=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
        if not duration_text:raise ValueError('動画の長さを読み取れません')
        h,m,s=duration_text.groups();video_seconds=int(h)*3600+int(m)*60+float(s)
        if video_seconds>45:raise ValueError('動画が45秒を超えました')
        record=dict(material=str(args.material),topic=args.topic,voice_seconds=sum(durations),video_seconds=video_seconds,
                    question_count=sum(s['speaker']==3 for s in audio),video=str(video),
                    validation='questions/grounded material/speaker/layout/audio 45s: PASS',frames=layouts,
                    settings='existing SPEAKER_TUNE/PRE_PHONEME/POST_PHONEME/PAUSE_SCALE unchanged')
        (args.out/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k!='frames'},ensure_ascii=False))


if __name__=='__main__':main()
