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


NEWS_BG, NEWS_RED, PAPER, INK_DARK = (20, 32, 56), (196, 44, 52), (247, 242, 223), (34, 36, 42)


def _art(spec):
    """用語の絵（assets/illustrations の台帳にある物だけ）。無い・壊れている時は絵なし。"""
    name = spec.get('illustration')
    if not name:
        return None
    try:
        import market_art
        from PIL import Image
        row = market_art.resolve(name, None, catalog=market_art.ledger())
        if not row.get('available'):
            return None
        return Image.open(row['path']).convert('RGBA')
    except (OSError, ValueError, KeyError) as error:
        print('[warn] 用語の絵を使わずに続けます: ' + str(error))
        return None


def _paste(im, art, x, y, size):
    piece = art.resize((size, size))
    im.paste(piece, (round(x), round(y)), piece)


def _news(im, cards, r3, spec, t, y, width):
    """ニュースの見出しを2〜3本。実在の局名・ロゴは出さず、日付と出典を添える。
    1本ずつ0.3秒で現れる（順出し）。揺れ・動きはつけない。"""
    from PIL import Image
    rows = spec['news'][:3]
    inner = width - 40
    plans = []
    for row in rows:
        lines = _wrap(cards, row['text'], 46, inner - 24)
        plans.append((row, lines, 22 + 30 + 10 + _block(lines, 46, 10) + 30 + 20))
    head = 30 + 56 + 22
    # 安全域（立ち絵の頭より上）に入らない時は、後ろの見出しから落とす。
    while len(plans) > 1 and head + sum(h + 14 for _, _, h in plans) + 16 > BOTTOM - y:
        plans.pop()
    height = head + sum(h + 14 for _, _, h in plans) + 16
    top = round((y + BOTTOM - height) / 2)
    cards.panel(im, (cards.L, top, cards.R, top + height), fill=NEWS_BG)
    draw = __import__('PIL.ImageDraw', fromlist=['Draw']).Draw(im)
    draw.rounded_rectangle((cards.L + 28, top + 24, cards.L + 28 + 178, top + 24 + 56), 10, fill=NEWS_RED)
    cards.text(im, cards.L + 50, top + 34, 'ニュース', 36, (255, 255, 255), width=150)
    cards.text(im, cards.L + 230, top + 38, '最近の見出し', 30, SOFT, width=width - 230)
    yy = top + head
    for i, (row, lines, h) in enumerate(plans):
        box = (cards.L + 20, yy, cards.R - 20, yy + h)
        # 四角の描画は右・下の端の1pxも塗るので、重ねる範囲を1px広げる（出る前の線を残さない）。
        area = (box[0], box[1], box[2] + 1, box[3] + 1)
        before = im.crop(area)
        draw.rounded_rectangle(box, 12, fill=PAPER)
        draw.rectangle((box[0], yy, box[0] + 12, yy + h), fill=NEWS_RED)
        cards.text(im, box[0] + 32, yy + 22, row['date'], 28, NEWS_RED, width=inner)
        ly = yy + 22 + 30 + 10
        for line in lines:
            cards.text(im, box[0] + 32, ly, line, 46, INK_DARK, width=inner - 24)
            ly += 46 + 10
        cards.text(im, box[0] + 32, ly + 2, row['source'], 26, (110, 112, 120), width=inner - 24)
        alpha = max(0.0, min(1.0, (t - 0.15 - 0.35 * i) / 0.3))
        if alpha < 1:
            after = im.crop(area)
            im.paste(Image.blend(before, after, alpha), area[:2])
        yy += h + 14


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
    if index is None and not opening:
        index = meta.get('term_shown')   # 問い・言い直しの行は直前の札を残す
    summary = spec.get('summary', '')
    y = r3.CONTENT_TOP + TOP_GAP

    main, reading = _split(spec['term'])
    art = _art(spec)
    if opening and meta.get('term_line', 0) == 0 and spec.get('news') and index is None:
        # 勘違いの行：ニュースの見出しを順に出し、「よく見る言葉」から入る。
        _news(im, cards, r3, spec, t, y, width)
    elif opening:
        # 用語を大きく。読みは小さく添える。札も出す行では少し小さくして、両方が収まるようにする。
        size = 104 if index is not None else 128
        art_size = 0 if art is None else (220 if index is not None else 280)
        inner = width - (art_size + 24 if art_size else 0)
        rows = [main]                # 1行。入らなければ共通の text が字を縮める
        sub = _wrap(cards, summary, 46, inner) if summary else []
        height = (56 + _block(rows, size, 18) + (52 + 14 if reading else 0)
                  + (_block(sub, 46, 14) + 18 if sub else 0))
        height = max(height, art_size + 48)
        if index is None:
            y = round((y + BOTTOM - height) / 2)
        cards.panel(im, (cards.L, y, cards.R, y + height))
        yy = y + 32
        for row in rows:
            cards.text(im, cards.L + 32, yy, row, size, width=inner)
            yy += size + 18
        if reading:
            cards.text(im, cards.L + 32, yy, reading, 44, SOFT, width=inner)
            yy += 52 + 14
        yy += 18
        for row in sub:
            cards.text(im, cards.L + 32, yy, row, 46, r3.GOLD, width=inner)
            yy += 46 + 14
        if art_size:
            _paste(im, art, cards.R - 24 - art_size, y + (height - art_size) // 2, art_size)
        y += height + 36
    else:
        # 帯：途中から見た人にも、何の言葉の話かが分かるように。1行ずつ、入らなければ字を縮める。
        # 右に小さく用語の絵を置き、上の空きをさみしくしない。
        band = width + 64 - (140 if art is not None else 0)
        if art is not None:
            _paste(im, art, cards.R - 120, y - 4, 120)
        cards.text(im, cards.L, y, main + ('　' + reading if reading else ''), 52, r3.GOLD, width=band)
        y += 52 + 14
        if summary:
            cards.text(im, cards.L, y, summary, 40, width=band)
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
