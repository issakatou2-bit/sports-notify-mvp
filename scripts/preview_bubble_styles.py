"""Saved MLB 17:00/soccer material, production frames + saved voice, no upload.

These are static scene/voice previews for comparing captions, not motion proofs.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mlb-dir',type=Path,required=True)
    ap.add_argument('--soccer-dir',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args = ap.parse_args()
    os.environ.update(COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v5',COLLESPO_DUO='off',COLLESPO_EXPR='')
    import ps_brand_components as fonts
    # Preview and pixel comparison must use the same bundled font on Windows/Linux.
    fonts.FONT_CANDIDATES['jp'] = [str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
    fonts.FONT_CANDIDATES['latin'] = [str(ROOT/'assets/fonts/Oswald[wght].ttf')]
    fonts.FONT_CANDIDATES['serif'] = fonts.FONT_CANDIDATES['jp']
    fonts._cache.clear()
    import bignumber_render as bn
    import characters as c
    import review_render_v3 as r3
    import soccer_slots_v4 as slots
    import soccer_v5_cards as v5
    import synthesize_narration as sn
    import video_common as vc
    import imageio_ffmpeg
    from preview_unified_v3 import sheet
    args.out.mkdir(parents=True,exist_ok=True)
    bindir = args.out/'bin';bindir.mkdir(exist_ok=True)
    ffmpeg = str((bindir/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')).resolve())
    shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),ffmpeg)
    os.environ['PATH'] = str(bindir.resolve())+os.pathsep+os.environ.get('PATH','')
    narr = load(args.mlb_dir/'narration.json')
    recap = load(args.mlb_dir/'recap.json')
    audio = load(args.mlb_dir/'audio/manifest.json')['segments']
    for s in audio:
        s['file'] = str((args.mlb_dir/'audio'/Path(s['file']).name).resolve())
    if any((s['text'],s['speaker']) != (v['text'],v['speaker']) for s,v in zip(narr['segments'],audio)) or len(audio)!=len(narr['segments']):
        raise ValueError('保存したMLB音声と原稿が違います')
    times = [sn.audio_duration(Path(s['file']))+.7 for s in audio]
    timeline = bn.timeline(bn.scenes_from_morning(recap,narr),times)
    mlb = [(s['t0'],s['dur'],narr['segments'][s['segment']],lambda t,s=s:bn.scene(t,s)) for s in timeline]
    soccer = slots.program('preview',load(args.soccer_dir/'material.json'))
    soccer['narration'] = load(args.soccer_dir/'narration.json')
    sa = load(args.soccer_dir/'audio/manifest.json')['segments']
    for s in sa:
        s['file'] = str((args.soccer_dir/'audio'/Path(s['file']).name).resolve())
    st = slots.durations(soccer['narration']['segments'],sa)
    soccer_scenes = [(sum(st[:i]),dur,seg,lambda t,seg=seg:slots.frame(t,seg,soccer)) for i,(seg,dur) in enumerate(zip(soccer['narration']['segments'],st))]
    reports = []
    for label,scenes,voices,voice_times in [('mlb-1700',mlb,audio,times),('soccer',soccer_scenes,sa,st)]:
        track_dir = args.out/label; track_dir.mkdir(exist_ok=True)
        track = vc.build_narration_track(voices,voice_times,track_dir)
        baseline = []
        for start,dur,seg,render in scenes:
            os.environ['COLLESPO_BUBBLE'] = ''
            r3.set_program_clock(start);r3.set_caption(seg['text'],dur,sum(voice_times),speaker=seg['speaker'],hide_caption=seg['kind']=='outro')
            r3.set_program_clock(start+min(1.4,dur*.6))
            baseline.append(render(min(1.4,dur*.6)))
        fixture = ROOT/'scripts/fixtures/bubble/legacy.py'
        scope = {};exec(compile(fixture.read_text(encoding='utf-8'),str(fixture),'exec'),scope)
        old_soccer = dict(vars(v5))
        sf = ROOT/'scripts/fixtures/bubble/soccer_presenter.py'
        exec(compile(sf.read_text(encoding='utf-8'),str(sf),'exec'),old_soccer)
        with patch.object(c,'bubble',scope['bubble']), patch.object(v5,'_presenter',old_soccer['_presenter']):
            for i,(start,dur,seg,render) in enumerate(scenes):
                r3.set_program_clock(start);r3.set_caption(seg['text'],dur,sum(voice_times),speaker=seg['speaker'],hide_caption=seg['kind']=='outro')
                r3.set_program_clock(start+min(1.4,dur*.6))
                if render(min(1.4,dur*.6)).tobytes()!=baseline[i].tobytes():raise ValueError('既定の全画素が変わりました')
        for style,pattern in [('slant','stripes'),('glass','stripes'),('glass','lights')]:
            os.environ.update(COLLESPO_BUBBLE=style,COLLESPO_GLASS_BACKGROUND=pattern)
            dest = args.out/(style+'-'+pattern)/label;dest.mkdir(parents=True,exist_ok=True)
            frames = [];readings = []
            for i,(start,dur,seg,render) in enumerate(scenes):
                r3.set_program_clock(start);r3.set_caption(seg['text'],dur,sum(voice_times),speaker=seg['speaker'],hide_caption=seg['kind']=='outro')
                r3.set_program_clock(start+min(1.4,dur*.6))
                im = render(min(1.4,dur*.6));im.save(dest/f'{i+1:02}.png');frames.append(im)
                report = im.info.get('bubble_style')
                if seg['kind']!='outro' and not report:raise ValueError('指定した吹き出しが接続されていません')
                if report:
                    if min(report['contrast'],report['name_contrast'])<4.5:raise ValueError('読みにくい字幕')
                    readings.append(report)
            sheet(frames,[s[2]['kind'] for s in scenes],dest/'all-screens.png',columns=4)
            video = dest/'preview.mp4'
            command = [ffmpeg,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','10','-i','-',
                       '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-t',str(sum(voice_times)),'-movflags','+faststart',str(video)]
            with (dest/'ffmpeg.log').open('w',encoding='utf-8') as log:
                p = subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
                try:
                    written = 0
                    for im,(start,dur,_,_) in zip(frames,scenes):
                        raw=im.convert('RGB').tobytes()
                        end = round((start+dur)*10)
                        for _ in range(end-written):p.stdin.write(raw)
                        written = end
                finally:p.stdin.close()
                if p.wait():raise ValueError('動画の書出し失敗')
            decode = subprocess.run([ffmpeg,'-v','error','-i',str(video),'-f','null','-'],capture_output=True)
            if decode.returncode:raise ValueError('動画の復号失敗')
            reports.append(dict(slot=label,style=style,pattern=pattern,screens=len(frames),contrast=readings,seconds=sum(voice_times),video=str(video),default_pixel_match=len(baseline),voice='saved verified voice',motion='static scene preview'))
    r3.set_program_clock(None)
    (args.out/'confirmation.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('保存音声つき6本・全画面・コントラスト・既定画素一致:',args.out)


if __name__ == '__main__':main()
