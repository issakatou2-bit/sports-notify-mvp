"""選手の話題の回。既存v4の背景・札・字幕・下隅キャラ・音声結合を再利用。"""
import motion
import argparse
from datetime import timedelta, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

os.environ['COLLESPO_SHORT_LOOK'] = 'v4'
from PIL import ImageDraw  # noqa: E402
import ps_brand_components as brand  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# この枠は同梱書体だけで描く。Windowsフォント・aptの結果に依存しない。
brand.FONT_CANDIDATES['jp'] = [str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
brand.FONT_CANDIDATES['latin'] = [str(ROOT/'assets/fonts/Oswald[wght].ttf')]
import review_render_v3 as r3  # noqa: E402
import short_v4_cards as cards  # noqa: E402
import video_common as vc  # noqa: E402
import player_story as story  # noqa: E402
import fan_events  # noqa: E402


def bundled_font(size, latin=False, serif=False):
    f = brand.font(size, latin, serif)
    if not latin and not serif:
        # 可変書体の既定はThin。共通v4の太字と同程度の700に固定する。
        f.set_variation_by_axes([700])
    return f


r3.font = bundled_font
HEADINGS = {'numbers': '本人の数字', 'intro': '現地報道', 'report': '現地の報道',
            'fan': '匿名のファンの感想', 'closing': 'コレスポからの応援'}


@motion.slot('reddit')
def frame(t, seg, narr):
    if narr.get('program')!='reddit_reaction':return _frame(t,seg,narr)
    previous=os.environ.get('COLLESPO_BUBBLE')
    style=previous or 'glass'
    if style not in ('glass','slant'):raise ValueError('この回の吹き出しはglassかslantです')
    os.environ['COLLESPO_BUBBLE']=style
    try:
        im=_frame(t,seg,narr)
        if seg['kind'] in ('fan','fan_reply') and im.info.get('duo_caption',{}).get('rows',0)>2:
            raise ValueError('コメントの字幕が2行を超えます。別のコメントを選んでください')
        return im
    finally:
        if previous is None:os.environ.pop('COLLESPO_BUBBLE',None)
        else:os.environ['COLLESPO_BUBBLE']=previous


def _frame(t, seg, narr):
    im = r3.background(t, narr['player'].get('team_id'))
    r3._header(ImageDraw.Draw(im), narr.get('program_label') or '選手のいまの流れ')
    cards.panel(im, (72, 270, r3.SAFE_RIGHT, 1140))
    cards.text(im, 100, 305, narr['player']['name_jp'], 72, r3.GOLD, width=760)
    cards.text(im, 100, 410, seg['meta'].get('heading') or HEADINGS[seg['kind']], 38, width=760)
    y = 500
    lines, size = r3._lines(ImageDraw.Draw(im), seg['text'], 54, 740, 6, floor=40)
    if ''.join(lines).replace(' ', '') != seg['text'].replace(' ', '').replace('\n', ''):
        raise ValueError('札の文章が欠けています。原稿を短くしてください')
    for line in lines:
        cards.text(im, 104, y, line, size, width=740)
        y += size+20
    meta = seg['meta']; report = meta.get('report') or {}
    if narr.get('program')=='reddit_reaction':
        if meta.get('parent_translation'):
            cards.text(im,100,710,'返信元：'+meta['parent_translation'],30,width=740)
        metrics=[]
        if meta.get('likes') is not None:metrics.append(f"高評価 {meta['likes']:,}")
        if meta.get('replies') is not None:metrics.append(f"返信 {meta['replies']:,}件")
        if metrics:cards.text(im,100,850,'　'.join(metrics),48,r3.GOLD,width=740)
    credit = report.get('author') or meta['source']
    if report.get('author'):
        credit += ' / '+meta['source']
    at = meta.get('display_time') or meta.get('at') or narr['label']
    if not meta.get('display_time') and 'T' in at:
        when = story.stamp(at).astimezone(timezone(timedelta(hours=9)))
        at = f'{when.month}/{when.day} {when:%H:%M} JST'
    for text in (credit, at):
        cards.text(im, 100, 990 if text == credit else 1060, text, 30, r3.GOLD, width=740)
    r3.presenter(im, t)
    import host_split
    r3.ticker(im, t, host_split.credit('音声：VOICEVOX 四国めたん　'+narr['label']+'　'+(narr.get('program_label') or '選手の話題')))
    return im


def render(narr, audio, out):
    __import__('slant_by_episode').set_episode(narr.get('program') or 'player_story')
    if not narr.get('can_make'):
        return None
    if narr.get('program')=='reddit_reaction':
        import reddit_reaction
        reddit_reaction.validate(narr)
    else: story.validate(narr)
    from synthesize_narration import audio_duration
    if len(audio) != len(narr['segments']):
        raise ValueError('音声の数が原稿と違います')
    times = []
    for seg, row in zip(narr['segments'], audio):
        if any(seg[k] != row.get(k) for k in ('kind', 'text', 'speaker', 'meta')):
            raise ValueError('音声と原稿が一致しません')
        path = Path(row.get('file') or '')
        if not path.is_file():
            raise ValueError('実音声がありません')
        actual = audio_duration(path)
        if actual <= 0 or abs(actual-float(row.get('duration') or 0)) > .05:
            raise ValueError('音声の実測尺が不一致です')
        times.append(math.ceil(max(2.5, actual)*24)/24)
    if motion.enabled():
        motion.measured(audio)
        times = [math.ceil(max(t, float(row['duration']) + vc.SEGMENT_TAIL)*24)/24 for t, row in zip(times, audio)]
    if sum(times) > story.RULES['max_story_seconds']:
        raise ValueError('60秒を超えています。原稿を短くしてください')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    track = vc.build_narration_track(audio, times, out)
    if not track:
        raise ValueError('声を結合できませんでした')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fan_events.TRACK.clear()
    rule = story.RULES[narr['direction']]; clock = 0.
    for seg, seconds in zip(narr['segments'], times):
        decision = dict(face=rule['face'], effect=rule['effect'], event=None, highlights=[],
                        evidence=dict(direction=narr['direction']),
                        reason=narr['player']['name_jp']+'・保存材料の流れ='+narr['direction'])
        fan_events.TRACK.append(dict(start=clock, end=clock+seconds, text=seg['text'], speech=seconds, decision=decision))
        clock += seconds
    video = out/'collespo_player_story.mp4'
    cmd = [ffmpeg, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', '24',
           '-i', '-', '-i', str(track), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-t', str(sum(times)), '-movflags', '+faststart', str(video)]
    images = []; clock = 0.; previous=None
    with (out/'ffmpeg.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, seconds) in enumerate(zip(narr['segments'], times)):
                r3.set_caption(seg['text'], seconds, sum(times), speaker=2, duo=False)
                r3.set_program_clock(clock+1.4)
                im = frame(1.4, seg, narr)
                verify_frame(im)
                im.save(out/f'{i+1:02d}.png'); images.append(im.copy())
                for k in range(round(seconds*24)):
                    r3.set_program_clock(clock+k/24)
                    image=frame(k/24, seg, narr).convert('RGB')
                    raw=motion.transition(previous, image, k, 24) if motion.enabled() else image.tobytes()
                    proc.stdin.write(raw)
                previous=image.tobytes();clock += seconds
        finally:
            proc.stdin.close(); code = proc.wait(); r3.set_program_clock(None)
            fan_events.TRACK.clear()
    if code:
        raise ValueError('動画生成に失敗しました。ffmpeg.logを確認してください')
    from preview_unified_v3 import sheet
    sheet(images, [s['kind'] for s in narr['segments']], out/'all-screens.png', columns=3)
    verification = dict(seconds=sum(times), screens=len(images), direction=narr['direction'],
                        audio='実音声の一致と尺を確認', publication='未実施',
                        expression=rule if fan_events.enabled() else '既定の表情')
    (out/'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(verification, ensure_ascii=False))
    return verification


def verify_frame(im):
    for box in im.info.get('v3_layout', []):
        x0, y0, x1, y1 = box['box']
        if x0 < 0 or y0 < 0 or x1 > 1080 or y1 > 1920:
            raise ValueError('文字が画面からはみ出しています: '+box.get('text', ''))
        if box.get('v4_font', 40) < 28:
            raise ValueError('文字が小さすぎます: '+box.get('text', ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--narration', required=True)
    ap.add_argument('--audio-dir', required=True)
    ap.add_argument('--out', default='build/player_story')
    args = ap.parse_args()
    import host_split
    host_split.render_audio(args.audio_dir, args.out, args.narration)
    if os.environ.get('COLLESPO_PLAYER_STORY') != 'on':
        print('選手の話題の回は既定オフです'); return
    narr = story.read(args.narration)
    render(narr, story.read(Path(args.audio_dir)/'manifest.json')['segments'], args.out)
    host_split.bind_video(Path(args.out)/'collespo_player_story.mp4', args.audio_dir)


if __name__ == '__main__':
    main()
