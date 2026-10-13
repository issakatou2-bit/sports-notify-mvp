"""保存した山本の成績を使う非公開の3本。投稿処理なし。"""
import json
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import bignumber_render as bn
import fan_events
import generate_morning_short as g
import review_render_v3 as r3
import sound_mix
import synthesize_narration as synth
import video_common
from PIL import Image


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('out',nargs='?',type=Path,default=Path('build/fan2-previews'))
    out=ap.parse_args().out
    out.mkdir(parents=True,exist_ok=True)
    bn._no_network()
    confirmation=[]
    for label,day in [('start','2026-09-15'),('success','2026-09-09'),('loss','2026-09-23')]:
        source=Path('data/recap_history')/(day+'.json')
        data=json.loads(source.read_text(encoding='utf-8'))
        p=next(p for p in data['players'] if p['name']=='山本由伸')
        if label=='start':
            if p.get('gs')!=1:raise ValueError('先発の記録が無い')
            material=dict(players=[dict(name=p['name'],type='pitcher',starter_confirmed=True,source=str(source)+' / gs=1')])
            text='山本由伸が先発した日の成績です。'
        else:
            material=dict(players=[p])
            text=f'山本由伸は{p["ip"]}回を投げて{p["so"]}奪三振。'+('勝ち投手でした。' if label=='success' else 'この日は負けがつきました。')
        dest=out/label;dest.mkdir(exist_ok=True)
        wav=dest/'voice.wav'
        if not synth.synth_one(text,2,wav):raise ValueError('声の合成に失敗')
        speech=synth.audio_duration(wav);duration=speech+.7
        seg=dict(kind='hero',text=text,speaker=2,duration=speech,meta={})
        narration=dict(label=g.jp_date(data['date_jst']),segments=[seg])
        scenes=bn.scenes_from_morning(dict(data,players=[p]),narration)
        plan=bn.timeline(scenes,[duration])
        fan_events.prepare(material,[seg],[duration],dest)
        cues=bn.plan_cues(plan)+fan_events.event_cues()
        voice=video_common.build_narration_track([dict(seg,file=str(wav))],[duration],dest)
        mixed=sound_mix.mix_file(voice,dest/'mixed.wav',sound_mix.bgm_path(),cues)
        video=dest/(label+'.mp4')
        proc=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-vcodec','rawvideo',
            '-pix_fmt','rgb24','-s','1080x1920','-r','24','-i','-','-i',str(mixed),
            '-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',
            '-c:a','aac',str(video)],stdin=subprocess.PIPE)
        r3.set_program_clock(0);r3.set_caption(text,speech,duration,speaker=2)
        sample=None
        try:
            for i in range(int(duration*24)):
                t=i/24;r3.set_program_clock(t)
                im=bn.frame(t,plan)
                proc.stdin.write(im.convert('RGB').tobytes())
                if i==int(speech*.5*24):sample=im.copy()
        finally:
            proc.stdin.close()
        if proc.wait():raise RuntimeError('動画の書出し失敗')
        if sample:sample.save(dest/'frame.png')
        confirmation.append(dict(kind=label,source=str(source),date_jst=data['date_jst'],speech_seconds=speech,video=str(video),
                                 text=text,decision=fan_events.TRACK[0]['decision']))
    r3.set_program_clock(None)
    (out/'confirmation.json').write_text(json.dumps(confirmation,ensure_ascii=False,indent=2),encoding='utf-8')
    thumbs=[]
    for label,_ in [('start',0),('success',0),('loss',0)]:
        im=Image.open(out/label/'frame.png');im.thumbnail((360,640));thumbs.append(im)
    sheet=Image.new('RGB',(1080,640))
    for i,im in enumerate(thumbs):sheet.paste(im,(i*360,0))
    sheet.save(out/'all-screens.png')
    print('3本保存:',out)


if __name__=='__main__':main()
