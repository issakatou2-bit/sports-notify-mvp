"""長編の新しい見た目（COLLESPO_STYLE=v2 の時だけ。11/10 本人「全動画・配信・ショートを」）。

Argon 11/11 の画面割り（旧の長編は54点）：
- 上の帯 0〜72px：コレスポ・回の題・章の札（いまの章は黄の字＋下線）。
- 情報の札 x80〜1440・y100〜860：ここだけが入れ替わる（右から0.28秒、以後は止まる）。
- 字幕 x80〜1440・y884〜1040：暗い真っ直ぐな帯、左の細い線だけ話者の色、数字は黄。
- 立ち絵は右下に小さく（話している方を明るく）。
札の中身は台本の panel["v2"]（数字の形のまま）から描く。文字は省略・切り捨てをせず、
入らなければ字を小さくし、それでも入らなければ止める。
"""
from functools import lru_cache
import re

from PIL import Image, ImageDraw

import style_v2 as s2

W, H = 1920, 1080
AREA = (80, 100, 1440, 850)
CAP = (80, 870, 1440, 1044)   # 字幕の帯の最大。行数に合わせて下から伸びる
CARD = (16, 28, 56)
CARD_LINE = (52, 66, 100)
BAR_BG = (6, 10, 18)
TAB_DIM = (148, 163, 184)
LABEL = (203, 213, 225)
BADGE = (30, 41, 59)
FOCUS = (30, 41, 66)
NAVY = (15, 23, 42)
SPEAKER_LINE = {'ずんだもん': (120, 200, 120), '四国めたん': (230, 130, 180)}
# 立ち絵：(全身の高さ, 横の中心, 上端)。胸から下は画面の外。めたんを手前に（Argon：x1450〜1900）。
PORTRAITS = {'ずんだもん': (620, 1580, 600), '四国めたん': (760, 1790, 530)}
PORTRAIT_ORDER = ('ずんだもん', '四国めたん')
NUM_RE = re.compile(r'[0-9][0-9.,:/%]*')


def enabled(panel):
    import review_render_v3 as r3
    return r3.STYLE_V2 and isinstance(panel, dict) and isinstance(panel.get('v2'), dict)


# ---------------------------------------------------------------- 字の道具
def fit(d, text, size, width, weight='Black', minimum=24, number=False):
    """幅に入る大きさ。入らなければ止める（省略しない）。"""
    for s in range(size, minimum - 1, -2):
        f = s2.num(s) if number else s2.jp(s, weight)
        if d.textlength(str(text), font=f) <= width:
            return f, s
    raise ValueError('長編の札に入りません（省略せず停止）: ' + str(text))


def rich(d, x, y, text, size, color=s2.WHITE, accent=s2.ACCENT, weight='Bold'):
    """文の中の数字だけ黄（Oswald、少し大きく）。y は文字の上端。戻り値は右端。"""
    base = y + round(size * 0.88)
    jp, num = s2.jp(size, weight), s2.num(round(size * 1.12))
    pos = 0
    for m in list(NUM_RE.finditer(text)) + [None]:
        head = text[pos:m.start()] if m else text[pos:]
        if head:
            d.text((x, base), head, font=jp, fill=color, anchor='ls')
            x += d.textlength(head, font=jp)
        if m:
            d.text((x + 2, base), m.group(), font=num, fill=accent, anchor='ls')
            x += d.textlength(m.group(), font=num) + 4
            pos = m.end()
    return x


def rich_width(d, text, size, weight='Bold'):
    jp, num = s2.jp(size, weight), s2.num(round(size * 1.12))
    total, pos = 0, 0
    for m in NUM_RE.finditer(text):
        total += d.textlength(text[pos:m.start()], font=jp) + d.textlength(m.group(), font=num) + 6
        pos = m.end()
    return total + d.textlength(text[pos:], font=jp)


def number_with_unit(d, x, base, value, unit, size, color, unit_size, unit_color=s2.WHITE):
    """Oswald の数字＋日本語の単位（下端をそろえる）。戻り値は右端。"""
    d.text((x, base), str(value), font=s2.num(size), fill=color, anchor='ls')
    x += d.textlength(str(value), font=s2.num(size)) + 14
    if unit:
        d.text((x, base), unit, font=s2.jp(unit_size, 'Bold'), fill=unit_color, anchor='ls')
        x += d.textlength(unit, font=s2.jp(unit_size, 'Bold'))
    return x


def card(d, box, fill=CARD):
    d.rectangle(box, fill=fill)
    d.line((box[0], box[1], box[2], box[1]), fill=CARD_LINE, width=2)


def heading(d, text, fixture, y=AREA[1]):
    x = AREA[0]
    d.rectangle((x, y + 6, x + 7, y + 50), fill=s2.ACCENT)
    f, _ = fit(d, text, 44, AREA[2] - AREA[0] - 40 - (330 if fixture else 0))
    d.text((x + 28, y + 28), text, font=f, fill=s2.WHITE, anchor='lm')
    if fixture:
        fixture_label(d, y + 28)


def fixture_label(d, y):
    d.text((AREA[2], y), '【検証用・数値は架空】', font=s2.jp(26, 'Bold'), fill=s2.ACCENT, anchor='rm')


# ---------------------------------------------------------------- 札の種類
def _opening(d, v):
    x0, y0, x1, y1 = AREA
    card(d, AREA)
    if v.get('fixture'):
        fixture_label(d, y0 + 44)
    d.text((x0 + 60, y0 + 50), v['lead'], font=s2.jp(34, 'Bold'), fill=s2.GREY)
    base = y0 + 420
    right = number_with_unit(d, x0 + 52, base, v['count'], '人', 300, s2.ACCENT, 84)
    d.text((x0 + 64, base + 16), '招集メンバー', font=s2.jp(40, 'Bold'), fill=s2.WHITE)
    col = max(right + 80, x0 + 640)
    d.line((col - 40, y0 + 120, col - 40, y1 - 120), fill=CARD_LINE, width=2)
    y = y0 + 150
    for label, value in v['facts']:
        d.text((col, y), label, font=s2.jp(28, 'Medium'), fill=s2.GREY)
        f, _ = fit(d, value, 46, x1 - col - 50, 'Bold')
        rich(d, col, y + 40, value, f.size, weight='Bold')
        y += 150
    note = v.get('note')
    if note:
        f, _ = fit(d, note, 28, x1 - x0 - 120, 'Medium')
        d.text((x0 + 60, y1 - 70), note, font=f, fill=s2.GREY)


def _player_row(d, box, p):
    x0, y0, x1, y1 = box
    card(d, box)
    d.rectangle((x0, y0, x0 + 96, y1), fill=BADGE)
    d.text((x0 + 48, (y0 + y1) // 2), p['position'], font=s2.num(30), fill=LABEL, anchor='mm')
    name_w = 470
    f, _ = fit(d, p['name'], 50, name_w)
    d.text((x0 + 130, y0 + 34), p['name'], font=f, fill=s2.WHITE)
    if p.get('first_call'):
        tx = x0 + 130 + d.textlength(p['name'], font=f) + 18
        d.rectangle((tx, y0 + 46, tx + 104, y0 + 84), fill=s2.ACCENT)
        d.text((tx + 52, y0 + 65), '初招集', font=s2.jp(24, 'Black'), fill=BAR_BG, anchor='mm')
    f, _ = fit(d, p['club'], 30, name_w + 40, 'Medium')
    d.text((x0 + 130, y0 + 112), p['club'], font=f, fill=s2.GREY)
    col = x0 + 700
    if p.get('appearances') is None and p.get('goals') is None:
        d.text((col, (y0 + y1) // 2), '今季の数値は未確認', font=s2.jp(34, 'Medium'), fill=s2.GREY, anchor='lm')
        return
    base = y1 - 40
    if p.get('appearances') is not None:
        d.text((col, y0 + 22), 'リーグ戦出場', font=s2.jp(24, 'Medium'), fill=s2.GREY)
        number_with_unit(d, col, base, p['appearances'], '試合', 96, s2.WHITE, 30)
    if p.get('goals') is not None:
        gx = col + 330
        d.text((gx, y0 + 22), 'リーグ戦得点', font=s2.jp(24, 'Medium'), fill=s2.GREY)
        number_with_unit(d, gx, base, p['goals'], '点', 104, s2.ACCENT if p['goals'] else s2.WHITE, 30)


def _players(d, v):
    heading(d, v['title'], v.get('fixture'))
    rows = v['players']
    if not rows:
        card(d, (AREA[0], AREA[1] + 100, AREA[2], AREA[1] + 300))
        d.text((AREA[0] + 60, AREA[1] + 200), v.get('empty', ''), font=s2.jp(40, 'Bold'), fill=s2.GREY, anchor='lm')
        return
    gap, top = 24, AREA[1] + 96
    h = min(210, (AREA[3] - top - gap * (len(rows) - 1)) // len(rows))
    for i, p in enumerate(rows):
        y = top + i * (h + gap)
        _player_row(d, (AREA[0], y, AREA[2], y + h), p)


def _stat_parts(p):
    out = []
    if p.get('appearances') is not None:
        out.append((p['appearances'], '試合', s2.WHITE))
    if p.get('goals') is not None:
        out.append((p['goals'], '点', s2.ACCENT if p['goals'] else s2.WHITE))
    return out


def _cell(d, box, p, on):
    """名札。名前と所属は左、数字は右寄せ（Oswald）。数字が無ければ右は空ける。"""
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=FOCUS if on else CARD)
    if on:
        d.rectangle((x0, y0, x0 + 6, y1), fill=s2.ACCENT)
    h = y1 - y0
    size = max(28, min(40, h // 3))
    nsize, usize = round(size * 1.35), 20
    base = y0 + h // 2 + round(nsize * 0.38)
    right = x1 - 22
    for value, unit, color in reversed(_stat_parts(p)):
        uw = d.textlength(unit, font=s2.jp(usize, 'Bold'))
        d.text((right, base), unit, font=s2.jp(usize, 'Bold'), fill=LABEL, anchor='rs')
        right -= uw + 6
        d.text((right, base), str(value), font=s2.num(nsize), fill=color, anchor='rs')
        right -= d.textlength(str(value), font=s2.num(nsize)) + 18
    name_w = right - x0 - 36
    f, size = fit(d, p['name'], size, name_w, minimum=22)
    block = size + 10 + 24
    ny = y0 + (h - block) // 2 - 4
    d.text((x0 + 26, ny), p['name'], font=f, fill=s2.WHITE if on else LABEL)
    if p.get('first_call'):
        tx = x0 + 26 + d.textlength(p['name'], font=f) + 12
        if tx + 84 < right:
            d.rectangle((tx, ny + 6, tx + 84, ny + 34), fill=s2.ACCENT)
            d.text((tx + 42, ny + 20), '初招集', font=s2.jp(20, 'Black'), fill=BAR_BG, anchor='mm')
    f, _ = fit(d, p['club'], 24, name_w, 'Medium', minimum=18)
    d.text((x0 + 26, ny + size + 12), p['club'], font=f, fill=s2.GREY)


def _roster(d, v):
    """その位置の全員を1枚の名札一覧に。いま話している選手だけ明るく（Argon 11/11：未確認が続く画面を避ける）。"""
    heading(d, v['title'], v.get('fixture'))
    rows = v['players']
    focus = set(v.get('focus', []))
    if len(rows) <= 3:
        gap, top = 24, AREA[1] + 96
        h = min(210, (AREA[3] - top - gap * (len(rows) - 1)) // len(rows))
        for i, p in enumerate(rows):
            y = top + i * (h + gap)
            _player_row(d, (AREA[0], y, AREA[2], y + h), p)
            if p['name'] in focus and focus != {r['name'] for r in rows}:
                d.rectangle((AREA[0], y, AREA[0] + 6, y + h), fill=s2.ACCENT)
        return
    cols = 2 if len(rows) <= 8 else 3
    lines = -(-len(rows) // cols)
    gap, top, bottom = 14, AREA[1] + 92, AREA[3] - 52
    h = (bottom - top - gap * (lines - 1)) // lines
    w = (AREA[2] - AREA[0] - gap * (cols - 1)) // cols
    for i, p in enumerate(rows):
        c, r = i // lines, i % lines
        x, y = AREA[0] + c * (w + gap), top + r * (h + gap)
        _cell(d, (x, y, x + w, y + h), p, p['name'] in focus)
    missing = sum(p.get('appearances') is None and p.get('goals') is None for p in rows)
    if missing:
        d.text((AREA[0], AREA[3] - 14), f'数字なしの{missing}人は今季の数値が未確認（ゼロではありません）',
               font=s2.jp(24, 'Medium'), fill=s2.GREY, anchor='ls')


def _player(d, v):
    x0, y0, x1, y1 = AREA
    card(d, AREA)
    p = v['player']
    d.text((x0 + 60, y0 + 50), p['position'] + '　注目選手', font=s2.jp(30, 'Bold'), fill=s2.ACCENT)
    if v.get('fixture'):
        fixture_label(d, y0 + 68)
    f, _ = fit(d, p['name'], 92, 700)
    d.text((x0 + 60, y0 + 130), p['name'], font=f, fill=s2.WHITE)
    f, _ = fit(d, p['club'], 46, 700, 'Bold')
    d.text((x0 + 60, y0 + 280), p['club'], font=f, fill=s2.WHITE)
    d.text((x0 + 60, y0 + 350), p.get('league', ''), font=s2.jp(34, 'Medium'), fill=s2.GREY)
    d.text((x0 + 60, y1 - 70), v.get('note', ''), font=s2.jp(26, 'Medium'), fill=s2.DIM)
    col = x0 + 820
    d.line((col - 50, y0 + 60, col - 50, y1 - 60), fill=CARD_LINE, width=2)
    blocks = []
    if p.get('appearances') is not None:
        blocks.append(('リーグ戦出場', p['appearances'], '試合', s2.WHITE, s2.GREY, 150))
    if p.get('goals') is not None:
        blocks.append(('リーグ戦得点', p['goals'], '点', s2.ACCENT if p['goals'] else s2.WHITE, s2.ACCENT, 170))
    if not blocks:
        d.text((col, (y0 + y1) // 2), '今季の数値は未確認', font=s2.jp(40, 'Bold'), fill=s2.GREY, anchor='lm')
        return
    span = (y1 - y0 - 120) // len(blocks)
    for i, (label, value, unit, color, label_color, size) in enumerate(blocks):
        top = y0 + 60 + i * span
        d.text((col, top + 20), label, font=s2.jp(32, 'Bold'), fill=LABEL if label_color == s2.GREY else label_color)
        number_with_unit(d, col, top + 50 + round(size * 0.92), value, unit, size, color, 44)


def _matches(d, v):
    heading(d, v['title'], v.get('fixture'))
    rows = v['matches']
    x0, x1 = AREA[0], AREA[2]
    if not rows:
        card(d, (x0, AREA[1] + 100, x1, AREA[1] + 300))
        d.text((x0 + 60, AREA[1] + 200), v.get('empty', ''), font=s2.jp(40, 'Bold'), fill=s2.GREY, anchor='lm')
        return
    gap, top = 28, AREA[1] + 100
    h = min(280, (AREA[3] - top - gap * (len(rows) - 1)) // len(rows))
    for i, m in enumerate(rows):
        y = top + i * (h + gap)
        card(d, (x0, y, x1, y + h))
        d.text((x0 + 50, y + 40), m['date'], font=s2.jp(30, 'Medium'), fill=s2.GREY)
        f, _ = fit(d, m['competition'], 40, 420, 'Bold')
        d.text((x0 + 50, y + 92), m['competition'], font=f, fill=s2.WHITE)
        win = m['result'] == '勝利'
        cx, mid = x0 + 820, y + h // 2
        score = f"{m['gf']} - {m['ga']}"
        sf = s2.num(min(120, h - 80))
        d.text((cx, mid), score, font=sf, fill=s2.ACCENT if win else s2.WHITE, anchor='mm')
        half = d.textlength(score, font=sf) / 2
        d.text((cx - half - 30, mid), '日本', font=s2.jp(40, 'Bold'), fill=s2.WHITE, anchor='rm')
        d.text((cx + half + 30, mid), m['opponent'], font=s2.jp(40, 'Bold'), fill=s2.WHITE, anchor='lm')
        tag = (x1 - 200, mid - 34, x1 - 50, mid + 34)
        d.rectangle(tag, outline=s2.ACCENT if win else s2.GREY, width=3)
        d.text(((tag[0] + tag[2]) // 2, mid), m['result'], font=s2.jp(36, 'Black'),
               fill=s2.ACCENT if win else s2.GREY, anchor='mm')


def _kickoff(d, v):
    x0, y0, x1, y1 = AREA
    card(d, AREA)
    if v.get('fixture'):
        fixture_label(d, y0 + 44)
    x = x0 + 60
    d.text((x, y0 + 50), '日本', font=s2.jp(72, 'Black'), fill=s2.WHITE)
    x += d.textlength('日本', font=s2.jp(72, 'Black')) + 30
    d.text((x, y0 + 64), 'vs', font=s2.num(64), fill=s2.ACCENT)
    x += d.textlength('vs', font=s2.num(64)) + 30
    f, _ = fit(d, v['opponent'], 72, x1 - x - 60)
    d.text((x, y0 + 50), v['opponent'], font=f, fill=s2.WHITE)
    base = y0 + 400
    right = number_with_unit(d, x0 + 56, base, v['date'], '', 180, s2.ACCENT, 0)
    right = number_with_unit(d, right + 50, base, v['time'], '', 160, s2.WHITE, 0)
    d.text((right + 20, base), v.get('weekday', '') + '（日本時間）', font=s2.jp(34, 'Bold'), fill=s2.GREY, anchor='ls')
    y = base + 90
    d.line((x0 + 60, y, x1 - 60, y), fill=CARD_LINE, width=2)
    for i, (label, value) in enumerate(v['facts']):
        cx = x0 + 60 + i * 640
        d.text((cx, y + 40), label, font=s2.jp(28, 'Medium'), fill=s2.GREY)
        f, _ = fit(d, value, 46, 580, 'Bold')
        d.text((cx, y + 84), value, font=f, fill=s2.WHITE)


LAYOUTS = {'roster': _roster, 'opening': _opening, 'players': _players, 'player': _player, 'matches': _matches, 'kickoff': _kickoff}


def content(panel):
    """情報の札の層（透明、1920x1080）。"""
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    v = panel['v2']
    LAYOUTS[v['layout']](ImageDraw.Draw(lay), v)
    return lay


# ---------------------------------------------------------------- 枠
def header(d, topic, chapters, idx, progress):
    d.rectangle((0, 0, W, 72), fill=BAR_BG)
    d.line((0, 72, W, 72), fill=(30, 41, 59), width=2)
    brand = s2.jp(30, 'Black')
    d.text((40, 36), 'コレスポ', font=brand, fill=s2.WHITE, anchor='lm')
    x = 40 + d.textlength('コレスポ', font=brand) + 28
    titles = []
    for ch in chapters or []:
        titles.append(str(ch.get('title') if isinstance(ch, dict) else ch))
    for size in (24, 22, 20, 18):
        tabs = [(str(i + 1), t) for i, t in enumerate(titles)]
        widths = [d.textlength(n, font=s2.num(size + 2)) + 10 + d.textlength(t, font=s2.jp(size, 'Bold')) for n, t in tabs]
        need = sum(widths) + 36 * len(widths)
        topic_w = d.textlength(topic, font=s2.jp(24, 'Bold'))
        if x + topic_w + 60 + need <= W - 40:
            break
    else:
        topic = ''
    d.text((x, 36), topic, font=s2.jp(24, 'Bold'), fill=s2.GREY, anchor='lm')
    tx = W - 40 - need + 36
    for i, ((n, t), w) in enumerate(zip(tabs, widths)):
        on = i == idx
        color = s2.ACCENT if on else TAB_DIM
        d.text((tx, 36), n, font=s2.num(size + 2), fill=color, anchor='lm')
        d.text((tx + d.textlength(n, font=s2.num(size + 2)) + 10, 36), t, font=s2.jp(size, 'Bold'), fill=color if on else TAB_DIM, anchor='lm')
        if on:
            d.rectangle((tx, 62, tx + w, 66), fill=s2.ACCENT)
        tx += w + 36
    if progress is not None:
        d.rectangle((0, 70, round(W * max(0.0, min(1.0, progress))), 72), fill=s2.ACCENT)


def caption_lines(d, text, width):
    """(大きさ, 行の高さ, 行)。文節の区切りが有効ならそれで折る。3行まで。"""
    import caption_breaks
    import longform_render_v3 as v3
    import video_common
    for size, lh in ((40, 52), (36, 48), (32, 44)):
        f = s2.jp(size, 'Bold')
        try:
            lines = (caption_breaks.wrap(text, lambda v: video_common.text_width(d, v, f), width)
                     if caption_breaks.enabled() else v3.wrap(d, text, f, width))
        except ValueError:
            continue
        if len(lines) * lh <= CAP[3] - CAP[1] - 28 and all(rich_width(d, v, size) <= width + 8 for v in lines):
            return size, lh, lines
    raise ValueError('長編の字幕が帯に入りません。文節でページを分けてください')


def caption(d, seg, who_name):
    """暗い真っ直ぐな帯。話者は左の細い線の色だけ（名前の札は出さない）。数字は黄。"""
    import longform_render_v3 as v3
    x0, _, x1, y1 = CAP
    size, lh, lines = caption_lines(d, v3.subtitle_text(seg), x1 - x0 - 80)
    y0 = y1 - len(lines) * lh - 28
    d.rectangle((x0, y0, x1, y1), fill=BAR_BG + (236,))
    d.rectangle((x0, y0, x0 + 5, y1), fill=SPEAKER_LINE.get(who_name, s2.ACCENT))
    y = y0 + 14 + (lh - size) // 2
    for line in lines:
        rich(d, x0 + 40, y, line, size)
        y += lh
    return y0


@lru_cache(maxsize=8)
def figure(who, dim):
    """話していない方は Argon の指示どおり 65% ほどの明るさに。"""
    import longform_render_v3 as v3
    art = v3.standing(who, False)
    h = PORTRAITS[who][0]
    art = art.resize((max(1, round(art.width * h / art.height)), h), Image.LANCZOS)
    if dim:
        alpha = art.getchannel('A')
        gray = art.convert('L').convert('RGB')
        rgb = Image.blend(gray, art.convert('RGB'), 0.75).point(lambda v: round(v * 0.58))
        rgb = Image.blend(rgb, Image.new('RGB', rgb.size, NAVY), 0.25)
        art = rgb.convert('RGBA')
        art.putalpha(alpha)
    return art


def portraits(im, talking, both):
    for who in PORTRAIT_ORDER:
        on = both or who == talking
        art = figure(who, not on)
        _, cx, top = PORTRAITS[who]
        im.paste(art, (cx - art.width // 2, top), art)


def render_line(t, seg, topic, panel, *, chapters=None, progress=None, panel_t=None, dur=None):
    import generate_longform as gl
    import longform_render_v3 as v3
    seg = seg or {}
    pt = t if panel_t is None else panel_t
    im = s2.background(t, W, H).convert('RGB')
    d = ImageDraw.Draw(im, 'RGBA')
    header(d, topic, chapters, v3.chapter_index(seg, chapters), progress)
    is_card = seg.get('kind') in ('intro', 'outro')
    who = gl._speaker(seg)
    portraits(im, who['name'], is_card)
    layer = content(panel)
    if pt < s2.TR and panel['v2'].get('enter', True):
        u = s2.ease_sharp(pt / s2.TR)
        layer = s2.shifted(layer, (1 - u) * 360, u)
    if layer is not None:
        base = im.convert('RGBA')
        base.alpha_composite(layer)
        im = base.convert('RGB')
        d = ImageDraw.Draw(im, 'RGBA')
    if not is_card:
        caption(d, seg, who['name'])
    d.text((CAP[0], 1062), v3.CREDIT, font=s2.jp(18, 'Medium'), fill=TAB_DIM, anchor='lm')
    im.info['longform_v2'] = dict(layout=panel['v2']['layout'], entering=pt < s2.TR)
    return im
