"""新枠の保存試作。v4・同梱書体・実尺検査。取得/投稿は呼出元の責務。"""
import json
import functools
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=256)
def bundled_font(size, latin=False, serif=False):
    from PIL import ImageFont
    font = ImageFont.truetype(str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf'),size)
    font.set_variation_by_axes([700])
    return font


def setup():
    os.environ['COLLESPO_SHORT_LOOK'] = 'v4'
    os.environ.setdefault('COLLESPO_SOCCER_LOOK', 'v4')
    os.environ['COLLESPO_DUO'] = 'off'
    bundled = str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')
    os.environ['COLLESPO_FONT'] = bundled
    import ps_brand_components as brand
    # These two new slots use one bundled font on Windows and Linux alike.
    brand.FONT_CANDIDATES = {role: [bundled] for role in ('jp', 'latin', 'serif')}
    brand._cache.clear()
    brand.font = bundled_font


def render(narr, frame, out, *, voiced, filename='preview.mp4', reuse_audio=False):
    setup()
    import review_render_v3 as r3
    import soccer_results_render as rr
    import synthesize_narration as sn
    import video_common as vc
    import motion
    import v3_rules as rules
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out/'narration.json').write_text(json.dumps(narr, ensure_ascii=False, indent=2), encoding='utf8')
    import host_split
    split_audio = voiced and host_split.enabled() and bool(narr.get('host_assignment'))
    saved_manifest = {}
    if split_audio:
        import sys
        subprocess.run([sys.executable, str(ROOT/'scripts/synthesize_narration.py'), '--narration',
                        str(out/'narration.json'), '--out-dir', str(out/'audio')], check=True)
        saved_manifest = host_split.read(out/'audio/manifest.json')
        narr = host_split.read(out/'narration.json')
        host_split.render_audio(out/'audio', out)
        metadata = host_split.read(out/'metadata.json')
        if metadata.get('description'):
            metadata['description'] = host_split.credit(metadata['description'])
            (out/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf8')
    previous_path=out/'audio/manifest.json'
    previous=json.loads(previous_path.read_text(encoding='utf8')).get('segments',[]) if reuse_audio and previous_path.exists() else []
    audio = saved_manifest.get('segments', [])
    for i, seg in enumerate([] if split_audio else narr['segments']):
        if voiced:
            file = out/f'audio/{i:02d}.wav'; file.parent.mkdir(exist_ok=True)
            reuse=(i<len(previous) and file.exists() and previous[i].get('text')==seg['text'] and previous[i].get('speaker')==seg['speaker'])
            if not reuse and not sn.synth_one(seg['text'], seg['speaker'], file):
                raise ValueError('VOICEVOXの合成失敗（無音へ置換しません）')
            audio.append(dict(seg, file=str(file.resolve()), duration=sn.audio_duration(file)))
    times = rr.durations(narr['segments'], audio) if voiced else [max(3.5, len(s['text'].split())/2.5) for s in narr['segments']]
    if __import__('soccer_look').readable():
        from soccer_readable import minimum_seconds
        times = [max(t, minimum_seconds(s)) for s,t in zip(narr['segments'],times)]
    if motion.enabled():motion.measured(audio)
    times=[max(duration,len(seg['caption_en'].split())/3) if seg.get('caption_en') else duration for seg,duration in zip(narr['segments'],times)]
    times = [math.ceil(t*30)/30 for t in times]
    if sum(times) > 40: raise ValueError('40秒を超えるため原稿を短くしてください')
    import short_content
    short_content.require(narr, times, out, narr.get('soccer_material'), maximum=40, video_name=filename)
    ffmpeg = rr.ensure_ffmpeg(out)
    track = vc.build_narration_track(audio, times, out) if voiced else None
    cmd = [ffmpeg, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', '30', '-i', '-']
    if track: cmd += ['-i', str(track), '-c:a', 'aac']
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-t', str(sum(times)), '-movflags', '+faststart', str(out/filename)]
    images = []; clock = 0; previous_frame=None
    with (out/'ffmpeg.log').open('w', encoding='utf8') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, duration) in enumerate(zip(narr['segments'], times)):
                r3.set_caption(seg.get('caption_en',seg['text']), duration, sum(times), speaker=2, duo=False)
                r3.set_program_clock(clock+1.8)
                im = frame(1.8, seg)
                errors = rules.check_layout(im)+rules.check_spacing(im)
                if errors: raise ValueError(f'画面{i}: {errors}')
                im.save(out/f'{i+1:02d}.png'); images.append(im)
                for k in range(round(duration*30)):
                    r3.set_program_clock(clock+k/30)
                    image=frame(k/30,seg)
                    raw=motion.transition(previous_frame,image,k,30) if motion.enabled() else image.tobytes()
                    proc.stdin.write(raw)
                previous_frame=image.tobytes()
                clock += duration
        finally:
            proc.stdin.close(); code = proc.wait(); r3.set_program_clock(None)
    if code: raise ValueError('動画生成失敗: ffmpeg.log')
    manifest = [dict(a,index=i,duration=duration,speech_duration=a['duration']) for i,(a,duration) in enumerate(zip(audio,times))]
    (out/'audio/manifest.json').parent.mkdir(exist_ok=True)
    payload = dict(saved_manifest, segments=manifest) if split_audio else {'segments':manifest}
    (out/'audio/manifest.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    from preview_unified_v3 import sheet
    sheet(images, [s['kind'] for s in narr['segments']], out/'all-screens.png', columns=3)
    probe = subprocess.run([ffmpeg,'-hide_banner','-i',str(out/filename)],capture_output=True,text=True,encoding='utf8',errors='replace')
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
    if not match: raise ValueError('実動画の尺を取得できません')
    actual = int(match[1])*3600+int(match[2])*60+float(match[3])
    if actual>40 or abs(actual-sum(times))>.1: raise ValueError('実動画の尺が計画と異なります')
    if voiced and not re.search(r'Stream .*Audio:',probe.stderr): raise ValueError('実動画に音声がありません')
    decode = subprocess.run([ffmpeg,'-v','error','-i',str(out/filename),'-f','null','-'],capture_output=True)
    if decode.returncode or decode.stderr: raise ValueError('実動画の読み出しに失敗')
    receipt = dict(video_seconds=actual, voice_seconds=sum(a['duration'] for a in audio),
                   screens=len(images), layout='PASS', font='bundled NotoSansJP', published=False,
                   voice=host_split.credit('VOICEVOX:四国めたん') if voiced else 'none / English captions')
    (out/'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    host_split.bind_video(out/filename, out/'audio')
    return receipt
