"""コレスポの新しい見た目（11/10 本人了承「そういうデザイン感で全動画・配信・ショートを」）。

Argon と4回往復した見本（11/10、93点）を部品にしたもの。どの型もここの部品で描く。
決まり：
- 色は濃紺の地＋白・灰＋黄1色（ACCENT）だけ。赤や金の差し色を足さない。
- 数字は Oswald（縦長）、日本語は Noto Sans JP。
- 動くのは真ん中の情報の塊だけ。背景・上の札・キャラ・字幕の枠は動かさない。
- 入れ替えは 0.28 秒、右から入り左へ抜ける（前後を重ねる）。回転・めくり・弾みは使わない。
- 補足はその場でフェード。棒グラフは置いたまま色だけ移す。字幕は重ねない。
関数はすべて時刻 t の純関数（同じ t なら同じ絵）。
"""
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
NOTO = ROOT / 'assets/fonts/soccer-v5/NotoSansJP-VF.ttf'
OSWALD = ROOT / 'assets/fonts/Oswald[wght].ttf'

ACCENT = (214, 250, 70)
NAVY_IN, NAVY_OUT = (16, 30, 62), (5, 10, 24)
WHITE, GREY, DIM = (244, 246, 250), (150, 162, 186), (120, 130, 150)
BAR_OFF = (70, 78, 98)

TR = 0.28            # 入れ替えの長さ（Argon 11/10：0.25〜0.3秒）
SUPPORT_DELAY = 0.15  # 塊が止まってから補足が出るまで
SUPPORT_FADE = 0.2
CAPTION_FADE = 0.12


@lru_cache(maxsize=64)
def jp(size, weight='Black'):
    f = ImageFont.truetype(str(NOTO), size)
    f.set_variation_by_name(weight)
    return f


@lru_cache(maxsize=64)
def num(size, weight='Bold'):
    f = ImageFont.truetype(str(OSWALD), size)
    f.set_variation_by_name(weight)
    return f


def clamp(t):
    return max(0.0, min(1.0, t))


def ease_out(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_sharp(t):
    """入れ替え用。出だしが速く、ピタッと止まる。"""
    return 1 - (1 - clamp(t)) ** 5


def mix(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


@lru_cache(maxsize=4)
def _base(w, h):
    """中心から外へ暗くなるグラデーション（対角線の0.62倍で一番暗い）＋±5の粒子。乱数は固定。"""
    import numpy as np
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.clip(np.hypot(x - w * 0.45, y - h * 0.36) / ((w * w + h * h) ** 0.5 * 0.62), 0, 1)[..., None]
    rgb = np.array(NAVY_IN, np.float32) + (np.array(NAVY_OUT, np.float32) - np.array(NAVY_IN, np.float32)) * t
    rgb += (np.random.default_rng(7).random((h, w, 1), dtype=np.float32) - 0.5) * 10
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')


@lru_cache(maxsize=4)
def _band(w, h):
    b = Image.new('RGBA', (w * 2, h), (0, 0, 0, 0))
    s = h / 1920
    ImageDraw.Draw(b).polygon([(300 * s, 1250 * s), (660 * s, 1250 * s), (1660 * s, 250 * s), (1300 * s, 250 * s)],
                              fill=(120, 170, 255, 16))
    return b.filter(ImageFilter.GaussianBlur(40))


def background(t, w=1080, h=1920, span=18.0):
    """地。斜めの光の帯が span 秒で 260px ほどゆっくり流れる（唯一の常時の動き）。"""
    im = _base(w, h).copy()
    bx = int(w - (t / span) * 260 * (w / 1080)) % w
    im.alpha_composite(_band(w, h).crop((bx, 0, bx + w, h)))
    return im


def header(lay, brand, label, x=64, y=128, w=None):
    d = ImageDraw.Draw(lay)
    w = w or lay.width
    d.text((x, y), brand, font=jp(40, 'Bold'), fill=WHITE)
    bw = d.textlength(brand, font=jp(40, 'Bold'))
    d.text((x + bw + 36, y + 4), label, font=jp(36, 'Medium'), fill=GREY)
    d.line((x, y + 68, w - x, y + 68), fill=(255, 255, 255, 40), width=2)


def shadow_text(lay, xy, text, font, fill, blur=12, alpha=130):
    s = Image.new('RGBA', lay.size, (0, 0, 0, 0))
    ImageDraw.Draw(s).text((xy[0], xy[1] + 6), text, font=font, fill=(0, 0, 0, alpha))
    lay.alpha_composite(s.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(lay).text(xy, text, font=font, fill=fill)


def hero(size, meta, name, value, unit, sub, x=64, y=300):
    """主役の塊：所属の行・名前・大きな数字・単位・小さな補足。透明な層で返す。"""
    lay = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if meta:
        d.text((x, y), meta, font=jp(34, 'Medium'), fill=GREY)
    shadow_text(lay, (x, y + 46), name, jp(124 if len(name) <= 6 else 96), WHITE)
    if value not in (None, ''):
        shadow_text(lay, (x - 4, y + 170), str(value), num(380), ACCENT, blur=16, alpha=150)
        d = ImageDraw.Draw(lay)
        nw = d.textlength(str(value), font=num(380))
        if unit:
            d.text((x + nw + 40, y + 350), unit, font=jp(96), fill=WHITE)
        if sub:
            d.text((x + nw + 42, y + 480), sub, font=jp(40, 'Medium'), fill=GREY)
    return lay


def support(size, text, x=64, y=960, w=None):
    """補足の帯：薄い白＋左だけ黄の太線、文字は黄。"""
    lay = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    right = (w or size[0]) - x
    d.rectangle((x, y, right, y + 110), fill=(255, 255, 255, 22))
    d.rectangle((x, y, x + 10, y + 110), fill=ACCENT)
    d.text((x + 40, y + 22), text, font=jp(54, 'Bold'), fill=ACCENT)
    return lay


def bars(size, title, note, rows, highlight, x=64, y=1130, unit_px=None, label_w=220):
    """比べる棒。rows=[(名前, 値)]、highlight[i]＝その行の黄色の強さ 0〜1。棒は置いたまま色だけ移す。"""
    lay = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.text((x, y), title, font=jp(40, 'Bold'), fill=WHITE)
    if note:
        d.text((x + d.textlength(title, font=jp(40, 'Bold')) + 24, y + 10), note, font=jp(26, 'Medium'), fill=GREY)
    top = max([v for _, v in rows] + [1])
    unit_px = unit_px or (size[0] - x * 2 - label_w - 120) / top
    for i, (name, v) in enumerate(rows):
        yy = y + 74 + i * 66
        h = highlight[i] if i < len(highlight) else 0.0
        d.text((x, yy), name, font=jp(36, 'Bold'), fill=mix(GREY, WHITE, h))
        L = v * unit_px
        if L > 1:
            d.rectangle((x + label_w, yy + 10, x + label_w + L, yy + 44), fill=mix(BAR_OFF, ACCENT, h))
        d.text((x + label_w + L + 16, yy - 8), str(v), font=num(52), fill=mix(GREY, WHITE, h))
    return lay


def caption_box(lay, y=1610, h=180):
    d = ImageDraw.Draw(lay)
    d.rectangle((0, y, lay.width, y + h), fill=(0, 0, 0, 150))
    d.rectangle((0, y, lay.width, y + 4), fill=(255, 255, 255, 40))


def caption(size, text, x=64, y=1660):
    lay = Image.new('RGBA', size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((x, y), text, font=jp(46, 'Bold'), fill=WHITE)
    return lay


def credit(lay, text, x=64, y=1830):
    ImageDraw.Draw(lay).text((x, y), text, font=jp(24, 'Medium'), fill=DIM)


def shifted(lay, dx, alpha=1.0):
    """層を横にずらし、濃さを掛ける。見えないときは None。"""
    if alpha <= 0.01:
        return None
    w, h = lay.size
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dx = int(dx)
    if dx >= 0:
        out.alpha_composite(lay.crop((0, 0, w - dx, h)), (dx, 0))
    else:
        out.alpha_composite(lay.crop((-dx, 0, w, h)), (0, 0))
    if alpha < 1:
        out.putalpha(out.getchannel('A').point(lambda v: int(v * alpha)))
    return out


def slot(t, start, end, first=False, last=False, width=1080):
    """区間 [start, end) を受け持つ塊の (横位置, 濃さ, 入り終わりの時刻)。見えなければ None。
    入りは start-TR から start（最初の塊は start から start+TR）、出は end-TR から end。前後の塊と重なる。"""
    a0, a1 = (start, start + TR) if first else (start - TR, start)
    if t < a0 or (not last and t >= end):
        return None
    if t < a1:
        u = ease_sharp((t - a0) / (a1 - a0))
        return (1 - u) * width * 0.5, u, a1
    if not last and t >= end - TR:
        u = ease_sharp((t - (end - TR)) / TR)
        return -u * width * 0.5, 1 - u, a1
    return 0.0, 1.0, a1


def support_alpha(t, entered, end, last=False):
    a = ease_out((t - entered - SUPPORT_DELAY) / SUPPORT_FADE)
    if not last:
        a *= 1 - ease_out((t - (end - TR - 0.15)) / 0.15)
    return a


def caption_alpha(t, entered, end, last=False):
    a = ease_out((t - entered) / CAPTION_FADE)
    if not last:
        a *= 1 - ease_out((t - (end - TR)) / CAPTION_FADE)
    return a
