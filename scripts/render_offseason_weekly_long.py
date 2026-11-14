"""オフ週刊長編の描画。既存の週まとめ長編の札（soccer_weekly）と v2 の見た目を使い、
新しい札の形は「表」1種類だけ（期限の表。確定・報道の札、冒頭、来週の注目も同じ形）。"""
import argparse
import math
import os
from pathlib import Path
import re
import sys
import wave

import offseason_weekly_long as weekly
import render_soccer_weekly as soccer_render

MIN_SECONDS, MAX_SECONDS = 180, 420   # 目標は4〜6分。前後に1分の余裕を持たせた止めどころ
REPORT = (120, 170, 255)


# ---------------------------------------------------------------- 表の札（v2）
def _wrap(d, text, size, width, atomic=()):
    """氏名・媒体名・数字の塊を途中で切らない。数字は黄で太く描くので、その幅で測る。"""
    import longform_v2 as v2
    terms = sorted({t for t in atomic if t}, key=len, reverse=True)
    pattern = ('(?:'+'|'.join(re.escape(t) for t in terms)+')[、。）」』]?|' if terms else '')+r'[0-9][0-9.,:/%]*[、。）」』]?|.[、。）」』]?'
    lines, line = [], ''
    for token in re.findall(pattern, text):
        if v2.rich_width(d, token, size) > width:
            raise ValueError('表の札に入りません（省略せず停止）: '+token)
        if line and v2.rich_width(d, line+token, size) > width:
            lines.append(line)
            line = ''
        line += token
    if line:
        lines.append(line)
    return lines


def _tag(d, right, mid, row):
    import longform_v2 as v2
    import style_v2 as s2
    text, tone = row['tag'], row.get('tag_tone')
    if tone == 'done':
        box = (right-90, mid-30, right, mid+30)
        d.rectangle(box, outline=s2.GREY, width=3)
        d.text(((box[0]+box[2])//2, mid), text, font=s2.jp(34, 'Black'), fill=s2.GREY, anchor='mm')
    elif tone == 'today':
        box = (right-130, mid-32, right, mid+32)
        d.rectangle(box, fill=s2.ACCENT)
        d.text(((box[0]+box[2])//2, mid), text, font=s2.jp(36, 'Black'), fill=v2.BAR_BG, anchor='mm')
    else:
        days = re.search(r'\d+', text).group()
        d.text((right, mid+22), '日', font=s2.jp(32, 'Bold'), fill=s2.WHITE, anchor='rs')
        x = right-d.textlength('日', font=s2.jp(32, 'Bold'))-8
        d.text((x, mid+26), days, font=s2.num(64), fill=s2.ACCENT, anchor='rs')
        x -= d.textlength(days, font=s2.num(64))+8
        d.text((x, mid+22), 'あと', font=s2.jp(30, 'Bold'), fill=v2.LABEL, anchor='rs')


def _badge(d, x, mid, row):
    import longform_v2 as v2
    import style_v2 as s2
    badge, tone = row['badge'], row.get('tone')
    if tone == 'fact' or tone == 'report':
        color = s2.ACCENT if tone == 'fact' else REPORT
        box = (x, mid-22, x+104, mid+22)
        if tone == 'fact':
            d.rectangle(box, fill=color)
            d.text(((box[0]+box[2])//2, mid), badge, font=s2.jp(26, 'Black'), fill=v2.BAR_BG, anchor='mm')
        else:
            d.rectangle(box, outline=color, width=3)
            d.text(((box[0]+box[2])//2, mid), badge, font=s2.jp(26, 'Black'), fill=color, anchor='mm')
        return 104
    d.text((x+30, mid), badge, font=s2.num(44), fill=v2.LABEL, anchor='mm')
    return 60


def _table(d, v):
    import longform_v2 as v2
    import style_v2 as s2
    x0, y0, x1, y1 = v2.AREA
    v2.heading(d, v['title'], v.get('fixture'))
    rows = v['rows']
    note = v.get('note')
    top, bottom = y0+96, y1-(44 if note else 0)
    gap = 14
    avail = bottom-top
    atomic = v.get('atomic', [])
    text_left = x0+34
    layout = None
    for size in (38, 36, 34, 32, 30, 28):
        heights, wrapped, ok = [], [], True
        for row in rows:
            if row.get('date'):
                heights.append(None)
                wrapped.append(None)
                continue
            left = text_left+((104+26) if row.get('badge') and row.get('tone') in ('fact', 'report') else 90 if row.get('badge') else 0)
            right = x1-34-(0 if not row.get('tag') else 240)
            try:
                lines = _wrap(d, row['text'], size, right-left, atomic)
            except ValueError:
                ok = False
                break
            heights.append(max(84, len(lines)*(size+14)+36))
            wrapped.append((lines, left))
        if not ok:
            continue
        dated = [i for i, h in enumerate(heights) if h is None]
        fixed = sum(h for h in heights if h is not None)
        free = avail-fixed-gap*(len(rows)-1)
        date_h = min(112, free//len(dated)) if dated else 0
        if dated and date_h < 72:
            continue
        if free < 0:
            continue
        layout = (size, [date_h if h is None else h for h in heights], wrapped)
        break
    if not layout:
        raise ValueError('表の札が入りません（省略せず停止）: '+v['title'])
    size, heights, wrapped = layout
    y = top
    for row, h, lines in zip(rows, heights, wrapped):
        box = (x0, y, x1, y+h)
        v2.card(d, box)
        tone = row.get('tone')
        d.rectangle((x0, y, x0+8, y+h), fill=s2.ACCENT if tone == 'fact' else REPORT if tone == 'report' else v2.CARD_LINE)
        mid = y+h//2
        if row.get('date'):
            done = row.get('tag_tone') == 'done'
            d.text((x0+34, mid+20), row['date'], font=s2.num(58), fill=s2.GREY if done else s2.ACCENT, anchor='ls')
            dx = x0+34+d.textlength(row['date'], font=s2.num(58))+22
            d.text((dx, mid+18), row['time'], font=s2.num(32), fill=v2.LABEL, anchor='ls')
            f, _ = v2.fit(d, row['label'], 40, x1-x0-450-250, 'Bold', minimum=26)
            d.text((x0+450, mid), row['label'], font=f, fill=s2.GREY if done else s2.WHITE, anchor='lm')
            _tag(d, x1-34, mid, row)
        else:
            left = lines[1]
            if row.get('badge'):
                _badge(d, text_left, mid, row)
            ty = y+(h-len(lines[0])*(size+14)+14)//2
            for line in lines[0]:
                v2.rich(d, left, ty, line, size)
                ty += size+14
            if row.get('tag'):
                _tag(d, x1-34, mid, row)
        y += h+gap
    if note:
        f, _ = v2.fit(d, note, 26, x1-x0, 'Medium', minimum=20)
        d.text((x0, y1-6), note, font=f, fill=s2.GREY, anchor='ls')


def install(doc=None):
    import longform_v2 as v2
    soccer_render.install(doc)
    v2.LAYOUTS['table'] = _table


def preflight(doc):
    """札が入るかを全部事前に確かめる。v2の表と、v2を使わない時の旧い札の両方。"""
    import longform_v2 as v2
    install(doc)
    for panel in doc['panels'].values():
        v2.content(panel)
    soccer_render.preflight(doc)


def prepare(doc):
    weekly.validate_document(doc)
    install(doc)
    preflight(doc)


def frames(doc, directory, keys=None):
    """静止画の見本。既定は冒頭・期限の表・選手1人の札。"""
    prepare(doc)
    import longform_render_v3 as v3
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    keys = keys or ['opening', 'deadlines', 'p0_f0']
    total = max(1, len(keys)-1)
    for index, key in enumerate([k for k in keys if k in doc['panels']]):
        seg = next(s for s in doc['segments'] if s.get('panel') == key and s['kind'] == 'talk')
        page = v3.paginate([seg])[0]
        image = v3.render_line(8, page, topic=doc['top'], panel=doc['panels'][key], panel_t=8,
                               chapters=doc['chapters'], chapter_t=8, progress=index/total, dur=10)
        image.save(directory/(key+'.png'))
    return directory


def audio_duration(doc, manifest):
    """速める・切る・空白を足して長さを合わせない。"""
    import video_common
    rows = manifest['segments']
    if len(rows) != len(doc['segments']):
        raise ValueError('台本と音声の行数が一致しません')
    total = 0
    for row, seg in zip(rows, doc['segments']):
        duration = float(row.get('duration') or 0)
        if (row.get('text') != seg['text'] or row.get('speaker') != seg['speaker'] or not row.get('file')
                or not Path(row['file']).is_file() or not math.isfinite(duration) or duration <= 0):
            raise ValueError('台本と音声が一致しないか、一部の声がありません')
        try:
            with wave.open(str(row['file']), 'rb') as audio:
                measured = audio.getnframes()/audio.getframerate()
        except (OSError, EOFError, wave.Error) as error:
            raise ValueError('実音声を測れません') from error
        if abs(measured-duration) > .02:
            raise ValueError('音声manifestと実際のWAVの長さが一致しません')
        row['duration'] = measured
        row['chapter'] = seg.get('chapter')
        total += max(1.6, measured+video_common.SEGMENT_TAIL)
    if not MIN_SECONDS <= total <= MAX_SECONDS:
        raise ValueError(f'実音声は{total:.1f}秒です。{MIN_SECONDS}〜{MAX_SECONDS}秒に収まるよう見直してください')
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dialogue', required=True, type=Path)
    ap.add_argument('--frames', type=Path)
    ap.add_argument('--check', action='store_true')
    args, rest = ap.parse_known_args()
    doc = weekly.load(args.dialogue)
    prepare(doc)
    if args.frames:
        frames(doc, args.frames)
        return 0
    if args.check:
        return 0
    if '--require-audio' not in rest:
        raise ValueError('長編の動画は--require-audioが必要です')
    audio_dir = Path(rest[rest.index('--audio-dir')+1]) if '--audio-dir' in rest else Path('build/lf/audio')
    manifest = weekly.load(audio_dir/'manifest.json')
    audio_duration(doc, manifest)
    weekly.save(audio_dir/'manifest.json', manifest)
    import generate_longform
    os.environ['COLLESPO_LONGFORM_STYLE'] = 'v3'
    sys.argv = [sys.argv[0], '--dialogue', str(args.dialogue), *rest]
    result = generate_longform.main()
    if result == 0:
        out_dir = Path(rest[rest.index('--out')+1]) if '--out' in rest else Path('build/lf')
        weekly.save(out_dir/'metadata.json', weekly.metadata(doc, out_dir/'render_timeline.json'))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
