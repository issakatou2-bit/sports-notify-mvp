"""既存の長尺v3に週まとめの札を登録。この実行だけに適用する。"""
import argparse
from pathlib import Path
import re
import sys

import soccer_weekly_long as weekly


def wrap_row(d, text, font, width, atomic=()):
    """氏名・クラブ名・指定語を途中で切らない。同じ書体で実測する。"""
    protected = {'先発', '途中出場', '出場なし', 'けがで離脱中', '復帰見込み', 'ホーム', 'アウェー'}
    protected.update(s for s in atomic if s)
    protected.update(re.findall(r'(?:枠内シュート|シュート|セーブ)\d+本|(?:警告|退場)\d+回|約?\d+分出場|\d+(?:得点|アシスト)|\d+月\d+日', str(text)))
    terms = sorted(protected, key=len, reverse=True)
    pattern = '(?:'+'|'.join(re.escape(s) for s in terms)+r')[、。）」』]?|.'
    lines = []
    for paragraph in str(text).split('\n'):
        line = ''
        for token in re.findall(pattern, paragraph):
            if d.textlength(token, font=font) > width:
                raise ValueError('氏名・クラブ名が札の幅に入りません')
            if line and d.textlength(line+token, font=font) > width:
                lines.append(line.rstrip())
                line = ''
            line += token if line else token.lstrip()
        lines.append(line.rstrip())
    return lines


def draw_panel(layer, d, panel, pt, ctx):
    import longform_render_v3 as v3
    rows = panel.get('rows') or []
    heading = panel['heading']
    atomic = panel.get('atomic', [])
    heading_lines = wrap_row(d, heading, v3.font(40), v3.INNER_W, atomic)
    y = 36
    for line in heading_lines:
        d.text((v3.CARD_PAD, y), line, font=v3.font(40), fill=v3.GOLD)
        y += 54
    y += 16
    columns = 2 if len(rows) > 8 else 1
    width = (v3.INNER_W-32*(columns-1))//columns
    per_column = (len(rows)+columns-1)//columns
    max_y = v3.CARD_BOTTOM-v3.CARD_Y-32
    for size in (36, 34, 32, 30, 28):
        columns_lines = []
        try:
            for col in range(columns):
                group = rows[col*per_column:(col+1)*per_column]
                lines = [wrap_row(d, row, v3.font(size), width, atomic) for row in group]
                columns_lines.append(lines)
        except ValueError:
            continue
        if all(y+sum(len(row)*(size+10)+14 for row in col) <= max_y for col in columns_lines):
            break
    else:
        raise ValueError('週まとめの札が入りません（省略せず停止）')
    bottom = y
    for col, lines in enumerate(columns_lines):
        yy = y
        x = v3.CARD_PAD+col*(width+32)
        for row in lines:
            for line in row:
                d.text((x, yy), line, font=v3.font(size), fill=v3.INK)
                yy += size+10
            d.line((x, yy+4, x+width, yy+4), fill=(255, 255, 255, 40), width=2)
            yy += 14
        bottom = max(bottom, yy)
    return bottom


def install(doc=None):
    import longform_render_v3 as v3
    v3.PANELS['soccer_weekly'] = draw_panel
    if doc:
        atomic = [term for panel in doc['panels'].values() for term in panel.get('atomic', [])]
        # 同じ改行規則をこの動画の字幕にも使う。既存制作器のファイルは変更しない。
        v3.wrap = lambda d, text, font, width: wrap_row(d, text, font, width, atomic)


def preflight(doc):
    from PIL import Image, ImageDraw
    import longform_render_v3 as v3
    for panel in doc['panels'].values():
        image = Image.new('RGBA', (v3.CARD_W, v3.CARD_BOTTOM-v3.CARD_Y))
        draw_panel(image, ImageDraw.Draw(image), panel, 8, {})


def frames(doc, directory):
    import longform_render_v3 as v3
    install(doc)
    weekly.validate_document(doc)
    preflight(doc)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    candidates = ['opening']
    candidates += [k for k in doc['panels'] if k.startswith('game_')][:1]
    candidates += [k for k, p in doc['panels'].items() if k.startswith('game_') and len(p['rows']) > 3][:1]
    candidates += ['league_PD', 'absent']
    candidates += [k for k in doc['panels'] if k.startswith('ranks_')][:1]
    for key in candidates:
        if key not in doc['panels']:
            continue
        seg = next(s for s in doc['segments'] if s.get('panel') == key and s['kind'] == 'talk')
        page = v3.paginate([seg])[0]
        image = v3.render_line(8, page, topic=doc['top'], panel=doc['panels'][key],
                               panel_t=8, chapters=doc['chapters'], chapter_t=8, progress=.3, dur=10)
        image.save(directory/(key+'.png'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames', type=Path)
    ap.add_argument('--dialogue', required=True)
    args, rest = ap.parse_known_args()
    doc = weekly.load(args.dialogue)
    weekly.validate_document(doc)
    if not doc['soccer_weekly_material']['can_make']:
        print(doc['soccer_weekly_material']['reason'])
        return 0
    install(doc)
    preflight(doc)
    if args.frames:
        frames(doc, args.frames)
        return 0
    import os
    import generate_longform
    os.environ['COLLESPO_LONGFORM_STYLE'] = 'v3'
    # 共通合成器のmanifestへ章の指定を戻す。音声と台本の不一致・一部欠落は停止。
    if '--require-audio' in rest:
        audio_dir = Path(rest[rest.index('--audio-dir')+1]) if '--audio-dir' in rest else Path('build/lf/audio')
        manifest = weekly.load(audio_dir/'manifest.json')
        rows = manifest['segments']
        if len(rows) != len(doc['segments']):
            raise ValueError('台本と音声の行数が一致しません')
        for seg, source in zip(rows, doc['segments']):
            if (seg.get('text') != source['text'] or seg.get('speaker') != source['speaker']
                    or not seg.get('file') or not Path(seg['file']).is_file() or not seg.get('duration')):
                raise ValueError('台本と音声が一致しないか、一部の音声がありません')
            seg['chapter'] = source.get('chapter')
        weekly.save(audio_dir/'manifest.json', manifest)
    sys.argv = [sys.argv[0], '--dialogue', args.dialogue, *rest]
    result = generate_longform.main()
    if result == 0:
        out_dir = Path(rest[rest.index('--out')+1]) if '--out' in rest else Path('build/lf')
        weekly.save(out_dir/'metadata.json', weekly.metadata(doc, out_dir/'render_timeline.json'))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
