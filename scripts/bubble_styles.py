"""Opt-in caption designs. Shared glass renderer is vendored without changes."""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import liquid_glass
import review_render_v3 as r3

WHITE = (255, 255, 255)
GOLD = (255, 210, 90)
SHADOW = (15, 18, 24)


def luminance(rgb):
    c = np.asarray(rgb, dtype=float) / 255
    c = np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    return c @ np.array([.2126, .7152, .0722])


def contrast(a, b):
    x, y = luminance(a), luminance(b)
    return (np.maximum(x, y) + .05) / (np.minimum(x, y) + .05)


def background(base, box, color, variant):
    """Only the local glass backdrop changes; never cover information above it."""
    x0, y0, x1, y1 = box
    pad = 18
    area = (x0-pad, y0-32, x1+pad, y1+pad)
    tile = base.crop(area).convert('RGBA')
    layer = Image.new('RGBA', tile.size)
    d = ImageDraw.Draw(layer)
    if variant == 'lights':
        for x, y, r, a in [(90, 60, 65, 100), (440, 175, 95, 75), (760, 40, 60, 100)]:
            d.ellipse((x-r, y-r, x+r, y+r), fill=color+(a,))
        layer = layer.filter(ImageFilter.GaussianBlur(26))
    else:
        for x in range(-20, tile.width, 38):
            d.rectangle((x, 0, x+9, tile.height), fill=color+(54,))
        layer = layer.filter(ImageFilter.GaussianBlur(1))
    tile.alpha_composite(layer)
    # Restrict the support pattern to a gently feathered local area.
    mask = Image.new('L', tile.size)
    ImageDraw.Draw(mask).rounded_rectangle((8, 8, tile.width-8, tile.height-8), radius=28, fill=255)
    base.paste(tile, area[:2], mask.filter(ImageFilter.GaussianBlur(8)))


def _runs(d, text, box, style):
    import fan_events
    x0, y0, x1, y1 = box
    left = 96 if style == 'slant' else 44
    room = y1-y0-44
    width = x1-x0-left-50-(40 if fan_events.enabled() else 0)
    # Unlike the old caption, an opt-in style never silently drops a fourth row.
    for size in range(48, 19, -1):
        rows = r3._caption_lines(d, text, size, width)
        lh = round(size*1.36)
        if len(rows) <= 3 and len(rows)*lh <= room:
            break
    else:
        raise ValueError('吹き出しに全文が入りません。台詞を分割してください')
    y = y0+30+(room-len(rows)*lh)//2
    runs = []
    for row in rows:
        x = x0+left
        for part, isnum in row:
            f = r3.num_font(round(size*1.15)) if isnum else r3.font(size)
            focus = isnum and fan_events.number_focus(part)
            drawn = r3.num_font(round(size*1.15*1.06)) if focus else f
            ink = GOLD if style == 'glass' and isnum else WHITE if style == 'glass' else (155,79,8) if isnum else (30,30,34)
            runs.append((x, y+size, part, drawn, ink))
            reserve = r3.num_font(round(size*1.15*1.06)) if isnum and fan_events.enabled() else f
            x += d.textlength(part, font=reserve)
        y += lh
    return runs, size, len(rows)


def _readability(base, runs, glass=False):
    """Measure the actual opaque glyph positions against their pre-text pixels."""
    masks = []
    for x, y, text, f, ink in runs:
        mask = Image.new('L', base.size)
        ImageDraw.Draw(mask).text((x,y), text, font=f, fill=255, anchor='ls')
        masks.append((np.asarray(mask) >= 240, ink))
    scrim = 0
    if glass:
        # Keep prescribed darken=.22 in the glass renderer. Add an adaptive,
        # local support scrim only if a very bright source compromises reading.
        x0,y0,x1,y1 = __import__('characters').BUBBLE
        for alpha in range(0, 211, 10):
            trial = base.copy()
            if alpha:
                overlay = Image.new('RGBA',base.size)
                ImageDraw.Draw(overlay).rounded_rectangle((x0+35,y0+30,x1-35,y1-14),radius=15,fill=(0,0,0,alpha))
                trial.alpha_composite(overlay)
            arr = np.asarray(trial.convert('RGB'))
            if all(not m.any() or float(np.min(contrast(ink,arr[m]))) >= 4.5 for m,ink in masks):
                base = trial; scrim = alpha
                break
        else:
            raise ValueError('ガラス字幕のコントラスト不足')
    arr = np.asarray(base.convert('RGB'))
    scores = [float(np.min(contrast(ink,arr[m]))) for m,ink in masks if m.any()]
    return base, min(scores, default=21), scrim


def draw(im, speaker, text):
    import characters as c
    style = os.environ['COLLESPO_BUBBLE']
    x0,y0,x1,y1 = c.BUBBLE
    color = c.COLORS[speaker]
    base = im.convert('RGBA')
    if style == 'slant':
        k = 34
        poly = [(x0+k,y0),(x1,y0),(x1-k,y1),(x0,y1)]
        sh = Image.new('RGBA',im.size)
        ImageDraw.Draw(sh).polygon([(x+6,y+10) for x,y in poly],fill=(0,0,0,120))
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
        layer = Image.new('RGBA',im.size); d = ImageDraw.Draw(layer)
        d.polygon(poly,fill=(250,247,238,255))
        d.polygon([(x0+k,y0),(x0+k+22,y0),(x0+22,y1),(x0,y1)],fill=color+(255,))
        for i in range(1,4):
            d.line((x0+k+26+i*7,y0+6,x0+26+i*7,y1-6),fill=color+(40,),width=2)
        base.alpha_composite(layer)
    else:
        variant = os.environ.get('COLLESPO_GLASS_BACKGROUND','stripes')
        if variant not in ('stripes','lights'): variant = 'stripes'
        background(base,c.BUBBLE,color,variant)
        base = liquid_glass.liquid_glass(base,c.BUBBLE,radius=40,blur=3,refract=42,bezel=46,darken=.22)
    runs,size,rows = _runs(ImageDraw.Draw(base),text,c.BUBBLE,style)
    base,ratio,scrim = _readability(base,runs,glass=style=='glass')
    d = ImageDraw.Draw(base); f = r3.font(28); w = d.textlength(c.NAMES[speaker],font=f)+56
    if style == 'slant':
        d.polygon([(x0+74,y0-26),(x0+74+w,y0-26),(x0+60+w,y0+22),(x0+60,y0+22)],fill=(30,30,38))
        d.text((x0+67+w/2,y0-2),c.NAMES[speaker],font=f,fill=color,anchor='mm')
        name_ratio = float(contrast(color,(30,30,38)))
    else:
        base = liquid_glass.liquid_glass(base,(x0+30,y0-24,x0+30+int(w),y0+24),radius=20,
                                        blur=3,refract=42,bezel=46,tint=color,tint_alpha=.6,darken=.22)
        d = ImageDraw.Draw(base)
        d.text((x0+30+w/2,y0),c.NAMES[speaker],font=f,fill=WHITE,anchor='mm',stroke_width=2,stroke_fill=SHADOW)
        name_ratio = float(contrast(WHITE,SHADOW))  # opaque outline around every glyph
    for x,y,value,f,ink in runs:
        if style == 'glass': d.text((x+2,y+2),value,font=f,fill=SHADOW,anchor='ls')
        d.text((x,y),value,font=f,fill=ink,anchor='ls')
    im.paste(base.convert(im.mode))
    r3.record_box(im,'caption',c.BUBBLE,text)
    im.info['duo_caption'] = dict(box=list(c.BUBBLE),speaker=speaker,font_size=size,rows=rows)
    im.info['bubble_style'] = dict(style=style,background=os.environ.get('COLLESPO_GLASS_BACKGROUND','stripes') if style=='glass' else None,
                                  contrast=ratio,name_contrast=name_ratio,scrim=scrim,full_text=True)
