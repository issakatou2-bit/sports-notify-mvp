"""縦のショートで情報、字幕、左右の胸上を分けて描く。"""
from contextvars import ContextVar
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw

import review_render_v3 as r3

CAPTION = (64, 990, 930, 1135)
BODY_BOTTOM = CAPTION[1] - 12
SOURCE_X, SOURCE_RIGHT = 350, 645
SOURCE_TOP, SOURCE_BOTTOM = 1215, 1345
DEFERRED = ContextVar('short_cast_footer', default=None)
BODY_ROLES = {'header', 'source', 'caption', 'ticker', 'face'}


def compact_body(im, background, *, reserve_bottom=0):
    entries = [row for row in im.info.get('v3_layout', []) if row['role'] not in BODY_ROLES]
    if not entries:
        return
    bottom = max(reserve_bottom, max(row['box'][3] for row in entries)) + 4
    if bottom <= BODY_BOTTOM:
        return
    top = max(236, min(row['box'][1] for row in entries) - 4)
    if bottom <= top:
        return
    scale = (BODY_BOTTOM - top) / (bottom - top)
    right = max(r3.SAFE_RIGHT + 2, max(row['box'][2] for row in entries) + 4)
    area = (0, top, right, bottom)
    center = (r3.LEFT + r3.SAFE_RIGHT) / 2
    x0 = round(center * (1 - scale))
    original = im.crop(area)
    ground = background().crop(area)
    channels = ImageChops.difference(original, ground).split()
    difference = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    foreground = difference.point(lambda value: 255 if value > 1 else 0)
    dimensions = (round(right * scale), BODY_BOTTOM - top)
    body = original.resize(dimensions, Image.Resampling.LANCZOS)
    mask = foreground.resize(dimensions, Image.Resampling.LANCZOS)
    im.paste(ground, area[:2])
    im.paste(body, (x0, top), mask)
    adjusted = set()
    for key in ('v3_layout', 'v4_badges'):
        for row in im.info.get(key, ()):
            if id(row) in adjusted or row.get('role') in BODY_ROLES or 'box' not in row:
                continue
            a, b, c, d = row['box']
            if b < top:
                continue
            row['box'] = [round(x0 + a * scale), round(top + (b - top) * scale),
                          round(x0 + c * scale), round(top + (d - top) * scale)]
            adjusted.add(id(row))
    if 'preview_body' in im.info:
        a, b, c, d = im.info['preview_body']
        im.info['preview_body'] = [round(x0 + a * scale), round(top + (b - top) * scale),
                                   round(x0 + c * scale), round(top + (d - top) * scale)]
    im.info['short_cast_body_scale'] = scale


@lru_cache(maxsize=256)
def caption_pages(chunks):
    import bubble_styles
    return tuple(''.join(rows) for chunk in chunks
                 for rows in bubble_styles.page_lines(chunk, CAPTION, size=39, vertical_inset=38))


def caption_at(ctx, elapsed):
    if not ctx.get('text') or ctx.get('hide_caption'):
        return ''
    pages = caption_pages(tuple(ctx.get('caption_units') or r3.caption_chunks(ctx['text'])))
    cursor = max(0, elapsed) / max(.1, ctx['duration']) * sum(map(len, pages))
    for page in pages:
        cursor -= len(page)
        if cursor < 0:
            return page
    return pages[-1] if pages else ''


def caption(im, speaker, elapsed, alpha=1):
    import bubble_styles
    import short_common
    line = caption_at(r3._CAPTION, elapsed)
    # 重複の判定と記録は、字幕がまだ見えない（alpha 0）出始めにも行う（出始めだけ記録が抜けていた）。
    duplicate = bool(line) and short_common.duplicate_caption(im, line)
    if line and alpha > 0 and not duplicate:
        before = im.copy() if alpha < 1 else None
        bubble_styles.draw(im, speaker, line, style='slant', box=CAPTION, seconds=elapsed)
        if before is not None:
            im.paste(Image.blend(before, im, alpha))
    return bool(line and alpha > 0)


def _source_tokens(text):
    """出典の折り返し単位。媒体名の区切り「・」でも折り、英字の媒体名（Sportiva）を途中で切らない。"""
    out, cur = [], ''
    for c in str(text):
        cur += c
        if c in '　、：・' or (c == ' ' and cur.strip()):
            out.append(cur)
            cur = ''
    if cur:
        out.append(cur)
    return out


def source(im, text, color):
    if not text:
        return
    draw = ImageDraw.Draw(im)
    width = SOURCE_RIGHT - SOURCE_X
    letters = ''.join(str(text).split())
    for initial, lines in ((23, 1), (23, 4), (21, 5)):
        rows, size = r3._lines(draw, text, initial, width, lines, 19, tokens=_source_tokens)
        if ''.join(''.join(rows).split()) == letters:
            break
    else:
        raise ValueError('出典が立ち絵の間に収まりません')
    for i, row in enumerate(rows):
        r3._text(draw, (SOURCE_X, SOURCE_TOP + i * (size + 5)), row,
                 font=r3.font(size), fill=color, role='source')


def finish_mlb(im, t, footer):
    import characters
    compact_body(im, lambda: r3.background(t, None))
    im.info['short_cast'] = True
    speaker, elapsed, line, clock = footer['presenter']
    ctx = r3._CAPTION
    characters.corner_busts(im, speaker, line, elapsed, clock, ctx['duration'])
    if footer.get('source'):
        source(im, *footer['source'])
    # この配置では流れる帯を使わない。切替で前の帯が復活するのも防ぐ。
    r3.LAST_TICKER[0] = None
    if not im.info.get('v3_outro'):
        caption(im, speaker, elapsed)
    r3.progress(ImageDraw.Draw(im))
    return im
