"""Fixed pre-extension functions; supplied current globals. No runtime Git access."""
def layout_subtitle(d, text):
    """(大きさ, 行の高さ, 行)。字幕の札に収まるいちばん大きい文字で。"""
    width = SUB_X1 - SUB_X0 - SUB_BAR - SUB_PAD_X * 2
    room = SUB_Y1 - SUB_Y0 - SUB_PAD_TOP - SUB_PAD_BOTTOM
    import caption_breaks
    lines = []
    for size, lh in SUB_SIZES:
        try:
            lines = caption_breaks.wrap(text,lambda s:video_common.text_width(d,s,font(size)),width) if caption_breaks.enabled() else wrap(d,text,font(size),width)
        except ValueError:continue
        if len(lines) * lh <= room:
            return size, lh, lines
    size, lh = SUB_SIZES[-1]
    keep = max(1, room // lh)
    if caption_breaks.enabled() and (not lines or len(lines)>keep):
        raise ValueError('字幕の全文が入りません。文節でページ分割してください')
    if len(lines) > keep:
        print(f"[warn] 字幕が札に入りきりません（{len(text)}字）。分け方を見直してください")
    return size, lh, lines[:keep]


def paginate(segs):
    """長い台詞を、この字幕の札に入る画面に分ける（generate_longform.paginate の新デザイン版）。

    いまの長編の paginate は、古い台詞の箱（幅1064・高さ336）で分けている。新しい字幕の札は
    幅も高さも違うので、新デザインのときはこちらで分ける。音は分けない（1つの読み上げのまま）。
    尺は文字数で按分する（いまの長編と同じ）。戻り値の形も同じ（_size・_lines・_share）。
    """
    import caption_breaks
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    width = SUB_X1 - SUB_X0 - SUB_BAR - SUB_PAD_X * 2
    room = SUB_Y1 - SUB_Y0 - SUB_PAD_TOP - SUB_PAD_BOTTOM
    out = []
    for s in segs:
        text = " ".join(str(s.get("text") or "").split())
        size, lh, lines = SUB_SIZES[-1] + (None,)
        for size, lh in SUB_SIZES:
            try:
                lines = caption_breaks.wrap(text,lambda s:video_common.text_width(d,s,font(size)),width) if caption_breaks.enabled() else wrap(d,text,font(size),width)
            except ValueError:continue
            if len(lines) * lh <= room:
                break
        if caption_breaks.enabled() and lines is None:raise ValueError('文節が字幕の幅に入りません')
        per = max(1, room // lh)
        pages = [lines[i:i + per] for i in range(0, len(lines), per)] or [[]]
        if caption_breaks.enabled():
            measure=lambda value:video_common.text_width(d,value,font(size))
            values=caption_breaks.pages(text,fits=lambda value:len(caption_breaks.wrap(value,measure,width))<=per)
            pages=[caption_breaks.wrap(value,measure,width) for value in values] or [[]]
        if len(pages) == 1:
            out.append({**s, "_size": size, "_lines": pages[0], "_share": 1.0})
            continue
        chars = [sum(len(x) for x in pg) or 1 for pg in pages]
        total = sum(chars)
        for pg, c in zip(pages, chars):
            out.append({**s, "_size": size, "_lines": pg, "_share": c / total})
    return out


def subtitle(im, d, t, seg, who, dur=None):
    text = subtitle_text(seg)
    if not text:
        return
    color = who["color"]
    name_ink=DARK_INK
    import caption_breaks
    if caption_breaks.enabled():
        import characters
        import bubble_styles
        key=next((k for k,v in characters.NAMES.items() if v==who['name']),'metan')
        color=characters.COLORS[key]
        name_ink=max((bubble_styles.WHITE,bubble_styles.SHADOW),key=lambda ink:float(bubble_styles.contrast(ink,color)))
    d.rounded_rectangle((SUB_X0, SUB_Y0, SUB_X1, SUB_Y1), radius=24, fill=SUB_BG)
    d.rounded_rectangle((SUB_X0, SUB_Y0, SUB_X0 + SUB_BAR + 8, SUB_Y1), radius=8, fill=color)
    d.rectangle((SUB_X0 + SUB_BAR, SUB_Y0, SUB_X0 + SUB_BAR + 8, SUB_Y1), fill=SUB_BG)
    # 名前の札（e: 札の左上に、話者の色で）
    nm = who["name"]
    f = font(26)
    nw = _textlen(d, nm, f) + 36
    d.rounded_rectangle((SUB_X0 + 28, SUB_Y0 - 26, SUB_X0 + 28 + nw, SUB_Y0 + 18), radius=8, fill=color)
    d.text((SUB_X0 + 28 + nw / 2, SUB_Y0 - 4), nm, font=f, fill=name_ink, anchor="mm")
    # 文字。数字（単位まで）は金色。左から現れる（e-type の clip-path を行ごとに）。
    size, lh, lines = layout_subtitle(d, text)
    f = font(size)
    widths = [video_common.text_width(d, ln, f) for ln in lines]
    total = sum(widths) or 1
    k = _clamp((t - T_TYPE0) / type_seconds(text, dur))
    shown = total * k
    x0 = SUB_X0 + SUB_BAR + SUB_PAD_X
    block = len(lines) * lh
    room = SUB_Y1 - SUB_Y0 - SUB_PAD_TOP - SUB_PAD_BOTTOM
    y = SUB_Y0 + SUB_PAD_TOP + max(0, (room - block) // 2) + (lh - size) // 2 - round(size * 0.1)
    for ln, w in zip(lines, widths):
        if shown <= 0:
            break
        lay = Image.new("RGBA", (int(w) + 16, lh + 8), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        x = 0
        for part, gold in _gold_runs(ln):
            x = _draw_text(lay, ld, (x, 0), part, f, GOLD if gold else INK)
        cut = int(min(w, shown)) + (16 if shown >= w else 0)
        part = lay.crop((0, 0, cut, lay.height))
        im.paste(part, (x0, y), part)
        shown -= w
        y += lh
