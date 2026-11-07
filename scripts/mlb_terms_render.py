"""固定用語回のv4描画。材料一覧の読み込みからは独立させる。"""

def frame(t, meta, spec):
    """既存v4の札・字幕・立ち絵を使い、札自体は静止させる。"""
    import review_render_v3 as r3
    import short_v4_cards as cards
    if r3.LOOK != 'v4':
        raise ValueError('MLB用語の掛け合いはv4で描画してください')
    im = cards.canvas(t, 'MLB用語')
    width = cards.R - cards.L - 64
    index = meta.get('term_card')
    opening = meta.get('term_line', 0) < 2
    if index is None:
        head, body, size = '', spec['term'], 64
    else:
        head, body, size = spec['items'][index][0], spec['items'][index][1], 46
    rows = cards.lines(body, size, width)
    title_rows = cards.lines(spec['term'], 64, width) if opening and index is not None else []
    title_height = len(title_rows) * 84
    height = title_height + 96 + len(rows) * (size + 20) + (60 if head else 0)
    y = round((r3.CONTENT_TOP + min(r3.CONTENT_BOTTOM, 1080) - height) / 2)
    cards.panel(im, (cards.L, y, cards.R, y + height))
    for i, row in enumerate(title_rows):
        cards.text(im, cards.L + 32, y + 28 + i * 84, row, 64, width=width)
    y += title_height
    if head:
        cards.text(im, cards.L + 32, y + 30, head, 30, r3.GOLD, width=width)
    for i, row in enumerate(rows):
        cards.text(im, cards.L + 32, y + (92 if head else 44) + i * (size + 20), row, size, width=width)
    im.info['skip_short_effects'] = True
    im.info['asset_v4'] = dict(kind='term', head=head, animation_time=t)
    return cards.finish(im, t, '', '出典：' + spec['source_label'])
