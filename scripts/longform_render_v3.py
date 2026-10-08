#!/usr/bin/env python3
"""長編（横長 1920×1080）の新デザイン「電光掲示板」で、台詞1つぶんの画面を描く（下書き）。

指示書: collespo/指示書/Opus-18.md
モック: collespo/指示書/mocks/E_Longform.dc.html（960×540 で描いてあるので、ここでは座標を2倍）

何をするか:
  generate_longform.render_line(p, seg, portrait_dir, topic, panel, state, score) と
  **同じ材料**を受けて、同じ大きさ（1920×1080）の絵を返す。違うのは最初の引数だけで、
  p（0〜1の進み具合）の代わりに t（その台詞が出てからの秒）を受ける。
  ショートの新デザイン（scripts/review_render_v3.py）と同じく、背景が動き続けるため。

画面の割りつけ（モックの2倍）:
    ┌──────────────────────────────────────────────────────────┐
    │コレスポ 回の題                         [1 章][2 章][3 章] │ ← 上の帯（章の札は材料にあるときだけ）
    │━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 進み具合の線                  │
    │┌───────────────────────────┐                             │
    ││ 札（panel の種類ごと）       │         ずんだもん  四国めたん│
    │└───────────────────────────┘                             │
    │┌[名前]─────────────────────────────┐                     │
    ││ 字幕（左から現れる）                 │                     │
    │└───────────────────────────────────┘                     │
    │音声: VOICEVOX …                                           │
    └──────────────────────────────────────────────────────────┘

決まり（指示書より）:
  - 札の**数字・言葉は panel にあるものだけ**。計算で新しい数字を作らない
    （再生回数も「125.2万」に丸めず、材料の数をそのまま 1,252,420 と描く）。
    順位の目盛りの位置だけは「276人中4位」から割り出すが、割った数は描かない。
  - 動きと効果音は、下の「時刻表」の定数だけを見る。cues() も同じ定数から時刻を返す。
  - 立ち絵は四国めたん（大きく）・ずんだもん（少し小さく）。話している方を明るく。

使い方:
  import longform_render_v3 as lr3
  im = lr3.render_line(t, seg, topic=topic, panel=current, score=score,
                       chapters=chapters, progress=0.4, panel_t=t + 2.0)
  cue = lr3.cues(seg, current, panel_since=2.0)   # [(秒, 種類, 案, 追加の音量dB)]
"""

import functools
import math
import os
import pathlib
import re
import sys

# ---------------------------------------------------------------------------
# コレスポの部品（scripts/）を読む場所
# ---------------------------------------------------------------------------
# この作業リポジトリでは collespo/src/scripts に写しがある。コレスポ側へ
# 取り込んで scripts/ に置いたときは、同じフォルダにある。
# 写し（src/）は書き換えない決まりなので、そこへ __pycache__ も作らない。
HERE = pathlib.Path(__file__).resolve().parent


def _find_scripts():
    cands = [pathlib.Path(os.environ["COLLESPO_SCRIPTS"])] if os.environ.get("COLLESPO_SCRIPTS") else []
    cands += [HERE, HERE.parent / "src" / "scripts", HERE.parent / "scripts"]
    for c in cands:
        if (c / "review_render_v3.py").exists() and (c / "generate_longform.py").exists():
            return c
    raise ImportError("review_render_v3.py が見つかりません（COLLESPO_SCRIPTS で場所を指定できます）")


SCRIPTS = _find_scripts()
ROOT = SCRIPTS.parent
if SCRIPTS != HERE:
    sys.dont_write_bytecode = True          # 読むだけの写しにキャッシュを残さない
for _p in (str(SCRIPTS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

import video_common  # noqa: E402
import review_render_v3 as r3  # noqa: E402
import generate_longform as gl  # noqa: E402

W, H = 1920, 1080
FPS = gl.FPS

# 色（モックの値。球団色は colors() で r3 と同じ考え方で決める）
INK = r3.INK                       # #f7f2df
GOLD = r3.GOLD                     # #ffd16c
DARK_INK = r3.DARK_INK             # #1b1a17
DIM = (196, 206, 212)              # #c4ced4（ラベル・補足）
SUB_BG = (11, 20, 32, 245)         # 字幕の札（モックは #0b1420e6。立ち絵が透けないよう少し濃く）
QUOTE_BG = (247, 242, 223, 255)    # 引用の札（ショートの番記者の札と同じ）

# ---------------------------------------------------------------------------
# 時刻表（秒）。描画と効果音（cues）の両方がここだけを見る。
# モックの @keyframes は 10 秒で1周なので、% × 10 がそのまま秒になる。
# ---------------------------------------------------------------------------
T_CARD = 0.0                  # 札が左から飛び込む（e-in 0%）
CARD_IN = 0.8                 # 着くまで（e-in 8%。少し行き過ぎる）
CARD_SETTLE = 1.1             # 戻って止まる（e-in 11%）
T_ROLL = (0.6, 2.2)           # 大きな数字が回り始める・止まる（e-roll 6%→22%）
T_METER = (1.8, 3.4)          # 目盛りが伸びる（e-meter 18%→34%）
T_DOT = (3.0, 3.6, 4.0)       # 順位の点が出る・膨らむ・落ち着く（e-dot 30%→36%→40%）
T_ROW0, T_ROW_GAP = 0.5, 0.25  # 並びの札の1行目と間隔
ROW_IN = 0.45                 # 行が飛び込むのにかかる秒
T_TILE0, T_TILE_GAP = 0.5, 0.18  # 成績の札の1枚目と間隔
TILE_IN = 0.3
T_INN0, T_INN_GAP = 0.4, 0.06  # スコアボードの回の数字
T_WIN = T_ROLL[1] + 0.2       # 勝った側の札
T_CHIPS = 0.9                 # 引用の下の札（賛否・高評価）
T_CHAPTER = (0.4, 0.8)        # 章の札が明るくなる（e-chip 4%→8%）
BEAM_CYCLE, BEAM_PASS = 10.0, 4.5   # 照明の光（e-beam: 10秒で1回、45%で横切り終わる）
STRIPE_SPEED = 16.0           # ストライプ（e-stripes: 96px を6秒）
BOB_PERIOD, BOB_AMP = 2.6, 8  # 話している方が上下に揺れる（e-bob）
# 字幕。モックは 1秒待って5秒かけて出す（e-type 10%→60%）が、本番は声と同時に
# 始まるので待たない。1秒に TYPE_CPS 文字の速さで出し、尺がわかるときは
# 尺の TYPE_SHARE までに出し切る（声より遅れて字が出ないように）。
T_TYPE0, TYPE_CPS, TYPE_SHARE = 0.0, 16.0, 0.7

# ---------------------------------------------------------------------------
# 割りつけ（モックの座標 × 2）
# ---------------------------------------------------------------------------
M = 56                                 # 左右の余白
TOP_BAND = 10                          # いちばん上の球団の2色目の帯
HEAD_Y = 58                            # 上の帯の文字の高さの中心
PROG_Y = 100                           # 進み具合の線
CARD_X, CARD_Y, CARD_W = M, 144, 1080  # 札
CARD_BOTTOM = 760                      # 札の下端の限界（字幕の名前の札より上）
CARD_MIN_H = 300
CARD_PAD = 48
SUB_X0, SUB_Y0, SUB_X1, SUB_Y1 = M, 800, 1150, 1036   # 字幕の札（立ち絵にかからない幅。10/8）
SUB_BAR = 12                           # 字幕の左の、話者の色の帯
SUB_PAD_X, SUB_PAD_TOP, SUB_PAD_BOTTOM = 40, 30, 26
SUB_SIZES = ((40, 58), (36, 52), (32, 46), (30, 44))   # (文字の大きさ, 行の高さ)
CREDIT_Y = 1058
CREDIT = "音声: VOICEVOX ずんだもん / 四国めたん"

# 立ち絵。素材（1024×1536）の透明な余白を落としてから縮める。
PORTRAIT_DIR = ROOT / "assets/portraits/collespo-20260923"
PORTRAIT_FILES = {
    "四国めたん": "metan/3-black/base.png",
    "ずんだもん": "zundamon/C-cheer/base-black-brow-candidate.png",
}
# 名前: (高さ, 横の中心, 上端)。足元は画面の外へ出す。めたんを大きく、手前に。
PORTRAIT_PLACE = {
    "ずんだもん": (760, 1400, 470),
    "四国めたん": (1000, 1669, 300),
}
PORTRAIT_ORDER = ("ずんだもん", "四国めたん")   # 奥から
DIM_BRIGHT, DIM_SAT = 0.72, 0.85                # 話していない方（明るさ・色の濃さ。0.5/0.6 は濁って見えた 10/8）

BOTH = gl.BOTH


# ---------------------------------------------------------------------------
# 小さな道具
# ---------------------------------------------------------------------------
font = video_common.font   # 共通のものをそのまま使う


def num_font(size, weight="Bold"):
    return r3.num_font(size, weight)


_mix = r3._mix
ease_out = r3.ease_out
back_out = r3.back_out


def _clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def _alpha(c, a):
    return tuple(c[:3]) + (int(a),)


def _textlen(d, s, f):
    return d.textlength(s, font=f) if s else 0.0


def _fit(d, s, sizes, width, fnt=font):
    """幅に収まるいちばん大きい文字の大きさ。"""
    for sz in sizes:
        if _textlen(d, s, fnt(sz)) <= width:
            return sz
    return sizes[-1]


def _ellipsize(d, s, f, width):
    """1行に収まらなければ、後ろを「…」にする（題・名前の札だけに使う）。"""
    s = str(s or "")
    if _textlen(d, s, f) <= width:
        return s
    while s and _textlen(d, s + "…", f) > width:
        s = s[:-1]
    return s + "…" if s else ""


wrap = video_common.wrap


def _over(im, layer, xy, k=1.0):
    """透明つきの絵を、地（RGB）に重ねる。k は全体の不透明さ。"""
    if k <= 0:
        return
    if k < 1:
        layer = layer.copy()
        layer.putalpha(layer.split()[3].point(lambda v: round(v * k)))
    im.paste(layer, (int(xy[0]), int(xy[1])), layer)


def _draw_text(layer, d, xy, s, f, fill):
    """絵文字が混じっていても描ける（絵文字だけ別の書体で貼る）。"""
    if video_common.EMOJI_RE.search(s):
        return video_common.text_emoji(layer, d, xy, s, f, fill)
    d.text(xy, s, font=f, fill=fill)
    return xy[0] + d.textlength(s, font=f)


# 数字は Oswald、それ以外は日本語の書体。「4打数1安打」「31本」「1勝1敗」を1行に混ぜて描く。
_NUM_RUN = re.compile(r"[0-9][0-9.,:/%+]*|[.+\-][0-9][0-9.,:/%]*")


def _runs(s):
    """[(文字列, 数字か)]。"""
    out, pos = [], 0
    for m in _NUM_RUN.finditer(str(s)):
        if m.start() > pos:
            out.append((s[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], False))
    return out


def _ascii(s):
    return all(32 <= ord(c) < 127 for c in str(s))


def mixed_width(d, s, num_size, jp_size):
    return sum(_textlen(d, t, num_font(num_size) if isnum else font(jp_size))
               for t, isnum in _runs(s))


def draw_mixed(d, x, base_y, s, num_size, jp_size, num_fill, jp_fill):
    """数字と日本語を同じ下端（ベースライン）に揃えて描く。戻り値は右端の x。"""
    for t, isnum in _runs(s):
        f = num_font(num_size) if isnum else font(jp_size)
        d.text((x, base_y), t, font=f, fill=num_fill if isnum else jp_fill, anchor="ls")
        x += _textlen(d, t, f)
    return x


def _digit_box(size):
    """Oswald の数字の高さ（ベースラインから上）。"""
    b = num_font(size).getbbox("0", anchor="ls")
    return -b[1], b[3]


def reel(layer, d, x, base_y, value, size, k, fill=GOLD, jp_size=None):
    """大きな数字がスロットのように回って止まる（e-roll）。

    k は 0（回り始め）〜1（止まった）。止まったあとは文字列をそのまま1回で描く
    （描いた文字を検査で拾えるように。途中の数字は動きのあいだだけ出る）。
    数字の各桁は 0 から材料の桁まで回る。数字でない文字（. , % 本 など）は動かない。
    """
    jp_size = jp_size or max(24, round(size * 0.42))
    value = str(value)
    if k >= 1:
        return draw_mixed(d, x, base_y, value, size, jp_size, fill, fill)
    f = num_font(size)
    asc, desc = _digit_box(size)
    pad = max(4, size // 40)                 # 窓（overflow: hidden）は数字の高さだけ
    step = asc + max(16, size // 6)          # 次の数字は窓の外から入ってくる
    for t, isnum in _runs(value):
        if not isnum:
            d.text((x, base_y), t, font=font(jp_size), fill=fill, anchor="ls")
            x += _textlen(d, t, font(jp_size))
            continue
        for ch in t:
            cw = _textlen(d, ch, f)
            if not ch.isdigit():
                d.text((x, base_y), ch, font=f, fill=fill, anchor="ls")
                x += cw
                continue
            pos = k * int(ch)
            cell = Image.new("RGBA", (int(cw) + 8, asc + pad * 2), (0, 0, 0, 0))
            cd = ImageDraw.Draw(cell)
            lo = math.floor(pos)
            for j in (lo, lo + 1):
                if 0 <= j <= 9 and abs(j - pos) < 1:
                    cd.text((4, pad + asc + round((j - pos) * step)), str(j), font=f, fill=fill, anchor="ls")
            layer.alpha_composite(cell, (int(x) - 4, int(base_y - asc - pad)))
            x += cw
    return x


# ---------------------------------------------------------------------------
# 球団色
# ---------------------------------------------------------------------------
def team_id_of(panel=None, score=None, team_id=None):
    """札（なければ試合）から球団を探す。分からなければ None（既定の色）。"""
    if team_id:
        return str(team_id)
    import notability_engine as ne
    names = {v: k for k, v in ne.MLB_TEAM_NAME_JP.items()}
    p = panel or {}
    if p.get("team_id"):
        return str(p["team_id"])
    if p.get("team") in names:
        return names[p["team"]]
    for src in (p if p.get("type") == "score" else None, score):
        if not src:
            continue
        a, h = src.get("away_score"), src.get("home_score")
        first = src.get("away") if (isinstance(a, int) and isinstance(h, int) and a > h) else src.get("home")
        for nm in (first, src.get("home"), src.get("away")):
            if nm in names:
                return names[nm]
    return None


def colors(tid):
    """(地の色, 2色目, 札の色)。ショートの新デザインと同じ決め方。"""
    return r3.colors(tid)


# ---------------------------------------------------------------------------
# 背景（ストライプ・照明・上の帯）
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=2)
def _beam():
    """照明の光。幅280の白い帯をぼかして18度傾ける（e-beam）。"""
    im = Image.new("L", (520, 1700), 0)
    ImageDraw.Draw(im).rectangle((120, 0, 400, 1700), fill=30)
    im = im.filter(ImageFilter.GaussianBlur(56)).rotate(-18, expand=True, resample=Image.BICUBIC)
    return Image.new("RGB", im.size, (255, 255, 255)), im


def background(t, tid):
    base, second, _ = colors(tid)
    im = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(im)
    line = _mix(base, second, 0.10)
    off = (t * STRIPE_SPEED) % 96
    x = -96 + off
    while x < W:
        d.rectangle((round(x) + 92, 0, round(x) + 96, H), fill=line)
        x += 96
    ph = (t % BEAM_CYCLE)
    if ph < BEAM_PASS:
        white, mask = _beam()
        k = ph / BEAM_PASS
        a = _clamp(ph / (0.1 * BEAM_CYCLE)) * (1 - _clamp((k - 0.8) / 0.2))
        if a < 1:
            mask = mask.point(lambda v: round(v * a))
        bx = round(-700 + k * (W + 900))
        im.paste(white, (bx, -280), mask)
    d.rectangle((0, 0, W, TOP_BAND), fill=second)
    return im


# ---------------------------------------------------------------------------
# 上の帯: コレスポ・回の題・章の札・進み具合の線
# ---------------------------------------------------------------------------
def chapter_index(seg, chapters):
    """いまの章の番号（0から）。章が無い・分からないときは None。

    seg["chapter"] は章の id（構成表の "c3" など）か、0から数えた番号。
    """
    if not chapters or not seg:
        return None
    key = seg.get("chapter")
    if key is None:
        return None
    if isinstance(key, int) and not isinstance(key, bool):
        return key if 0 <= key < len(chapters) else None
    for i, ch in enumerate(chapters):
        if isinstance(ch, dict) and str(ch.get("id")) == str(key):
            return i
    return None


def _chapter_title(ch):
    return str(ch.get("title") or "") if isinstance(ch, dict) else str(ch or "")


def _score_text(score):
    """上の帯の試合（いまの長編の draw_top_strip と同じく、試合がある回だけ）。"""
    if not (score and score.get("away") and score.get("home")):
        return ""
    a, h = score.get("away_score"), score.get("home_score")
    av = "-" if a is None else str(a)
    hv = "-" if h is None else str(h)
    return f"{score['away']} {av} - {hv} {score['home']}"


def header(im, d, topic, chapters, idx, progress, chapter_t, score=None):
    f_logo = font(36)
    d.text((M, HEAD_Y), "コレスポ", font=f_logo, fill=GOLD, anchor="lm")
    x = M + _textlen(d, "コレスポ", f_logo) + 32
    right = W - M

    # 章の札（材料にあるときだけ）。右から詰めて、入らなければ今の章以外を番号だけにする。
    if chapters:
        f = font(22)
        labels = [f"{i + 1} {_chapter_title(c)}".strip() for i, c in enumerate(chapters)]
        short = [str(i + 1) for i in range(len(chapters))]
        room = right - x - 360

        def widths(ls):
            return [_textlen(d, s, f) + 40 for s in ls]

        use = labels
        if sum(widths(use)) + 12 * (len(use) - 1) > room:
            use = [labels[i] if i == idx else short[i] for i in range(len(labels))]
        if sum(widths(use)) + 12 * (len(use) - 1) > room and idx is not None:
            use = [_ellipsize(d, labels[i], f, room - 60 * len(labels)) if i == idx else short[i]
                   for i in range(len(labels))]
        ws = widths(use)
        cx = right - (sum(ws) + 12 * (len(ws) - 1))
        for i, (s, w) in enumerate(zip(use, ws)):
            box = (cx, HEAD_Y - 20, cx + w, HEAD_Y + 20)
            if i == idx:
                a, b = T_CHAPTER
                k = 0.35 + 0.65 * _clamp((chapter_t - a) / (b - a))
                lay = Image.new("RGBA", (int(w) + 2, 42), (0, 0, 0, 0))
                ld = ImageDraw.Draw(lay)
                ld.rounded_rectangle((0, 0, int(w), 40), radius=20, fill=GOLD + (255,))
                ld.text((w / 2, 20), s, font=f, fill=DARK_INK, anchor="mm")
                _over(im, lay, (int(cx), HEAD_Y - 20), k)
            else:
                d.rounded_rectangle(box, radius=20, outline=(255, 255, 255, 64), width=2)
                d.text((cx + w / 2, HEAD_Y), s, font=f, fill=DIM, anchor="mm")
            cx += w + 12
        right = right - (sum(ws) + 12 * (len(ws) - 1)) - 32

    # 回の題と、試合（あれば）
    f_title = font(24)
    title = str(topic or "")
    sc = _score_text(score)
    if sc:
        f_sc = font(24)
        scw = _textlen(d, sc, f_sc)
        title = _ellipsize(d, title, f_title, max(0, right - x - scw - 36)) if title else ""
        if title:
            d.text((x, HEAD_Y), title, font=f_title, fill=DIM, anchor="lm")
            x += _textlen(d, title, f_title) + 36
        draw_mixed(d, x, HEAD_Y + 10, sc, 30, 24, INK, INK)
    elif title:
        d.text((x, HEAD_Y), _ellipsize(d, title, f_title, right - x), font=f_title, fill=DIM, anchor="lm")

    # 進み具合の線
    d.rectangle((M, PROG_Y, W - M, PROG_Y + 5), fill=(255, 255, 255, 31))
    if progress is None and idx is not None:
        progress = (idx + 1) / len(chapters)
    if progress is not None:
        k = _clamp(float(progress))
        if k > 0:
            d.rectangle((M, PROG_Y, M + round((W - 2 * M) * k), PROG_Y + 5), fill=GOLD)


# ---------------------------------------------------------------------------
# 札（左）。どの関数も (layer, d, panel, pt, ctx) -> 書き終わりの y。
# pt はその札が出てからの秒。layer は札の大きさの透明な絵（幅 CARD_W）。
# ---------------------------------------------------------------------------
INNER_W = CARD_W - CARD_PAD * 2


def _label(d, s, y=36):
    d.text((CARD_PAD, y), s, font=font(24), fill=DIM)


def _chip(d, x, y, s, size, fill=GOLD, ink=DARK_INK, pad=(28, 12), radius=8):
    f = font(size)
    w = _textlen(d, s, f) + pad[0] * 2
    h = size + pad[1] * 2 + 4
    d.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill)
    d.text((x + w / 2, y + h / 2), s, font=f, fill=ink, anchor="mm")
    return w, h


def _chip_size(d, s, size, pad=(28, 12)):
    return _textlen(d, s, font(size)) + pad[0] * 2, size + pad[1] * 2 + 4


def _name_line(d, y, name, team=""):
    """選手名（大）と球団（小）を同じ下端に。"""
    sz = _fit(d, str(name), (56, 52, 46, 40), INNER_W - (_textlen(d, team, font(26)) + 24 if team else 0))
    f = font(sz)
    base = y + sz
    d.text((CARD_PAD, base), str(name), font=f, fill=INK, anchor="ls")
    if team:
        d.text((CARD_PAD + _textlen(d, str(name), f) + 20, base), str(team), font=font(26),
               fill=DIM, anchor="ls")
    return base + 22


RANK_RE = re.compile(r"(\d+)人中(\d+)位")


def rank_scale(rank):
    """「276人中4位」→ (276, 4)。読めなければ None。"""
    m = RANK_RE.search(str(rank or ""))
    if not m:
        return None
    n, r = int(m.group(1)), int(m.group(2))
    return (n, r) if 1 <= r <= n else None


def _panel_stat(layer, d, p, pt, ctx):
    y = _name_line(d, 84, p.get("name", ""), p.get("team", ""))
    stat = str(p.get("stat", ""))
    if stat:
        if _ascii(stat):
            d.text((CARD_PAD, y + 4), stat, font=num_font(36, "Medium"), fill=DIM)
            y += 52
        else:
            d.text((CARD_PAD, y + 4), stat, font=font(30), fill=DIM)
            y += 48
    value = str(p.get("value", ""))
    rank = str(p.get("rank") or "")
    chip_w, chip_h = _chip_size(d, rank, 44) if rank else (0, 0)
    side = rank and True
    size = 208
    while size > 96 and mixed_width(d, value, size, round(size * 0.42)) > INNER_W - (chip_w + 36 if side else 0):
        size -= 8
    if rank and mixed_width(d, value, size, round(size * 0.42)) > INNER_W - chip_w - 36:
        side = False
    asc, _ = _digit_box(size)
    base = y + asc + 8
    a, b = T_ROLL
    if value:
        end = reel(layer, d, CARD_PAD, base, value, size, ease_out((pt - a) / (b - a)))
    else:
        end, base = CARD_PAD, y
    if rank:
        if side:
            _chip(d, end + 36, base - chip_h - 28, rank, 44)
            y = base + 30
        else:
            _chip(d, CARD_PAD, base + 24, rank, 44)
            y = base + 24 + chip_h + 26
    else:
        y = base + 30
    sc = rank_scale(rank)
    if sc:
        n, r = sc
        f = font(22)
        d.text((CARD_PAD, y), "トップ", font=f, fill=DIM)
        last = f"{n}位"
        d.text((CARD_PAD + INNER_W, y), last, font=f, fill=DIM, anchor="ra")
        by = y + 38
        d.rounded_rectangle((CARD_PAD, by, CARD_PAD + INNER_W, by + 20), radius=10, fill=(255, 255, 255, 31))
        a, b = T_METER
        k = ease_out((pt - a) / (b - a))
        if k > 0:
            grad = _gradient(round(INNER_W * k), 20)
            mask = Image.new("L", grad.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, grad.width - 1, 19), radius=10, fill=255)
            g = grad.copy()
            g.putalpha(Image.composite(grad.split()[3], mask, mask))
            layer.alpha_composite(g, (CARD_PAD, by))
        # 点（e-dot）。位置は順位から割り出す（割った数そのものは描かない）。
        t0, t1, t2 = T_DOT
        if pt >= t0:
            s = (pt - t0) / (t1 - t0) * 1.5 if pt < t1 else (1.5 - 0.5 * _clamp((pt - t1) / (t2 - t1)))
            rr = 20 * s
            frac = (r - 1) / max(1, n - 1)
            cx = CARD_PAD + 20 + (INNER_W - 40) * frac
            cy = by + 10
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=GOLD, outline=ctx["base"] + (255,),
                      width=max(1, round(6 * min(1, s))))
        y = by + 20 + 24
    note = str(p.get("note") or "")
    if note:
        f = font(24)
        for ln in wrap(d, note, f, INNER_W)[:2]:
            d.text((CARD_PAD, y), ln, font=f, fill=DIM)
            y += 36
    return y + 4


@functools.lru_cache(maxsize=8)
def _gradient(w, h):
    """目盛りの棒（金色→薄い金色）。"""
    w = max(1, w)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for x in range(w):
        a = round(255 - (255 - 51) * x / max(1, w - 1))
        for yy in range(h):
            px[x, yy] = GOLD + (a,)
    return im


def _panel_views(layer, d, p, pt, ctx):
    y = 84
    f = font(34)
    for ln in wrap(d, str(p.get("title", "")), f, INNER_W)[:2]:
        d.text((CARD_PAD, y), ln, font=f, fill=INK)
        y += 50
    try:
        v = f"{int(p.get('views') or 0):,}"
    except (TypeError, ValueError):
        v = str(p.get("views") or "")
    unit = "回再生"
    size = 180
    while size > 96 and mixed_width(d, v, size, 0) + _textlen(d, unit, font(48)) + 24 > INNER_W:
        size -= 8
    asc, _ = _digit_box(size)
    base = y + 16 + asc
    a, b = T_ROLL
    end = reel(layer, d, CARD_PAD, base, v, size, ease_out((pt - a) / (b - a)))
    d.text((end + 20, base), unit, font=font(48), fill=INK, anchor="ls")
    return base + 40


def _panel_quote(layer, d, p, pt, ctx):
    text = str(p.get("text", ""))
    y = 84
    iw = INNER_W - 72
    max_h = CARD_BOTTOM - CARD_Y - y - 140       # 下の札のぶんを残す
    lines, size = [], 28
    for size in (46, 42, 38, 34, 30, 28):
        lines = wrap(d, text, font(size), iw)
        if len(lines) * round(size * 1.5) + 96 <= max_h:
            break
    lh = round(size * 1.5)
    keep = max(1, (max_h - 96) // lh)
    if len(lines) > keep:                        # 入らないときだけ。黙って切らずに印を付ける
        lines = lines[:keep]
        lines[-1] = lines[-1][:-1] + "…"
        print(f"[warn] 引用が札に入りきりません（{len(text)}字）")
    h = len(lines) * lh + 80
    d.rounded_rectangle((CARD_PAD, y + 16, CARD_PAD + INNER_W, y + 16 + h), radius=20, fill=QUOTE_BG)
    d.text((CARD_PAD + 22, y + 104), "“", font=num_font(120), fill=GOLD, anchor="ls")
    yy = y + 16 + 44
    h += 16
    for ln in lines:
        _draw_text(layer, d, (CARD_PAD + 36, yy), ln, font(size), DARK_INK)
        yy += lh
    y += h + 24
    chips = []
    if p.get("tone"):
        chips.append((str(p["tone"]), True))
    try:
        if p.get("likes"):
            chips.append((f"高評価 {int(p['likes']):,}", False))
        if p.get("replies"):
            chips.append((f"返信 {int(p['replies'])}", False))
    except (TypeError, ValueError):
        pass
    k = ease_out((pt - T_CHIPS) / 0.3)
    if chips and k > 0:
        x = CARD_PAD
        lay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for s, hot in chips:
            w, hh = _chip(ld, x, y, s, 26, fill=GOLD if hot else (255, 255, 255, 36),
                          ink=DARK_INK if hot else INK, pad=(20, 8), radius=24)
            x += w + 14
        lay.putalpha(lay.split()[3].point(lambda v: round(v * k)))
        layer.alpha_composite(lay)
    return y + 26 + 16 + 4


def _tokens(line):
    """成績の行を札に分ける（空白・全角空白・「・」で）。"""
    return [t for t in re.split(r"[\s　・]+", str(line or "")) if t]


def _panel_star(layer, d, p, pt, ctx):
    y = _name_line(d, 84, p.get("name", ""), p.get("team", ""))
    toks = _tokens(p.get("line", ""))
    num, jp, gap, padx, th = 64, 30, 14, 22, 92
    rows, row, x = [], [], 0
    for tk in toks:
        w = (mixed_width(d, tk, num, jp) if any(c.isdigit() for c in tk)
             else _textlen(d, tk, font(32))) + padx * 2
        if w > INNER_W:
            rows = None
            break
        if row and x + w > INNER_W:
            rows.append(row)
            row, x = [], 0
        row.append((tk, w))
        x += w + gap
    if rows is not None and row:
        rows.append(row)
    if not rows or len(rows) > 3:
        # 札に分けられない行は、そのまま金色の文字で
        f = font(40)
        for ln in wrap(d, str(p.get("line", "")), f, INNER_W)[:4]:
            d.text((CARD_PAD, y + 10), ln, font=f, fill=GOLD)
            y += 58
        return y + 20
    y += 14
    i = 0
    for row in rows:
        x = CARD_PAD
        for tk, w in row:
            k = ease_out((pt - T_TILE0 - i * T_TILE_GAP) / TILE_IN)
            i += 1
            if k > 0:
                lay = Image.new("RGBA", (int(w) + 2, th + 2), (0, 0, 0, 0))
                ld = ImageDraw.Draw(lay)
                if any(c.isdigit() for c in tk):
                    ld.rounded_rectangle((0, 0, int(w), th), radius=14, fill=(255, 255, 255, 26),
                                         outline=(255, 255, 255, 46), width=2)
                    draw_mixed(ld, padx, th - 22, tk, num, jp, GOLD, INK)
                else:
                    ld.rounded_rectangle((0, 0, int(w), th), radius=14, fill=GOLD)
                    ld.text((w / 2, th / 2), tk, font=font(32), fill=DARK_INK, anchor="mm")
                lay.putalpha(lay.split()[3].point(lambda v: round(v * k)))
                layer.alpha_composite(lay, (int(x), int(y + round(24 * (1 - k)))))
            x += w + gap
        y += th + gap
    return y + 16


def _panel_group(layer, d, p, pt, ctx):
    y = 84
    head = str(p.get("head", ""))
    if head:
        d.text((CARD_PAD, y), _ellipsize(d, head, font(34), INNER_W), font=font(34), fill=INK)
        y += 62
    rows = (p.get("rows") or [])[:4]
    rh = 92 if len(rows) <= 3 else 84
    for i, row in enumerate(rows):
        name, val = str(row.get("name", "")), str(row.get("value", ""))
        k = back_out((pt - T_ROW0 - i * T_ROW_GAP) / ROW_IN)
        if k > 0:
            lay = Image.new("RGBA", (CARD_W, rh), (0, 0, 0, 0))
            ld = ImageDraw.Draw(lay)
            ld.line((CARD_PAD, rh - 1, CARD_PAD + INNER_W, rh - 1), fill=(255, 255, 255, 40), width=2)
            vw = mixed_width(ld, val, 60, 34)
            fn = font(44)
            ld.text((CARD_PAD, rh - 26), _ellipsize(ld, name, fn, INNER_W - vw - 40), font=fn,
                    fill=INK, anchor="ls")
            draw_mixed(ld, CARD_PAD + INNER_W - vw, rh - 22, val, 60, 34, GOLD, GOLD)
            lay.putalpha(lay.split()[3].point(lambda v: round(v * min(1.0, k * 1.6))))
            dx = round(-90 * (1 - k))
            if dx < 0:
                lay = lay.crop((-dx, 0, lay.width, lay.height))
                dx = 0
            layer.alpha_composite(lay, (dx, y))
        y += rh
    return y + 24


def _panel_score(layer, d, p, pt, ctx):
    inn = p.get("innings") or []
    n = len(inn)
    total_w = 130
    name_w = max(300, min(360, INNER_W - total_w - n * 56))
    cell = max(44, min(80, (INNER_W - name_w - total_w) / max(1, n)))
    x0 = CARD_PAD
    rx = x0 + name_w + cell * n + total_w / 2
    y = 92
    fh = num_font(28, "Medium")
    for i, ig in enumerate(inn):
        cx = x0 + name_w + cell * i + cell / 2
        d.text((cx, y), str(ig.get("num", "")), font=fh, fill=DIM, anchor="mt")
    d.text((rx, y), "計", font=font(26), fill=DIM, anchor="mt")
    y += 52
    a, h = p.get("away_score"), p.get("home_score")
    win = None
    if isinstance(a, int) and isinstance(h, int):
        win = "away" if a > h else ("home" if h > a else None)
    ra, rb = T_ROLL
    kroll = ease_out((pt - ra) / (rb - ra))
    for nm, side, total in ((p.get("away", ""), "away", a), (p.get("home", ""), "home", h)):
        col = GOLD if side == win else INK
        base = y + 74
        d.line((x0, y + 100, x0 + INNER_W, y + 100), fill=(255, 255, 255, 40), width=2)
        fn = font(_fit(d, str(nm), (40, 36, 32, 28, 26), name_w - 24))
        d.text((x0, base - 8), _ellipsize(d, str(nm), fn, name_w - 24), font=fn, fill=col, anchor="ls")
        for i, ig in enumerate(inn):
            if pt < T_INN0 + i * T_INN_GAP:
                continue
            v = ig.get(side)
            s = "-" if v is None else str(v)
            cx = x0 + name_w + cell * i + cell / 2
            d.text((cx, base - 6), s, font=num_font(48), fill=INK if v else DIM, anchor="ms")
        s = "-" if total is None else str(total)
        f = num_font(88)
        tw = _textlen(d, s, f)
        if s.isdigit():
            reel(layer, d, rx - tw / 2, base, s, 88, kroll, fill=col)
        else:
            d.text((rx, base), s, font=f, fill=col, anchor="ms")
        y += 104
    if win:
        wn = p.get("away") if win == "away" else p.get("home")
        k = back_out((pt - T_WIN) / 0.3, 2.4)
        if k > 0:
            s = f"{wn}の勝ち"
            w, hh = _chip_size(d, s, 34)
            lay = Image.new("RGBA", (int(w) + 2, int(hh) + 2), (0, 0, 0, 0))
            _chip(ImageDraw.Draw(lay), 0, 0, s, 34)
            if k != 1:
                lay = lay.resize((max(1, round(lay.width * k)), max(1, round(lay.height * k))))
            layer.alpha_composite(lay, (x0, int(y + 24 + (hh - lay.height) / 2)))
        y += 24 + 34 + 28
    return y + 24


def _panel_topic(layer, d, p, pt, ctx):
    y = 84
    text = str(p.get("topic") or "MLB")
    for size in (72, 64, 56, 48):
        lines = wrap(d, text, font(size), INNER_W)
        if len(lines) <= 3:
            break
    for i, ln in enumerate(lines[:3]):
        d.text((CARD_PAD, y), ln, font=font(size), fill=INK)
        y += round(size * 1.35)
    d.text((CARD_PAD, y + 16), "コレスポ", font=font(36), fill=GOLD)
    return y + 16 + 36 + 30


PANELS = {"score": _panel_score, "views": _panel_views, "quote": _panel_quote,
          "stat": _panel_stat, "star": _panel_star, "group": _panel_group,
          "topic": _panel_topic}


def panel_kind(panel, topic=""):
    """描く札の種類と中身。知らない種類は「きょうの話」にする（いまの長編と同じ）。"""
    kind = (panel or {}).get("type")
    if kind not in PANELS:
        return "topic", {"type": "topic", "topic": topic}
    return kind, panel


def panel_title(kind, panel):
    """札の上の小さな見出し。いまの長編（generate_longform._TITLES）と同じ言葉。"""
    if kind == "quote":
        return f"{panel.get('source') or '現地のコメント欄'}（翻訳）"
    return gl._TITLES.get(kind, "")


def draw_card(kind, panel, pt, base_rgb):
    """札1枚（RGBA、幅 CARD_W）。高さは中身に合わせる（CARD_MIN_H〜限界）。"""
    max_h = CARD_BOTTOM - CARD_Y
    content = Image.new("RGBA", (CARD_W, max_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(content)
    title = panel_title(kind, panel)
    if title:
        _label(d, _ellipsize(d, title, font(24), INNER_W))
    bottom = PANELS[kind](content, d, panel, pt, {"base": tuple(base_rgb)})
    h = int(min(max_h, max(CARD_MIN_H, bottom + 20)))
    if bottom + 20 > max_h:
        print(f"[warn] 札（{kind}）が下にはみ出しそうです（{bottom + 20 - max_h}px）")
    card = Image.new("RGBA", (CARD_W, h), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, CARD_W - 1, h - 1), radius=32, fill=(255, 255, 255, 20),
                                           outline=(255, 255, 255, 46), width=4)
    card.alpha_composite(content.crop((0, 0, CARD_W, h)))
    return card, bottom


def card_motion(pt):
    """札の飛び込み（e-in）: (横のずれ, 不透明さ)。"""
    if pt >= CARD_SETTLE:
        return 0, 1.0
    if pt < CARD_IN:
        k = ease_out(pt / CARD_IN)
        return round(-120 + 132 * k), _clamp(pt / CARD_IN)
    k = (pt - CARD_IN) / (CARD_SETTLE - CARD_IN)
    return round(12 * (1 - k)), 1.0


def paste_card(im, kind, panel, pt, base_rgb):
    card, _ = draw_card(kind, panel, pt, base_rgb)
    dx, a = card_motion(pt)
    if a <= 0:
        return card
    _over(im, card, (CARD_X + dx, CARD_Y), a)
    return card


# ---------------------------------------------------------------------------
# 立ち絵（右）
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=8)
def standing(who, dim=False):
    """立ち絵（余白を落として縮めたもの）。dim=True は話していない方（暗く・色を薄く）。"""
    path = PORTRAIT_DIR / PORTRAIT_FILES[who]
    art = Image.open(path).convert("RGBA")
    art = art.crop(art.getbbox())
    h = PORTRAIT_PLACE[who][0]
    art = art.resize((max(1, round(art.width * h / art.height)), h), Image.LANCZOS)
    if dim:
        rgb = art.convert("RGB")
        gray = rgb.convert("L").convert("RGB")
        rgb = Image.blend(gray, rgb, DIM_SAT)
        rgb = rgb.point(lambda v: round(v * DIM_BRIGHT))
        out = rgb.convert("RGBA")
        out.putalpha(art.split()[3])
        art = out
    return art


def portrait_box(who, t=0.0, talking=False):
    """立ち絵の置き場 (x0, y0, x1, y1)（検査でも使う）。"""
    art = standing(who)
    _, cx, top = PORTRAIT_PLACE[who]
    bob = round(BOB_AMP * math.sin(t * 2 * math.pi / BOB_PERIOD)) if talking else 0
    x0 = round(cx - art.width / 2)
    return x0, top - bob, x0 + art.width, top - bob + art.height


def paste_portraits(im, t, talking):
    for who in PORTRAIT_ORDER:
        on = talking == BOTH or who == talking
        art = standing(who, dim=not on)
        x0, y0, _, _ = portrait_box(who, t, on)
        im.paste(art, (x0, y0), art)


# ---------------------------------------------------------------------------
# 字幕（下）
# ---------------------------------------------------------------------------
def subtitle_text(seg):
    """この画面の字幕。長い台詞を画面で分けた（paginate）ときは、そのページのぶん。"""
    if seg.get("_lines") is not None:
        return "".join(seg["_lines"])
    return " ".join(str(seg.get("text") or "").split())


def layout_subtitle(d, text):
    """(大きさ, 行の高さ, 行)。字幕の札に収まるいちばん大きい文字で。"""
    width = SUB_X1 - SUB_X0 - SUB_BAR - SUB_PAD_X * 2
    room = SUB_Y1 - SUB_Y0 - SUB_PAD_TOP - SUB_PAD_BOTTOM
    lines = []
    for size, lh in SUB_SIZES:
        lines = wrap(d, text, font(size), width)
        if len(lines) * lh <= room:
            return size, lh, lines
    size, lh = SUB_SIZES[-1]
    keep = max(1, room // lh)
    if len(lines) > keep:
        print(f"[warn] 字幕が札に入りきりません（{len(text)}字）。分け方を見直してください")
    return size, lh, lines[:keep]


def paginate(segs):
    """長い台詞を、この字幕の札に入る画面に分ける（generate_longform.paginate の新デザイン版）。

    いまの長編の paginate は、古い台詞の箱（幅1064・高さ336）で分けている。新しい字幕の札は
    幅も高さも違うので、新デザインのときはこちらで分ける。音は分けない（1つの読み上げのまま）。
    尺は文字数で按分する（いまの長編と同じ）。戻り値の形も同じ（_size・_lines・_share）。
    """
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    width = SUB_X1 - SUB_X0 - SUB_BAR - SUB_PAD_X * 2
    room = SUB_Y1 - SUB_Y0 - SUB_PAD_TOP - SUB_PAD_BOTTOM
    out = []
    for s in segs:
        text = " ".join(str(s.get("text") or "").split())
        size, lh, lines = SUB_SIZES[-1] + (None,)
        for size, lh in SUB_SIZES:
            lines = wrap(d, text, font(size), width)
            if len(lines) * lh <= room:
                break
        per = max(1, room // lh)
        pages = [lines[i:i + per] for i in range(0, len(lines), per)] or [[]]
        if len(pages) == 1:
            out.append({**s, "_size": size, "_lines": pages[0], "_share": 1.0})
            continue
        chars = [sum(len(x) for x in pg) or 1 for pg in pages]
        total = sum(chars)
        for pg, c in zip(pages, chars):
            out.append({**s, "_size": size, "_lines": pg, "_share": c / total})
    return out


def type_seconds(text, dur=None):
    """字幕を出し切るまでの秒（左から現れる）。"""
    sec = len(text) / TYPE_CPS
    if dur:
        sec = min(sec, max(0.2, dur * TYPE_SHARE))
    return max(0.2, sec)


def subtitle(im, d, t, seg, who, dur=None):
    text = subtitle_text(seg)
    if not text:
        return
    color = who["color"]
    d.rounded_rectangle((SUB_X0, SUB_Y0, SUB_X1, SUB_Y1), radius=24, fill=SUB_BG)
    d.rounded_rectangle((SUB_X0, SUB_Y0, SUB_X0 + SUB_BAR + 8, SUB_Y1), radius=8, fill=color)
    d.rectangle((SUB_X0 + SUB_BAR, SUB_Y0, SUB_X0 + SUB_BAR + 8, SUB_Y1), fill=SUB_BG)
    # 名前の札（e: 札の左上に、話者の色で）
    nm = who["name"]
    f = font(26)
    nw = _textlen(d, nm, f) + 36
    d.rounded_rectangle((SUB_X0 + 28, SUB_Y0 - 26, SUB_X0 + 28 + nw, SUB_Y0 + 18), radius=8, fill=color)
    d.text((SUB_X0 + 28 + nw / 2, SUB_Y0 - 4), nm, font=f, fill=DARK_INK, anchor="mm")
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


def _gold_runs(line):
    out, pos = [], 0
    for m in r3.NUM_RE.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], False))
    return [(p, g) for p, g in out if p]


# ---------------------------------------------------------------------------
# 1枚まるごと
# ---------------------------------------------------------------------------
def render_line(t, seg, portrait_dir="", topic="", panel=None, state=None, score=None, *,
                chapters=None, progress=None, panel_t=None, chapter_t=None, dur=None,
                team_id=None):
    """台詞1つぶんの画面（1920×1080、RGB）。

    t: その台詞（paginate で分けたときはそのページ）が出てからの秒。
    seg・topic・panel・score: generate_longform.render_line と同じ材料。
    portrait_dir・state: 受けるが使わない（新しい立ち絵は1枚絵で、口・目の部品が無い）。
    chapters: 構成表の章の一覧（[{"id","title"}, …] か題の文字列の一覧）。無ければ章の札を出さない。
              いまの章は seg["chapter"]（章の id か 0 から数えた番号）。
    progress: 回の中の進み具合（0〜1）。無ければ章から（章も無ければ線だけ）。
    panel_t: いまの札が出てからの秒（札が前の台詞から続いているときは t より大きい）。既定は t。
    chapter_t: いまの章が始まってからの秒。既定は t。
    dur: この画面の尺（秒）。字幕を尺のうちに出し切るのに使う。
    team_id: 球団（分かっていれば）。無ければ札・試合の球団名から探す。
    """
    seg = seg or {}
    pt = t if panel_t is None else panel_t
    ct = t if chapter_t is None else chapter_t
    kind, panel_ = panel_kind(panel, topic)
    tid = team_id_of(panel_, score, team_id)
    base, second, _ = colors(tid)
    im = background(t, tid)
    d = ImageDraw.Draw(im, "RGBA")          # 半透明の色を地に重ねて描く
    idx = chapter_index(seg, chapters)
    header(im, d, topic, chapters, idx, progress, ct, score)
    is_card = seg.get("kind") in ("intro", "outro")
    who = gl._speaker(seg)
    talking = BOTH if is_card else who["name"]
    paste_portraits(im, t, talking)
    try:
        paste_card(im, kind, panel_, pt, base)
    except Exception as e:                       # noqa: BLE001
        # 札が1枚描けないだけで動画を落とさない（いまの長編と同じ）。黙って空にもしない。
        print(f"[warn] 札を描けません({kind}): {e}")
        paste_card(im, "topic", {"type": "topic", "topic": topic}, pt, base)
    if not is_card:
        subtitle(im, d, t, seg, who, dur)
    d.text((M, CREDIT_Y), CREDIT, font=font(20), fill=DIM, anchor="lm")
    return im


# ---------------------------------------------------------------------------
# 効果音の時刻（描画と同じ時刻表から）
# ---------------------------------------------------------------------------
def _panel_events(kind, panel):
    """札が出てからの秒で、[(秒, 種類, 案, 追加の音量dB)]。"""
    out = [(T_CARD, "notify" if kind == "quote" else "swish", "a", -3)]
    if kind == "stat":
        if panel.get("value"):
            out.append((T_ROLL[0], "roll", "a", -2))
            out.append((T_ROLL[1] - 0.04, "stop", "a", 0))
        if rank_scale(panel.get("rank")):
            out.append((T_METER[0], "rise", "a", -6))
            out.append((T_DOT[0], "pop", "a", -2))
    elif kind == "views":
        out.append((T_ROLL[0], "roll", "a", -2))
        out.append((T_ROLL[1] - 0.04, "stop", "a", 0))
    elif kind == "score":
        a, h = panel.get("away_score"), panel.get("home_score")
        if isinstance(a, int) or isinstance(h, int):
            out.append((T_ROLL[0], "roll", "a", -4))
            out.append((T_ROLL[1] - 0.04, "stop", "a", 0))
        if isinstance(a, int) and isinstance(h, int) and a != h:
            out.append((T_WIN, "pop", "a", -2))
    elif kind == "group":
        for i, _ in enumerate((panel.get("rows") or [])[:4]):
            out.append((T_ROW0 + i * T_ROW_GAP, "swish", "b", -5))
    elif kind == "star":
        n = len(_tokens(panel.get("line", "")))
        for i in range(min(n, 8)):
            out.append((T_TILE0 + i * T_TILE_GAP, "pop", "b", -8))
    elif kind == "quote":
        if panel.get("tone") or panel.get("likes") or panel.get("replies"):
            out.append((T_CHIPS, "pop", "b", -6))
    return out


def cues(seg, panel=None, topic="", *, panel_since=0.0, chapter_start=False, chapters=None):
    """この画面の効果音 [(秒, 種類, 案, 追加の音量dB)]。秒はこの画面が出てから。

    panel_since: いまの札がこの画面より何秒前に出ていたか（0 = この画面で出た）。
                 もう鳴り終わった音は返さない（同じ札が続くあいだは鳴らさない）。
    chapter_start: この画面で章が変わったか（章の札が明るくなるときに切り替えの音）。
    """
    out = []
    if chapter_start and chapter_index(seg or {}, chapters) is not None:
        out.append((0.0, "transition", "b", -6))
    kind, panel_ = panel_kind(panel, topic)
    for at, k, v, db in _panel_events(kind, panel_):
        rel = at - panel_since
        if rel >= 0:
            out.append((round(rel, 3), k, v, db))
    return sorted(out)


# ---------------------------------------------------------------------------
# 本番の書き出しの輪で使うもの（generate_longform.main から呼ぶ。README を参照）
# ---------------------------------------------------------------------------
def timeline(pages, cards, fps=FPS):
    """画面ごとの時刻と札。描画と効果音の両方がこれを使う（時刻がずれないように）。

    pages: [(seg, 秒)]（generate_longform.main の pages と同じ）。cards: 台本の panels。
    戻り値: [{seg, dur, frames, start, panel, panel_since, chapter_start, chapter_since}]。
    start は動画の頭からの秒（1画面のコマ数 int(秒×fps) を積んだもの。書き出しと同じ数え方）。
    panel_since・chapter_since は、いまの札・章がこの画面より何秒前に出ていたか。
    """
    out, start, current, panel_at, key_now, chapter_now = [], 0.0, None, 0.0, None, None
    chapter_at = 0.0
    for seg, dur in pages:
        if seg.get("panel") and seg["panel"] in cards:
            if seg["panel"] != key_now:
                panel_at = start
            current, key_now = cards.get(seg["panel"]), seg["panel"]
        elif seg.get("panel"):
            pass                                  # 知らない鍵は捨てる（前の札のまま）
        ch = seg.get("chapter")
        n = int(dur * fps)
        new_chapter = ch is not None and ch != chapter_now
        if new_chapter:
            chapter_at = start
        out.append({"seg": seg, "dur": dur, "frames": n, "start": start, "panel": current,
                    "panel_since": start - panel_at,
                    "chapter_start": new_chapter, "chapter_since": start - chapter_at})
        chapter_now = ch if ch is not None else chapter_now
        start += n / fps
    return out


def all_cues(pages, cards, topic="", chapters=None, fps=FPS):
    """動画全体の効果音 [(動画の頭からの秒, 種類, 案, 追加の音量dB)]。"""
    out = []
    for row in timeline(pages, cards, fps):
        for at, k, v, db in cues(row["seg"], row["panel"], topic, panel_since=row["panel_since"],
                                 chapter_start=row["chapter_start"], chapters=chapters):
            if at < row["dur"]:
                out.append((round(row["start"] + at, 3), k, v, db))
    return out


DEFAULT_BGM = None   # sound_mix.DEFAULT_BGM（ショートと同じ曲）


def add_sound(audio_path, pages, cards, out_dir, topic="", chapters=None, bgm=None, fps=FPS):
    """読み上げに BGM と効果音を重ねる（手本は generate_asset_video.add_sound）。

    尺は変えない（sound_mix.mix は読み上げと同じ長さで返す）。
    BGM は引数 → 環境変数 COLLESPO_LONGFORM_BGM → COLLESPO_BGM → DEFAULT_BGM。空なら BGM なし。
    失敗したら読み上げだけで続ける（動画は止めない）。
    """
    import sound_mix
    cue = all_cues(pages, cards, topic, chapters, fps)
    name = bgm if bgm is not None else (os.environ.get("COLLESPO_LONGFORM_BGM")
                                        or os.environ.get("COLLESPO_BGM") or DEFAULT_BGM
                                        or sound_mix.DEFAULT_BGM)
    path = ROOT / "assets" / "bgm" / f"{name}.mp3" if name else None
    try:
        out = sound_mix.mix_file(audio_path, pathlib.Path(out_dir) / "narration_mixed.wav",
                                 path if path and path.exists() else None, cue)
        print(f"[info] BGM {name if path and path.exists() else 'なし'}・効果音{len(cue)}個を重ねました")
        return out
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] BGM・効果音を重ねられません（読み上げだけで続けます）: {e}")
        return audio_path
