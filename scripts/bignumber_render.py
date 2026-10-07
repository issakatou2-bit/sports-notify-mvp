#!/usr/bin/env python3
"""ショートの新デザイン 案B「数字ドーン」（Opus-11）。17:00 の成績の回に使う。

モック: collespo/指示書/mocks/B_BigNumber.dc.html（540×960 で描いてある。ここでは2倍の 1080×1920）。

  - 1場面に1つの大きな数字。カウントアップか、スロットのように回って止まるか、判を押すように出る。
  - 数字の後ろを、球団の2色目の大きな塊（斜めの平行四辺形）が左から入って支える。
    場面の終わりに右へ抜ける。塊の無い場面は、出だしで塊が横切る。
  - 背景には球団名の大きな透かし文字（線だけ）が、ゆっくり左右に動き続ける。
  - 数字の下に短い説明（材料の成績の行そのまま）と、小さな札（名前のある記録など）。

書き方は review_render_v3.py と同じ:
  - 時刻はすべて「その場面が出てからの秒」t。p（0〜1）は使わない。
  - 時刻表は下の定数。描画（scene）と効果音（cues）が同じ定数を見る。
  - 重い部品（文字の絵・数字の絵・透かし文字・場面の配置）は lru_cache で1回だけ作り、毎コマは貼るだけ。
  - 背景は動き続ける（コマを使い回さない）。色は review_render_v3.colors(team_id)。
  - 書体は ps_brand_components.font と review_render_v3.num_font。
  - 安全域（ps_render_template.SAFE_BOTTOM・SAFE_RIGHT）の外に大事な文字を置かない。

数字・言葉は材料にあるものだけ。足さない・言い換えない。
大きな数字は、材料の成績の行（headline など）の中の文字をそのまま切り出す（計算で作らない）。

使い方:
  import bignumber_render as bn
  scenes = bn.scenes_from_morning(data, narration)       # 17:00 の材料と原稿 → 場面の列
  plan = bn.timeline(scenes, durations)                  # 画面ごとの秒（plan_durations）で場面に時刻を付ける
  im = bn.frame(t, plan)                                 # 動画の t 秒目の絵（1080×1920、RGB）
  cues = bn.plan_cues(plan)                              # 効果音 [(秒, 種類, 案, 追加dB)] → sound_mix.mix_file

  python bignumber_render.py --material src/data/morning_recap.json --out build/bn   # 見本の PNG（作業場所は collespo/）
"""
import argparse
import functools
import json
import math
import pathlib
import re
import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

HERE = pathlib.Path(__file__).resolve().parent


def _find_root():
    """コレスポのコードのある場所。本番（scripts/ に置く）は1つ上。下書き（collespo/）では写しの src/。"""
    for cand in (HERE.parent, HERE / "src", HERE):
        if (cand / "scripts" / "review_render_v3.py").exists():
            return cand
    return HERE.parent


ROOT = _find_root()
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

import ps_brand_components as pbc  # noqa: E402

# ps_brand_components の書体が見つからない環境（この作業環境など）だけ、候補の最後に
# 手元の日本語書体を足す（動いている間だけ。ファイルは書き換えない）。
# コレスポの PC・Actions では最初の候補が見つかるので、何も変わらない。
FONT_FALLBACKS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "C:/Windows/Fonts/meiryob.ttc",
)


def ensure_font() -> bool:
    try:
        pbc.font(40)
        return True
    except (ValueError, OSError):
        pass
    path = next((p for p in FONT_FALLBACKS if pathlib.Path(p).exists()), None)
    if not path:
        return False
    for role in ("jp", "latin"):
        if path not in pbc.FONT_CANDIDATES[role]:
            pbc.FONT_CANDIDATES[role].append(path)
    try:
        pbc.font(40)
        return True
    except (ValueError, OSError):
        return False


ensure_font()

import review_render_v3 as r3  # noqa: E402
from ps_brand_components import font  # noqa: E402
from ps_render_template import SAFE_BOTTOM, SAFE_RIGHT  # noqa: E402

W, H = r3.W, r3.H
LEFT = r3.LEFT
INK, GOLD, DARK_INK = r3.INK, r3.GOLD, r3.DARK_INK
SOURCE = "出典：MLB公式（Stats API）"

# ------------------------------------------------------------------ 時刻表（秒）
# モックの b-scene / b-block / b-sub（12秒で3場面＝1場面4秒）を秒に直したもの。
T_FADE_IN = 0.36          # 場面が出る。1.18倍から縮みながら濃くなる（b-scene 0→3%）
FADE_SCALE = 1.18
T_BLOCK_IN = 0.72         # 色の塊が左から入りきる（b-block 0→6%）
T_SWEEP = 0.7             # 塊の無い場面で、塊が左から右へ横切る秒
T_OUT = 0.36              # 場面の終わりの、この秒数で塊が右へ抜け、場面が消える（30→33%）
T_ROLL = (0.25, 1.35)     # 数字が回り始める・止まる
SPINS = 2                 # 止まるまでに何周回るか
T_COUNT = (0.25, 1.15)    # カウントアップの始め・終わり
T_STAMP, STAMP = 0.3, 0.3  # 判を押すように出る（1.4倍→1倍）時刻と長さ
T_SUB = 0.6               # 説明が下から出始める（b-sub 5%）
SUB_IN = 0.48             # 出きるまで（b-sub 5→9%）
T_NOTE_GAP = 0.12         # 説明の行ごとの遅れ
T_CHIP0, T_CHIP_GAP = 1.5, 0.12   # 小さな札の1枚目と間隔（数字が止まる音のあと）
T_CARD0, T_CARD_GAP = 0.3, 0.25   # 札の画面（数字の無い場面）の札
SLIDE = r3.SLIDE          # 札が右から飛び込む秒（review_render_v3 と同じ）
DRIFT_SECONDS, DRIFT_PX = 14.0, 520   # 透かし文字: 14秒で 520px 左へ、行って戻る（b-drift）
BOB_SECONDS, BOB_PX = 2.4, 12         # 立ち絵が上下する（b-bob）

# ------------------------------------------------------------------ 配置（モックの2倍）
HEAD_BASE = 336           # 名前の行の基準線
BLOCK_TOP, BLOCK_BOTTOM = 420, 1080
BLOCK_LEFT = -60
SKEW = round(math.tan(math.radians(14)) * (BLOCK_BOTTOM - BLOCK_TOP) / 2)   # skewX(-14deg) の上下のずれ
NUM_MAX = 680             # 塊の上の数字（モック 340px）
PLAIN_NUM_MAX = 440       # 塊の無い場面の数字（モック 220px）
UNIT_MAX = 184            # 縦に積む単位（モック 92px）
CONTENT_BOTTOM = 1330     # 文字の下端。これより下は立ち絵（左下）と出典
PRESENTER_X = 36
SOURCE_X, SOURCE_BOTTOM = 300, 1552
WATERMARK_SIZE, WATERMARK_ALPHA = 760, 0x24 / 255   # Oswald 380px・線 2px・色 #c4ced424（モック）
WATERMARK_XY = (-80, 600)

# 大きな数字に選ぶもの（材料の行の中の「数字＋単位」）。上から見て、最小値以上の最初のもの。
# 投手は正の奪三振数。投球回や小数は選ばず、無い日は勝利貢献順位。
PICK = {
    "batter": (("本塁打", 1), ("打点", 1), ("安打", 1)),
    "pitcher": (("奪三振", 1),),
}
# カウントアップしない単位（数えると意味が変わる。motion.DENY_UNITS と同じ考え方）
NO_COUNT_UNITS = ("位", "年", "月", "日", "時", "分", "秒", "戦", "号", "番", "歳", "回")
MIN_COUNT = 10            # これより小さい整数は数えない（motion.MIN_COUNT と同じ）


def clamp(x):
    return max(0.0, min(1.0, x))


def ease_out(x):
    return r3.ease_out(x)


def ease_in_out(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def _rgb(c):
    return tuple(int(v) for v in c[:3])


# ------------------------------------------------------------------ 大きな数字を選ぶ
def pick_big(text, kind="batter"):
    """材料の行（例「4打数3安打　2本塁打　3打点」）から、大きく出す (数字, 単位) を選ぶ。
    正の整数だけを選ぶ。投球回の小数表記は大きな数字に使わない。"""
    text = str(text or "")
    rules = PICK.get(kind) or (PICK["batter"] + PICK["pitcher"])
    for unit, least in rules:
        for m in re.finditer(r"(?<![\d.])(\d+)" + re.escape(unit), text):
            if float(m.group(1)) > 0 and float(m.group(1)) >= least:
                return m.group(1), unit
    return "", ""


def anim_of(spec):
    """数字の出し方。roll（回って止まる）・count（カウントアップ）・stamp（判を押す）。"""
    a = spec.get("anim")
    if a in ("roll", "count", "stamp", "none"):
        return a
    big, unit = str(spec.get("big") or ""), str(spec.get("unit") or "")
    if big.isdigit() and int(big) >= MIN_COUNT and not big.startswith("0") \
            and not any(unit.startswith(u) for u in NO_COUNT_UNITS):
        return "count"
    return "roll"


def number_text(t, spec):
    """t 秒のときに画面に出ている数字の文字（途中は画面だけ。止まったら材料の文字そのもの）。"""
    big = str(spec.get("big") or "")
    a = anim_of(spec)
    if a == "count":
        k = (t - T_COUNT[0]) / (T_COUNT[1] - T_COUNT[0])
        if k >= 1:
            return big
        return str(round(int(big) * ease_out(k)))
    if a == "roll":
        k = (t - T_ROLL[0]) / (T_ROLL[1] - T_ROLL[0])
        if k >= 1:
            return big
        return "".join(str(math.floor(_roll_pos(int(c), k)) % 10) if c.isdigit() else c for c in big)
    if a == "stamp" and t < T_STAMP:
        return ""
    return big


def _roll_pos(target, k):
    return (target + 10 * SPINS) * ease_out(k)


# ------------------------------------------------------------------ 文字の絵（1回だけ作る）
@functools.lru_cache(maxsize=1024)
def _sprite(text, size, color, num=False, anchor="ls"):
    """文字を切り抜いた RGBA と、貼る位置のずれ。d.text((x, y), anchor=anchor) と同じ所に出る。"""
    f = r3.num_font(size) if num else font(size)
    x0, y0, x1, y1 = f.getbbox(text, anchor=anchor)
    pad = 4
    im = Image.new("RGBA", (max(1, x1 - x0 + 2 * pad), max(1, y1 - y0 + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), text, font=f, fill=_rgb(color) + (255,), anchor=anchor)
    return im, x0 - pad, y0 - pad


def _width(text, size, num=False):
    f = r3.num_font(size) if num else font(size)
    return f.getlength(str(text))


@functools.lru_cache(maxsize=64)
def _cap(size):
    """数字の高さ（基準線から上）。"""
    x0, y0, x1, y1 = r3.num_font(size).getbbox("0123456789", anchor="ls")
    return -y0


@functools.lru_cache(maxsize=256)
def _glyph(ch, size, color):
    """数字1文字の絵。幅は送り幅、高さは数字の高さ＋上下の余白。基準線は上から pad+cap。"""
    f = r3.num_font(size)
    cap, pad = _cap(size), round(size * 0.08)
    w = max(1, math.ceil(f.getlength(ch)))
    im = Image.new("RGBA", (w + 2 * pad, cap + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad, pad + cap), ch, font=f, fill=_rgb(color) + (255,), anchor="ls")
    return im, pad


@functools.lru_cache(maxsize=64)
def _chip(text, color, size=38):
    """小さな札（枠だけ。モックの「6-3」の札）。"""
    f = font(size)
    w = round(f.getlength(text)) + 48
    h = size + 30
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, w - 3, h - 3), radius=6, outline=_rgb(color) + (255,), width=4)
    d.text((24, h // 2), text, font=f, fill=INK + (255,), anchor="lm")
    return im


@functools.lru_cache(maxsize=64)
def _tag(text, size=40):
    """名前の前の金色の札（「2位」「ここ7日」）。"""
    f = font(size)
    w = round(f.getlength(text)) + 36
    h = size + 26
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8, fill=GOLD + (255,))
    d.text((18, h // 2), text, font=f, fill=DARK_INK + (255,), anchor="lm")
    return im


@functools.lru_cache(maxsize=128)
def _card(title, body, w, panel, second, title_size, body_size, max_lines):
    """札の画面の札（タイトル＋本文）。本文は折り返す（切らない）。"""
    lines, bs = wrap(body, body_size, w - 64, max_lines)
    pad = round(title_size * 0.8)
    h = pad + (title_size + 14 if title else 0) + len(lines) * (bs + 14) + pad - 14
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=22, fill=_rgb(panel) + (255,))
    d.rectangle((0, 18, 8, h - 18), fill=_rgb(second) + (255,))
    y = pad
    if title:
        d.text((32, y + title_size), title, font=font(title_size), fill=_rgb(second) + (255,), anchor="ls")
        y += title_size + 14
    for line in lines:
        d.text((32, y + bs), line, font=font(bs), fill=INK + (255,), anchor="ls")
        y += bs + 14
    return im


def wrap(text, size, width, max_lines=2, minimum=34):
    """折り返す。max_lines に入らなければ文字を小さくする（minimum まで）。文字は捨てない。"""
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    text = str(text or "")
    if not text:
        return [], size
    while True:
        lines, s = r3._lines(probe, text, size, width, 99)
        if len(lines) <= max_lines or size <= minimum:
            return lines, s
        size -= 4


# ------------------------------------------------------------------ 透かし文字
_TWO_WORD = ("Red Sox", "White Sox", "Blue Jays")


def team_word(team_id):
    """透かし文字にする球団の呼び名（英語、大文字）。MLB_TEAM_NAME_EN の後ろの語。"""
    import notability_engine as ne
    name = ne.MLB_TEAM_NAME_EN.get(str(team_id)) or ""
    if not name:
        return "MLB"
    for two in _TWO_WORD:
        if name.endswith(two):
            return two.upper()
    return name.split()[-1].upper()


@functools.lru_cache(maxsize=8)
def _watermark(word):
    """線だけの大きな文字（-8度傾ける）の型（L）と、傾ける前の文字の箱の中心。"""
    f = r3.num_font(WATERMARK_SIZE)
    x0, y0, x1, y1 = f.getbbox(word, anchor="ls")
    pad = 12
    size = (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
    full, inner = Image.new("L", size, 0), Image.new("L", size, 0)
    at = (pad - x0, pad - y0)
    ImageDraw.Draw(full).text(at, word, font=f, fill=255, anchor="ls", stroke_width=4, stroke_fill=255)
    ImageDraw.Draw(inner).text(at, word, font=f, fill=255, anchor="ls")
    line = ImageChops.subtract(full, inner)
    rot = line.rotate(8, expand=True, resample=Image.BICUBIC)
    # 文字の箱（CSS の div。行の高さ1）は (-80, 600) から。字の上端は箱の少し下
    cx = WATERMARK_XY[0] + size[0] / 2
    cy = WATERMARK_XY[1] + round(WATERMARK_SIZE * 0.08) + size[1] / 2
    return rot, cx, cy


def _paste_mask(im, color, mask, x, y):
    """mask（L）を (x, y) に置いて color で塗る。画面の外は切る。"""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(im.width, x + mask.width), min(im.height, y + mask.height)
    if x1 <= x0 or y1 <= y0:
        return
    im.paste(color, (x0, y0, x1, y1), mask.crop((x0 - x, y0 - y, x1 - x, y1 - y)))


def drift(t):
    """透かし文字の横のずれ（px）。行って戻る（linear alternate）。"""
    u = (t / DRIFT_SECONDS) % 2.0
    return -DRIFT_PX * (u if u <= 1 else 2 - u)


def background(t, team_id):
    """地の色＋ゆっくり動く透かし文字。t は動画の頭からの秒（場面をまたいで続く）。"""
    base, second, _ = r3.colors(team_id)
    im = Image.new("RGB", (W, H), base)
    mask, cx, cy = _watermark(team_word(team_id))
    x = round(cx + drift(t) - mask.width / 2)
    y = round(cy - mask.height / 2)
    _paste_mask(im, r3._mix(base, second, WATERMARK_ALPHA), mask, x, y)
    return im


# ------------------------------------------------------------------ 場面の配置（1回だけ計算する）
LAYOUT_KEYS = ("layout", "big", "unit", "pre", "tag", "head", "head2", "sub", "notes", "chips",
               "cards", "anim", "team_id")


def _key(spec):
    return json.dumps({k: spec.get(k) for k in LAYOUT_KEYS}, ensure_ascii=False, sort_keys=True)


def layout_of(spec):
    return _layout(_key(spec))


def _kind(spec):
    lay = spec.get("layout")
    if lay in ("block", "plain", "cards"):
        return lay
    return "block" if spec.get("big") else "cards"


# 塊の高さ。下の説明・札が入りきらないときだけ、塊を低くする（数字も小さくなる）
BLOCK_HEIGHTS = (BLOCK_BOTTOM - BLOCK_TOP, 600, 540, 480)


@functools.lru_cache(maxsize=256)
def _layout(key):
    spec = json.loads(key)
    for bh in (BLOCK_HEIGHTS if _kind(spec) == "block" else BLOCK_HEIGHTS[:1]):
        L = _build(spec, bh)
        if not L["dropped"]:
            break
    return L


def _skew(h):
    return round(math.tan(math.radians(14)) * h / 2)


def _build(spec, bh):
    base, second, panel = r3.colors(spec.get("team_id"))
    kind = _kind(spec)
    L = {"kind": kind, "pieces": [], "chips": [], "cards": [], "dropped": [], "block": None, "num": None,
         "unit": [], "base": base, "second": second, "panel": panel}
    pieces = L["pieces"]

    def piece(text, size, color, x, y, appear, num=False, role="text"):
        im, dx, dy = _sprite(text, size, _rgb(color), num)
        pieces.append({"text": text, "img": im, "x": x + dx, "y": y + dy, "appear": appear, "role": role})
        return x + _width(text, size, num)

    # 名前の行（金色の札・名前・所属）
    x = LEFT
    if spec.get("tag"):
        tg = _tag(spec["tag"])
        pieces.append({"text": spec["tag"], "img": tg, "x": x, "y": HEAD_BASE - tg.height + 12,
                       "appear": 0.0, "role": "tag"})
        x += tg.width + 24
    head = str(spec.get("head") or "")
    if head:
        size = 60
        room = SAFE_RIGHT - x - (_width(spec.get("head2") or "", 34) + 24 if spec.get("head2") else 0)
        while size > 40 and _width(head, size) > room:
            size -= 2
        x = piece(head, size, INK, x, HEAD_BASE, 0.0, role="head") + 24
    if spec.get("head2"):
        h2 = str(spec["head2"])
        if x + _width(h2, 34) <= SAFE_RIGHT:
            piece(h2, 34, second, x, HEAD_BASE, 0.0, role="head")
        else:
            L["dropped"].append(h2)

    big, unit, pre = str(spec.get("big") or ""), str(spec.get("unit") or ""), str(spec.get("pre") or "")
    y = BLOCK_TOP
    if kind == "block" and big:
        # 縦に積む単位
        bottom, skew = BLOCK_TOP + bh, _skew(bh)
        n = len(unit)
        us = min(round(UNIT_MAX * bh / BLOCK_HEIGHTS[0]), int((bh - 60) / (1.05 * max(n, 1)))) if n else 0
        room = SAFE_RIGHT - LEFT - 50 - skew - 30 - us
        size = round(NUM_MAX * bh / BLOCK_HEIGHTS[0] / 10) * 10
        while size > 240 and _width(big, size, True) > room:
            size -= 10
        nw = _width(big, size, True)
        cap = _cap(size)
        mid = (BLOCK_TOP + bottom) / 2
        L["num"] = {"text": big, "size": size, "x": LEFT, "base": round(mid + cap / 2), "w": nw,
                    "color": base, "anim": anim_of(spec)}
        right = LEFT + nw + 50
        L["block"] = {"right": right, "top": BLOCK_TOP, "bottom": bottom}
        ux = right + skew + 30
        top = mid - n * us * 1.05 / 2
        for i, ch in enumerate(unit):
            im, dx, dy = _sprite(ch, us, INK, False, "lt")
            L["unit"].append({"img": im, "x": round(ux) + dx, "y": round(top + i * us * 1.05) + dy, "text": ch})
        y = bottom + 44
    elif big:
        # 塊の無い場面: [前の言葉][数字][単位] を1行に、基準線をそろえる
        pw = _width(pre, 96) + 16 if pre else 0
        uw = _width(unit, 128) + 16 if unit else 0
        size = PLAIN_NUM_MAX
        while size > 200 and pw + _width(big, size, True) + uw > SAFE_RIGHT - LEFT:
            size -= 10
        cap = _cap(size)
        base_y = BLOCK_TOP + cap + 30
        if pre:
            piece(pre, 96, INK, LEFT, base_y, 0.0, role="unit")
        nx = LEFT + pw
        nw = _width(big, size, True)
        L["num"] = {"text": big, "size": size, "x": nx, "base": base_y, "w": nw, "color": GOLD,
                    "anim": anim_of(spec)}
        if unit:
            piece(unit, 128, INK, nx + nw + 16, base_y, 0.0, role="unit")
        y = base_y + 56

    # 説明（材料の行）・補足・小さな札
    t_next = T_SUB
    if spec.get("sub"):
        size = 60 if kind == "block" else 56
        lines, s = wrap(spec["sub"], size, SAFE_RIGHT - LEFT, 1, 48)     # 1行に入るならそのまま
        if len(lines) > 1:
            lines, s = wrap(spec["sub"], size - 4, SAFE_RIGHT - LEFT, 2, 40)
        for line in lines:
            if y + s > CONTENT_BOTTOM:
                L["dropped"].append(line)
                continue
            piece(line, s, GOLD if kind == "block" else INK, LEFT, y + s, t_next, role="sub")
            y += s + 18
            t_next += T_NOTE_GAP
        y += 10
    for note in spec.get("notes") or []:
        lines, s = wrap(note, 36, SAFE_RIGHT - LEFT, 2, 30)
        for line in lines:
            if y + s > CONTENT_BOTTOM:
                L["dropped"].append(line)
                continue
            piece(line, s, second, LEFT, y + s, t_next, role="note")
            y += s + 12
        t_next += T_NOTE_GAP
    chips = [str(c) for c in (spec.get("chips") or []) if c]
    if chips:
        y += 14
        cx = LEFT
        for i, c in enumerate(chips):
            im = _chip(c, _rgb(second))
            if cx + im.width > SAFE_RIGHT:
                cx, y = LEFT, y + im.height + 14
            if y + im.height > CONTENT_BOTTOM:
                L["dropped"].append(c)
                continue
            L["chips"].append({"text": c, "img": im, "x": cx, "y": y, "appear": T_CHIP0 + len(L["chips"]) * T_CHIP_GAP})
            cx += im.width + 16
        y += 80

    # 札の画面（数字の無い場面）の札。入りきるまで文字を小さくする
    cards = spec.get("cards") or []
    if cards:
        y = max(y, BLOCK_TOP)
        for ts, bs, ml, gap in ((36, 48, 3, 22), (32, 42, 3, 16), (30, 38, 2, 12), (28, 34, 2, 10)):
            ims = [_card(str(c.get("title") or ""), str(c.get("body") or ""), SAFE_RIGHT - LEFT,
                         _rgb(panel), _rgb(second), ts, bs, ml) for c in cards]
            if y + sum(im.height for im in ims) + gap * (len(ims) - 1) <= CONTENT_BOTTOM:
                break
        for i, (c, im) in enumerate(zip(cards, ims)):
            if y + im.height > CONTENT_BOTTOM:
                L["dropped"].append(str(c.get("body") or ""))
                continue
            L["cards"].append({"text": [c.get("title") or "", c.get("body") or ""], "img": im, "x": LEFT,
                               "y": y, "appear": T_CARD0 + len(L["cards"]) * T_CARD_GAP})
            y += im.height + gap
    L["bottom"] = y
    return L


# ------------------------------------------------------------------ 描く
def _put(target, img, x, y, alpha=1.0):
    """RGBA の絵を target（RGB の画面か、透明の層）に重ねる。"""
    if alpha <= 0:
        return
    x, y = int(round(x)), int(round(y))
    if alpha < 1:
        img = img.copy()
        img.putalpha(img.getchannel("A").point([round(a * alpha) for a in range(256)]))
    if target.mode == "RGBA":
        sx, sy = max(0, -x), max(0, -y)
        if sx >= img.width or sy >= img.height or x >= target.width or y >= target.height:
            return
        if sx or sy:
            img = img.crop((sx, sy, img.width, img.height))
        target.alpha_composite(img, (x + sx, y + sy))
    else:
        target.paste(img, (x, y), img)


def _block_poly(left, right, dx, top=BLOCK_TOP, bottom=BLOCK_BOTTOM):
    skew = _skew(bottom - top)
    return [(left + skew + dx, top), (right + skew + dx, top),
            (right - skew + dx, bottom), (left - skew + dx, bottom)]


def _draw_block(target, t, L, dur):
    second = _rgb(L["second"]) + (255,)
    d = ImageDraw.Draw(target)
    if L["block"]:
        b = L["block"]
        skew = _skew(b["bottom"] - b["top"])
        span = b["right"] - BLOCK_LEFT + 2 * skew
        dx = -(span + 40) * (1 - ease_out(t / T_BLOCK_IN))     # 左から入る
        if dur:
            k = clamp((t - (dur - T_OUT)) / T_OUT)
            dx += (W - BLOCK_LEFT + skew) * 1.2 * k ** 2         # 右へ抜ける
        d.polygon(_block_poly(BLOCK_LEFT, b["right"], round(dx), b["top"], b["bottom"]), fill=second)
    elif t < T_SWEEP:
        width = 720
        dx = -width - 2 * SKEW + (W + width + 4 * SKEW) * ease_in_out(t / T_SWEEP)
        d.polygon(_block_poly(0, width, round(dx)), fill=second)


def _draw_number(target, t, L):
    n = L["num"]
    if not n:
        return
    size, color, anim, text = n["size"], _rgb(n["color"]), n["anim"], n["text"]
    if anim == "stamp":
        if t < T_STAMP:
            return
        k = clamp((t - T_STAMP) / STAMP)
        scale = 1.0 + 0.4 * (1 - ease_out(k))
        im, dx, dy = _sprite(text, size, color, True)
        if scale != 1.0:
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.BILINEAR)
        cx, cy = n["x"] + n["w"] / 2, n["base"] - _cap(size) / 2
        _put(target, im, round(cx - im.width / 2), round(cy - im.height / 2), min(1.0, k * 3))
        return
    shown = number_text(t, {"big": text, "anim": anim, "unit": ""}) if anim == "count" else text
    if anim == "count":
        # 右寄せ。桁が増えても単位の位置は動かない
        x = n["x"] + n["w"] - _width(shown, size, True)
    else:
        x = n["x"]
    k = (t - T_ROLL[0]) / (T_ROLL[1] - T_ROLL[0])
    for ch in shown:
        g, pad = _glyph(ch, size, color)
        top = n["base"] - _cap(size) - pad
        if anim == "roll" and ch.isdigit() and k < 1:
            pos = _roll_pos(int(ch), k)
            frac = pos - math.floor(pos)
            shown = [(_glyph(str(j), size, color)[0], off) for j, off in
                     ((math.floor(pos) % 10, -frac), ((math.floor(pos) + 1) % 10, 1 - frac))]
            win = Image.new("RGBA", (max(g.width for g, _ in shown), g.height), (0, 0, 0, 0))
            for gj, off in shown:
                _put(win, gj, 0, round(off * g.height))     # 窓の外（上下）は切れる
            _put(target, win, round(x) - pad, top)
        else:
            _put(target, g, round(x) - pad, top)
        x += _width(ch, size, True)


def _draw_content(target, t, L, dur):
    _draw_block(target, t, L, dur)
    _draw_number(target, t, L)
    for u in L["unit"]:
        _put(target, u["img"], u["x"], u["y"])
    for p in L["pieces"]:
        if p["appear"] <= 0:
            _put(target, p["img"], p["x"], p["y"])
            continue
        k = ease_out((t - p["appear"]) / SUB_IN)
        _put(target, p["img"], p["x"], p["y"] + round(32 * (1 - k)), k)
    for c in L["chips"]:
        k = ease_out((t - c["appear"]) / 0.3)
        _put(target, c["img"], c["x"], c["y"] + round(24 * (1 - k)), k)
    for c in L["cards"]:
        k = r3.back_out((t - c["appear"]) / SLIDE)
        if k > 0:
            _put(target, c["img"], c["x"] + round(140 * (1 - k)), c["y"], min(1.0, k * 1.6))


@functools.lru_cache(maxsize=4)
def _bar_bg(base):
    return r3._mix(base, (255, 255, 255), 0.12)


def _chrome(im, tg, t, spec, base, second):
    """場面をまたいで残るもの: 上の見出し・進み具合の線・出典・立ち絵。"""
    d = ImageDraw.Draw(im)
    x = LEFT
    logo, dx, dy = _sprite("コレスポ", 44, GOLD)
    im.paste(logo, (x + dx, 212 + dy), logo)
    label = str(spec.get("label") or "")
    if label:
        lab, dx, dy = _sprite(label, 28, _rgb(second))
        im.paste(lab, (x + round(_width("コレスポ", 44)) + 28 + dx, 212 + dy), lab)
    d.rectangle((LEFT, 240, SAFE_RIGHT, 247), fill=_bar_bg(base))
    p0, p1 = spec.get("progress") or (0.0, 0.0)
    dur = spec.get("dur")
    p = p0 + (p1 - p0) * (clamp(t / dur) if dur else 0.0)
    if p > 0:
        d.rectangle((LEFT, 240, LEFT + round((SAFE_RIGHT - LEFT) * min(1.0, p)), 247), fill=GOLD)
    src = str(spec.get("source") if spec.get("source") is not None else SOURCE)
    if src:
        lines, s = wrap(src, 24, SAFE_RIGHT - SOURCE_X, 2, 22)
        for i, line in enumerate(lines):
            sp, dx, dy = _sprite(line, s, _rgb(second))
            yb = SOURCE_BOTTOM - (len(lines) - 1 - i) * (s + 8)
            im.paste(sp, (SOURCE_X + dx, yb + dy), sp)
    who = spec.get("who") or "metan"
    if who != "none":
        sp = r3._portrait(who)
        bob = round(BOB_PX * (0.5 - 0.5 * math.cos(2 * math.pi * tg / BOB_SECONDS)))
        im.paste(sp, (PRESENTER_X, SAFE_BOTTOM - 4 - sp.height - bob), sp)


def scene(t, scene_spec, team_id=None):
    """1場面の t 秒目の絵（1080×1920、RGB）。

    scene_spec の例: {"big": "3", "unit": "安打", "head": "大谷翔平", "sub": "4打数3安打", "team_id": 119}
      layout: block（塊の上の数字）/ plain（塊なし）/ cards（数字なし・札だけ）。無ければ big の有無で決める
      anim: roll / count / stamp。無ければ数字と単位で決める（anim_of）
      tag・head・head2: 名前の行。sub: 説明（材料の行）。notes: 補足の行。chips: 小さな札
      pre: 数字の前の言葉（plain だけ。「あと」）。cards: [{"title", "body"}]
      label: 上の見出し。who: 立ち絵（metan / zundamon / none）。source: 出典
      t0（動画の中の始まり）・dur（場面の長さ）・progress（[始め, 終わり] 0〜1）は timeline が付ける
    team_id を渡すと scene_spec の team_id より優先する。
    """
    spec = dict(scene_spec)
    if team_id is not None:
        spec['team_id'] = team_id
    import v3_slot_render as common
    view = unified_spec(spec)
    rows = [(c.get('title',''), c.get('body','')) for c in spec.get('cards', [])]
    if (spec.get('rank') or 0) > 1 or not spec.get('big') or rows:
        ranked_head = (f"{spec['rank']}位　" if spec.get('rank') else '')+spec.get('head','')
        rows = rows or [(ranked_head, spec.get('sub',''))]
        rows += [('', str(x)) for x in spec.get('notes', [])]
        return common.frame(t, view, rows, spec.get('label') or '日本人選手の成績', spec.get('source') or SOURCE)
    im = r3.intro(t, view, spec.get('label') or '日本人選手の成績')
    r3.source(ImageDraw.Draw(im), spec.get('source') or SOURCE, r3.colors(spec.get('team_id'))[1])
    return im


def unified_spec(spec):
    from notability_engine import MLB_TEAM_ABBR
    tid = spec.get('team_id')
    rank = spec.get('rank')
    return {'team_id': tid, 'abbr': MLB_TEAM_ABBR.get(str(tid), ''),
            'heading': '　'.join(str(spec.get(k) or '') for k in ('head', 'head2')).strip(),
            'v3': {'who': '　'.join(str(spec.get(k) or '') for k in ('head', 'head2')).strip(),
                   'big': str(spec.get('big') or ''), 'unit': str(spec.get('unit') or ''),
                   'sub': f'勝利貢献 第{rank}位' if rank else spec.get('pre') or spec.get('tag',''),
                   'tag': spec.get('sub') or spec.get('head2',''),
                   'chips': spec.get('player_chips', []),
                   'ticker': spec.get('ticker', '')}}



# ------------------------------------------------------------------ 効果音の時刻
def cues(scene_spec):
    """その場面の効果音 [(秒, 種類, 案, 追加の音量dB)]。描画と同じ時刻表・同じ配置から。"""
    if (scene_spec.get('rank') or 0) > 1 or not scene_spec.get('big') or scene_spec.get('cards'):
        rows = [(c.get('title',''), c.get('body','')) for c in scene_spec.get('cards', [])]
        rows = rows or [(scene_spec.get('head',''), scene_spec.get('sub',''))]
        rows += [('', str(x)) for x in scene_spec.get('notes', [])]
        out = r3.cues('list', unified_spec(scene_spec), rows, 0, len(rows))
    else:
        out = r3.cues('intro', unified_spec(scene_spec))
    dur = scene_spec.get('dur')
    return [c for c in out if not dur or c[0] < dur - T_OUT]



def texts(scene_spec):
    """その場面に（出そろったときに）描かれる文字の一覧。検査用。"""
    L = layout_of(scene_spec)
    out = ["コレスポ", str(scene_spec.get("label") or "")]
    src = scene_spec.get("source") if scene_spec.get("source") is not None else SOURCE
    out.append(str(src))
    if L["num"]:
        out.append(L["num"]["text"])
    out.append("".join(u["text"] for u in L["unit"]))
    out += [p["text"] for p in L["pieces"]]
    out += [c["text"] for c in L["chips"]]
    for c in L["cards"]:
        out += [str(x) for x in c["text"]]
    return [x for x in out if x]


def boxes(scene_spec):
    """大事な文字の箱 [(文字, (x0, y0, x1, y1))]。安全域の検査用（出そろったときの位置）。"""
    L = layout_of(scene_spec)
    out = []
    for p in L["pieces"] + L["chips"] + L["cards"] + L["unit"]:
        bx = p["img"].getbbox() or (0, 0, 0, 0)          # 色の付いているところ（透明の余白は除く）
        out.append((str(p["text"]), (p["x"] + bx[0], p["y"] + bx[1], p["x"] + bx[2], p["y"] + bx[3])))
    n = L["num"]
    if n:
        out.append((n["text"], (n["x"], n["base"] - _cap(n["size"]), n["x"] + n["w"], n["base"])))
    return out


# ------------------------------------------------------------------ 場面の列 → 動画の時刻
MIN_CHARS = 12            # 読み上げの短い場面にも、これだけの文字数ぶんの秒を取る
CHARS_PER_SECOND = 7.0    # 見本を作るときだけ使う（本番は音声の長さ）


def timeline(scenes, durations):
    """画面（読み上げの区切り）ごとの秒から、場面ごとの始まり t0・長さ dur・進み具合を付けた列。

    1つの画面に場面が2つ以上あるときは、読み上げの文字数で分ける（ps_program.focus_plan と同じ考え方）。
    """
    durations = [float(d) for d in durations]
    segs = sorted({int(s.get("segment", 0)) for s in scenes})
    if segs and segs[-1] >= len(durations):
        raise ValueError("画面の数と秒の数が合いません")
    total = sum(durations) or 1.0
    starts = [sum(durations[:i]) for i in range(len(durations))]
    plan = []
    for i, dur in enumerate(durations):
        group = [s for s in scenes if int(s.get("segment", 0)) == i]
        if not group:
            continue
        weights = [max(len(str(s.get("say") or "")), MIN_CHARS) for s in group]
        t = starts[i]
        for s, w in zip(group, weights):
            d = dur * w / sum(weights)
            plan.append(dict(s, t0=round(t, 4), dur=round(d, 4), progress=[t / total, (t + d) / total]))
            t += d
    return plan


def frame(t, plan):
    """動画の t 秒目の絵。"""
    if not plan:
        raise ValueError("場面がありません")
    cur = plan[0]
    for s in plan:
        if s["t0"] <= t:
            cur = s
        else:
            break
    return scene(t - cur["t0"], cur)


def plan_cues(plan):
    """動画全体の効果音 [(秒, 種類, 案, 追加dB)]。sound_mix.mix_file(cues=...) にそのまま渡す。"""
    out = []
    for s in plan:
        out += [(round(s["t0"] + at, 4), k, v, db) for at, k, v, db in cues(s)]
    return out


def estimate_durations(narration):
    """見本用の秒（音声が無いとき）。本番は generate_morning_short.plan_durations(segs) を使う。"""
    gms = _gms()
    return [max(float(gms.MIN_DURATION.get(s.get("kind"), 5.0)),
                len(s.get("text") or "") / CHARS_PER_SECOND + 0.7)
            for s in narration["segments"]]


# ------------------------------------------------------------------ 17:00 の成績の回 → 場面の列
def _gms():
    import generate_morning_short
    return generate_morning_short


def _mr():
    import morning_recap
    return morning_recap


WHO = {"四国めたん": "metan", "ずんだもん": "zundamon"}


def _player_scene(p, say, tag="", rank=None):
    """1人の成績の場面。大きな数字は成績の行（headline）から切り出す。"""
    head = str(p.get("headline") or "")
    big, unit = pick_big(head, p.get("type"))
    chips = list(_mr().badge_labels(p, 3))
    if p.get("clutch_label"):
        chips.append(p["clutch_label"])
    notes = [p["clutch_note"]] if p.get("clutch_note") else []
    sc = {"layout": "block", "big": big, "unit": unit, "tag": tag, "head": p.get("name", ""),
          "head2": p.get("team_jp", ""), "sub": head, "notes": notes, "chips": chips,
          "team_id": p.get("team_id"), "rank": rank, "say": say}
    if not big and rank is not None:
        sc.update(layout="plain", big=str(rank), unit="位", anim="stamp",
                  tag="勝利貢献順位", ranking_name=p.get("name", ""))
    elif not big:
        sc.update(layout="cards", big="", unit="", sub="",
                  cards=[{"title": p.get("team_jp", ""), "body": head}])
    return sc


def _intro_scenes(seg, players, day):
    """冒頭: 1位の成績（数字ドーン）→「○人の成績」。build_narration の intro と同じ組み立て。"""
    gms, mr = _gms(), _mr()
    top = players[0] if players else {}
    out = []
    if top:
        named = mr.badge_speech(top, limit=2)
        say = f"{top['name']}は{gms.yomi_stats(top['headline'])}。"
        walked = gms.on_base_lead(top)
        if walked:
            say = walked
        if named:
            say += "%s。" % "に".join(named)
        shot = gms.hr_detail(top)
        if shot:
            say += "%s。" % shot
        rare = gms.rare_lines(top, limit=2) if (mr.quiet_day(players) or len(players) <= 2) else []
        for line in rare:
            say += "%s。" % line
        sc = _player_scene(top, say, rank=1)
        sc["notes"] = [x for x in [shot] + list(rare) if x] + sc["notes"]
        out.append(sc)
    head = gms.INTRO_HEADINGS["players"][0]
    out.append({"layout": "plain", "big": str(len(players)), "unit": "人", "head": day,
                "sub": head, "chips": [p.get("name", "") for p in players],
                "player_chips": [{'label': p.get('name',''), 'score': ''.join(pick_big(p.get('headline'), p.get('type'))) or f'勝利貢献 {i}位'} for i,p in enumerate(players,1)],
                "team_id": top.get("team_id"),
                "say": f"{day}、日本人選手{len(players)}人の成績です。"})
    return out


def _list_scenes(seg, players, top_name):
    """一覧: generate_morning_short.spoken_list と同じ分け方で、読み上げる人ごとに1場面。"""
    gms, mr = _gms(), _mr()
    meta = seg.get("meta") or {}
    start = int(meta.get("start", 0))
    chunk = players[start:start + int(meta.get("count", 1))]
    out, skipped = [], []
    for j, p in enumerate(chunk):
        rank = start + j + 1
        if top_name and p.get("name") == top_name:
            out.append({"layout": "plain", "big": str(rank), "unit": "位", "anim": "stamp",
                        "head": p.get("name", ""), "head2": p.get("team_jp", ""),
                        "sub": p.get("headline", ""), "chips": list(mr.badge_labels(p, 3)),
                        "team_id": p.get("team_id"), "say": f"{rank}位は{p['name']}。"})
            continue
        if gms.worth_speaking(p, rank):
            named = mr.badge_speech(p, limit=2)
            say = (f"{rank}位、{p['name']}、{gms.yomi_stats(p['headline'])}。"
                   + (f"{'に'.join(named)}。" if named else "")
                   + (f"{p['clutch_label']}。" if p.get("clutch_label") else ""))
            out.append(_player_scene(p, say, tag=f"{rank}位", rank=rank))
        else:
            skipped.append((rank, p))
    if not out and chunk:
        p = chunk[0]
        out.append(_player_scene(p, f"{start + 1}位、{p['name']}、{gms.yomi_stats(p['headline'])}。",
                                 tag=f"{start + 1}位", rank=start + 1))
        skipped = [x for x in skipped if x[1] is not p]
    if skipped:
        said = [gms._surname_only(p.get("name", "")) for _, p in skipped if p.get("name")]
        say = ("ほか、" + "、".join(said) + "。") if said else f"ほか{len(skipped)}人は画面のとおりです。"
        out.append({"layout": "cards", "head": "ほか", "team_id": skipped[0][1].get("team_id"),
                    "cards": [{"title": f"{rank}位　{p.get('name', '')}（{p.get('team_jp', '')}）",
                               "body": p.get("headline", "")} for rank, p in skipped],
                    "say": say})
    return out


def _week_scenes(seg, players, days=7):
    """ここ7日: generate_morning_short.week_line と同じ組み立て（行は meta["week"]）。"""
    gms = _gms()
    rows = (seg.get("meta") or {}).get("week") or []
    team = {p.get("name"): p.get("team_id") for p in players}
    out = []
    for i, r in enumerate(rows[:2]):
        if i == 0:
            say = f"ここ{days}日では、{gms.speech_name(r['name'])}が{gms.yomi_stats(r['line'])}。"
            if r.get("late") and r.get("trend"):
                say += f"{gms.yomi_stats(r['late'])}で、{r['trend']}ところです。"
            elif r.get("late"):
                say += f"{gms.yomi_stats(r['late'])}です。"
        else:
            say = f"{gms.speech_name(r['name'])}は{gms.yomi_stats(r['line'])}。"
        big, unit = pick_big(r.get("line", ""), r.get("type"))
        out.append({"layout": "block" if big else "cards", "big": big, "unit": unit, "tag": f"ここ{days}日",
                    "head": r.get("name", ""), "sub": r.get("line", ""),
                    "notes": [r["late"]] if r.get("late") else [],
                    "chips": [r["trend"]] if r.get("trend") else [],
                    "cards": [] if big else [{"title": r.get("name", ""), "body": r.get("line", "")}],
                    "team_id": team.get(r.get("name")), "say": say})
    return out


def _reach_scenes(seg, players):
    """あと少しで届く記録: build_narration の reach と同じ組み立て（行は meta["reach"]）。"""
    gms = _gms()
    rows = (seg.get("meta") or {}).get("reach") or []
    team = {p.get("name"): p.get("team_id") for p in players}
    out = []
    for i, r in enumerate(rows):
        say = ("あと少しで届く記録です。" if i == 0 else "") + f"{gms.speech_name(r['name'])}は{r['text']}。"
        big = str(r.get("big", r.get("gap", "")))
        sc = {"layout": "plain", "pre": str(r.get("prefix", "あと")), "big": big, "unit": "",
              "head": r.get("name", ""), "sub": str(r.get("goal_text") or ""),
              "notes": [str(r["small"])] if r.get("small") else [],
              "chips": [str(r["kind"])] if r.get("kind") else [],
              "team_id": team.get(r.get("name")), "say": say}
        if not re.fullmatch(r"\d+", big):
            sc.update(layout="cards", big="", pre="", sub="", notes=[],
                      cards=[{"title": r.get("name", ""), "body": r.get("text", "")}])
        out.append(sc)
    return out


def _praise_scenes(seg, data):
    rows = ((data.get("voices") or {}).get("jp_praise") or [])[:int((seg.get("meta") or {}).get("count", 3))]
    return [{"layout": "cards", "head": "現地は何と言ったか",
             "cards": [{"title": "、".join(v.get("jp_players") or []), "body": (v.get("ja") or "").strip()}
                       for v in rows],
             "source": "MLB公式ハイライトのコメント欄・翻訳", "say": seg.get("text", "")}]


def _outro_scenes(seg):
    gms = _gms()
    import post_common
    rows = post_common.lineup(gms.MODE_KIND.get("players", ""))
    return [{"layout": "cards", "head": "コレスポ", "head2": "毎日、更新中",
             "cards": [{"title": name, "body": what} for _, name, what, _ in rows],
             "source": "音声: VOICEVOX:四国めたん　データ: MLB Stats API",
             "say": seg.get("text", "")}]


def scenes_from_morning(data, narration=None):
    """17:00 の成績の回（generate_morning_short --mode players）の材料と原稿から、場面の列を作る。

    data: morning_recap の材料（data/morning_recap.json。main と同じく players は貢献度順に並べ直す）。
    narration: build_narration(data, "players") の結果。無ければここで作る（読み上げは変えない）。

    場面は読み上げの順番どおり。場面ごとに say（その場面で読む部分の文字そのもの）と
    segment（何枚目の画面＝読み上げの区切りか）を持つ。1つの画面の say をつなぐと、その画面の読み上げと一致する
    （check_scenes で確かめる）。
    """
    gms = _gms()
    players = gms.sort_players(list(data.get("players") or []))
    if narration is None:
        narration = gms.build_narration(dict(data, players=players), "players")
    day = str(narration.get("label") or gms.jp_date(gms.recap_day(data)))
    label = f"{gms.INTRO_HEADINGS['players'][0]}　{day}"
    top = players[0] if players else {}
    out = []
    for i, seg in enumerate(narration.get("segments") or []):
        kind = seg.get("kind")
        if kind == "intro":
            got = _intro_scenes(seg, players, day)
        elif kind == "list":
            got = _list_scenes(seg, players, top.get("name", ""))
        elif kind == "week":
            got = _week_scenes(seg, players)
        elif kind == "reach":
            got = _reach_scenes(seg, players)
        elif kind == "praise":
            got = _praise_scenes(seg, data)
        elif kind == "outro":
            got = _outro_scenes(seg)
        else:
            got = [{"layout": "cards", "cards": [{"title": "", "body": seg.get("text", "")}],
                    "say": seg.get("text", "")}]
        _attach_bookend(got, seg.get("text", ""))
        who = WHO.get((seg.get("meta") or {}).get("who"), "metan")
        for sc in got:
            sc.setdefault("team_id", top.get("team_id"))
            if sc.get("team_id") is None:
                sc["team_id"] = top.get("team_id")
            sc.update(segment=i, kind=kind, label=label, who=who,
                      ticker='きょうの日本人選手　'+'　'.join(f'{j}位 {p.get("name", "")}' for j,p in enumerate(players,1)))
        out += got
    return out


def _attach_bookend(scenes, text):
    """「コレスポ。」（bookend）のように、画面の読み上げの前後に付いた言葉を、最初・最後の場面に足す。"""
    if not scenes:
        return
    joined = "".join(s.get("say", "") for s in scenes)
    if joined == text or not joined:
        return
    at = text.find(joined)
    if at < 0:
        return                      # ずれている。check_scenes が知らせる
    scenes[0]["say"] = text[:at] + scenes[0]["say"]
    scenes[-1]["say"] = scenes[-1]["say"] + text[at + len(joined):]


def check_scenes(scenes, narration, data=None):
    """場面と読み上げが1対1に対応しているか。問題の一覧（空なら良し）。

    - 1つの画面の場面の say をつなぐと、その画面の読み上げと同じ
    - 大きな数字（前の言葉・数字・単位）が、その場面の読み上げに入っている（読み方は yomi_stats でそろえる）
    """
    gms = _gms()
    out = []
    segs = narration.get("segments") or []
    for i, seg in enumerate(segs):
        joined = "".join(s.get("say", "") for s in scenes if s.get("segment") == i)
        if joined != seg.get("text", ""):
            out.append(f"{i + 1}枚目（{seg.get('kind')}）: 場面と読み上げがずれています")
    for s in scenes:
        if s.get("big"):
            if float(s["big"]) == 0:
                out.append("大きな数字に0を選んでいます")
            if s.get("ranking_name"):
                players = gms.sort_players((data or {}).get("players") or [])
                rank = next((i + 1 for i, p in enumerate(players)
                             if p.get("name") == s["ranking_name"]), None)
                if (s["big"], s.get("unit"), s.get("tag")) != (str(rank), "位", "勝利貢献順位"):
                    out.append("大きな順位が当日の勝利貢献順と合いません")
                continue
            said = gms.yomi_stats(f"{s.get('pre') or ''}{s['big']}{s.get('unit') or ''}")
            if said not in s.get("say", ""):
                out.append(f"「{s['big']}{s.get('unit') or ''}」が読み上げ（{s.get('say')}）にありません")
    return out


# ------------------------------------------------------------------ 見本
def _no_network():
    """見本・検査で外へ出ないように（材料は写しの data/ だけ）。"""
    import urllib.request

    def refuse(*a, **k):
        raise OSError("この作業では外部APIを呼びません")
    urllib.request.urlopen = refuse


def main(argv=None):
    ap = argparse.ArgumentParser(description="案B「数字ドーン」の見本（PNG）を作る")
    ap.add_argument("--material", default=str(ROOT / "data/morning_recap.json"))
    ap.add_argument("--out", default="build/bignumber")
    ap.add_argument("--at", type=float, default=2.2, help="場面が出てから何秒目を描くか")
    ap.add_argument("--width", type=int, default=540, help="保存する幅（軽くするため。1080で原寸）")
    ap.add_argument("--prefix", default="bn_", help="ファイル名の頭")
    args = ap.parse_args(argv)
    _no_network()
    import os
    data = json.loads(pathlib.Path(args.material).read_text(encoding="utf-8"))
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    here = os.getcwd()
    os.chdir(ROOT)                  # morning_recap などは data/… を作業場所から読む
    try:
        scenes = scenes_from_morning(data)
        narration = _gms().build_narration(dict(data, players=_gms().sort_players(data.get("players") or [])),
                                           "players")
    finally:
        os.chdir(here)
    problems = check_scenes(scenes, narration, data=data)
    plan = timeline(scenes, estimate_durations(narration))
    for i, s in enumerate(plan):
        im = scene(min(args.at, s["dur"] - T_OUT - 0.05), s)
        if args.width != W:
            im = im.resize((args.width, round(H * args.width / W)), Image.LANCZOS)
        im = im.quantize(256)                      # 見本は軽く（256色）
        im.save(out / f"{args.prefix}{i + 1:02d}_{s['kind']}.png", optimize=True)
    print(json.dumps({"scenes": len(plan), "problems": problems, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
