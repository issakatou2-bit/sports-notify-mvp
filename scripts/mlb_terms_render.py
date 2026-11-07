"""固定用語回のv4描画。材料一覧の読み込みからは独立させる。

11/7 本人「文字が小さい。項目を大きめに、ごちゃつかない範囲で追加情報があると画面がさみしくない」。
上に用語とひとことの意味の帯をずっと出し、札は大きく、札の下に補足を1行だけ添える。
最初の2行（勘違いと訂正）は帯の代わりに用語を大きく出す。
"""

TOP_GAP, BOTTOM = 24, 1010          # 立ち絵の頭（約1030）より上に収める
SOFT = (176, 196, 188)              # 補足の字。本文より一段薄く


def _block(rows, size, gap):
    return len(rows) * (size + gap)


def _wrap(cards, value, size, width):
    """区切り（全角の空白・読点・矢印）で折る。「5シーズ／ン」のような切れ目を作らない。
    1つの区切りが1行に入らない時だけ、共通の1字ずつの折り方に任せる。"""
    import re
    import review_render_v3 as r3
    f = r3.font(size)
    pieces = [p for p in re.split(r'(?<=[　、→」])', str(value)) if p]
    rows, line = [], ''
    for piece in pieces:
        if f.getlength((line + piece).rstrip('　')) <= width:
            line += piece
            continue
        if line:
            rows.append(line.rstrip('　'))
        line = ''
        if f.getlength(piece.rstrip('　')) <= width:
            line = piece
        else:
            *head, line = cards.lines(piece, size, width)
            rows += head
    if line.strip():
        rows.append(line.rstrip('　'))
    return rows or ['']


def _split(term):
    """「QO（クオリファイング・オファー）」→ 大きく出す「QO」と、添える読み。"""
    if '（' in term and term.endswith('）'):
        main, sub = term[:-1].split('（', 1)
        return main, sub
    return term, ''


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
    summary = spec.get('summary', '')
    y = r3.CONTENT_TOP + TOP_GAP

    main, reading = _split(spec['term'])
    if opening:
        # 用語を大きく。読みは小さく添える。札も出す行では少し小さくして、両方が収まるようにする。
        size = 104 if index is not None else 128
        rows = [main]                # 1行。入らなければ共通の text が字を縮める
        sub = _wrap(cards, summary, 46, width) if summary else []
        height = (56 + _block(rows, size, 18) + (52 + 14 if reading else 0)
                  + (_block(sub, 46, 14) + 18 if sub else 0))
        if index is None:
            y = round((y + BOTTOM - height) / 2)
        cards.panel(im, (cards.L, y, cards.R, y + height))
        yy = y + 32
        for row in rows:
            cards.text(im, cards.L + 32, yy, row, size, width=width)
            yy += size + 18
        if reading:
            cards.text(im, cards.L + 32, yy, reading, 44, SOFT, width=width)
            yy += 52 + 14
        yy += 18
        for row in sub:
            cards.text(im, cards.L + 32, yy, row, 46, r3.GOLD, width=width)
            yy += 46 + 14
        y += height + 36
    else:
        # 帯：途中から見た人にも、何の言葉の話かが分かるように。1行ずつ、入らなければ字を縮める。
        cards.text(im, cards.L, y, main + ('　' + reading if reading else ''), 52, r3.GOLD, width=width + 64)
        y += 52 + 14
        if summary:
            cards.text(im, cards.L, y, summary, 40, width=width + 64)
            y += 40 + 10
        y += 40

    head = ''
    if index is not None:
        card = spec['cards'][index]
        head, body, note = card['head'], card['body'], card.get('note', '')
        rows = _wrap(cards, body, 66, width)
        notes = _wrap(cards, '補足　' + note, 36, width) if note else []
        height = 44 + 48 + 22 + _block(rows, 66, 20) + (_block(notes, 36, 12) + 24 if notes else 0) + 16
        if not opening:
            y = max(y, round((y + BOTTOM - height) / 2))
        cards.panel(im, (cards.L, y, cards.R, y + height))
        yy = y + 30
        cards.text(im, cards.L + 32, yy, head, 44, r3.GOLD, width=width)
        yy += 48 + 22
        for row in rows:
            cards.text(im, cards.L + 32, yy, row, 66, width=width)
            yy += 66 + 20
        if notes:
            yy += 12
            for row in notes:
                cards.text(im, cards.L + 32, yy, row, 36, SOFT, width=width)
                yy += 36 + 12
    # 上の帯（用語と意味）は札より上に固定する。共通の中央寄せで意味の行だけ下へずれないように。
    im.info['v3_card_contents'] = True
    im.info['skip_short_effects'] = True
    im.info['asset_v4'] = dict(kind='term', head=head, animation_time=t)
    return cards.finish(im, t, '', '出典：' + spec['source_label'])
