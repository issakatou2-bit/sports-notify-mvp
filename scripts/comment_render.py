#!/usr/bin/env python3
"""ショートの新デザイン 案D「コメント欄ライブ」（Opus-13）。ファンの声の画面。

モック: collespo/指示書/mocks/D_CommentLive.dc.html（540×960 で描いてある。ここでは2倍の 1080×1920）。

  - ファンのコメントが吹き出しになって、下から上がってきて上から順に積み上がる。
    入りきらなくなったら、チャットのように古い吹き出しが上へ押し出される（上の端で薄くなって消える）。
  - 吹き出しの中の大事な語に、マーカーが左から引かれる（金色）。
  - 上に事実の帯（球団の2色目）が右から左へ流れ続ける。
  - 小さな輪が下から浮かんで消える。見出しの横の赤い点が点滅する。
  - 左下に立ち絵（四国めたん）、その右に引用元。

書き方は review_render_v3.py と同じ:
  - 時刻はすべて「その画面が出てからの秒」t。p（0〜1）は使わない。
  - 時刻表は下の定数。描画（comments）と効果音（cues）が同じ定数・同じ start_times を見る。
  - 重い部品（吹き出しの絵・帯・輪の絵）は lru_cache で1回だけ作り、毎コマは貼るだけ。
  - 背景は動き続ける（輪・帯・点滅・立ち絵。コマを使い回さない）。色は review_render_v3.colors(team_id)。
  - 書体は ps_brand_components.font と review_render_v3.num_font。
  - 安全域（ps_render_template.SAFE_BOTTOM・SAFE_RIGHT）の外に大事な文字を置かない。

数字・言葉は材料にあるものだけ。足さない・言い換えない。
  - 吹き出しの文（said）は材料の訳文そのまま。縮めない・切らない（入らないときは字を小さくし、
    それでも入らなければ吹き出しを縦に伸ばして、古い吹き出しを上へ押し出す）。
  - マーカーの語（mark）は said の部分文字列だけ（pick_mark が said の中から選ぶ。言い換えない）。

使い方:
  import comment_render as cr
  voices = [{"said": "訳文", "who": "短い説明", "mark": cr.pick_mark("訳文")}, ...]
  im = cr.comments(t, voices, team_id, "事実の帯の文")      # t 秒目の絵（1080×1920、RGB）
  cues = cr.cues(voices)                                    # 効果音 [(秒, 種類, 案, 追加dB)]

  # (a) review_render_v3 の項目の画面（「ハイライトのコメント欄から」「番記者の投稿から」がある頁だけ D に）
  im = cr.list_page(t, spec, items, start, count, page, pages, "PSの話題")
  cues = cr.list_cues(spec, items, start, count)
  # (b) 17:30「現地のファンは何と言ったか」（generate_morning_short の voices / thread の画面）
  im = cr.voices_screen(t, seg, voices_data, dur)
  cues = cr.voices_cues(seg, voices_data, dur)

  python comment_render.py --out samples        # 見本の PNG（写しの材料から。作業場所は collespo/）
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

from PIL import Image, ImageDraw  # noqa: E402

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
import video_common  # noqa: E402  （絵文字を貼る部品。ハイライトのコメントには絵文字が入る）
from ps_brand_components import font  # noqa: E402
from ps_render_template import SAFE_BOTTOM, SAFE_RIGHT  # noqa: E402,F401  （SAFE_BOTTOM は検査が見る）

W, H = r3.W, r3.H
LEFT = r3.LEFT
INK, GOLD, DARK_INK = r3.INK, r3.GOLD, r3.DARK_INK
LIVE_RED = (255, 138, 122)       # 見出しの横の点と「ハイライトのコメント欄」（モック #ff8a7a）
WHO_ON_LIGHT = (93, 90, 99)      # 白い吹き出しの説明の行（#5d5a63）

# ------------------------------------------------------------------ 時刻表（秒）
# モック D（10秒で1周）の @keyframes と animation-delay を秒に直したもの。
BUBBLE_AT = (0.3, 2.2, 4.2)      # 吹き出しが出る時刻（delay .3s / 2.2s / 4.2s）。4つ目からは BUBBLE_GAP おき
BUBBLE_GAP = 2.0
RISE, RISE_PX = 0.6, 120         # 下から上がって濃くなる（d-up 0→6%、60px→0）
MARK_AFTER, MARK_IN = 1.0, 1.0   # 吹き出しが出てから1秒待ち、1秒で左から引き終わる（d-mark 10→20%）
SCROLL_IN = 0.6                  # 入りきらないとき、古い吹き出しが上へ押し出される秒（吹き出しが出るのと同時）
STRIP_SPEED = 110                # 帯の流れる速さ px/秒（d-strip 14秒で1本ぶん ≒ 110px/秒）
BLINK = 1.2                      # 赤い点の点滅（d-blink 1.2秒、前半が点く）
BOB_SECONDS, BOB_PX = 2.4, 12    # 立ち絵が上下する（d-bob 2.4秒・6px）
RING_RISE = 1400                 # 輪が上がる距離（d-float 700px）
# 輪: (左, 下端のy, 外径, 色, 1周の秒, 遅れ)。色 "second" は球団の2色目（モック #c4ced4）
RINGS = ((120, 1680, 48, "second", 7.0, 0.0),
         (460, 1760, 36, "gold", 9.0, 2.0),
         (800, 1640, 56, "second", 8.0, 4.0))
RING_WIDTH = 6

# ------------------------------------------------------------------ 配置（モックの2倍）
HEAD_BASE = 214                  # 見出しの行の基準線（top 84）
STRIP_Y, STRIP_H = 244, 80       # 事実の帯（top 122・高さ 40）
STRIP_SIZE = 36
AREA_TOP = 392                   # 吹き出しの並びの上端（top 196）
AREA_BOTTOM = 1320               # 吹き出しの並びの下端。これより下は立ち絵と引用元
AREA_FADE = 56                   # 押し出された吹き出しが上の端で薄くなる幅
GAP = 36                         # 吹き出しの間（gap 18px）
AVATAR = 88                      # 丸の大きさ（44px）
AVATAR_GAP = 24                  # 丸と吹き出しの間（gap 12px）
REPLY_INDENT = 56                # 返信の吹き出しを右へずらす幅
PAD_X, PAD_Y = 32, 28            # 吹き出しの内側の余白（14px 16px）
WHO_SIZE = 24                    # 説明の行（12px）
WHO_GAP = 8                      # 説明の行と本文の間（margin-top 4px）
SAID_SIZES = (44, 40, 36, 32)    # 本文の字の大きさ（22px）。全部が並びに入らなければ1段ずつ小さく
LINE_H = 1.45                    # 行の高さ（line-height 1.45）
FACT_SIZE = 36                   # 事実の吹き出し（金色・右寄せ。18px）。本文の字がこれより小さければそちらに
RADIUS, RADIUS_SMALL = 36, 8     # 角の丸み（18px・4px）
PRESENTER_X, PRESENTER_BOTTOM = 40, 1570   # 立ち絵（left 20・bottom 175）
SOURCE_X, SOURCE_Y = 300, 1490   # 引用元（left 150・top 745）
SOURCE_SIZE, SOURCE_MIN = 24, 18

# 決まった言葉（材料ではなく、画面の見出し）
TITLE = "現地のファンの声"
LIVE_COMMENTS = "ハイライトのコメント欄"
LIVE_REPORTER = "番記者の投稿"
COMMENT_HEAD = "ハイライトのコメント欄から"
REPORTER_TAIL = "番記者の投稿から"
VOICES_SHOWN = 3                 # 17:30 の声の画面に並べる数（generate_morning_short.VOICES_SHOWN と同じ）


def clamp(x):
    return max(0.0, min(1.0, x))


ease_out = r3.ease_out


def _mix(a, b, k):
    return r3._mix(a, b, k)


# ------------------------------------------------------------------ マーカーの語を選ぶ
_STOP = set("、。，．！？!?「」『』（）()…：:；;\"“”‘’〜～　\n")
_HIRA = re.compile(r"[\u3041-\u309f]")
_NUM_CORE = re.compile(r"\d[\d,.\-]*[^\s\u3041-\u309f、。！？!?「」（）]{0,3}")
MARK_MAX = 16                    # これより長い「数字を含む語句」は、数字＋後ろ3文字までに縮める


def _is_break(ch):
    return ch in _STOP or bool(_HIRA.match(ch)) or bool(video_common.EMOJI_RE.match(ch))


def number_phrases(said):
    """訳文の中の「数字を含む語句」を (始まり, 終わり) で、前から順に。

    語句 = 数字を含む、ひらがな・句読点・かっこで区切られたひと続き（例「60年間 Sox ファン」「3年連続」「11-1」）。
    @で始まる名前（返信先の表示名）や URL の中の数字は語句にしない。"""
    said = str(said or "")
    out, i = [], 0
    for m in re.finditer(r"\d", said):
        if m.start() < i:
            continue
        a = m.start()
        while a > 0 and not _is_break(said[a - 1]):
            a -= 1
        b = m.end()
        while b < len(said) and not _is_break(said[b]):
            b += 1
        i = b
        while a < b and said[a] == " ":
            a += 1
        while b > a and said[b - 1] == " ":
            b -= 1
        word = said[a:b]
        if "@" in word or "http" in word.lower() or "/" in word:
            continue
        if len(word) > MARK_MAX:
            core = _NUM_CORE.match(said, m.start())
            a, b = core.start(), core.end()
        out.append((a, b))
    return out


@functools.lru_cache(maxsize=1)
def default_names():
    """球団名・選手名の候補（材料と本番の表から。足さない）。

    球団: notability_engine の日本語名・英語の正式名と愛称（"White Sox" など）。
    選手: data/player_kana.json の名前（英語と日本語）と notability_engine.JP_PLAYER_READINGS の名前。"""
    import notability_engine as ne
    names = set(ne.MLB_TEAM_NAME_JP.values())
    for full in ne.MLB_TEAM_NAME_EN.values():
        words = full.split()
        names.add(full)
        names.add(" ".join(words[-2:]) if words[-1] in ("Sox", "Jays") else words[-1])
    names.update(getattr(ne, "JP_PLAYER_READINGS", {}).keys())
    try:
        kana = json.loads((ROOT / "data" / "player_kana.json").read_text(encoding="utf-8"))
        for en, jp in (kana.get("names") or {}).items():
            names.add(en)
            if jp:
                names.add(jp)
    except (OSError, ValueError, AttributeError):
        pass
    return tuple(sorted((n for n in names if n and len(n) >= 2), key=len, reverse=True))


def name_spans(said, names=()):
    """訳文の中の球団名・選手名を (始まり, 終わり) で。英字の名前は単語の切れ目でだけ当てる。"""
    said = str(said or "")
    out = []
    for n in tuple(names or ()) + default_names():
        if not n:
            continue
        if re.fullmatch(r"[\x00-\x7f]+", n):
            pat = r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])"
            out += [(m.start(), m.end()) for m in re.finditer(pat, said)]
        else:
            k = said.find(n)
            while k >= 0:
                out.append((k, k + len(n)))
                k = said.find(n, k + 1)
    return out


def pick_mark(said, names=()):
    """マーカーを引く語。訳文の中の、数字を含む語句・球団名・選手名のうち最初の1つ（said の部分文字列）。
    無ければ ""（そのときは引かない）。同じ位置から始まるときは長いほう。"""
    said = str(said or "")
    spans = number_phrases(said) + name_spans(said, names)
    if not spans:
        return ""
    a, b = min(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    return said[a:b]


def mark_span(said, mark):
    """mark が said の中のどこか。部分文字列でなければ None（引かない）。"""
    if not mark:
        return None
    k = str(said or "").find(mark)
    return (k, k + len(mark)) if k >= 0 else None


# ------------------------------------------------------------------ 文字を並べる
_EMOJI = video_common.EMOJI_RE
_TOKEN = re.compile(r"[A-Za-z0-9@#'’.,\-_/]+|\s|.", re.S)


def _tokens(text):
    """(始まり, 文字列, 絵文字か)。英数字の単語・絵文字のまとまりは1つにして、途中で折らない。"""
    out, pos = [], 0
    for part in _EMOJI.split(text):
        if not part:
            continue
        if _EMOJI.fullmatch(part):
            for ch in video_common._emoji_chunks(part):
                out.append((pos, ch, True))
                pos += len(ch)
            continue
        for m in _TOKEN.finditer(part):
            out.append((pos + m.start(), m.group(0), False))
        pos += len(part)
    return out


_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _width(tok, size, emoji):
    if emoji:
        return video_common.emoji_width(tok, size)
    return _PROBE.textlength(tok, font=font(size))


def layout_text(text, size, width):
    """文を幅 width で折り返す。行ごとに [(始まり, 文字列, x, 幅, 絵文字か)]。

    文字は1つも捨てない（行頭の空白だけは描かない）。句読点・閉じかっこは行頭に来ないようにぶら下げる。
    全角スペースで区切られたかたまり（「ホワイトソックス ケイ 3分の1回を2失点」）は、
    今の行に入らず次の行に入るなら、全角スペースのところで折る（review_render_v3.rich_lines と同じ考え方）。"""
    text = str(text or "").replace("\n", " ")
    toks = _tokens(text)
    widths = [_width(tok, size, emoji) for _, tok, emoji in toks]
    lines, cur, x = [], [], 0.0
    for j, (start, tok, emoji) in enumerate(toks):
        w = widths[j]
        if tok == "　" and cur:
            k = j + 1
            while k < len(toks) and toks[k][1] != "　":
                k += 1
            seg = sum(widths[j + 1:k])
            if x + w + seg > width and seg <= width:
                lines.append(cur)
                cur, x = [], 0.0
                continue
        if cur and x + w > width and tok not in r3.NO_HEAD and not tok.isspace():
            if not emoji and len(tok) > 1 and w > width:
                # 1語が1行より長い（長い英単語など）。文字で折る
                for k, ch in enumerate(tok):
                    cw = _width(ch, size, False)
                    if cur and x + cw > width and ch not in r3.NO_HEAD:
                        lines.append(cur)
                        cur, x = [], 0.0
                    cur.append((start + k, ch, x, cw, False))
                    x += cw
                continue
            lines.append(cur)
            cur, x = [], 0.0
        if not cur and tok.isspace():
            continue
        cur.append((start, tok, x, w, emoji))
        x += w
    if cur:
        lines.append(cur)
    return lines


def _line_width(line):
    return max((x + w for _, tok, x, w, _ in line if not tok.isspace()), default=0)


def _draw_tokens(layer, lines, size, x0, y0, line_h, fill):
    d = ImageDraw.Draw(layer)
    f = font(size)
    for i, line in enumerate(lines):
        base = y0 + i * line_h + round(size * 1.1)
        for _, tok, x, w, emoji in line:
            if emoji:
                im = video_common.emoji_image(tok, size)
                if im is not None:
                    layer.alpha_composite(im, (round(x0 + x), max(0, round(base - size * 0.92))))
            elif not tok.isspace():
                d.text((x0 + x, base), tok, font=f, fill=fill, anchor="ls")


def _mark_boxes(lines, span, size, x0, y0, line_h):
    """マーカーの帯（行ごとの四角）。左の行から順に引くので、並びは読む順。"""
    if not span:
        return ()
    a, b = span
    boxes = []
    for i, line in enumerate(lines):
        xs = []
        for start, tok, x, w, emoji in line:
            end = start + len(tok)
            if end <= a or start >= b:
                continue
            if emoji or len(tok) == 1:
                xs += [x, x + w]
                continue
            # 単語の途中から・途中まで
            ka, kb = max(a, start) - start, min(b, end) - start
            f = font(size)
            xs += [x + _PROBE.textlength(tok[:ka], font=f), x + _PROBE.textlength(tok[:kb], font=f)]
        if xs:
            base = y0 + i * line_h + round(size * 1.1)
            boxes.append((round(x0 + min(xs)), round(base - size * 0.98),
                          round(x0 + max(xs)), round(base + size * 0.2)))
    return tuple(boxes)


# ------------------------------------------------------------------ 吹き出し
def _palette(style, base, second):
    if style == "light":
        return {"bg": INK, "text": DARK_INK, "who": WHO_ON_LIGHT, "mark": GOLD + (255,)}
    if style == "dark":
        return {"bg": _mix(base, (255, 255, 255), 0.09), "text": INK, "who": second, "mark": GOLD + (85,)}
    return {"bg": GOLD, "text": DARK_INK, "who": _mix(GOLD, DARK_INK, 0.6), "mark": None}


def _bubble_shape(d, w, h, fill, small="tl"):
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=RADIUS, fill=fill)
    s = RADIUS * 2
    if small == "tl":
        d.rounded_rectangle((0, 0, s, s), radius=RADIUS_SMALL, fill=fill)
    else:
        d.rounded_rectangle((w - 1 - s, 0, w - 1, s), radius=RADIUS_SMALL, fill=fill)


def _avatar(d, x, y, fill, ink, icon=""):
    d.ellipse((x, y, x + AVATAR, y + AVATAR), fill=fill)
    cx, cy = x + AVATAR / 2, y + AVATAR / 2
    if icon:
        size = 40 if len(icon) <= 2 else 32
        d.text((cx, cy), icon, font=r3.num_font(size), fill=ink, anchor="mm")
        return
    # 名前を出さない人の印（頭と肩）。材料の文字ではない
    d.ellipse((cx - 13, cy - 26, cx + 13, cy), fill=ink)
    d.pieslice((cx - 25, cy + 4, cx + 25, cy + 52), 180, 360, fill=ink)


@functools.lru_cache(maxsize=256)
def _bubble(said, who, mark, style, indent, icon, base, second, size):
    """1つの吹き出し（丸＋吹き出し）を、マーカー抜きの絵・文字の絵・マーカーの帯に分けて作る。"""
    pal = _palette(style, base, second)
    fact = style == "fact"
    full = SAFE_RIGHT - LEFT - indent
    max_w = full - (0 if fact else AVATAR + AVATAR_GAP)
    text_w = max_w - 2 * PAD_X
    lines = layout_text(said, size, text_w)
    who_lines = layout_text(who, WHO_SIZE, text_w) if who else []
    who_h = len(who_lines) * round(WHO_SIZE * 1.4)
    line_h = round(size * LINE_H)
    inner_w = max([_line_width(ln) for ln in lines + who_lines] + [1])
    bw = min(max_w, round(inner_w) + 2 * PAD_X + 2)
    bh = PAD_Y + who_h + (WHO_GAP if who_lines else 0) + len(lines) * line_h + PAD_Y
    ox = 0 if fact else AVATAR + AVATAR_GAP
    width = ox + bw
    bg = Image.new("RGBA", (width, max(bh, AVATAR)), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    if not fact:
        _avatar(d, 0, 0, _mix(base, (255, 255, 255), 0.16) + (255,), second + (255,), icon)
    shape = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    _bubble_shape(ImageDraw.Draw(shape), bw, bh, pal["bg"] + (255,), "tr" if fact else "tl")
    bg.alpha_composite(shape, (ox, 0))
    text = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    y = PAD_Y
    if who_lines:
        _draw_tokens(text, who_lines, WHO_SIZE, ox + PAD_X, y - round(WHO_SIZE * 0.1),
                     round(WHO_SIZE * 1.4), pal["who"])
        y += who_h + WHO_GAP
    _draw_tokens(text, lines, size, ox + PAD_X, y - round(size * 0.12), line_h, pal["text"])
    boxes = _mark_boxes(lines, None if fact else mark_span(said, mark), size, ox + PAD_X,
                        y - round(size * 0.12), line_h)
    return {"bg": bg, "text": text, "boxes": boxes, "mark": pal["mark"], "size": size,
            "lines": lines, "width": width, "height": bg.height}


def _marked(b, k):
    """マーカーを k（0〜1）まで引いた吹き出し。左の行から順に伸びる。"""
    if not b["boxes"] or k <= 0:
        return _final(b, 0)
    if k >= 1:
        return _final(b, 1)
    im = b["bg"].copy()
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    total = sum(x1 - x0 for x0, _, x1, _ in b["boxes"])
    left = total * k
    for x0, y0, x1, y1 in b["boxes"]:
        if left <= 0:
            break
        d.rectangle((x0, y0, min(x1, x0 + left), y1), fill=b["mark"])
        left -= x1 - x0
    im.alpha_composite(lay)
    im.alpha_composite(b["text"])
    return im


def _final(b, k):
    """マーカーを引く前（k=0）と引き終わり（k=1）の吹き出し。吹き出しごとに1回だけ作る。"""
    cache = b.setdefault("final", {})
    if k not in cache:
        im = b["bg"].copy()
        if k and b["boxes"]:
            lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            for box in b["boxes"]:
                d.rectangle(box, fill=b["mark"])
            im.alpha_composite(lay)
        im.alpha_composite(b["text"])
        cache[k] = im
    return cache[k]


def _styles(voices):
    """事実は金色。コメントは白と濃い色を交互に（事実をはさんでも、最初のコメントは白）。"""
    out, n = [], 0
    for v in voices:
        if v.get("fact"):
            out.append("fact")
        else:
            out.append("light" if n % 2 == 0 else "dark")
            n += 1
    return out


def _key(voices):
    return tuple((str(v.get("said") or ""), str(v.get("who") or ""), str(v.get("mark") or ""),
                  bool(v.get("fact")), bool(v.get("reply")), str(v.get("icon") or "")) for v in voices)


def _bubbles(key, base, second, size):
    out = []
    for (said, who, mark, fact, reply, icon), style in zip(key, _styles([{"fact": k[3]} for k in key])):
        out.append(_bubble(said, who, mark, style, REPLY_INDENT if reply else 0, icon,
                           tuple(base), tuple(second), min(size, FACT_SIZE) if fact else size))
    return out


def start_times(voices):
    """吹き出しが出る時刻。voice に "at"（秒）があればそれ、無ければモックの時刻表。"""
    out, last = [], None
    for i, v in enumerate(voices):
        at = v.get("at")
        if at is None:
            at = BUBBLE_AT[i] if i < len(BUBBLE_AT) else BUBBLE_AT[-1] + (i - len(BUBBLE_AT) + 1) * BUBBLE_GAP
        at = float(at)
        if last is not None and at < last:
            at = last
        out.append(at)
        last = at
    return out


def stack(voices, team_id=None):
    """吹き出しの並び。[(x, y（並びの上端からの位置）, 吹き出し)] と、出るたびに要る押し出しの量。"""
    return _stack(_key(voices), team_id)


@functools.lru_cache(maxsize=64)
def _stack(key, team_id):
    """字の大きさは画面の中で1つにそろえる。全部が並びに入る、いちばん大きい字（SAID_SIZES）。
    いちばん小さくしても入らないときだけ、古い吹き出しを上へ押し出す（文は切らない）。"""
    base, second, _ = r3.colors(team_id)
    room = AREA_BOTTOM - AREA_TOP
    for size in SAID_SIZES:
        bubbles = _bubbles(key, base, second, size)
        if sum(b["height"] for b in bubbles) + GAP * (len(bubbles) - 1) <= room:
            break
    rows, y = [], 0
    for k, b in zip(key, bubbles):
        x = SAFE_RIGHT - b["width"] if k[3] else LEFT + (REPLY_INDENT if k[4] else 0)
        rows.append((x, y, b))
        y += b["height"] + GAP
    prev, steps = 0, []
    for x, y, b in rows:
        n = max(prev, y + b["height"] - room)
        steps.append(n - prev)
        prev = n
    return tuple(rows), tuple(steps)


def scroll_at(t, voices, team_id=None):
    """t 秒のときの押し出しの量（px）。吹き出しが出るのに合わせて滑らかに増える。"""
    _, steps = stack(voices, team_id)
    return sum(s * ease_out((t - at) / SCROLL_IN) for s, at in zip(steps, start_times(voices)))


# ------------------------------------------------------------------ 背景・帯・見出し
@functools.lru_cache(maxsize=16)
def _ring(size, color):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((0, 0, size - 1, size - 1), outline=color + (255,), width=RING_WIDTH)
    return im


def background(t, team_id):
    """地の色に、小さな輪が下から浮かんで消える（d-float）。"""
    base, second, _ = r3.colors(team_id)
    im = Image.new("RGB", (W, H), base)
    for x, bottom, size, which, period, delay in RINGS:
        if t < delay:
            continue
        ph = ((t - delay) % period) / period
        alpha = 0.5 * ph / 0.1 if ph < 0.1 else 0.5 * (1 - ph) / 0.9
        if alpha <= 0.01:
            continue
        ring = _ring(size, GOLD if which == "gold" else tuple(second))
        a = ring.split()[3].point(lambda v, k=alpha: round(v * k))
        im.paste(ring, (x, round(bottom - size - RING_RISE * ph)), a)
    return im


@functools.lru_cache(maxsize=16)
def _strip(text, second):
    f = font(STRIP_SIZE)
    one = round(_PROBE.textlength(text, font=f)) + 96
    n = max(2, math.ceil(W / one) + 1)
    im = Image.new("RGB", (one * n, STRIP_H), second)
    d = ImageDraw.Draw(im)
    for k in range(n):
        d.text((k * one + 48, STRIP_H // 2), text, font=f, fill=DARK_INK, anchor="lm")
    return im, one


def strip(im, t, text, second):
    """事実の帯。右から左へ流れ続ける（d-strip）。"""
    if not text:
        return
    band, one = _strip(text, tuple(second))
    off = round(t * STRIP_SPEED) % one
    im.paste(band.crop((off, 0, off + W, STRIP_H)), (0, STRIP_Y))


def header(d, t, title, live, second, page=None):
    d.text((LEFT, HEAD_BASE), "コレスポ", font=font(44), fill=GOLD, anchor="ls")
    x = LEFT + d.textlength("コレスポ", font=font(44)) + 28
    if title:
        d.text((x, HEAD_BASE), title, font=font(28), fill=second, anchor="ls")
        x += d.textlength(title, font=font(28)) + 28
    if live:
        if (t % BLINK) < BLINK / 2:
            d.ellipse((x, HEAD_BASE - 22, x + 16, HEAD_BASE - 6), fill=LIVE_RED)
        d.text((x + 28, HEAD_BASE), live, font=font(26), fill=LIVE_RED, anchor="ls")
    if page:
        d.text((SAFE_RIGHT, HEAD_BASE), page, font=r3.num_font(40), fill=GOLD, anchor="rs")


def _fit_line(d, text, width):
    size = SOURCE_SIZE
    while size > SOURCE_MIN and d.textlength(text, font=font(size)) > width:
        size -= 1
    return size


def source(d, lines, color):
    """引用元（立ち絵の右。モックの「引用：…」「数字：…」）。1行ずつ、入らなければ字を小さく。"""
    y = SOURCE_Y
    for line in [x for x in lines if x][:2]:
        size = _fit_line(d, line, SAFE_RIGHT - SOURCE_X)
        d.text((SOURCE_X, y), line, font=font(size), fill=color)
        y += round(SOURCE_SIZE * 1.5)


def presenter(im, t):
    sp = r3._portrait("metan")
    bob = round(BOB_PX / 2 * (1 - math.cos(t * 2 * math.pi / BOB_SECONDS)))
    im.paste(sp, (PRESENTER_X, PRESENTER_BOTTOM - sp.height - bob), sp)


# ------------------------------------------------------------------ 画面
def comments(t, voices, team_id, strip_text, title=TITLE, live=LIVE_COMMENTS,
             source_lines=("引用：MLB公式ハイライトのコメント欄（訳：コレスポ）",), page=None, backdrop=None):
    """コメント欄ライブの t 秒目の絵（1080×1920、RGB）。

    voices: [{"said": 訳文, "who": 短い説明, "mark": マーカーの語（said の部分文字列。無ければ引かない）}]
      ほかに入れてよいもの: "at"（出る秒）・"fact"（True なら金色の事実の吹き出し、右寄せ）・
      "reply"（True なら返信。少し右へずらす）・"icon"（丸の中の短い英字。無ければ人の印）。
    strip_text: 上を流れる事実の帯の文（材料の文そのまま）。"""
    voices = list(voices or [])
    base, second, _ = r3.colors(team_id)
    im = (backdrop or background)(t, team_id)
    d = ImageDraw.Draw(im)
    header(d, t, title, live, second, page)
    strip(im, t, strip_text, second)
    rows, _ = stack(voices, team_id)
    off = scroll_at(t, voices, team_id)
    layer_h = AREA_BOTTOM - AREA_TOP + RISE_PX + 40
    layer = Image.new("RGBA", (W, layer_h), (0, 0, 0, 0))
    for (x, y, b), at in zip(rows, start_times(voices)):
        if t < at:
            continue
        k = ease_out((t - at) / RISE)
        yy = round(y - off + RISE_PX * (1 - k))
        if yy + b["height"] <= 0 or yy >= layer_h:
            continue
        card = _marked(b, ease_out((t - at - MARK_AFTER) / MARK_IN))
        if k < 1:
            card = card.copy()
            card.putalpha(card.split()[3].point(lambda v, kk=k: round(v * kk)))
        if yy < 0:
            card = card.crop((0, -yy, card.width, card.height))
            yy = 0
        layer.alpha_composite(card, (x, yy))
    if off > 0:
        # 押し出された吹き出しは、上の端で薄くなって消える
        fade = min(1.0, off / AREA_FADE)
        alpha = layer.split()[3]
        ramp = Image.linear_gradient("L").resize((W, AREA_FADE))
        ramp = ramp.point(lambda v: round(255 - (255 - v) * fade))
        top = Image.composite(alpha.crop((0, 0, W, AREA_FADE)), Image.new("L", (W, AREA_FADE), 0), ramp)
        alpha.paste(top, (0, 0))
        layer.putalpha(alpha)
    im.paste(layer, (0, AREA_TOP), layer)
    source(d, source_lines, second)
    presenter(im, t)
    return im


def unified_comments(t, voices, team_id, strip_text, title=TITLE, live=LIVE_COMMENTS,
                     source_lines=(), page=None, backdrop=None):
    import v3_slot_render as common
    voices = list(voices or [])
    rows = [(common.screen_text(v.get('who','')), common.screen_text('「'+v.get('said','')+'」' if not v.get('fact') else v.get('said',''))) for v in voices]
    spec = {'team_id': team_id, 'heading': common.screen_text(live), 'page': page, 'v3': {'ticker': common.screen_text(strip_text)}}
    return common.frame(t, spec, rows, common.screen_text(title), common.screen_text('\n'.join(source_lines)), start_times(voices),
                        [v.get('reply', False) for v in voices], ends=[v.get('end',v.get('at',0)+4) for v in voices])


def texts(voices, strip_text, title=TITLE, live=LIVE_COMMENTS,
          source_lines=("引用：MLB公式ハイライトのコメント欄（訳：コレスポ）",), page=None):
    """comments が描く文字のすべて（検査用。材料に無い数字を描いていないかを見る）。"""
    out = ["コレスポ", title or "", live or "", strip_text or "", page or ""]
    for v in voices or []:
        out += [str(v.get("who") or ""), str(v.get("said") or ""), str(v.get("icon") or "")]
    out += [x for x in source_lines if x][:2]
    return [x for x in out if x]


def cues(voices):
    """効果音 [(秒, 種類, 案, 追加の音量dB)]。描画と同じ start_times と時刻表から。

    吹き出しが出る → notify（返信は b）。事実の吹き出し → pop。マーカーが引かれ始める → marker。"""
    voices = list(voices or [])
    out = []
    for v, at in zip(voices, start_times(voices)):
        if v.get("fact"):
            out.append((at, "pop", "a", -3))
            continue
        out.append((at, "notify", "b" if v.get("reply") else "a", -3))
        if mark_span(v.get("said"), v.get("mark")):
            out.append((at + MARK_AFTER, "marker", "a", -4))
    return sorted(out, key=lambda c: c[0])


def unified_cues(voices):
    """効果音 [(秒, 種類, 案, 追加の音量dB)]。描画と同じ start_times と時刻表から。

    吹き出しが出る → notify（返信は b）。事実の吹き出し → pop。マーカーが引かれ始める → marker。"""
    import v3_slot_render as common
    voices = [v for v in voices or [] if v.get('read') is not False]
    rows = [(v.get('who',''), ('「'+v.get('said','')+'」') if not v.get('fact') else v.get('said','')) for v in voices]
    return common.cues(rows, start_times(voices))



def timed(voices, spoken, dur, lead=0.4, min_gap=0.8):
    """読み上げ（spoken）の中で、その声を読み始める位置に合わせて "at" を付けた写しを返す。

    読み始める少し前（lead 秒）に吹き出しを出す。読み上げに見つからない声は前の声の min_gap 秒後。
    尺（dur）に入りきらない時刻は、尺の終わりの RISE 秒前に寄せる。"""
    spoken = str(spoken or "")
    n = max(1, len(spoken))
    out, last, pos = [], None, 0
    for v in voices:
        key = str(v.get("said") or "").strip().rstrip("。！!、.")[:12]
        k = spoken.find(key, pos) if key else -1
        if k >= 0:
            at = max(BUBBLE_AT[0], dur * k / n - lead)
            pos = k + len(key)
        else:
            at = (last + min_gap) if last is not None else BUBBLE_AT[0]
        if last is not None:
            at = max(at, last + min_gap)
        at = min(at, max(0.0, dur - RISE))
        last = at
        out.append(dict(v, at=round(at, 3)))
    return out


# ------------------------------------------------------------------ (a) review_render_v3 の項目の画面
def is_voice_head(head):
    return head == COMMENT_HEAD or str(head).endswith(REPORTER_TAIL)


def uses_comments(items, start=0, count=None):
    page = list(items)[start:start + count] if count is not None else list(items)[start:]
    return any(is_voice_head(h) for h, _ in page)


def unquote(body):
    """項目の本文の外側の「」だけを外す（gs.quoted が付けたもの。中の言葉は変えない）。"""
    s = str(body or "")
    return s[1:-1] if len(s) >= 2 and s.startswith("「") and s.endswith("」") else s


def voices_from_items(items, spec=None):
    """項目 [(見出し, 本文)] を吹き出しに。引用（「」）は吹き出し、それ以外は金色の事実の吹き出し。

    説明の行は見出しから「から」を外したもの（「ハイライトのコメント欄」「ホワイトソックスの番記者の投稿」）。
    番記者は、材料に名前と所属があれば添える（spec["source"] の author・outlet）。"""
    spec = spec or {}
    names = tuple(x.get("name") for x in (spec.get("japanese") or []) if x.get("name"))
    src = spec.get("source") or {}
    out = []
    for head, body in items:
        head, body = str(head), str(body)
        who = head[:-2] if head.endswith("から") else head
        if is_voice_head(head) or body.startswith("「"):
            said = unquote(body)
            if head.endswith(REPORTER_TAIL) and src.get("author"):
                who += f"　{src['author']}" + (f"（{src['outlet']}）" if src.get("outlet") else "")
            out.append({"said": said, "who": who, "mark": pick_mark(said, names)})
        else:
            out.append({"said": body, "who": who, "mark": "", "fact": True})
    return out


def _strip_of(spec):
    return (spec.get("v3") or {}).get("ticker") or spec.get("hook") or spec.get("heading") or ""


def _page_source(spec, page_items):
    from review_render import page_source
    line = page_source(page_items)
    if _strip_of(spec) and "MLB公式（Stats API）" not in line:
        line += "・MLB公式（Stats API）"
    return (line,)


def _live_of(page_items):
    heads = [h for h, _ in page_items]
    live = []
    if COMMENT_HEAD in heads:
        live.append(LIVE_COMMENTS)
    if any(str(h).endswith(REPORTER_TAIL) for h in heads):
        live.append(LIVE_REPORTER)
    return "・".join(live)


def list_page(t, spec, items, start, count, page, pages, kind_label):
    """review_render_v3.list_page と同じ引数。コメント欄・番記者の項目がある頁だけ D の見た目にする。"""
    page_items = list(items)[start:start + count]
    if not uses_comments(page_items):
        return r3.list_page(t, spec, items, start, count, page, pages, kind_label)
    return unified_comments(t, voices_from_items(page_items, spec), spec.get("team_id"), _strip_of(spec),
                    title=kind_label, live=_live_of(page_items),
                    source_lines=_page_source(spec, page_items), page=f"{page}/{pages}")


def list_cues(spec, items, start=0, count=0):
    """review_render_v3.cues("list", …) の代わり。D の頁は吹き出しとマーカーの音。"""
    page_items = list(items)[start:start + count]
    if not uses_comments(page_items):
        return r3.cues("list", spec, items, start, count)
    return unified_cues(voices_from_items(page_items, spec))


# ------------------------------------------------------------------ (b) 17:30「現地のファンは何と言ったか」
def who_of(v):
    """コメントの説明の行。名前（アカウント名）は出さず、材料の高評価の数だけ。"""
    likes = v.get("likes") or 0
    return f"高評価{likes:,}件のコメント" if likes else "コメント"


def voices_for_segment(seg, voices_data):
    """generate_morning_short の画面（kind が voices / thread）を吹き出しの並びに。

    voices: meta["picked"] の順（読み上げと同じ並び）に、VOICES_SHOWN 件まで。
    thread: 1件のコメントと、それへの返信（reply_ja の先頭3件。読み上げと同じ）。"""
    kind, meta = seg.get("kind"), seg.get("meta") or {}
    vs = (voices_data or {}).get("voices") or []
    if 'quote_rows' in meta:
        allowed={v.get('ja','') for v in vs}
        allowed.update(r.get('ja','') for v in vs for r in v.get('reply_ja',[]))
        for row in meta['quote_rows']:
            if not row.get('fact') and row.get('said') not in allowed:
                raise ValueError('引用区間のコメントが原材料にありません')
        return list(meta['quote_rows'])
    out = []
    if kind == 'intro':
        i=meta.get('used_voice')
        if type(i) is int and 0<=i<len(vs):
            v=vs[i]
            out.append({'said':v.get('ja',''),'who':who_of(v)})
    elif kind == "voices":
        picked = meta.get("picked")
        if picked is not None and any(type(i) is not int or not 0 <= i < len(vs) for i in picked):
            raise ValueError("コメント番号が材料と合いません")
        rows = [vs[i] for i in picked] if picked is not None else list(vs)
        for v in rows[:VOICES_SHOWN]:
            said = str(v.get("ja") or "").strip()
            if said:
                out.append({"said": said, "who": who_of(v), "mark": pick_mark(said, v.get("jp_players") or ())})
    elif kind == "thread":
        i = meta.get("index")
        if i is None:
            return out
        if type(i) is not int or not 0 <= i < len(vs):
            raise ValueError("返信元のコメント番号が材料と合いません")
        v = vs[i]
        said = str(v.get("ja") or "").strip()
        likes, replies = v.get("likes") or 0, v.get("replies") or 0
        who = "・".join(x for x in ((f"高評価{likes:,}件" if likes else ""),
                                     (f"返信{replies}件" if replies else "")) if x) or "コメント"
        if not meta.get('parent_read'):
            out.append({"said": said, "who": who, "mark": pick_mark(said, v.get("jp_players") or ())})
        for r in (v.get("reply_ja") or [])[:3]:
            rs = str(r.get("ja") or "").strip()
            if rs:
                out.append({"said": rs, "who": "返信", "mark": pick_mark(rs), "reply": True})
    return out


def jp_matchup(matchup):
    try:
        import mlb_buzz
        return mlb_buzz.jp_matchup(matchup)
    except Exception:                                      # noqa: BLE001
        return str(matchup or "").split(":")[0].strip()


def strip_for_voices(voices_data, seg=None):
    """17:30 の事実の帯: 「どの試合のハイライトか」と「何を翻訳したか」。材料の文字だけ。"""
    vs = (voices_data or {}).get("voices") or []
    meta = (seg or {}).get("meta") or {}
    idx = meta.get("picked") or ([meta["index"]] if meta.get("index") is not None else range(len(vs)))
    games = []
    for i in idx:
        if i < len(vs) and vs[i].get("matchup"):
            g = jp_matchup(vs[i]["matchup"])
            if g and g not in games:
                games.append(g)
    src = (voices_data or {}).get("source") or ""
    return "　".join(games[:2] + ([f"{src}を翻訳"] if src else []))


def _voices_source(voices_data):
    return ('引用：MLBコメント（訳：コレスポ）','コレスポの見解ではありません')


def reading_times(voices,spoken,duration):
    """原稿の引用位置を表示区間へ写す。未読の札は出さない。"""
    out=[];cursor=0;scale=duration/max(1,len(spoken))
    for voice in voices:
        if voice.get('read') is False:
            out.append(dict(voice,at=0,end=0));continue
        if voice.get('clip'):
            if voice['said'].strip().rstrip('。！!、.') not in spoken:
                raise ValueError('引用区間と読み上げが一致しません')
            out.append(dict(voice,at=0,end=duration));continue
        body=str(voice.get('said','')).strip().rstrip('。！!、.')
        key=body[:12]
        at=spoken.find(key,cursor)
        if not key or at<0:
            raise ValueError('画面の引用が読み上げ順にありません: '+key)
        finish=min(len(spoken),at+len(body))
        out.append(dict(voice,at=at*scale,end=finish*scale))
        cursor=finish
    return out


def voices_screen(t, seg, voices_data, dur=None, team_id=None):
    """17:30 の voices / thread の画面を D で。dur（その画面の秒）があれば、読み上げに合わせて出す。"""
    voices = voices_for_segment(seg, voices_data)
    if dur:
        voices = reading_times(voices, seg.get("text") or "", dur)
    return unified_comments(t, voices, team_id, strip_for_voices(voices_data, seg),
                    source_lines=_voices_source(voices_data))


def voices_cues(seg, voices_data, dur=None):
    voices = voices_for_segment(seg, voices_data)
    if dur:
        voices = reading_times(voices, seg.get("text") or "", dur)
    return unified_cues(voices)


# ------------------------------------------------------------------ 見本
def _no_network():
    """見本・検査で外部へつながないように（材料は写しの data/ だけ）。"""
    import socket

    def refuse(*a, **k):
        raise OSError("外部への接続はしません（見本・検査）")
    socket.socket.connect = refuse
    try:
        import urllib.request
        urllib.request.urlopen = refuse
    except ImportError:
        pass


def load_json(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def sample_segments(voices_data):
    """17:30 の原稿を、本番の build_narration で写しの材料から作る（声の回）。"""
    import generate_morning_short as gms
    data = {"players": [], "voices": voices_data, "date": ""}
    return [s for s in gms.build_narration(data, "voices")["segments"] if s["kind"] in ("voices", "thread")]


def estimate_dur(text, chars_per_sec=7.0, least=6.0):
    """見本用の尺の見積もり（本番は読み上げの音声の長さ。ここでは文字数から）。"""
    return max(least, len(str(text or "")) / chars_per_sec)


def main(argv=None):
    ap = argparse.ArgumentParser(description="案D「コメント欄ライブ」の見本を描く")
    ap.add_argument("--out", default="samples")
    ap.add_argument("--width", type=int, default=540, help="見本の横幅（既定 540 = 半分。1080 で原寸）")
    args = ap.parse_args(argv)
    _no_network()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def save(im, name):
        if args.width != W:
            im = im.resize((args.width, round(H * args.width / W)), Image.LANCZOS)
        im = im.quantize(256)                      # 見本は軽く（256色）
        im.save(out / name, optimize=True)
        print(f"[info] {out / name}")

    vd = load_json("local_voices.json")
    segs = {s["kind"]: s for s in sample_segments(vd)}
    team = None
    seg = segs.get("voices")
    if seg:
        dur = estimate_dur(seg["text"])
        vs = timed(voices_for_segment(seg, vd), seg["text"], dur)
        at = start_times(vs)
        save(voices_screen(at[0] + 1.5, seg, vd, dur, team), "comment_01_voices_mark.png")
        save(voices_screen(dur - 0.2, seg, vd, dur, team), "comment_02_voices_all.png")
    seg = segs.get("thread")
    if seg:
        dur = estimate_dur(seg["text"])
        save(voices_screen(dur - 0.2, seg, vd, dur, team), "comment_03_thread.png")

    # (a) PSの話題の項目の画面（ホワイトソックス対ガーディアンズ 地区シリーズ第2戦）
    topics = load_json("ps_game_topics.json")["topics"]
    spec = next((x for x in topics if any(h == COMMENT_HEAD for h, _ in x.get("items") or [])), None)
    if spec:
        spec = dict(spec)
        items = [tuple(x) for x in spec["items"]]
        # 写しの ps_game_topics.json のこのコメントは、直す前の訳し替え（Sox → ボストン・レッドソックス）が
        # 残ったもの（本番は ps_game_story.team_words で直っている）。見本では同じコメントの
        # local_voices.json の訳をそのまま使う（同じ url・同じ原文。文字は変えない）。
        voice = spec.get("voice") or {}
        raw = next((v for v in vd.get("voices") or [] if v.get("url") == voice.get("url")
                    and v.get("title") == voice.get("text")), None)
        if raw:
            items = [(h, f"「{raw['ja']}」" if h == COMMENT_HEAD else b) for h, b in items]
        k = next(i for i, (h, _) in enumerate(items) if h == COMMENT_HEAD)
        start = k - k % 2
        pages = (len(items) + 1) // 2
        save(list_page(5.0, spec, items, start, 2, start // 2 + 1, pages, "PSの話題"),
             "comment_04_ps_item_page.png")

    # (a) 番記者の項目（写しの local_reporters.json の投稿1件。ps_momentum と同じ見出しの形）
    rep = load_json("local_reporters.json")
    import notability_engine as ne
    team_ids = {v: int(k) for k, v in ne.MLB_TEAM_NAME_JP.items()}
    # 本番の pick_reporter と同じ長さ（80文字まで）で、球団の分かる投稿の最初の1件
    post = next((p for p in rep.get("posts") or [] if p.get("jp") and 30 <= len(p["jp"]) <= 80
                 and p.get("team") in team_ids), None)
    if post:
        tid = team_ids[post["team"]]
        spec = {"team_id": tid, "hook": "", "heading": "",
                "source": {"author": post.get("author"), "outlet": post.get("outlet")}}
        items = [(f"{post['team']}の{REPORTER_TAIL}", f"「{post['jp']}」")]
        save(list_page(3.0, spec, items, 0, 1, 1, 1, "PSの話題"), "comment_05_reporter.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
