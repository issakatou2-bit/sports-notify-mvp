"""ショートの新デザイン「電光掲示板」（10/6 本人が案Aを選んだ。モックは Design の canvas）。

いまの v2（review_render）との違い:
  - 背景が動く: 球団色の地に、2色目のピンストライプが流れ、照明の光が横切る。
  - 表紙: 大きな数字がスロットのように回って止まる。試合の札が1枚ずつ飛び込み、○が付く。
  - 下に次の試合などのテロップが流れ続ける（全画面で同じ位置）。
  - 項目の画面: 項目が札になって右から飛び込む（少し行き過ぎて戻る）。

材料・読み上げ・尺は v2 と同じ。画面だけを差し替える（style="v3"）。
効果音の時刻は cues() が、この描画と同じ時刻表から返す（動きと音がずれない）。

時刻はすべて「その画面が出てからの秒」t。p（0〜1）は使わない。
"""
import functools
import re
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from ps_brand_components import TEAM_SECONDARY_COLORS, font  # noqa: E402
from ps_render_template import SAFE_BOTTOM, SAFE_RIGHT  # noqa: E402
from review_render import page_source, _lines, PORTRAITS  # noqa: E402

W, H = 1080, 1920
LEFT = 72
INK = (247, 242, 223)
GOLD = (255, 209, 108)
DARK_INK = (27, 26, 23)
ROOT = pathlib.Path(__file__).resolve().parents[1]
NUM_FONT = ROOT / "assets/fonts/Oswald[wght].ttf"

# 時刻表（秒）。描画と効果音の両方がここを見る。
T_WHO = 0.0          # 球団の行が上がってくる
T_ROLL = (0.35, 1.6)  # 数字が回り始める・止まる
T_TAG = 0.5          # 「4試合すべて敵地」の帯
T_CHIP0, T_CHIP_GAP = 1.0, 0.3   # 札の1枚目と間隔
T_RING_AFTER = 0.55  # 札が着いてから○が付くまで
T_CARD0, T_CARD_GAP = 0.15, 0.35  # 項目の札
SLIDE = 0.45         # 飛び込みにかかる秒


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, k):
    return tuple(round(a[i] * (1 - k) + b[i] * k) for i in range(3))


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def colors(team_id):
    """地の色（暗くして文字を読めるように）・2色目・札の色。"""
    import notability_engine as ne
    base = _hex(ne.MLB_TEAM_COLOR.get(str(team_id)) or "#183b35")
    # 明るさだけでなく、色の強さ（赤など）も抑える。地が派手だと文字が読みにくい
    while _lum(base) > 0.16 or max(base) > 120:
        base = _mix(base, (0, 0, 0), 0.2)
    second = _hex(TEAM_SECONDARY_COLORS.get(str(team_id)) or "#c4ced4")
    if _lum(second) < 0.35:
        second = _mix(second, (255, 255, 255), 0.55)
    panel = _mix(base, (255, 255, 255), 0.09)
    return base, second, panel


@functools.lru_cache(maxsize=64)
def num_font(size, weight="Bold"):
    try:
        f = ImageFont.truetype(str(NUM_FONT), size)
        f.set_variation_by_name(weight)
        return f
    except (OSError, ValueError):
        return font(size, True)


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def back_out(x, s=1.6):
    """少し行き過ぎて戻る。"""
    x = max(0.0, min(1.0, x))
    x -= 1
    return 1 + x * x * ((s + 1) * x + s)


# ------------------------------------------------------------------ 背景
@functools.lru_cache(maxsize=4)
def _beam():
    im = Image.new("L", (360, 2600), 0)
    d = ImageDraw.Draw(im)
    d.rectangle((110, 0, 250, 2600), fill=34)
    im = im.filter(ImageFilter.GaussianBlur(40)).rotate(-18, expand=True, resample=Image.BICUBIC)
    return Image.new("RGB", im.size, (255, 255, 255)), im


def background(t, team_id):
    base, second, _ = colors(team_id)
    im = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(im)
    line = _mix(base, second, 0.10)
    off = (t * 16) % 96
    x = -96 + off
    while x < W:
        d.rectangle((round(x) + 92, 0, round(x) + 96, H), fill=line)
        x += 96
    # 照明の光（9秒で1回横切る）
    ph = (t % 9.0) / 9.0
    if ph < 0.5:
        white, beam = _beam()
        bx = round(-900 + ph / 0.5 * 2200)
        im.paste(white, (bx, -300), beam)
    d.rectangle((0, 0, W, 16), fill=second)
    return im


# ------------------------------------------------------------------ 部品
def _header(d, label, page=None, second=(196, 206, 212)):
    d.text((LEFT, 168), "コレスポ", font=font(44), fill=GOLD)
    d.text((LEFT + 210, 180), label, font=font(28), fill=second)
    if page:
        d.text((SAFE_RIGHT, 172), page, font=num_font(40), fill=GOLD, anchor="ra")


def _badge(d, x, y, abbr, base, second):
    w = max(150, round(d.textlength(abbr, font=num_font(44))) + 56)
    d.rounded_rectangle((x, y, x + w, y + 76), radius=16, fill=_mix(base, (0, 0, 0), 0.3),
                        outline=second, width=6)
    d.text((x + w / 2, y + 38), abbr, font=num_font(44), fill=INK, anchor="mm")
    return w


@functools.lru_cache(maxsize=16)
def _ticker_strip(text):
    f = font(40)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    w = round(probe.textlength(text, font=f)) + 112
    im = Image.new("RGB", (w * 2, 88), GOLD)
    d = ImageDraw.Draw(im)
    for k in range(2):
        d.text((k * w + 56, 44), text, font=f, fill=DARK_INK, anchor="lm")
    return im, w


def ticker(im, t, text, y=1486):
    if not text:
        return
    strip, w = _ticker_strip(text)
    off = round(t * 80) % w
    im.paste(strip.crop((off, 0, off + W, 88)), (0, y))


@functools.lru_cache(maxsize=4)
def _portrait(who="metan"):
    # 10/6 本人「ずんだもんより、めたんをメインで使っていきたい。自信作だから」。
    # 新デザインの回は四国めたん（声も四国めたん。generate_asset_video が話者を合わせる）。
    path = ROOT / PORTRAITS / ("metan/3-black/base.png" if who == "metan"
                               else "zundamon/C-cheer/base-black-brow-candidate.png")
    sp = Image.open(path).convert("RGBA").crop((150, 0, 910, 680))
    sp.thumbnail((250, 240))
    return sp


def source(d, text, color):
    """出典。立ち絵（右下）にかからない幅で、2行まで。"""
    lines, size = _lines(d, text, 24, SAFE_RIGHT - LEFT - 280, 2)
    for i, line in enumerate(lines):
        d.text((LEFT, 1478 - (len(lines) - i) * (size + 6)), line, font=font(size), fill=color)


def presenter(im, t, which="right", who="metan"):
    sp = _portrait(who)
    bob = round(6 * math.sin(t * 2 * math.pi / 2.4))
    x = SAFE_RIGHT - sp.width if which == "right" else 24
    # テロップ（1486〜1574）の上に立つ。テロップの文字を隠さない
    im.paste(sp, (x, 1480 - sp.height + bob), sp)


def _paste_card(im, card, x, y, k):
    """札を、飛び込みの進み具合 k（0〜1、行き過ぎあり）で置く。"""
    if k <= 0:
        return
    dx = round(140 * (1 - k))
    alpha = card.split()[3].point(lambda a: round(a * min(1.0, k * 1.6)))
    im.paste(card, (x + dx, y), alpha)


# ------------------------------------------------------------------ 表紙
@functools.lru_cache(maxsize=32)
def _chip(label, score, w, base_rgb, second_rgb):
    card = Image.new("RGBA", (w, 168), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, 167), radius=20, fill=_mix(base_rgb, (255, 255, 255), 0.1) + (255,),
                        outline=_mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
    size = 28
    while size > 18 and d.textlength(label, font=font(size)) > w - 48:
        size -= 1
    d.text((24, 22), label, font=font(size), fill=second_rgb)
    d.text((24, 66), score, font=num_font(80), fill=INK)
    return card


def _reel(d, im, x, y, value, t, size=400):
    """数字がスロットのように回って止まる。value は数字の文字列（数字以外はそのまま）。"""
    f = num_font(size)
    a, b = T_ROLL
    k = ease_out((t - a) / (b - a))
    cx = x
    h = round(size * 1.0)
    for ch in value:
        cw = round(d.textlength(ch, font=f))
        if ch.isdigit():
            target = int(ch)
            pos = k * target                      # 0 → target
            lay = Image.new("RGBA", (cw + 8, h), (0, 0, 0, 0))
            ld = ImageDraw.Draw(lay)
            base = math.floor(pos)
            frac = pos - base
            for j in (base, base + 1):
                if 0 <= j <= 9:
                    ld.text((4, round((j - pos) * h) - round(size * 0.12)), str(j), font=f, fill=GOLD)
            im.paste(lay, (cx - 4, y), lay)
            del frac
        else:
            d.text((cx, y - round(size * 0.12)), ch, font=f, fill=GOLD)
        cx += cw
    return cx


def intro(t, spec, kind_label):
    v3 = spec.get("v3") or {}
    tid = spec.get("team_id")
    base, second, _ = colors(tid)
    im = background(t, tid)
    d = ImageDraw.Draw(im)
    _header(d, kind_label, second=second)
    # 球団の行
    k = ease_out((t - T_WHO) / 0.5)
    y = 260 + round(48 * (1 - k))
    x = LEFT
    if spec.get("abbr"):
        x += _badge(d, LEFT, y, spec["abbr"], base, second) + 24
    who = v3.get("who") or spec.get("label", "")
    lines, size = _lines(d, who, 44, SAFE_RIGHT - x, 1)
    d.text((x, y + 38), lines[0] if lines else "", font=font(size), fill=INK, anchor="lm")
    big = str(v3.get("big") or "")
    if big:
        end = _reel(d, im, LEFT - 8, 350, big, t)
        unit = v3.get("unit") or ""
        d.text((end + 16, 526), unit, font=font(128), fill=INK)
        if v3.get("sub"):
            d.text((end + 20, 682), v3["sub"], font=font(40), fill=second)
        y = 772
    else:
        hook = spec.get("hook") or spec.get("label", "")
        lines, size = _lines(d, hook, 96, SAFE_RIGHT - LEFT, 4)
        e = ease_out(t / 0.6)
        for i, line in enumerate(lines):
            d.text((LEFT - round(56 * (1 - e)), 400 + i * (size + 20)), line, font=font(size),
                   fill=GOLD if i == 0 else INK)
        y = 400 + len(lines) * (size + 20) + 40
    tag = v3.get("tag")
    if tag:
        k = ease_out((t - T_TAG) / 0.4)
        if k > 0:
            f = font(48)
            w = round(d.textlength(tag, font=f)) + 56
            reveal = round(w * k)
            d.rectangle((LEFT, y, LEFT + reveal, y + 84), fill=GOLD)
            lay = Image.new("RGBA", (w, 84), (0, 0, 0, 0))
            ImageDraw.Draw(lay).text((28, 42), tag, font=f, fill=DARK_INK, anchor="lm")
            im.paste(lay.crop((0, 0, reveal, 84)), (LEFT, y), lay.crop((0, 0, reveal, 84)))
        y += 116
    chips = v3.get("chips") or []
    if chips:
        cw = (SAFE_RIGHT - LEFT - 24) // 2
        for i, c in enumerate(chips[:4]):
            cx = LEFT + (i % 2) * (cw + 24)
            cy = y + (i // 2) * 192
            t0 = T_CHIP0 + i * T_CHIP_GAP
            card = _chip(c.get("label", ""), c.get("score", ""), cw, base, second)
            _paste_card(im, card, cx, cy, back_out((t - t0) / SLIDE))
            if c.get("win"):
                kr = back_out((t - t0 - SLIDE - T_RING_AFTER) / 0.25, 2.4)
                if kr > 0:
                    r = round(30 * kr)
                    ox, oy = cx + cw - 64, cy + 112
                    d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=GOLD, width=max(2, round(8 * min(1, kr))))
    ticker(im, t, v3.get("ticker"))
    source(d, page_source(spec.get("items") or []), second)
    presenter(im, t)
    return im


# ------------------------------------------------------------------ 項目の画面
# 文字の大中小（10/6 本人「注目個所に色、重要度で文字サイズに差を」）。
#   大: 項目の1つ目のかたまり（全角スペースまで）。いちばん言いたいこと。金色。
#   中: 2つ目以降のかたまり。数字（単位まで）だけ金色。
#   小: かっこの中の補足。くすんだ色。
SIZE_L, SIZE_M, SIZE_S = 66, 46, 34
NUM_RE = re.compile(r"\d[\d,.]*(?:対\d+)?(?:本塁打|奪三振|打数|安打|打点|試合|連勝|連敗|勝|敗|本|点|年|回|戦|位|人|%|割|秒|分)?")
NO_HEAD = "、。，．）」』・ー％%"


def _runs(body):
    """本文を (文字列, 大中小, 金色か) の並びに。読み上げと同じ文字だけを使う（足さない）。"""
    out = []
    for i, seg in enumerate(str(body).split("　")):
        if not seg:
            continue
        if i:
            out.append(("　", "M", False))
        for part in re.split(r"(（[^）]*）)", seg):
            if not part:
                continue
            if part.startswith("（"):
                out.append((part, "S", False))
            elif i == 0:
                out.append((part, "L", True))
            else:
                pos = 0
                for m in NUM_RE.finditer(part):
                    if m.start() > pos:
                        out.append((part[pos:m.start()], "M", False))
                    out.append((m.group(0), "M", True))
                    pos = m.end()
                if pos < len(part):
                    out.append((part[pos:], "M", False))
    return out


def _atoms(runs):
    """折り返してよい単位。数字＋単位はひとかたまり。"""
    for text, size, gold in runs:
        if gold and size == "M":
            yield text, size, gold
            continue
        # カタカナの語（「ブレーブス」「エンリケ・エルナンデス」）も途中で折り返さない
        for m in re.finditer(r"\d[\d,.]*(?:対\d+)?[^\d\s　（）・、]?|[ァ-ヴ][ァ-ヴー・]*[ァ-ヴー]|.", text):
            yield m.group(0), size, gold


def rich_lines(runs, width, second_rgb):
    sizes = {"L": SIZE_L, "M": SIZE_M, "S": SIZE_S}
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    atoms = list(_atoms(runs))
    widths = [probe.textlength(a[0], font=font(sizes[a[1]])) for a in atoms]
    lines, cur, x = [], [], 0
    for k, (text, size, gold) in enumerate(atoms):
        f = font(sizes[size])
        w = widths[k]
        if text == "　" and cur:
            # 次のかたまり（次の全角スペースまで）が今の行に入らず、次の行には入るなら、ここで改行
            j = k + 1
            while j < len(atoms) and atoms[j][0] != "　":
                j += 1
            seg = sum(widths[k + 1:j])
            if x + w + seg > width and seg <= width:
                lines.append(cur)
                cur, x = [], 0
                continue
        if cur and x + w > width and text not in NO_HEAD and text.strip("　 "):
            lines.append(cur)
            cur, x = [], 0
        if not cur and not text.strip("　 "):
            continue                                       # 行頭の空白は捨てる
        color = GOLD if gold else (_mix(second_rgb, INK, 0.3) if size == "S" else INK)
        cur.append((x, text, f, color, sizes[size]))
        x += w
    if cur:
        lines.append(cur)
    return lines


@functools.lru_cache(maxsize=64)
def _item_card(head, body, w, base_rgb, second_rgb):
    quote = "番記者" in head or str(body).startswith("「")
    if not quote:
        lines = rich_lines(_runs(body), w - 72, second_rgb)
        heights = [max(it[4] for it in ln) + 16 for ln in lines]
        h = 84 + sum(heights) + 30
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=24, fill=_mix(base_rgb, (255, 255, 255), 0.1) + (255,),
                            outline=_mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
        d.text((36, 30), head, font=font(32), fill=second_rgb)
        y = 84
        for ln, lh in zip(lines, heights):
            base_y = y + lh - 16
            for x, text, f, color, _ in ln:
                d.text((36 + x, base_y), text, font=f, fill=color, anchor="ls")
            y += lh
        return card
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines, size = _lines(probe, body, 52 if quote else 64, w - 72, 8 if quote else 4)
    h = 40 + 50 + len(lines) * (size + 14) + 36
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    fill = (247, 242, 223, 255) if quote else _mix(base_rgb, (255, 255, 255), 0.1) + (255,)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=24, fill=fill,
                        outline=None if quote else _mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
    d.text((36, 30), head, font=font(32), fill=(93, 90, 99) if quote else second_rgb)
    for i, line in enumerate(lines):
        color = DARK_INK if quote else (GOLD if i == 0 else INK)
        d.text((36, 84 + i * (size + 14)), line, font=font(size), fill=color)
    return card


def list_page(t, spec, items, start, count, page, pages, kind_label):
    v3 = spec.get("v3") or {}
    tid = spec.get("team_id")
    base, second, _ = colors(tid)
    im = background(t, tid)
    d = ImageDraw.Draw(im)
    _header(d, kind_label, f"{page}/{pages}", second)
    heading = spec.get("heading") or spec.get("label", "")
    hl, hs = _lines(d, heading, 52, SAFE_RIGHT - LEFT, 2)
    for i, line in enumerate(hl):
        d.text((LEFT, 250 + i * (hs + 10)), line, font=font(hs), fill=INK)
    # 進み具合の線
    d.rectangle((LEFT, 236, SAFE_RIGHT, 240), fill=_mix(base, (255, 255, 255), 0.15))
    d.rectangle((LEFT, 236, LEFT + round((SAFE_RIGHT - LEFT) * page / max(pages, 1)), 240), fill=GOLD)
    y = 250 + len(hl) * (hs + 10) + 44
    w = SAFE_RIGHT - LEFT
    for i, (head, body) in enumerate(items[start:start + count]):
        card = _item_card(head, body, w, base, second)
        if y + card.height > 1400:
            break
        _paste_card(im, card, LEFT, y, back_out((t - T_CARD0 - i * T_CARD_GAP) / SLIDE))
        y += card.height + 28
    ticker(im, t, v3.get("ticker"))
    source(d, page_source(items[start:start + count]), second)
    presenter(im, t)
    return im


# ------------------------------------------------------------------ 効果音の時刻
def people(t, spec, rows, heading, kind_label):
    """読み上げと同じ最大3人を表示。v3は声・立ち絵とも四国めたん。"""
    base, second, _ = colors(spec.get("team_id"))
    im = background(t, spec.get("team_id"))
    d = ImageDraw.Draw(im)
    _header(d, kind_label, "", second)
    d.text((LEFT, 250), heading, font=font(64), fill=INK)
    d.text((LEFT, 340), spec.get("label", ""), font=font(32), fill=second)
    y = 430
    for i, row in enumerate(rows[:3]):
        card = _item_card(row.get("name", ""), row.get("line", row.get("why", "")),
                          SAFE_RIGHT - LEFT, base, second)
        if y + card.height > 1400:
            break                                              # 収まらない分は描かない（動画は止めない）
        _paste_card(im, card, LEFT, y, back_out((t - T_CARD0 - i * T_CARD_GAP) / SLIDE))
        y += card.height + 28
    ticker(im, t, (spec.get("v3") or {}).get("ticker"))
    source(d, "出典: MLB公式（Stats API）", second)
    presenter(im, t)
    return im


def cues(kind, spec, items=(), start=0, count=0):
    """その画面の効果音 [(秒, 種類, 案, 追加の音量dB)]。描画と同じ時刻表から。"""
    v3 = spec.get("v3") or {}
    out = []
    if kind == "intro":
        out.append((T_WHO, "swish", "a", -4))
        if v3.get("big"):
            out.append((T_ROLL[0], "roll", "a", -2))
            out.append((T_ROLL[1] - 0.04, "stop", "a", 0))
        if v3.get("tag"):
            out.append((T_TAG, "marker", "a", -3))
        for i, c in enumerate((v3.get("chips") or [])[:4]):
            t0 = T_CHIP0 + i * T_CHIP_GAP
            out.append((t0, "swish", "b", -3))
            if c.get("win"):
                out.append((t0 + SLIDE + T_RING_AFTER, "pop", "a", -2))
    elif kind == "list":
        out.append((0.0, "transition", "b", -6))
        for i, (head, body) in enumerate(list(items)[start:start + count]):
            quote = "番記者" in head or str(body).startswith("「")
            out.append((T_CARD0 + i * T_CARD_GAP, "notify" if quote else "swish", "a", -3))
    return out
