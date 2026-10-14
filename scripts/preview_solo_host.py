"""保存した朝の成績回で雨衣の立ち絵・声を確認する。公開処理なし。

--silent は声の不足を明記した画面試作。音声付きは雨衣のmanifestを必須とする。
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
from unittest.mock import patch


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--portrait-dir', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--audio-dir', type=Path)
    ap.add_argument('--silent', action='store_true')
    ap.add_argument('--frames-only', action='store_true', help='全場面の配置を先に静止画で確認する')
    args = ap.parse_args()
    if args.silent == bool(args.audio_dir):
        ap.error('--silent または --audio-dir のどちらか一方を指定してください')
    os.environ.update(COLLESPO_MOTION='on', COLLESPO_BUBBLE='slant', COLLESPO_SHORT_LOOK='v4',
                      COLLESPO_SOLO_HOST='ui', COLLESPO_EXPR='', COLLESPO_UI_PORTRAIT_DIR=str(args.portrait_dir.resolve()))
    import bignumber_render as bn
    import characters
    import imageio_ffmpeg
    import motion
    import ps_brand_components as fonts
    import review_render_v3 as r3
    import slant_by_episode
    import solo_host
    import synthesize_narration as sn
    import video_common as vc
    root = Path(__file__).resolve().parents[1]
    fonts.FONT_CANDIDATES['jp'] = [str(root/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
    fonts.FONT_CANDIDATES['latin'] = [str(root/'assets/fonts/Oswald[wght].ttf')]
    fonts.FONT_CANDIDATES['serif'] = fonts.FONT_CANDIDATES['jp']; fonts._cache.clear()
    for size in range(12, 121):
        fonts.font(size).set_variation_by_name('Bold')
    slant_by_episode.set_episode('morning_players')
    narration = read(args.source/'narration.json')
    if solo_host.for_segments(narration['segments']) != 'ui':
        raise ValueError('保存原稿がめたんソロではありません')
    audio_dir = args.audio_dir or args.source/'audio'
    audio = read(audio_dir/'manifest.json')['segments']
    if len(audio) != len(narration['segments']):
        raise ValueError('原稿と音声の区間数が違います')
    for seg, voice in zip(narration['segments'], audio):
        if any(seg.get(k) != voice.get(k) for k in ('text', 'speaker', 'meta', 'kind')):
            raise ValueError('原稿と音声の文・話者・札が違います')
        voice['file'] = str((audio_dir/Path(voice['file']).name).resolve())
        voice['duration'] = sn.audio_duration(Path(voice['file']))
        if voice['duration'] <= 0:
            raise ValueError('保存音声がありません')
    args.out.mkdir(parents=True, exist_ok=True)
    fps = motion.SETTINGS['fps']
    times = [math.ceil((v['duration']+vc.SEGMENT_TAIL)*fps)/fps for v in audio]
    scenes = bn.scenes_from_morning(read(args.source/'recap.json'), narration)
    errors = bn.check_scenes(scenes, narration, read(args.source/'recap.json'))
    if errors:
        raise ValueError(errors)
    plan = bn.timeline(scenes, times); motion.measured(audio)
    original_bust = characters.bust
    original_source = r3.source
    def preview_bust(who, face, height, dim=False):
        if args.silent and who == 'ui':
            face = face.split(':mouth')[0]+':mouth0'
        return original_bust(who, face, height, dim)
    def preview_source(draw, text, *args, **kwargs):
        if args_silent and solo_host.UI_CREDIT in text:
            text = text.replace('音声: '+solo_host.UI_CREDIT, '雨衣の立ち絵試作（声未生成）')
        return original_source(draw, text, *args, **kwargs)
    args_silent = args.silent
    if args.frames_only:
        clock = 0
        with patch.object(characters, 'bust', preview_bust), patch.object(r3, 'source', preview_source):
            for i, (seg, duration) in enumerate(zip(narration['segments'], times)):
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'], duration, sum(times), speaker=2, hide_caption=seg['kind']=='outro')
                r3.set_program_clock(clock+1.5)
                im = bn.frame(clock+1.5, plan)
                im.save(args.out/f'{i+1:02d}.png')
                clock += duration
        return
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video = args.out/('ui-morning-silent.mp4' if args.silent else 'ui-morning.mp4')
    command = [ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', str(fps), '-i', '-']
    if not args.silent:
        solo_host.validate_audio(audio)
        track = vc.build_narration_track(audio, times, args.out)
        command += ['-i', str(track), '-c:a', 'aac']
    command += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)]
    receipts = []; clock = 0; count = 0; previous = None
    with (args.out/'ffmpeg.log').open('w') as log, patch.object(characters, 'bust', preview_bust), patch.object(r3, 'source', preview_source):
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, duration) in enumerate(zip(narration['segments'], times)):
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'], duration, sum(times), speaker=2, hide_caption=seg['kind']=='outro')
                for k in range(round(duration*fps)):
                    r3.set_program_clock(clock+k/fps)
                    im = bn.frame(clock+k/fps, plan)
                    from PIL import ImageDraw
                    if args.silent:
                        draw = ImageDraw.Draw(im)
                        draw.rectangle((0, 0, im.width, 46), fill=(28, 41, 51))
                        draw.text((24, 6), '雨衣の立ち絵試作（声未生成・口は閉じたまま）', font=r3.font(24), fill='white')
                    if k == min(round(1.5*fps), round(duration*fps)-1):
                        im.save(args.out/f'{i+1:02d}.png')
                        portraits = im.info.get('duo_portraits', [])
                        if not portraits or {p['who'] for p in portraits} != {'ui'}:
                            raise ValueError('雨衣の立ち絵がありません')
                        if seg['kind'] != 'outro' and im.info.get('duo_caption', {}).get('speaker') != 'ui':
                            raise ValueError('吹き出しの話者が雨衣ではありません')
                        receipts.append(dict(segment=i, portraits=portraits, caption=im.info.get('duo_caption')))
                    process.stdin.write(motion.transition(previous, im, k, fps)); count += 1
                previous = im.tobytes(); clock += duration
        finally:
            process.stdin.close(); r3.set_program_clock(None)
        if process.wait():
            raise ValueError('雨衣の試作動画を書き出せませんでした')
    subprocess.run([ffmpeg, '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
    report = dict(video=str(video), fps=fps, frames=count, seconds=clock, full_decode='PASS',
                  audio=not args.silent, credit=solo_host.UI_CREDIT, samples=receipts,
                  note='雨衣の声は認証不足で未生成。保存めたん音声の尺だけを参照。' if args.silent else '雨衣の実音声')
    (args.out/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k != 'samples'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
