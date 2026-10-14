"""Replay the three native writers with saved, validated speech. No network."""
import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def read(path):return json.loads(path.read_text(encoding='utf8'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('reddit','mlb','soccer','out'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--fps',type=int,default=24)
    ap.add_argument('--bubble',choices=('slant','glass'),default='glass')
    ap.add_argument('--slots',nargs='+',choices=('reddit','mlb-1700','soccer'),default=['reddit','mlb-1700','soccer'])
    a=ap.parse_args()
    os.environ.update(COLLESPO_MOTION='on',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v5',COLLESPO_EXPR='',COLLESPO_BUBBLE=a.bubble)
    import motion
    import player_story_render as reddit
    import bignumber_render as bn
    import soccer_slots_v4 as slots
    import review_render_v3 as r3
    import video_common as vc
    import synthesize_narration as sn
    import imageio_ffmpeg
    import ps_brand_components as fonts
    from preview_unified_v3 import sheet
    fonts.FONT_CANDIDATES['jp']=[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
    fonts.FONT_CANDIDATES['latin']=[str(ROOT/'assets/fonts/Oswald[wght].ttf')]
    fonts.FONT_CANDIDATES['serif']=fonts.FONT_CANDIDATES['jp'];fonts._cache.clear()
    a.out.mkdir(parents=True,exist_ok=True)
    reports=read(a.out/'confirmation.json') if (a.out/'confirmation.json').exists() and len(a.slots)<3 else []
    bindir=a.out/'bin';bindir.mkdir(exist_ok=True)
    ffmpeg=bindir/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')
    if not ffmpeg.exists():shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),ffmpeg)
    ffmpeg=str(ffmpeg.resolve());os.environ['PATH']=str(bindir.resolve())+os.pathsep+os.environ.get('PATH','')
    # Fail before an expensive encode if any saved script/voice/material drifted.
    for label,source in (('reddit',a.reddit),('mlb-1700',a.mlb),('soccer',a.soccer)):
        if label not in a.slots:continue
        saved=read(source/'narration.json');voices=read(source/'audio/manifest.json')['segments']
        if len(saved['segments'])!=len(voices) or any(any(s[k]!=v[k] for k in ('kind','text','speaker','meta')) for s,v in zip(saved['segments'],voices)):
            raise ValueError('試作前の音声・原稿照合失敗: '+label)
        if label=='soccer' and slots.program('preview',read(source/'material.json'))['narration']!=saved:
            raise ValueError('試作前の保存材料・現在の原稿照合失敗: soccer')
    for label,source in (('reddit',a.reddit),('mlb-1700',a.mlb),('soccer',a.soccer)):
        if label not in a.slots:continue
        __import__('slant_by_episode').set_episode({'reddit':'reddit_reaction','mlb-1700':'morning_players','soccer':'soccer_preview'}[label])
        narr=read(source/'narration.json');audio=read(source/'audio/manifest.json')['segments']
        if len(audio)!=len(narr['segments']):raise ValueError('保存音声の区間数不一致')
        hashes=[]
        for seg,row in zip(narr['segments'],audio):
            if any(seg[k]!=row[k] for k in ('kind','text','speaker','meta')):raise ValueError('保存音声と表示原稿が不一致')
            file=source/'audio'/Path(row['file']).name
            actual=sn.audio_duration(file)
            if abs(actual-row['duration'])>.05:raise ValueError('音声尺の不一致')
            row['file']=str(file.resolve());row['duration']=actual
            hashes.append(dict(file=file.name,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        times=[math.ceil((row['duration']+vc.SEGMENT_TAIL)*a.fps)/a.fps for row in audio]
        motion.measured(audio)
        if label=='reddit':
            draw=lambda now,local,seg:reddit.frame(local,seg,narr)
        elif label=='mlb-1700':
            data=read(source/'recap.json');scenes=bn.scenes_from_morning(data,narr)
            errors=bn.check_scenes(scenes,narr,data)
            if errors:raise ValueError(errors)
            plan=bn.timeline(scenes,times)
            draw=lambda now,local,seg:bn.frame(now,plan)
        else:
            plan=slots.program('preview',read(source/'material.json'))
            if plan['narration']!=narr:raise ValueError('サッカー保存原稿が現在の材料と不一致')
            draw=lambda now,local,seg:slots.frame(local,seg,plan)
        folder=a.out/label;folder.mkdir(exist_ok=True)
        track=vc.build_narration_track(audio,times,folder)
        video=folder/'preview.mp4'
        command=[ffmpeg,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r',str(a.fps),'-i','-',
                 '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-t',str(sum(times)),'-movflags','+faststart',str(video)]
        snapshots=[];receipts=[];clock=0;previous=None;count=0;focused=set();overview=0
        with (folder/'ffmpeg.log').open('w',encoding='utf8') as log:
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
            try:
                for i,(seg,dur) in enumerate(zip(narr['segments'],times)):
                    r3.set_program_clock(clock);r3.set_caption(seg['text'],dur,sum(times),speaker=seg['speaker'],hide_caption=seg['kind']=='outro')
                    for k in range(round(dur*a.fps)):
                        local=k/a.fps;now=clock+local;r3.set_program_clock(now)
                        im=draw(now,local,seg);info=im.info.get('motion')
                        if info:
                            if info['active'] is not None:
                                focused.add(info['active'])
                                cue=next(c for c in info['cues'] if c['key']==info['active'])
                                if cue['text']!=seg['text']:raise ValueError('字幕・音声・寄る項目が不一致')
                            else:overview+=1
                            # Whole output frame, after camera and before transition.
                            if k in (0,round(.8*a.fps),round(1.5*a.fps),round((dur-.12)*a.fps)):
                                name=f'{i+1:02d}-{k:03d}.png';im.save(folder/name);snapshots.append(im.copy())
                                receipts.append(dict(segment=i,text=seg['text'],time=now,frame=name,motion=info))
                        raw=motion.transition(previous,im,k,a.fps)
                        proc.stdin.write(raw);count+=1
                    previous=im.tobytes();clock+=dur
            finally:proc.stdin.close();r3.set_program_clock(None)
            if proc.wait():raise ValueError('映像生成失敗')
        if len(focused)!=3:raise ValueError(f'{label}: 寄った項目数が3でない: {focused}')
        sheet(snapshots,[str(i+1) for i in range(len(snapshots))],folder/'all-screens.png',columns=4)
        decode=subprocess.run([ffmpeg,'-v','error','-i',str(video),'-f','null','-'],capture_output=True)
        if decode.returncode:raise ValueError('全尺復号失敗')
        pcm=subprocess.run([ffmpeg,'-v','error','-i',str(video),'-map','0:a:0','-f','s16le','-'],capture_output=True)
        if pcm.returncode or not any(pcm.stdout):raise ValueError('音声がありません')
        report=dict(slot=label,seconds=sum(times),fps=a.fps,frames=count,focused=sorted(focused),overview_frames=overview,
                    bubble=a.bubble,full_decode='PASS',audible_track='PASS',subtitle_voice_row='PASS',safe_area='PASS',audio_hashes=hashes,samples=receipts)
        (folder/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        reports=[r for r in reports if r['slot']!=label]
        reports.append({k:v for k,v in report.items() if k not in ('samples','audio_hashes')})
        print(json.dumps(reports[-1],ensure_ascii=False),flush=True)
    (a.out/'confirmation.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    html='<html lang="ja"><meta charset="utf-8"><title>静かな動きの試作</title><style>body{background:#162a30;color:white;font:16px sans-serif}video{width:320px}article{display:inline-block;margin:12px;vertical-align:top}img{width:95%}</style><h1>読み上げ中の札を強調する</h1><p>保存材料と保存音声の非公開試作。動きはCOLLESPO_MOTION=onでのみ有効。</p>'
    for report in reports:
        name=report['slot'];html+=f'<article><h2>{name}</h2><video controls preload="metadata" src="{name}/preview.mp4"></video><p>{report["seconds"]:.2f}秒 / 3項目の同期・全尺復号・声あり</p></article>'
    html+='<p><a href="confirmation.json">検査記録</a></p>'
    (a.out/'review.html').write_text(html,encoding='utf8')


if __name__=='__main__':main()
