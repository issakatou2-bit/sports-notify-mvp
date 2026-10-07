"""枠ごとの材料を、連勝回の既存部品で描く。台本と尺は扱わない。"""
import functools
from PIL import Image, ImageDraw
import review_render_v3 as r3


@functools.lru_cache(maxsize=128)
def item(head, body, width, base, second, reply=False):
    return r3._item_card(head, body, width, base, second, quote_size=38 if reply else 52,
                         attribution_above=str(body).startswith('「'),
                         quote_height=900 if str(body).startswith('「') else None)


def frame(t, spec, rows, label, source_text="", times=None, replies=None):
    """項目は全文を保持し、収まらない並びは次の札の入場に合わせて送る。"""
    base, second, _ = r3.colors(spec.get("team_id"))
    im = r3.background(t, spec.get("team_id"))
    d = ImageDraw.Draw(im)
    r3._header(d, label, spec.get("page"), second)
    heading = spec.get("heading") or spec.get("label") or ""
    lines, size = r3._lines(d, heading, 52, r3.SAFE_RIGHT-r3.LEFT, 2)
    for i, line in enumerate(lines):
        d.text((r3.LEFT, 250+i*(size+10)), line, font=r3.font(size), fill=r3.INK)
    top = 250+len(lines)*(size+10)+44
    width = r3.SAFE_RIGHT-r3.LEFT
    cards = [item(str(h), str(b), width, base, second, bool((replies or [False]*len(rows))[i]))
             for i, (h, b) in enumerate(rows)]
    ats = times if times is not None else [r3.T_CARD0+i*r3.T_CARD_GAP for i in range(len(cards))]
    bottom = 1216  # 右下の立ち絵の上で、札の本文を止める。
    positions, y, offset = [], top, 0
    for card, at in zip(cards, ats):
        positions.append(y)
        if t >= at:
            needed = max(0, y+card.height-bottom)
            offset = max(offset, needed*r3.ease_out((t-at)/r3.SLIDE))
        y += card.height+28
    layer = Image.new("RGBA", (1080, max(1, bottom-top)), (0,0,0,0))
    for card, y, at in zip(cards, positions, ats):
        r3._paste_card(layer, card, r3.LEFT, round(y-top-offset), r3.back_out((t-at)/r3.SLIDE))
    im.paste(layer, (0,top), layer)
    r3.ticker(im, t, (spec.get("v3") or {}).get("ticker"))
    r3.source(d, source_text, second)
    r3.presenter(im,t)
    return im


def cues(rows, times=None):
    result = r3.cues("list", {}, rows, 0, len(rows))
    if times is not None:
        result = [result[0]] + [(at, *cue[1:]) for at, cue in zip(times, result[1:])]
    return result
