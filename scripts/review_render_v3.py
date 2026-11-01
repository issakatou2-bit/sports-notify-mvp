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
from review_render import page_source, PORTRAITS, _tokens  # noqa: E402
import calm_motion  # noqa: E402  COLLESPO_MOTION=on のときだけ動きを控えめに（Opus-32）

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
# ショートの見た目 v4（10/8 本人「長編のデザインは良い。ショートは物足りない・代わり映えしない」）。
# 長編の良さ（読んでいる文の字幕・大きめの立ち絵・進み具合の線）を縦に持ってくる。
# 切り替えは COLLESPO_SHORT_LOOK=v4（リポジトリ変数）。試作を本人に見せてから。
import os  # noqa: E402
LOOK = os.environ.get("COLLESPO_SHORT_LOOK", "v3")
# サッカーv5も共通のcharacters/安全域はv4を使う。既存のv3/v4の値は変えない。
if os.environ.get('COLLESPO_SOCCER_LOOK') == 'v5' or LOOK == 'v5':
    LOOK = 'v4'
CONTENT_TOP = 236
# v4 は札の下に出典（2行）と字幕の箱を置くので、札の下端を上げる
CONTENT_BOTTOM = 1150 if LOOK == "v4" else 1216
CAPTION_TOP, CAPTION_RIGHT, CAPTION_BOTTOM = 1248, 668, 1472
SOURCE_BOTTOM = 1218 if LOOK == "v4" else 1478
METAN_PINK = (238, 140, 186)


def record_box(im, role, box, text=''):
    im.info.setdefault('v3_layout',[]).append({'role':role,'box':list(box),'text':str(text)})


def _text(d, xy, text, **kwargs):
    role=kwargs.pop("role","text")
    d.text(xy,text,**kwargs)
    box=d.textbbox(xy,text,**{k:v for k,v in kwargs.items() if k in ('font','anchor','stroke_width','spacing','align')})
    record_box(d._image,role,box,text)


def design_team(spec):
    teams={str(t.get('team_id',t.get('id'))) if isinstance(t,dict) else str(t) for t in spec.get('teams',[])}
    teams.update(str(p['team_id']) for p in spec.get('japanese',[]) if p.get('team_id') is not None)
    if spec.get('series_key'):
        teams.update(spec['series_key'].split(':')[-1].split('-'))
    return None if spec.get('multi_team') or spec.get('game') or len(teams)>1 else spec.get('team_id')


def _lines(d, text, size, width, max_lines=4, floor=24):
    """描画と同じ書体で札の幅を計測する。長い語も幅以内で折る。"""
    while True:
        f = font(size)
        lines, line = [], ''
        for part in str(text).split('\n'):
            for token in _tokens(part):
                if d.textbbox((0,0),line+token,font=f)[2] <= width:
                    line += token
                    continue
                if line:
                    lines.append(line.rstrip()); line = ''
                for ch in token:
                    if line and d.textbbox((0,0),line+ch,font=f)[2] > width:
                        lines.append(line.rstrip()); line = ''
                    line += ch
            if line:
                lines.append(line.rstrip()); line = ''
        if line:
            lines.append(line.rstrip())
        if len(lines) <= max_lines or size <= floor:
            return lines[:max_lines], size
        size -= 2


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
    """少し行き過ぎて戻る。COLLESPO_MOTION=on では行き過ぎを小さく（弾みは1回だけ）。"""
    s = s * calm_motion.value('overshoot', 1.0)
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
    import motion
    if motion.enabled():t *= motion.SETTINGS['background_speed']
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
    return motion.background(im,t)


# ------------------------------------------------------------------ 部品
def _header(d, label, page=None, second=(196, 206, 212)):
    _text(d,(LEFT, 168), "コレスポ", font=font(44), fill=GOLD, role="header")
    _text(d,(LEFT + 210, 180), label, font=font(28), fill=second, role="header")
    if page:
        _text(d,(SAFE_RIGHT, 172), page, font=num_font(40), fill=GOLD, anchor="ra", role="header")


def _badge(d, x, y, abbr, base, second):
    w = max(150, round(d.textlength(abbr, font=num_font(44))) + 56)
    d.rounded_rectangle((x, y, x + w, y + 76), radius=16, fill=_mix(base, (0, 0, 0), 0.3),
                        outline=second, width=6)
    _text(d,(x + w / 2, y + 38), abbr, font=num_font(44), fill=INK, anchor="mm")
    return w


@functools.lru_cache(maxsize=16)
def _ticker_strip(text):
    f = font(40)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    w = round(probe.textlength(text, font=f)) + 112
    repeats = (W+w-1)//w+2
    im = Image.new("RGB", (w * repeats, 88), GOLD)
    d = ImageDraw.Draw(im)
    for k in range(repeats):
        _text(d,(k * w + 56, 44), text, font=f, fill=DARK_INK, anchor="lm")
    return im, w


@functools.lru_cache(maxsize=16)
def _single_ticker(text):
    f = font(40)
    probe = ImageDraw.Draw(Image.new('RGB',(8,8)))
    box = probe.textbbox((0,44),text,font=f,anchor='lm')
    strip = Image.new('RGB',(box[2]-box[0]+112,88),GOLD)
    ImageDraw.Draw(strip).text((56-box[0],44),text,font=f,fill=DARK_INK,anchor='lm')
    return strip


# 帯は番組全体で1本の時計で流す（画面が変わるたびに頭へ戻らない）。
# 10/8 試作で、17:00〜18:00 の帯が画面ごとに「きょうの日本人選手」へ戻っていた。
# 動画を書く側が毎コマ set_program_clock(番組の頭からの秒) を呼ぶ。呼ばなければ画面内の t を使う。
_PROGRAM_CLOCK = [None]
LAST_TICKER = [None]


def set_program_clock(seconds):
    _PROGRAM_CLOCK[0] = seconds


def redraw_ticker(raw, size=(1080, 1920)):
    """切り替わりで2枚を混ぜた後に、帯だけを描き直す（帯が二重に見えないように）。"""
    last = LAST_TICKER[0]
    if not last or _PROGRAM_CLOCK[0] is None:
        return raw
    im = Image.frombytes("RGB", size, raw)
    ticker(im, _PROGRAM_CLOCK[0], last[0], y=last[1], once=last[2])
    return im.tobytes()


def ticker(im, t, text, y=1486, once=False):
    if not text:
        return
    # クラブ名は表示名の表（notability_engine.club_display_text）を通す。古い書き方を帯に出さない
    import notability_engine as ne
    text = ne.club_display_text(text)
    if _PROGRAM_CLOCK[0] is not None:
        t = _PROGRAM_CLOCK[0]
    LAST_TICKER[0] = (text, y, once)
    if once:
        strip = _single_ticker(text)
        band = Image.new('RGB',(W,88),GOLD)
        x = W-((W+round(t*80)) % (W+strip.width))
        band.paste(strip,(x,0))
        im.paste(band,(0,y))
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
    """出典。立ち絵（右下）にかからない幅で、2行まで（v4 は3行まで）。v4 は字幕の箱の上。"""
    # v4 は右に上半身が立つので、その手前まで（掛け合いは2人分）。入らなければ字を20まで小さく
    if LOOK == "v4":
        import characters
        width = SAFE_RIGHT - LEFT - characters.reserved_width(_CAPTION.get("duo"))
        lines, size = _lines(d, text, 24, width, 2, 20)
        if len("".join("".join(lines).split())) < len("".join(str(text).split())):
            lines, size = _lines(d, text, 20, width, 3, 20)   # 2行に入らないときだけ、20の字で3行
    else:
        lines, size = _lines(d, text, 24, SAFE_RIGHT - LEFT - 280, 2)
    for i, line in enumerate(lines):
        _text(d,(LEFT, SOURCE_BOTTOM - (len(lines) - i) * (size + 6)), line, font=font(size), fill=color, role="source")


@functools.lru_cache(maxsize=16)
def _portrait_v4(who="metan", face="base"):
    if who == "metan":
        path = ROOT / PORTRAITS / "metan/3-black" / f"{face}.png"
        if not path.exists():
            path = ROOT / PORTRAITS / "metan/3-black/base.png"
    else:
        path = ROOT / PORTRAITS / "zundamon/C-cheer/base-black-brow-candidate.png"
    sp = Image.open(path).convert("RGBA").crop((120, 0, 940, 900))
    sp.thumbnail((330, 330))
    return sp


# 表情（v4）。10/8 本人「めたんの表情とかポーズ差分ほしい」。差分はすでにある
# （metan/3-black: talk・smile・surprise・jitome・pose・pose-smile。base と同じ位置に描いてある）。
# 読んでいる文の言葉で表情を選び、ふつうの文では話している間だけ口を動かす（base と talk を交互に）。
FACE_WORDS = (
    ("surprise", ("自己最多", "初めて", "初の", "記録", "！", "!")),
    ("jitome", ("敗退", "負け", "敗れ", "失策", "無安打", "0安打", "黒星")),
    ("smile", ("勝ち", "勝って", "勝利", "突破", "王手", "優勝", "本塁打", "完封", "セーブ")),
    ("pose-smile", ("きょうの", "今日の", "こちら", "まとめ", "一覧", "全試合")),
)
MOUTH_RATE = 7.0      # 1秒に口を開け閉めする回数の目安（音に合わせた口パクではない）


def face_for(line, elapsed, duration):
    mood = next((m for m, words in FACE_WORDS if any(w in str(line) for w in words)), "base")
    speaking = elapsed < max(0.3, duration - 0.35)
    if mood == "base" and speaking and int(elapsed * MOUTH_RATE) % 2 == 1:
        return "talk"
    return mood


# ------------------------------------------------------------------ 字幕（v4）
# 動画を書く側が画面の頭で set_caption(読み上げの文, その画面の秒, 番組の秒) を呼ぶ。
# 時刻は番組の時計（set_program_clock）から測る。画面ごとの t の数え方が部品で違っても揃う。
_CAPTION = {"text": "", "start": 0.0, "duration": 0.0, "total": 0.0}


def set_caption(text, duration, total=None, speaker=2, duo=False, hide_caption=False, caption_units=None, phrase_wrap=False):
    if caption_units is not None and ''.join(caption_units) != str(text or ''):
        raise ValueError('吹き出しのまとまりと原稿が一致しません')
    _CAPTION.update(text=str(text or ""), duration=float(duration or 0),
                    start=_PROGRAM_CLOCK[0] or 0.0, total=float(total or _CAPTION["total"] or 0),
                    speaker=speaker, duo=bool(duo and LOOK=='v4'),hide_caption=hide_caption,
                    caption_units=caption_units, phrase_wrap=phrase_wrap)


def sentences(text):
    return [s for s in re.findall(r"[^。！？!?]+[。！？!?]?", str(text or "")) if s.strip()]


CAPTION_CHUNK = 38   # 字幕の箱に3行で入る字数の目安。短い文はまとめて出す


def caption_chunks(text, limit=CAPTION_CHUNK, *, layout=None):
    """短い文はまとめて1つの字幕にする（10/8 本人「細かく刻み過ぎ」。1文ずつだと切り替えが多い）。"""
    import caption_breaks
    if _CAPTION.get('phrase_wrap'):
        width, size, max_rows = layout or (CAPTION_RIGHT - (LEFT - 8) - 64, 42, 3)
        return list(_offseason_caption_chunks(str(text or ''), limit, width, size, max_rows))
    if caption_breaks.enabled():return caption_breaks.pages(str(text or ''),limit)
    out = []
    for s in sentences(text):
        if out and len(out[-1]) + len(s) <= limit:
            out[-1] += s
        else:
            out.append(s)
    return out


@functools.lru_cache(maxsize=4096)
def _offseason_caption_chunks(text, limit, width, size, max_rows):
    import caption_breaks
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    def fits(value):
        try:
            return len(_caption_lines(draw, value, size, width)) <= max_rows
        except ValueError:
            return False
    return tuple(caption_breaks.pages(text, limit, fits=fits,
                                     splitter=__import__('offseason_public').caption_phrases, min_clause=12))


def current_sentence(elapsed, text, duration, *, caption_layout=None):
    """読み上げの速さは文字数にほぼ比例するので、文字数で区切って今の字幕を選ぶ。"""
    parts = (_CAPTION.get('caption_units') if text == _CAPTION['text'] else None) or caption_chunks(text, layout=caption_layout)
    if not parts:
        return ""
    total = sum(len(p) for p in parts)
    at = max(0.0, elapsed) / max(0.1, duration) * total
    run = 0
    for p in parts:
        run += len(p)
        if at < run:
            return p
    return parts[-1]


def caption(im, t):
    import bubble_styles
    if bubble_styles.selected():
        if not _CAPTION['text'] or _CAPTION.get('hide_caption'):return
        import characters
        clock=_PROGRAM_CLOCK[0]
        elapsed=clock-_CAPTION['start'] if clock is not None else t
        line=current_sentence(elapsed,_CAPTION['text'],_CAPTION['duration'])
        if line:bubble_styles.draw(im,characters.SPEAKERS.get(_CAPTION.get('speaker'),'metan'),line,seconds=clock if clock is not None else t)
        return
    if LOOK != "v4" or not _CAPTION["text"]:
        return
    clock = _PROGRAM_CLOCK[0]
    elapsed = (clock - _CAPTION["start"]) if clock is not None else t
    line = current_sentence(elapsed, _CAPTION["text"], _CAPTION["duration"])
    if not line:
        return
    box = (LEFT - 8, CAPTION_TOP, CAPTION_RIGHT, CAPTION_BOTTOM)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle(box, radius=22, fill=(11, 20, 32, 232))
    ld.rectangle((box[0], box[1] + 18, box[0] + 10, box[3] - 18), fill=METAN_PINK)
    base = im.convert("RGBA")
    base.alpha_composite(layer)
    im.paste(base.convert("RGB"))
    d = ImageDraw.Draw(im)
    f = font(24)
    name,color,ink="四国めたん",METAN_PINK,DARK_INK
    import caption_breaks
    if caption_breaks.enabled():
        import characters
        import bubble_styles
        who=characters.SPEAKERS.get(_CAPTION.get('speaker'),'metan')
        name,color=characters.NAMES[who],characters.COLORS[who]
        ink=max((bubble_styles.WHITE,bubble_styles.SHADOW),key=lambda rgb:float(bubble_styles.contrast(rgb,color)))
    w = d.textlength(name, font=f) + 32
    d.rounded_rectangle((box[0] + 24, box[1] - 22, box[0] + 24 + w, box[1] + 22), radius=8, fill=color)
    d.text((box[0] + 24 + w / 2, box[1]), name, font=f, fill=ink, anchor="mm")
    # 数字は金色（項目の札と同じ書き分け）。3行まで、入らなければ字を小さく
    rows = []
    for size in ((42,) if _CAPTION.get('phrase_wrap') else (42, 38, 34)):
        try:rows = _caption_lines(d, line, size, box[2] - box[0] - 64)
        except ValueError:continue
        if len(rows) <= 3:
            break
    if (caption_breaks.enabled() or _CAPTION.get('phrase_wrap')) and (not rows or len(rows)>3):raise ValueError('字幕を文節でページ分割してください')
    y = box[1] + 44
    for row in rows[:3]:
        x = box[0] + 36
        for part, is_num in row:
            fnt = num_font(round(size * 1.18)) if is_num else font(size)
            d.text((x, y + size), part, font=fnt, fill=GOLD if is_num else INK, anchor="ls")
            x += d.textlength(part, font=fnt)
        y += round(size * 1.45)
    record_box(im, "caption", box, line)


@functools.lru_cache(maxsize=4096)
def _has_glyph(ch):
    f = font(42)
    mask, missing = f.getmask(ch), f.getmask("\U0010ffff")
    return (mask.size, bytes(mask)) != (missing.size, bytes(missing))


def _caption_lines(d, text, size, width):
    """数字の続き（3対2・4打数 など）を途中で切らずに折り返す。行頭に句読点を置かない。"""
    # 英語の語（Dodgers など）も途中で切らない。書体に無い字（絵文字など）は出さない
    text = "".join(ch for ch in str(text) if ch.isspace() or _has_glyph(ch))
    import caption_breaks
    if caption_breaks.enabled() or _CAPTION.get('phrase_wrap'):
        def measure(value):
            return sum(d.textlength(part,font=num_font(round(size*1.18)) if numeric else font(size)) for part,numeric in caption_breaks.runs(value))
        kwargs = ({'splitter': __import__('offseason_public').caption_phrases}
                  if _CAPTION.get('phrase_wrap') else {})
        return [caption_breaks.runs(row) for row in caption_breaks.wrap(text,measure,width,**kwargs)]
    tokens = re.findall(r"\d[\d.,:]*|[A-Za-z][A-Za-z'.\-]*|[^\d]", text)
    rows, cur, cur_w = [], [], 0.0
    for tok in tokens:
        is_num = tok[0].isdigit()
        fnt = num_font(round(size * 1.18)) if is_num else font(size)
        w = d.textlength(tok, font=fnt)
        if cur and cur_w + w > width and tok not in "、。！？」）":
            rows.append(cur)
            cur, cur_w = [], 0.0
        if cur and cur[-1][1] == is_num and not is_num:
            cur[-1] = (cur[-1][0] + tok, False)
        else:
            cur.append((tok, is_num))
        cur_w += w
    if cur:
        rows.append(cur)
    return rows


def progress(d):
    """見出しの下の、進み具合の線（v4）。"""
    if LOOK != "v4" or not _CAPTION["total"] or _PROGRAM_CLOCK[0] is None:
        return
    k = max(0.0, min(1.0, _PROGRAM_CLOCK[0] / _CAPTION["total"]))
    d.rectangle((LEFT, 222, SAFE_RIGHT, 226), fill=_mix(DARK_INK, (196, 206, 212), 0.35))
    d.rectangle((LEFT, 222, LEFT + round((SAFE_RIGHT - LEFT) * k), 226), fill=GOLD)


def presenter(im, t, which="right", who="metan"):
    if LOOK == "v4":
        # 10/9 本人: デフォルトの立ち絵（坂本アヒルさん）・横いっぱいの吹き出し（案1）。characters.py に1か所
        import characters
        return characters.presenter(im, t, ("zundamon", "metan") if _CAPTION.get("duo") else ("metan",))
    if LOOK == "v4":
        clock = _PROGRAM_CLOCK[0]
        elapsed = (clock - _CAPTION["start"]) if clock is not None else t
        line = current_sentence(elapsed, _CAPTION["text"], _CAPTION["duration"]) if _CAPTION["text"] else ""
        face = face_for(line, elapsed, _CAPTION["duration"]) if line else "smile"
        sp = _portrait_v4(who, face if who == "metan" else "base")
    else:
        sp = _portrait(who)
    bob = round(6 * calm_motion.value('presenter_bob', 1.0)
                * math.sin(t * 2 * math.pi / (2.4 * calm_motion.value('presenter_period', 1.0))))
    x = SAFE_RIGHT - sp.width + (24 if LOOK == "v4" else 0) if which == "right" else 24
    # テロップ（1486〜1574）の上に立つ。テロップの文字を隠さない
    im.paste(sp, (x, 1480 - sp.height + bob), sp)
    caption(im, t)
    progress(ImageDraw.Draw(im))


def _paste_card(im, card, x, y, k):
    """札を、飛び込みの進み具合 k（0〜1、行き過ぎあり）で置く。"""
    if k <= 0:
        return
    dx = round(140 * calm_motion.value('slide_distance', 1.0) * (1 - k))
    alpha = card.split()[3].point(lambda a: round(a * min(1.0, k * 1.6)))
    # 入場中も見出し・左右・テロップの予約領域へ出さない。
    if im.size==(W,H):
        left=max(LEFT,x+dx);top=max(CONTENT_TOP,y)
        right=min(SAFE_RIGHT,x+dx+card.width);bottom=min(CONTENT_BOTTOM,y+card.height)
    else:
        left=max(0,x+dx);top=max(0,y);right=min(im.width,x+dx+card.width);bottom=min(im.height,y+card.height)
    if left>=right or top>=bottom:
        return
    area=(left-x-dx,top-y,right-x-dx,bottom-y)
    im.paste(card.crop(area),(left,top),alpha.crop(area))
    record_box(im,'card',(left,top,right,bottom))
    im.info.setdefault('v3_card_contents',[]).append({'size':list(card.size),'text':card.info.get('v3_layout',[])})
    for entry in card.info.get('v3_layout',[]):
        a,b,c,e=entry['box']
        box=(max(left,x+dx+a),max(top,y+b),min(right,x+dx+c),min(bottom,y+e))
        if box[0]<box[2] and box[1]<box[3]:
            record_box(im,entry['role'],box,entry['text'])
            saved=im.info['v3_layout'][-1]
            for key in ('team_id','v4_font','v4_color'):
                if key in entry:
                    saved[key]=entry[key]
    # 札の中で描いた球団の小札も、画面の座標へ移して残す。
    for badge in card.info.get('v4_badges',[]):
        a,b,c,e=badge['box']
        box=(max(left,x+dx+a),max(top,y+b),min(right,x+dx+c),min(bottom,y+e))
        if box[0]<box[2] and box[1]<box[3]:
            moved=dict(badge)
            moved['box']=list(box)
            im.info.setdefault('v4_badges',[]).append(moved)


# ------------------------------------------------------------------ 表紙
@functools.lru_cache(maxsize=32)
def _chip(label, score, w, base_rgb, second_rgb):
    card = Image.new("RGBA", (w, 168), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, 167), radius=20, fill=_mix(base_rgb, (255, 255, 255), 0.1) + (255,),
                        outline=_mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
    size = 28
    while size > 8 and d.textbbox((0, 0), label, font=font(size))[2] > w - 48:
        size -= 1
    _text(d,(24, 22), label, font=font(size), fill=second_rgb)
    if re.fullmatch(r'[0-9.+:\-]+', str(score)):
        _text(d,(24, 66), score, font=num_font(80), fill=INK)
    else:
        score_lines, score_size = _lines(d, str(score), 42, w-48, 2)
        for i, line in enumerate(score_lines):
            _text(d,(24, 66+i*(score_size+8)), line, font=font(score_size), fill=INK)
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
            _text(d,(cx, y - round(size * 0.12)), ch, font=f, fill=GOLD)
        cx += cw
    return cx


def intro(t, spec, kind_label):
    if LOOK == 'v4':
        import asset_v4_cards as cards
        if cards.enabled(spec):
            return cards.intro(t, spec, kind_label)
    v3 = spec.get("v3") or {}
    tid = design_team(spec)
    base, second, _ = colors(tid)
    im = background(t, tid)
    d = ImageDraw.Draw(im)
    _header(d, kind_label, spec.get('page'), second=second)
    # 球団の行
    k = ease_out((t - T_WHO) / 0.5)
    y = 260 + round(48 * (1 - k))
    x = LEFT
    if spec.get("abbr"):
        x += _badge(d, LEFT, y, spec["abbr"], base, second) + 24
    who = v3.get("who") or spec.get("label", "")
    lines, size = _lines(d, who, 44, SAFE_RIGHT - x, 1)
    _text(d,(x, y + 38), lines[0] if lines else "", font=font(size), fill=INK, anchor="lm")
    big = str(v3.get("big") or "")
    if big:
        unit = v3.get("unit") or ""
        number_size = 400
        while number_size > 120 and d.textlength(big, font=num_font(number_size)) + d.textlength(unit, font=font(128)) + 32 > SAFE_RIGHT-LEFT:
            number_size -= 8
        end = _reel(d, im, LEFT, 350, big, t, size=number_size)
        record_box(im,'number',(LEFT,350,end,350+number_size),big)
        _text(d,(end + 16, 526), unit, font=font(128), fill=INK)
        if v3.get("sub"):
            _text(d,(end + 20, 682), v3["sub"], font=font(40), fill=second)
        y = 772
    else:
        hook = spec.get("hook") or spec.get("label", "")
        lines, size = _lines(d, hook, 96, SAFE_RIGHT - LEFT, 2)
        e = ease_out(t / 0.6)
        for i, line in enumerate(lines):
            _text(d,(LEFT, 400 + i * (size + 20)), line, font=font(size),
                   fill=GOLD if i == 0 else INK)
        y = 400 + len(lines) * (size + 20) + 40
    tag = v3.get("tag")
    if tag:
        k = ease_out((t - T_TAG) / 0.4)
        if k > 0:
            tag_lines, tag_size = _lines(d, tag, 48, SAFE_RIGHT-LEFT-56, 2)
            f = font(tag_size)
            w = min(SAFE_RIGHT-LEFT, round(max(d.textlength(line, font=f) for line in tag_lines)) + 56)
            height = max(84, len(tag_lines)*(tag_size+10)+24)
            reveal = round(w * k)
            d.rectangle((LEFT, y, LEFT + reveal, y + height), fill=GOLD)
            lay = Image.new("RGBA", (w, height), (0, 0, 0, 0))
            for i, line in enumerate(tag_lines):
                ImageDraw.Draw(lay).text((28, 12+i*(tag_size+10)), line, font=f, fill=DARK_INK)
            im.paste(lay.crop((0, 0, reveal, height)), (LEFT, y), lay.crop((0, 0, reveal, height)))
            record_box(im,'card',(LEFT,y,LEFT+w,y+height))
            for i,line in enumerate(tag_lines):
                record_box(im,'text',d.textbbox((LEFT+28,y+12+i*(tag_size+10)),line,font=f),line)
        else:
            height = 84
        y += height+32
    chips = v3.get("chips") or []
    if chips:
        cw = (SAFE_RIGHT - LEFT - 24) // 2
        ch=min(168,max(1,(CONTENT_BOTTOM-y-24)//((min(4,len(chips))+1)//2)))
        for i, c in enumerate(chips[:4]):
            cx = LEFT + (i % 2) * (cw + 24)
            cy = y + (i // 2) * (ch+24)
            t0 = T_CHIP0 + i * T_CHIP_GAP
            label=str(c.get('label',''))
            if c.get('win') and c.get('win_explanation'):
                label+=f'（○＝{c["win_explanation"]}）'
            card = _chip(label, c.get("score", ""), cw, base, second)
            if ch<card.height:
                factor=ch/card.height
                old=card.info.get('v3_layout',[])
                card=card.resize((cw,ch))
                card.info['v3_layout']=[dict(e,box=[e['box'][0],e['box'][1]*factor,e['box'][2],e['box'][3]*factor]) for e in old]
            _paste_card(im, card, cx, cy, back_out((t - t0) / SLIDE))
            if c.get("win") and c.get('win_explanation'):
                kr = back_out((t - t0 - SLIDE - T_RING_AFTER) / 0.25, 2.4)
                if kr > 0:
                    r = round(30 * kr)
                    ox, oy = cx + cw - 64, cy + 112
                    d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=GOLD, width=max(2, round(8 * min(1, kr))))
    ticker(im, t, v3.get("ticker"), once=v3.get('ticker_once',False))
    source(d, v3.get('source') or page_source(spec.get("items") or []), second)
    presenter(im, t)
    return im


# ------------------------------------------------------------------ 項目の画面
# 重要度の区分と色。カード本文では項目内のサイズを統一して使う。
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


OPEN_HEAD = "（「『【〈《"
CLOSE_HEAD = "）」』】〉》"
SMALL_HEAD = "ゃゅょっャュョッ"   # 小さい仮名は行頭に置かない


@functools.lru_cache(maxsize=128)
def _team_badge_id(text):
    """本文の1かたまりが球団名そのものなら、そのID。"""
    import notability_engine as ne
    for tid, name in ne.MLB_TEAM_NAME_JP.items():
        if text == name:
            return str(tid)
    return None


def _badge_width(tid, size):
    import short_v4_cards as cards
    return cards.inline_badge_width(tid, size)


BADGE_LEAD = 6


def _piece_width(probe, text, size, badges):
    w = probe.textlength(text, font=font(size))
    if badges:
        tid = _team_badge_id(text)
        if tid:
            # 前の文字との間にも少し空ける（字形のはみ出しは環境で違い、CI の字体で 0.4px 重なった）。
            w += BADGE_LEAD + _badge_width(tid, size) + 12
    return w


def _kinsoku_units(atoms):
    """折り返してよい単位。開き括弧は次へ、閉じ括弧・句読点は前へくっつける。"""
    units = []
    for atom in atoms:
        text = atom[0]
        if units and units[-1] and units[-1][-1][0] and units[-1][-1][0][-1] in OPEN_HEAD \
                and text != "　":
            units[-1].append(atom)
            continue
        if text == "　":
            units.append([atom])
            continue
        if text and (text[0] in CLOSE_HEAD or text[0] in NO_HEAD or text[0] in SMALL_HEAD):
            if units and units[-1][0][0] != "　":
                units[-1].append(atom)
            else:
                units.append([atom])
            continue
        units.append([atom])
    return units


def rich_lines(runs, width, second_rgb, size=None, badges=None):
    """本文を折る。size を渡すと項目全体を同じ大きさにそろえる。

    禁則: 開き括弧は行末に残さず、閉じ括弧・句読点・小さい仮名は行頭に置かない。
    全角スペースは区切りとして優先して折る。"""
    if badges is None:
        badges = LOOK == "v4"
    default_sizes = {"L": SIZE_L, "M": SIZE_M, "S": SIZE_S}
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def atom_size(size_class):
        return size or default_sizes[size_class]

    atoms = list(_atoms(runs))
    units = _kinsoku_units(atoms)
    # 「（…）」「「…」」は、幅に入るなら一続きにして途中で折らない。
    merged = []
    i = 0
    while i < len(units):
        first = units[i][0][0]
        if first and first[0] in OPEN_HEAD:
            j, total, closed = i, 0, False
            while j < len(units):
                if len(units[j]) == 1 and units[j][0][0] == "　":
                    break
                total += sum(_piece_width(probe, t, atom_size(s), badges) for t, s, _ in units[j])
                if any(atom[0] and atom[0][-1] in CLOSE_HEAD for atom in units[j]):
                    closed = True
                    break
                j += 1
            if closed and total <= width:
                merged.append([atom for unit in units[i:j + 1] for atom in unit])
                i = j + 1
                continue
        merged.append(units[i])
        i += 1
    units = merged
    # 幅に入らないかたまりだけ、文字へ分ける（長いカタカナ語・数字の連なり）。
    split_units = []
    for unit in units:
        space = len(unit) == 1 and unit[0][0] == "　"
        total = sum(_piece_width(probe, t, atom_size(s), badges) for t, s, _ in unit)
        if not space and total > width:
            pieces = []
            for atom in unit:
                # 札と球団名は離さない。入らない場合は項目全体のサイズで調整する。
                if badges and _team_badge_id(atom[0]):
                    pieces.append(atom)
                else:
                    pieces.extend((ch, atom[1], atom[2]) for ch in atom[0])
            split_units.extend(_kinsoku_units(pieces))
        else:
            split_units.append(unit)
    units = split_units

    lines, cur, x = [], [], 0
    for i, unit in enumerate(units):
        space = len(unit) == 1 and unit[0][0] == "　"
        uw = sum(_piece_width(probe, t, atom_size(s), badges) for t, s, _ in unit)
        if space:
            if not cur:
                continue                                   # 行頭の空白は捨てる
            # 次の区切りまでを1つのかたまりと見て、入らないならここで折る（優先）。
            j, seg = i + 1, 0
            while j < len(units) and not (len(units[j]) == 1 and units[j][0][0] == "　"):
                seg += sum(_piece_width(probe, t, atom_size(s), badges) for t, s, _ in units[j])
                j += 1
            if x + uw + seg > width:
                lines.append(cur)
                cur, x = [], 0
                continue
        if cur and x + uw > width:
            lines.append(cur)
            cur, x = [], 0
        for text, size_class, gold in unit:
            s = atom_size(size_class)
            w = _piece_width(probe, text, s, badges)
            color = GOLD if gold else (_mix(second_rgb, INK, 0.3) if size_class == "S" else INK)
            cur.append((x, text, font(s), color, s))
            x += w
    if cur:
        lines.append(cur)
    return lines


def _item_card(head, body, w, base_rgb, second_rgb, quote_size=52, attribution_above=False, quote_height=None):
    return _cached_item_card(head, body, w, base_rgb, second_rgb, quote_size,
                             attribution_above, quote_height, LOOK,
                             os.environ.get('COLLESPO_MLB_BADGE', ''))


@functools.lru_cache(maxsize=64)
def _cached_item_card(head, body, w, base_rgb, second_rgb, quote_size,
                      attribution_above, quote_height, look, badge_style):
    # 見た目・札の種類もキーに含め、切り替え前の札を使い回さない。
    quote = "番記者" in head or str(body).startswith("「")
    if not quote:
        runs = _runs(body)
        limit = quote_height or (CONTENT_BOTTOM - CONTENT_TOP)
        # まず行を増やし、それでも入らないときだけ一段ずつ小さくする。
        # 1つの項目の中で文字の大きさは混ぜない。
        lines = heights = None
        probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))
        for candidate in (SIZE_M, SIZE_M - 4, SIZE_M - 8, SIZE_M - 12, SIZE_M - 16, 26):
            wrapped = rich_lines(runs, w - 72, second_rgb, size=candidate)
            lh = candidate + 16
            total = 84 + lh * max(1, len(wrapped)) + 30
            fits_width = all(x + _piece_width(probe, text, drawn, LOOK == 'v4') <= w - 72
                             for line in wrapped for x, text, _, _, drawn in line)
            if total <= limit and fits_width:
                lines, heights = wrapped, [lh] * len(wrapped)
                break
        if lines is None:
            # 呼び出し元のpaginateが本文を次のカードへ分ける。
            raise ValueError('本文が札の安全域に収まりません')
        h = 84 + sum(heights) + 30
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=24, fill=_mix(base_rgb, (255, 255, 255), 0.1) + (255,),
                            outline=_mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
        label,label_size=_lines(d,head,32,w-72,1)
        _text(d,(36, 30),label[0] if label else '',font=font(label_size),fill=second_rgb)
        badges = LOOK == "v4"
        y = 84
        for ln, lh in zip(lines, heights):
            base_y = y + lh - 16
            for x, text, f, color, drawn in ln:
                left = 36 + x
                tid = _team_badge_id(text) if badges else None
                if tid:
                    import short_v4_cards as cards
                    left += BADGE_LEAD
                    bbox = f.getbbox(text, anchor="ls")
                    cards.inline_badge(card, left, base_y + bbox[1], tid, drawn,
                                       bbox[3] - bbox[1])
                    left += cards.inline_badge_width(tid, drawn) + 12
                _text(d,(left, base_y), text, font=f, fill=color, anchor="ls")
                entry = card.info['v3_layout'][-1]
                entry['v4_font'] = drawn
                entry['v4_color'] = color
                if tid:
                    entry['team_id'] = tid
            y += lh
        return card
    # 引用も同じ禁則を使い、行数の上限によって本文を切り捨てない。
    limit = quote_height or (CONTENT_BOTTOM - CONTENT_TOP)
    for size in range(quote_size, 23, -2):
        wrapped = rich_lines(_runs(body), w - 72, second_rgb, size=size, badges=False)
        lines = [''.join(text for _, text, _, _, _ in line) for line in wrapped]
        if 126 + len(lines) * (size + 14) <= limit:
            break
    else:
        raise ValueError('引用全文が共通札の安全域に収まりません')
    h = 40 + 50 + len(lines) * (size + 14) + 36
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    fill = (247, 242, 223, 255) if quote else _mix(base_rgb, (255, 255, 255), 0.1) + (255,)
    d.rounded_rectangle((0, 70 if attribution_above else 0, w - 1, h - 1), radius=24, fill=fill,
                        outline=None if quote else _mix(base_rgb, (255, 255, 255), 0.25) + (255,), width=4)
    _text(d,(36, 30), head, font=font(26 if attribution_above else 32), fill=second_rgb if attribution_above else (93, 90, 99) if quote else second_rgb)
    for i, line in enumerate(lines):
        color = DARK_INK if quote else (GOLD if i == 0 else INK)
        _text(d,(36, 84 + i * (size + 14)), line, font=font(size), fill=color)
    return card


_item_card.cache_clear = _cached_item_card.cache_clear
_item_card.cache_info = _cached_item_card.cache_info


def list_page(t, spec, items, start, count, page, pages, kind_label, focus=None):
    if LOOK == 'v4':
        import asset_v4_cards as cards
        if cards.enabled(spec):
            return cards.list_page(t, spec, items, start, count, page, pages, kind_label)
    import v3_slot_render as common
    view=dict(spec,team_id=design_team(spec),page=f'{page}/{pages}')
    selected=list(items)[start:start+count]
    return common.frame(t,view,selected,kind_label,page_source(selected),focus=focus)


# ------------------------------------------------------------------ 効果音の時刻
def people(t, spec, rows, heading, kind_label, focus=None):
    if LOOK == 'v4':
        import asset_v4_cards as cards
        if cards.enabled(spec) and rows:
            return cards.people(t, spec, rows, heading, kind_label)
    import v3_slot_render as common
    view=dict(spec,team_id=design_team(spec),heading=heading)
    items=[(r.get('name',''),r.get('line',r.get('why',''))) for r in rows[:3]]
    return common.frame(t,view,items,kind_label,'出典: MLB公式（Stats API）',focus=focus)


def cues(kind, spec, items=(), start=0, count=0):
    """その画面の効果音 [(秒, 種類, 案, 追加の音量dB)]。描画と同じ時刻表から。"""
    v3 = spec.get("v3") or {}
    out = []
    if kind == "outro":
        return outro_cues(spec.get("lineup_kind", ""))
    if kind == "intro":
        out.append((0.0, "transition", "b", -10))
        if v3.get("big"):
            out.append((T_ROLL[0], "roll", "a", -2))
            out.append((T_ROLL[1] - 0.04, "stop", "a", 0))
        if v3.get("tag"):
            out.append((T_TAG, "marker", "a", -3))
        for i, c in enumerate((v3.get("chips") or [])[:4]):
            t0 = T_CHIP0 + i * T_CHIP_GAP
            if c.get("win") and c.get('win_explanation'):
                out.append((t0 + SLIDE + T_RING_AFTER, "pop", "a", -2))
    elif kind == "list":
        out.append((0.0, "transition", "b", -10))
        for i, (head, body) in enumerate(list(items)[start:start + count]):
            quote = "番記者" in head or str(body).startswith("「")
            if quote:
                out.append((T_CARD0 + i * T_CARD_GAP, "notify", "a", -3))
    return out


# ------------------------------------------------------------------ 共通の締め
# 10/7 本人「最後のコレスポの紹介、ちょっと雑すぎ。もっと突き詰めて各ショートの最後に付けられる？」。
# どの枠の最後にも付ける。毎日の番組表（post_common.lineup、時刻つき）を時刻の順に並べ、
# いま見ている枠は外す。地はコレスポの色（球団色にしない）。
INSEASON_OUTRO_TEXT = ("コレスポでは毎日、日本人選手の成績や、明日の試合の見どころを届けています。"
              "チャンネル登録して、また見に来てくださいね。")
OFFSEASON_OUTRO_TEXT = ("コレスポでは毎日、MLBの話題と欧州サッカーの見どころを届けています。"
                        "チャンネル登録して、また見に来てくださいね。")


def outro_text(ps=None, today=None):
    import post_common
    original = OFFSEASON_OUTRO_TEXT if post_common.mlb_offseason(ps, today) else INSEASON_OUTRO_TEXT
    return __import__("outro_next").speech(original, today)


# 各制作器は1回の起動で原稿と描画を作る。既存の取り込み口を保つ。
OUTRO_TEXT = outro_text()
T_OUTRO_ROW0, T_OUTRO_GAP = 0.6, 0.18


def outro_rows(exclude=""):
    import post_common as pc
    rows = sorted(pc.lineup(exclude), key=lambda r: r[3])
    return [(at, name) for _, name, _, at in rows][:7]


def outro(t, spec=None, exclude="", credit="音声: VOICEVOX:四国めたん　データ: MLB Stats API",
          tagline="毎日のMLBを数字と現地の声で"):
    import solo_host
    offseason = bool((spec or {}).get('offseason'))
    if offseason:
        tagline = 'オフの動きを公式の記録で'
    if LOOK == 'v4' and solo_host.selected() == 'ui':
        credit = credit.replace('VOICEVOX:四国めたん', solo_host.UI_CREDIT)
    im = background(t, None)
    im.info['v3_outro']=True
    d = ImageDraw.Draw(im)
    k = ease_out(t / 0.5)
    _text(d,(LEFT, 250), "コレスポ", font=font(150), fill=GOLD)
    _text(d,(LEFT, 440), tagline, font=font(42), fill=INK)
    y = 520
    if not offseason:
        _text(d,(LEFT, y), "毎日のお届け", font=font(30), fill=(196, 206, 212))
    y += 44
    w = SAFE_RIGHT - LEFT - 250                                 # 右下の立ち絵にかからない幅
    for i, (at, name) in enumerate([] if offseason else outro_rows(exclude)):
        row = _outro_row(at, name, w)
        _paste_card(im, row, LEFT, y, back_out((t - T_OUTRO_ROW0 - i * T_OUTRO_GAP) / SLIDE))
        y += row.height + 8
    kb = ease_out((t - 1.8) / 0.4)
    if kb > 0:
        f = font(38)
        text = __import__("outro_next").card(_CAPTION.get("text", ""), "チャンネル登録で毎日届きます")
        bw = round(d.textlength(text, font=f)) + 56
        d.rectangle((LEFT, y + 20, LEFT + round(bw * kb), y + 100), fill=GOLD)
        lay = Image.new("RGBA", (bw, 80), (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((28, 40), text, font=f, fill=DARK_INK, anchor="lm")
        cut = lay.crop((0, 0, round(bw * kb), 80))
        im.paste(cut, (LEFT, y + 20), cut)
        record_box(im,'card',(LEFT,y+20,LEFT+bw,y+100))
        record_box(im,'text',d.textbbox((LEFT+28,y+60),text,font=f,anchor='lm'),text)
    source(d, credit, (196, 206, 212))
    presenter(im, t)
    return im


@functools.lru_cache(maxsize=16)
def _outro_row(at, name, w):
    # v4 は札の下端が上がるので、番組表が7行でも登録の札が収まるよう行を少し低く（ヒロの提案）
    h = 60 if LOOK == "v4" else 70
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=18, fill=(255, 255, 255, 26), outline=(255, 255, 255, 60), width=2)
    _text(d,(28, h // 2), at, font=num_font(44 if h == 70 else 40), fill=GOLD, anchor="lm")
    size = 40
    while size > 28 and ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(name, font=font(size)) > w - 190:
        size -= 2
    _text(d,(170, h // 2), name, font=font(size), fill=INK, anchor="lm")
    return card


def outro_cues(exclude=""):
    out = [(0.0, "transition", "b", -10)]
    out.append((1.8, "marker", "a", -4))
    return out
