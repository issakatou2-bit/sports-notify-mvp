"""代表戦の話題ショートを、新しい見た目（v2）・v6 focus・実音声で制作する。

ずんだもん（問い）は左下、めたん（答え）は右下に小さな胸上。真ん中の情報は問いの区間で右から入り、
答えの区間の終わりに左へ抜ける（同じ画面の間は動かさない）。画面の数字は原稿と同じ材料の数字だけ。
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import wave

import short_common
import soccer_national as national
import soccer_national_topics as topics
from duo import ZUNDA, METAN

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
VIDEO = topics.VIDEO
CREDIT = '音声: VOICEVOX:ずんだもん・四国めたん　出典: ESPN'


def credit(doc):
    """画面の出典。試合後の声は記事の媒体を先に出す（ESPN は試合結果だけ）。"""
    if doc.get('topic') != 'reactions':
        return CREDIT
    names = [q['source'].replace('／', '・') for q in doc['reaction_material']['quotes']]
    names += [f['source_names'] for f in doc['reaction_material'].get('facts', []) if f.get('source_names')]
    media = '・'.join(dict.fromkeys(n for part in names for n in part.split('・')))
    return f'音声: VOICEVOX:ずんだもん・四国めたん　出典: {media}・ESPN'


def clubs_for(doc):
    c = doc['topic_summary']['header']['competitions'][0]
    names = {}
    for t in c['competitors']:
        name = '日本' if str(t['id']) == national.JAPAN else national.team_name(t['team']['displayName'])
        names[name] = t['team'].get('abbreviation') or '?'
    return {n: dict(team_en=n, name_jp=n, abbr=a, primary=None, secondary=None, league='親善試合') for n, a in names.items()}


def frame(t, seg, doc, clubs, index=0, count=1):
    """index 番目の区間の時刻 t の絵。問い（ずんだもん）と答え（めたん）の組は同じ画面。"""
    if seg['kind'] == 'outro':
        import review_render_v3 as r3
        return r3.outro(t, credit=credit(doc))
    import soccer_readable as readable
    import soccer_v5_cards as cards

    class TopicScreen(readable.Screen):
        def __init__(self, clubs, t, shift=0.0):
            self.clubs, self.t, self.shift = clubs, t + shift, shift

        def _slide_v2(self, body_only, duration, enter=True, leave=True):
            # 答えの区間は行を出し切った状態にするため時刻を進めている。抜ける時刻は区間の本当の終わりで測る
            # （進めた分だけ早く消えていた。Argon 11/15「話し終わる約1秒前に枠が消える」）。
            return super()._slide_v2(body_only, duration + self.shift if duration else duration, enter, leave)

        def text(self, x, y, value, size=44, width=800, color=None, number=False, role='text'):
            # 国名「日本」をクラブの言及と取り違えない（代表番組と同じ）。
            if role == 'text' and (value == '日本時間' or any(name in value for name in clubs)):
                role = 'national_fact'
            return super().text(x, y, value, size, width, color, number, role)

    meta = seg['meta']
    asking = seg['speaker'] == ZUNDA
    # 答えの区間は同じ画面の続き。入場の動きを繰り返さない。
    s = TopicScreen(clubs, t, 0.0 if asking else 1.0)
    s.im = cards.canvas(s.t, clubs, '日本代表')
    s.im.info.update(soccer_readable=True, semantic_items=[], readable_motion='v2 右から0.28秒・説明中停止・左へ0.14秒')
    spec = dict(source=credit(doc), title='日本代表', presenter='zundamon' if asking else 'metan',
                slide_in=asking, slide_out=not asking)
    other = next(n for n in clubs if n != '日本')
    sub = f'日本対{other}' + ('' if meta.get('topic') == 'rematch' else '　親善試合')
    rows = [tuple(r) for r in meta['rows']]
    if meta.get('topic') == 'reactions':
        sub = f'日本対{other}　試合後'
        size = 72 if len(rows) == 1 else 64
        rows = [(label, chr(10).join(balanced_lines(value, size, readable.R - readable.L - 56))) for label, value in rows]

    if meta.get('compare'):
        cmp = meta['compare']
        return s.national_compare(meta['head'], cmp['rows'], cmp['teams'], spec, sub)
    return s.national_facts(meta['head'], rows, spec, sub)


NO_START = '、。，．」』）】!?！？ーぁぃぅぇぉっゃゅょ'


def kinsoku_lines(value, size, width):
    """行頭に句読点・閉じ括弧・小書きを置かない折り返し（前の行の最後の字を送る）。"""
    import soccer_v5_cards as cards
    out, current = [], ''
    for ch in str(value):
        if current and cards.measure(current + ch, size)[1] > width:
            if ch in NO_START and len(current) > 1:
                out.append(current[:-1]); current = current[-1]
            else:
                out.append(current); current = ''
        current += ch
    if current:
        out.append(current)
    return out


def balanced_lines(value, size, width):
    """同じ行数のまま、いちばん狭い幅で折り返して行の長さを揃える（最後の行に1〜2字だけ残さない）。"""
    count = len(kinsoku_lines(value, size, width))
    for w in range(width // 2, width + 1, 8):
        out = kinsoku_lines(value, size, w)
        if len(out) == count:
            return out
    return kinsoku_lines(value, size, width)


def allowed_numbers(doc):
    pool = json.dumps([doc['title'], [s['text'] for s in doc['segments']], [s['meta'] for s in doc['segments']]], ensure_ascii=False)
    return {float(v) for v in re.findall(r'\d+(?:\.\d+)?', pool)}


def validate_frame(im, clubs, doc):
    import soccer_readable
    import soccer_v4_cards
    errors = soccer_readable.check_frame(im, clubs)
    allowed = allowed_numbers(doc)
    drawn = {v for v in soccer_v4_cards.drawn_numbers(im)}
    drawn |= {v for e in im.info.get('v3_layout', []) if e['role'] == 'national_fact'
              for v in re.findall(r'\d+(?:\.\d+)?', str(e['text']))}
    extra = {v for v in drawn if float(v) not in allowed}
    if extra:
        errors.append(dict(numbers_missing_from_material=sorted(extra)))
    return errors


def silent_audio(narr, out, rate=24000):
    """声が無い環境の見本用。原稿の文字数から長さを決めた小さな音を、実音声の記録と同じ形で作る（公開には使えない）。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, seg in enumerate(narr['segments']):
        seconds = 1.4 if seg['kind'] == 'outro' else len(seg['text']) / 7.5 + .4
        path = out / f'{i:03d}.wav'
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            # 完全な無音は音声結合が止めるので、小さな低い音を入れる（見本専用）。
            w.writeframes(b''.join(struct.pack('<h', round(2500 * math.sin(2 * math.pi * 220 * j / rate)))
                                   for j in range(round(seconds * rate))))
        rows.append(dict(text=seg['text'], speaker=seg['speaker'], kind=seg['kind'], meta=seg['meta'],
                         file=str(path), duration=round(seconds, 3)))
    national.save(out / 'manifest.json', dict(segments=rows, silent_sample=True))
    return rows


def render(narr, audio, out, *, sample=False):
    import soccer_results_render as common
    import soccer_look
    import short_content
    import review_render_v3 as r3
    import video_common as vc
    import render_timeline
    import voice_manifest
    if topics.check(narr):
        raise ValueError('原稿と材料が一致しません')
    if not soccer_look.readable() or not soccer_look.focus():
        raise ValueError('話題ショートはv6 focusだけを使います')
    if os.environ.get('COLLESPO_STYLE') != 'v2':
        raise ValueError('話題ショートは新しい見た目 COLLESPO_STYLE=v2 だけを使います')
    out = Path(out); out.mkdir(parents=True, exist_ok=True); common.ensure_ffmpeg(out)
    times = common.durations(narr['segments'], audio)
    times = [math.ceil(t * FPS) / FPS for t in times]
    if sum(times) > topics.LIMIT:
        raise ValueError(f'{topics.LIMIT}秒を超えます: {sum(times):.2f}秒')
    short_content.require(narr, times, out, None, maximum=topics.LIMIT, video_name=VIDEO)
    track = vc.build_narration_track(audio, times, out)
    if not track:
        raise ValueError('実音声なし')
    track = short_common.add_audio(track, audio, times, out)
    clubs = clubs_for(narr); video = out / VIDEO; clock = 0; layouts = []
    timeline = render_timeline.Recorder(FPS, audio, narr)
    command = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', str(FPS), '-i', '-',
               '-i', str(track), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
               '-t', str(sum(times)), '-movflags', '+faststart', str(video)]
    with (out / 'ffmpeg.log').open('w', encoding='utf8') as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, duration) in enumerate(zip(narr['segments'], times)):
                timeline.select(audio[i], i)
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'], duration, sum(times), speaker=seg['speaker'], duo=False, hide_caption=seg['kind'] == 'outro')
                seen = set()
                for k in range(round(duration * FPS)):
                    t = k / FPS; r3.set_program_clock(clock + t); im = frame(t, seg, narr, clubs, i, len(times))
                    signature = json.dumps([im.info.get('bubble_style', {}).get('lines'), (im.info.get('v2_slide') or {}).get('phase')], ensure_ascii=False)
                    if t >= .35 and signature not in seen:
                        seen.add(signature)
                        if seg['kind'] != 'outro':
                            errors = validate_frame(im, clubs, narr)
                            layouts.append(dict(scene=i, frame=k, errors=errors, layout=im.info.get('v3_layout'), lines=im.info.get('bubble_style', {}).get('lines')))
                            national.save(out / 'layout_checks.json', layouts)
                            if errors:
                                raise ValueError(f'画面{i}: {errors}')
                    if k == min(42, round(duration * FPS) - 1):
                        im.save(out / f'{i + 1:02d}.png')
                    timeline.write(proc.stdin, im.tobytes(), im)
                clock += duration
        finally:
            proc.stdin.close(); code = proc.wait(); r3.set_program_clock(None)
    if code:
        raise ValueError('ffmpegの制作に失敗')
    timeline.save(video, Path(audio[0]['file']).parent)
    report = short_content.validate_upload(video)
    if not sample:
        voice_manifest.save(Path(audio[0]['file']).parent, audio, narr)
    national.save(out / 'verification.json', dict(seconds=report['actual_seconds'], information=report['information_count'],
        scenes=len(times), layout_states=len(layouts), voice_seconds=sum(a['duration'] for a in audio),
        silent_sample=sample, publication='not performed'))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/soccer_national_topics')
    ap.add_argument('--silent-sample', action='store_true', help='声が無い環境の見本（無音）。公開には使えない')
    args = ap.parse_args()
    os.environ.update(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SOCCER_FOCUS='on', COLLESPO_SHORT_LOOK='v4')
    narr = national.read(args.out / 'narration.json')
    if args.silent_sample:
        audio = silent_audio(narr, args.out / 'audio')
    else:
        audio = national.read(args.out / 'audio/manifest.json')['segments']
    render(narr, audio, args.out, sample=args.silent_sample)


if __name__ == '__main__':
    main()
