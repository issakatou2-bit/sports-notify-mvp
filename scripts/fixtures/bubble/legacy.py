"""Frozen main 09b1ea3e caption for portable pixel comparison."""
from PIL import Image,ImageDraw,ImageFilter
import review_render_v3 as r3
from characters import BUBBLE,COLORS,NAMES

def bubble(im, speaker, text):
    """横いっぱいの吹き出し（白地・話者の色の枠・名前の札）。数字は濃い金色。3行まで、入らなければ字を小さく。"""
    if not text:
        return
    x0, y0, x1, y1 = BUBBLE
    color = COLORS[speaker]
    base = im.convert("RGBA")
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 6, y0 + 10, x1 + 6, y1 + 10), radius=28, fill=(0, 0, 0, 110))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=(250, 247, 238), outline=color, width=6)
    f = r3.font(28); w = d.textlength(NAMES[speaker], font=f) + 40
    d.rounded_rectangle((x0 + 28, y0 - 24, x0 + 28 + w, y0 + 24), radius=24, fill=color)
    d.text((x0 + 28 + w / 2, y0), NAMES[speaker], font=f, fill=(255, 255, 255), anchor="mm")
    room = y1 - y0 - 44
    import fan_events
    for size in (48, 44, 40, 36, 33):
        rows = r3._caption_lines(d, text, size, x1 - x0 - (120 if fan_events.enabled() else 80))
        lh = round(size * 1.36)
        if len(rows) <= 3 and len(rows) * lh <= room:
            break
    y = y0 + 30 + (room - min(3, len(rows)) * lh) // 2
    for row in rows[:3]:
        x = x0 + 40
        for part, isnum in row:
            fnt = r3.num_font(round(size * 1.15)) if isnum else r3.font(size)
            focus = isnum and fan_events.number_focus(part)
            drawn = r3.num_font(round(size * 1.15 * 1.06)) if focus else fnt
            d.text((x, y + size), part, font=drawn, fill=(155, 79, 8) if focus else (196, 132, 16) if isnum else (30, 30, 34), anchor="ls")
            reserve = r3.num_font(round(size * 1.15 * 1.06)) if isnum and fan_events.enabled() else fnt
            x += d.textlength(part, font=reserve)
        y += lh
    im.paste(base.convert(im.mode))
    r3.record_box(im, "caption", (x0, y0, x1, y1), text)
    # 配置の検査（v3_rules）は、字幕の右端をここから読む
    im.info["duo_caption"] = dict(box=list(BUBBLE), speaker=speaker, font_size=size, rows=min(3, len(rows)))
