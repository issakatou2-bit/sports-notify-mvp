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
CTA = '高評価・チャンネル登録で応援を'


def credit(doc, panel=None):
    """画面の出典。試合後の声は記事の媒体を先に出す（ESPN は試合結果だけ）。"""
    if doc.get('program') == topics.MLB_PROGRAM:
        voice = '音声: VOICEVOX:ずんだもん・四国めたん'
        if panel is None:
            return voice
        return voice + '　出典: ' + doc['followup_material']['items'][panel]['source_names']
    if doc.get('credit'):
        return doc['credit']  # 欧州の注目試合（soccer_stake）は台本が出典を持つ。
    names = []
    if topics.is_reactions(doc.get('topic')):
        names += [q['source'].replace('／', '・') for q in doc['reaction_material']['quotes']]
        names += [f['source_names'] for f in doc['reaction_material'].get('facts', []) if f.get('source_names')]
    if doc.get('topic_reaction'):
        names += [q['source'].replace('／', '・') for q in doc['topic_reaction']['quotes']]
    if topics.is_followup(doc.get('topic')):
        # その後の話題は試合の数字を使わないので ESPN を出さない。
        names = [f['source_names'] for f in doc['followup_material']['items']]
        return '音声: VOICEVOX:ずんだもん・四国めたん　出典: ' + '・'.join(dict.fromkeys(n for part in names for n in part.split('・')))
    if not names:
        return CREDIT
    media = '・'.join(dict.fromkeys(n for part in names for n in part.split('・')))
    return f'音声: VOICEVOX:ずんだもん・四国めたん　出典: {media}・ESPN'


def clubs_for(doc):
    if doc.get('program') == topics.MLB_PROGRAM:
        return {}
    if doc.get('clubs'):
        return doc['clubs']
    c = doc['topic_summary']['header']['competitions'][0]
    names = {}
    for t in c['competitors']:
        name = '日本' if str(t['id']) == national.JAPAN else national.team_name(t['team']['displayName'])
        names[name] = t['team'].get('abbreviation') or '?'
    return {n: dict(team_en=n, name_jp=n, abbr=a, primary=None, secondary=None, league='親善試合') for n, a in names.items()}


def opening_frames(segments, first_frames):
    if not segments[0]['meta'].get('hook'):
        return 0
    return max(first_frames, math.ceil(topics.OPENING_SECONDS * FPS))


def topic_transition_cues(segments, frame_counts, hook_end):
    """話者の区間から、実際に表示する札の区間を作る。"""
    core = topics.core_panel(segments)
    screens = [dict(meta=dict(screen='hook'))] if hook_end else []
    lengths = [hook_end / FPS] if hook_end else []
    start = 0
    for seg, count in zip(segments, frame_counts):
        end = start + count
        visible = end - max(start, hook_end)
        start = end
        if visible <= 0:
            continue
        panel = seg['meta'].get('panel')
        screen = seg['kind'] if panel is None else panel
        screens.append(dict(meta=dict(screen=screen, core=core is not None and panel == core)))
        lengths.append(visible / FPS)
    return short_common.transition_cues(screens, lengths, core_only=True)


def frame(t, seg, doc, clubs, index=0, count=1, *, opening_hook=None):
    """index 番目の区間の時刻 t の絵。問い（ずんだもん）と答え（めたん）の組は同じ画面。"""
    if seg['kind'] == 'outro':
        import review_render_v3 as r3
        return r3.outro(t, credit=credit(doc), cta=CTA)
    import soccer_readable as readable
    import soccer_v5_cards as cards

    class TopicScreen(readable.Screen):
        def __init__(self, clubs, t, shift=0.0):
            self.clubs, self.t, self.shift = clubs, t + shift, shift

        def _slide_v2(self, body_only, duration, enter=True, leave=True):
            # 答えの区間は行を出し切った状態にするため時刻を進めている。抜ける時刻は区間の本当の終わりで測る
            # （進めた分だけ早く消えていた。Argon 11/15「話し終わる約1秒前に枠が消える」）。
            return super()._slide_v2(body_only, duration + self.shift if duration else duration, enter, leave)

        def lines(self, x, y, value, size=44, width=800, color=None, role='text'):
            # 数字は日本語より1.12倍の字で背が高い。数字を含む複数行は行の間を広げる
            # （11/15 引用「見事な2点で」の行が次の行に2px重なり描画が止まった）。
            rows = cards.lines(value, size, width)
            step = size + (20 if len(rows) > 1 and any(ch.isdigit() for ch in str(value)) else 12)
            for i, row in enumerate(rows):
                self.text(x, y + i * step, row, size, width, color, role=role)
            return y + len(rows) * step

        def text(self, x, y, value, size=44, width=800, color=None, number=False, role='text'):
            # 国名「日本」をクラブの言及と取り違えない（代表番組と同じ）。
            if role == 'text' and (value == '日本時間' or any(name in value for name in clubs)):
                role = 'national_fact'
            return super().text(x, y, value, size, width, color, number, role)

    meta = seg['meta']
    asking = seg['speaker'] == ZUNDA
    # 答えの区間は同じ画面の続き。入場の動きを繰り返さない。
    s = TopicScreen(clubs, t, 0.0 if asking else 1.0)
    hook = opening_hook or meta.get('hook')
    label = doc.get('screen_title') or '日本代表'
    s.im = cards.canvas(0 if hook else s.t, clubs, label)
    if doc.get('program') == topics.MLB_PROGRAM:
        import short_v4_cards
        short_v4_cards.pinstripe_badge(s.im, cards.L + 400, 163, doc['team_id'], 108, 54)
    s.im.info.update(soccer_readable=True, semantic_items=[], readable_motion='v2 右から0.28秒・説明中停止・左へ0.14秒')
    spec = dict(source=credit(doc, meta.get('panel')), title=label, presenter='zundamon' if asking else 'metan',
                cast=('zundamon', 'metan'), slide_in=asking, slide_out=not asking)
    if hook:
        spec.update(slide_in=False, slide_out=False)
        return hook_screen(s, hook, spec)
    if doc.get('program') == topics.MLB_PROGRAM:
        sub = '移籍報道'
    elif meta.get('sub'):
        sub = meta['sub']
    else:
        other = next(n for n in clubs if n != '日本')
        sub = f'日本対{other}' + ('' if meta.get('topic') == 'rematch' else '　親善試合')
    rows = [tuple(r) for r in meta['rows']]
    if doc.get('program') == topics.MLB_PROGRAM:
        rows = [row for row in rows if row[0] != '出典']
    # その後の話題も値を釣り合いよく折る（Argon 11/15「ヴォルフスブル／ク」の1字だけの改行）。
    if topics.is_reactions(meta.get('topic')) or meta.get('quote') or topics.is_followup(meta.get('topic')):
        if topics.is_reactions(meta.get('topic')):
            sub = f'日本対{other}　試合後'
    if topics.is_followup(meta.get('topic')):
        if doc.get('program') != topics.MLB_PROGRAM:
            sub = '日本代表　その後'
        size = 72 if len(rows) == 1 else 64
        rows = [(label, chr(10).join(balanced_lines(value, size, readable.R - readable.L - 56))) for label, value in rows]

    if topics.is_followup(meta.get('topic')) and meta.get('big'):
        facts = [tuple(r) for r in meta['rows']]
        # MLB は出典の行を外すだけ。折り返しは big_fact_screen で1回（2回折ると改行を測って Linux の raqm が落ちる）。
        if doc.get('program') == topics.MLB_PROGRAM:
            facts = [row for row in facts if row[0] != '出典']
        return big_fact_screen(s, meta['head'], meta['big'], facts, spec, sub)
    if meta.get('compare'):
        cmp = meta['compare']
        return s.national_compare(meta['head'], cmp['rows'], cmp['teams'], spec, sub)
    return s.national_facts(meta['head'], rows, spec, sub)


LOSS = (255, 112, 112)


def hook_screen(s, hook, spec):
    """題の中心の数字と結果を、最初のコマから静止した札で見せる。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    from PIL import ImageDraw
    win = hook['result'] == '勝利'
    accent = cards.LIME if win else LOSS if hook['result'] == '敗戦' else cards.CHALK
    s.text(readable.L, 260, hook['score'], 52, 560, role='national_fact')
    # 結果の札（勝ち＝黄、負け＝赤、引き分け＝白）
    chip = cards.measure(hook['result'], 40)[1] + 48
    d = ImageDraw.Draw(s.im)
    d.rounded_rectangle((readable.R - chip, 254, readable.R, 322), radius=10, fill=accent)
    cards.rec(s.im, 'card', (readable.R - chip, 254, readable.R, 322))
    s.text(readable.R - chip + 24, 266, hook['result'], 40, chip, cards.DARK if win or hook['result'] != '敗戦' else (40, 8, 8), role='supplement')
    big, unit = str(hook['big']), hook['unit']
    numeral = big.isascii()
    for size in (300, 260, 220, 180, 150, 120):
        bw = cards.measure(big, size, numeral)[1]
        uw = cards.measure(unit, 72)[1]
        if bw + 24 + uw <= 800:
            break
    # 中身の高さに合わせた箱を、本文の領域の真ん中に置く（下が空いた箱にしない）。
    subject_h = len(cards.lines(hook['subject'], 68, 800)) * 80
    b = cards.measure(big, size, numeral)[2]
    big_h = b[3] - b[1]
    note_h = len(cards.lines(hook['note'], 48, 800)) * 60 + 48 if hook.get('note') else 0
    height = 56 + subject_h + 40 + big_h + note_h + 56
    top = readable.BODY_TOP + (readable.BODY_BOTTOM - readable.BODY_TOP - height) // 2
    s.panel(top, top + height)
    y = s.lines(100, top + 56, hook['subject'], 68, 800, role='national_fact')
    box = s.text(100, y + 40, big, size, 800, accent, numeral, role='national_fact')
    s.text(box[2] + 24, box[3] - 84, unit, 72, 800 - (box[2] - 100) - 24, accent, role='national_fact')
    if hook.get('note'):
        s.lines(100, box[3] + 48, hook['note'], 48, 800, cards.MUTED, 'supplement')
    s.im.info['preview_body'] = [readable.L, top, readable.R, top + height]
    s.im.info['opening_hook'] = hook
    s.im.info['timeline_scene'] = '冒頭の札'
    return s.finish(spec)


def big_fact_screen(s, head, big, rows, spec, sub):
    """その後の話題の答え。要の数字1つを大きく、残りの行は小さく（Argon 11/15「字が均一で主役の数字が分からない」）。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    s.title(head, sub)
    value, unit = str(big['value']), big['unit']
    numeral = value.isascii()
    rsize, width = 44, readable.R - readable.L - 56
    rows = [(label, chr(10).join(balanced_lines(v, rsize, width))) for label, v in rows]
    heights = [70 + len(cards.lines(v, rsize, width)) * (rsize + 12) for _, v in rows]
    gap = 14
    for size in (240, 210, 180, 150, 120):
        _, advance, box = cards.measure(value, size, numeral)
        big_height = 100 + box[3] - box[1]
        height = big_height + sum(h + gap for h in heights)
        if advance + 24 + cards.measure(unit, 64)[1] <= 800 and height <= readable.BODY_BOTTOM - readable.BODY_TOP:
            break
    if height > readable.BODY_BOTTOM - readable.BODY_TOP:
        raise ValueError('要の数字の画面に行が入りません')
    top = readable.BODY_TOP + (readable.BODY_BOTTOM - readable.BODY_TOP - height) // 2
    s.panel(top, top + big_height)
    s.text(100, top + 18, big['label'], 30, 800, cards.MUTED, role='supplement')
    box = s.text(100, top + 66, value, size, 800, cards.LIME, numeral, role='national_fact')
    if unit:
        ub = cards.measure(unit, 64)[2]
        s.text(box[2] + 24, box[3] - (ub[3] - ub[1]), unit, 64, 800 - (box[2] - 100) - 24, cards.LIME, role='national_fact')
    y = top + big_height + gap
    for (label, v), h in zip(rows, heights):
        s.panel(y, y + h)
        s.text(100, y + 18, label, 30, 800, cards.MUTED, role='supplement')
        s.lines(100, y + 56, v, rsize, 800, role='national_fact')
        y += h + gap
    s.im.info['preview_body'] = [readable.L, top, readable.R, y - gap]
    return s.finish(spec)


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
    segments = narr['segments']
    frame_counts = [math.ceil(t * FPS) for t in common.durations(segments, audio)]
    times = [count / FPS for count in frame_counts]
    limit = topics.MLB_LIMIT if narr.get('program') == topics.MLB_PROGRAM else topics.LIMIT
    if sum(times) > limit:
        raise ValueError(f'{limit}秒を超えます: {sum(times):.2f}秒')
    short_content.require(narr, times, out, None, maximum=limit, video_name=VIDEO)
    track = vc.build_narration_track(audio, times, out)
    if not track:
        raise ValueError('実音声なし')
    hook_end = opening_frames(segments, frame_counts[0])
    cues = topic_transition_cues(segments, frame_counts, hook_end)
    track = short_common.add_audio(track, audio, times, out, cues=cues)
    clubs = clubs_for(narr); video = out / VIDEO; clock = 0; layouts = []
    timeline = render_timeline.Recorder(FPS, audio, narr)
    hook = segments[0]['meta'].get('hook')
    command = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', str(FPS), '-i', '-',
               '-i', str(track), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
               '-t', str(sum(times)), '-movflags', '+faststart', str(video)]
    with (out / 'ffmpeg.log').open('w', encoding='utf8') as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, duration, count) in enumerate(zip(segments, times, frame_counts)):
                timeline.select(audio[i], i)
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'], duration, sum(times), speaker=seg['speaker'], duo=False, hide_caption=seg['kind'] == 'outro')
                seen = set()
                for k in range(count):
                    t = k / FPS
                    r3.set_program_clock(clock + t)
                    showing_hook = round(clock * FPS) + k < hook_end
                    im = frame(t, seg, narr, clubs, i, len(times), opening_hook=hook if showing_hook else None)
                    signature = json.dumps([showing_hook, im.info.get('bubble_style', {}).get('lines'),
                                            (im.info.get('v2_slide') or {}).get('phase')], ensure_ascii=False)
                    if (showing_hook or t >= .35) and signature not in seen:
                        seen.add(signature)
                        if seg['kind'] != 'outro':
                            errors = validate_frame(im, clubs, narr)
                            layouts.append(dict(scene=i, frame=k, errors=errors, layout=im.info.get('v3_layout'), lines=im.info.get('bubble_style', {}).get('lines')))
                            national.save(out / 'layout_checks.json', layouts)
                            if errors:
                                raise ValueError(f'画面{i}: {errors}')
                    if k == min(42, count - 1):
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
