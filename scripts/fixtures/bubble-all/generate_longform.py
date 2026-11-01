"""Fixed pre-extension functions; supplied current globals. No runtime Git access."""
def layout_talk(d, text: str):
    """台詞を、置ける高さに収まる形にする。

    戻り値は (文字の大きさ, [1画面ぶんの行, ...])。
    **入り切らなくても捨てない。** 入らなければ画面を分ける。
    初版は lines[:5] で黙って切っていて、長い台詞は
    読み上げだけが続いて画面が止まって見えた。
    """
    import caption_breaks
    avail_w = COL_X1 - COL_X0 - TALK_PAD * 2
    avail_h = TALK_Y1 - TALK_Y0 - TALK_PAD * 2
    for size in TALK_SIZES:
        try:
            lines = caption_breaks.wrap(text,lambda s:video_common.text_width(d,s,font(size)),avail_w) if caption_breaks.enabled() else wrap(d,text,font(size),avail_w)
        except ValueError:continue
        per = max(1, avail_h // (size + TALK_LEAD))
        if len(lines) <= per:
            return size, [lines]
    # いちばん小さくしても入らない。画面を分ける。
    size = TALK_SIZES[-1]
    lines = caption_breaks.wrap(text,lambda s:video_common.text_width(d,s,font(size)),avail_w) if caption_breaks.enabled() else wrap(d,text,font(size),avail_w)
    per = max(1, avail_h // (size + TALK_LEAD))
    if caption_breaks.enabled():
        measure=lambda s:video_common.text_width(d,s,font(size))
        values=caption_breaks.pages(text,fits=lambda s:len(caption_breaks.wrap(s,measure,avail_w))<=per)
        return size,[caption_breaks.wrap(s,measure,avail_w) for s in values]
    return size, [lines[i:i + per] for i in range(0, len(lines), per)]


def render_stage(p, seg, portrait_dir="", topic="", panel=None,
                 score=None):
    """立ち絵以外の全部。下地・札・台詞・名前。

    立ち絵と分けてあるのは、**こちらは途中で止まるが、立ち絵は
    最後まで動く**ため。まばたきも口も1枚ごとに変わるので、
    一緒に描くと3分ぶん全部を描き直すことになる。
    止まったあとの下地を1枚持っておいて、その上に立ち絵だけ貼る。
    """
    im, d = base(p)
    who = _speaker(seg)

    draw_top_strip(d, topic, score)
    render_panel(d, panel, topic)

    # 立ち絵が無い日は、色の丸と名前で代用する。
    # 絵が無いから作れない、にはしない。
    for s in SPEAKERS.values():
        if video_common._parts(s["name"], portrait_dir):
            continue
        talking = s["name"] == who["name"]
        x = PORTRAIT_X if s["side"] == "left" else W - PORTRAIT_X
        col = s["color"] if talking else (52, 58, 72)
        r = 74 if talking else 62
        cy = H - PORTRAIT_H + 200
        d.ellipse([x - r, cy - r, x + r, cy + r], fill=col)
        f = font(38 if talking else 32)
        d.text((x - d.textlength(s["name"], font=f) / 2, cy + r + 24),
               s["name"], font=f, fill=col if talking else DIM)

    # 台詞。置ける場所は決まっている。中身をそこへ収める。
    size = seg.get("_size")
    lines = seg.get("_lines")
    if lines is None:
        size, pages = layout_talk(d, seg.get("text", ""))
        lines = pages[0]

    # 箱の高さは**毎回同じ**にする。
    #
    # 中身に合わせて縮めていたので、1行の台詞のときだけ箱が小さくなって
    # 札との間に穴が空いた。札と同じで、ここも「台詞が出る場所」。
    # 場所が動くと、そう見えない。
    # 代わりに、行が少ない日は上下の真ん中へ寄せる。
    y0 = TALK_Y0
    d.rounded_rectangle([COL_X0, y0, COL_X1, TALK_Y1], 24, fill=SURF)
    # 喋っている側の縁に色の帯。吹き出しの尻尾の代わり。
    left = who["side"] == "left"
    if left:
        d.rounded_rectangle([COL_X0, y0, COL_X0 + 10, TALK_Y1], 5,
                            fill=who["color"])
    else:
        d.rounded_rectangle([COL_X1 - 10, y0, COL_X1, TALK_Y1], 5,
                            fill=who["color"])

    # 名前の札。箱の上端に、喋っている側から出す。
    #
    # 文字が札の中で上に寄っていた。anchor="lm"（左・上下中央）で
    # 置くと、書体が変わっても真ん中のまま。座標の足し算で合わせると
    # フォントを替えたときにずれる。
    nm, fn = who["name"], font(32)
    nw = d.textlength(nm, font=fn) + 48
    nx = COL_X0 + 24 if left else COL_X1 - 24 - nw
    ny0, ny1 = y0 - NAME_H + 8, y0 + 12
    d.rounded_rectangle([nx, ny0, nx + nw, ny1], 13, fill=who["color"])
    d.text((nx + 24, (ny0 + ny1) / 2), nm, font=fn, fill=(16, 22, 18),
           anchor="lm")

    # 1行ずつ出す。ANIM_END までに出し切る。
    shown = len(lines) if p >= ANIM_END else max(
        1, int(len(lines) * (p / ANIM_END)))
    # 上下の真ん中から書き出す。
    block = len(lines) * (size + TALK_LEAD) - TALK_LEAD
    yy = y0 + max(TALK_PAD, ((TALK_Y1 - TALK_Y0) - block) // 2)
    for ln in lines[:shown]:
        d.text((COL_X0 + TALK_PAD, yy), ln, font=font(size), fill=TEXT)
        yy += size + TALK_LEAD

    # 音声の表記。立ち絵が画面の下端まで来ているので、
    # 左右の隅ではなく中央の列の下に置く(重ならない唯一の場所)。
    cr = "音声: VOICEVOX ずんだもん / 四国めたん"
    fc = font(26)
    d.text(((COL_X0 + COL_X1) / 2 - d.textlength(cr, font=fc) / 2, 1026),
           cr, font=fc, fill=DIM)
    return im
