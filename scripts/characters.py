"""立ち絵と吹き出し（v4 のショート・掛け合い・長編で共通）。

10/9 本人「一旦デフォルトのずんだもんとめたんに差し替えましょう。今後の動画全部。
デフォルトってのは、よく見るやつで、前使ってたやつです」→ assets/portraits/ の
坂本アヒルさんの立ち絵（部品つき。目・口・眉を組み合わせて表情を作る。video_common.face）。
掛け合いの配置は本人が選んだ案1：横いっぱいの吹き出し＋その上に2人の上半身（話す方を大きく明るく）。
絵を差し替えるときは、この1ファイルだけを変える。
"""
import functools
import math
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import review_render_v3 as r3
import video_common as vc

PORTRAIT_DIR = str(r3.ROOT / "assets/portraits")
NAMES = {"metan": "四国めたん", "zundamon": "ずんだもん"}
COLORS = {"metan": (236, 120, 178), "zundamon": (118, 190, 84)}
# v4 の表情の名前 → 部品の組み合わせ（眉, 目, 口）
FACE_PARTS = {
    "base": ("基本", "開", "閉"),
    "talk": ("基本", "開", "開"),
    "smile": ("基本", "開", "笑"),
    "surprise": ("上げ", "見開", "大"),
    "question": ("上げ", "開", "開"),
    "jitome": ("困り", "開", "閉"),     # ジト目は本人NG（10/8）。負けの日は困り眉
    "pose-smile": ("基本", "笑", "笑"),
}
for _k, _v in FACE_PARTS.items():
    vc.FACES.setdefault("v4_" + _k, _v)

# 配置（案1）。吹き出しは横いっぱい、2人の上半身は吹き出しの右上に立つ。
BUBBLE = (r3.LEFT, 1262, r3.SAFE_RIGHT, 1468)
BUST_ACTIVE, BUST_IDLE = 500, 430        # 全身の高さ（上半身はその上半分を使う）
BUST_BOTTOM = BUBBLE[1] + 22             # 上半身の下端（吹き出しに少しかかる）


def figure(who, face="base", height=1000):
    """全身（長編の立ち絵）。"""
    return vc.face(NAMES[who], height, "v4_" + face, PORTRAIT_DIR)


@functools.lru_cache(maxsize=64)
def bust(who, face, height, dim=False):
    art = vc.face(NAMES[who], height, "v4_" + face, PORTRAIT_DIR)
    if art is None:
        return None
    art = art.crop((0, 0, art.width, int(art.height * 0.5)))
    if dim:
        rgb = ImageEnhance.Brightness(art.convert("RGB")).enhance(0.6)
        out = rgb.convert("RGBA"); out.putalpha(art.getchannel("A")); art = out
    return art


def reserved_width(duo=False):
    """右下の上半身が横に占める幅（出典をその手前で折るため）。"""
    cast = ("zundamon", "metan") if duo else ("metan",)
    widths = [bust(w, "base", BUST_ACTIVE).width for w in cast]
    return sum(widths) - 30 * (len(widths) - 1) + 20


def redraw(im, layer):
    """place_busts が記録した立ち絵を描き直す（札の演出で消えた分を戻す）。"""
    for r in layer or ():
        art = bust(r["who"], r["face"], r["height"], r["dim"])
        if art is not None:
            art = art.crop((0, 0, art.width, min(art.height, r["cut"])))
            im.paste(art, tuple(r["at"]), art)
    return im


def portrait_strip():
    """立ち絵が出うる右下の範囲（画面の切り替え中も、ここは次の画面のまま保つ）。"""
    return (r3.SAFE_RIGHT - reserved_width(True) - 10, BUST_BOTTOM - BUST_ACTIVE // 2 - 12,
            r3.SAFE_RIGHT + 40, BUBBLE[3] + 12)


def zunda_face(line):
    if "？" in line or "?" in line:
        return "question"
    if any(w in line for w in ("記録", "初めて", "自己最多", "！")):
        return "surprise"
    if any(w in line for w in ("勝", "本塁打", "好投")):
        return "smile"
    return "base"


def place_busts(im, speaker, line, elapsed, duration, cast=("zundamon", "metan")):
    """右下に上半身を並べる（cast の順に左から）。話す方を大きく明るく、口と表情を動かす。"""
    speaking = bool(line) and elapsed < max(0.1, duration - 0.25)
    mouth = speaking and int(elapsed * r3.MOUTH_RATE) % 2 == 1
    arts = []
    for who in cast:
        active = who == speaker
        mood = zunda_face(line) if who == "zundamon" else r3.face_for(line, elapsed, duration)
        fan = fan_mood(line) if active else None
        if fan:
            mood = fan[0]
        if mood == "talk":
            mood = "base"
        face = ("talk" if (mouth and mood == "base") else mood) if active else "base"
        arts.append((who, active, bust(who, face, BUST_ACTIVE if active else BUST_IDLE, not active), face))
    x = r3.SAFE_RIGHT + 4
    # 吹き出しの無い画面（締め）は、吹き出しの場所まで下げて、上の札・ボタンにかけない
    bottom = BUST_BOTTOM if line and not r3._CAPTION.get("hide_caption") else BUBBLE[3]
    records, layer = [], []
    for who, active, art, face in reversed(arts):
        if art is None:
            continue
        x -= art.width - (30 if len(arts) > 1 else 0)
        bob = round(4 * math.sin(elapsed * math.pi * 2 / 1.2)) if active and speaking else 0
        y = bottom - art.height + bob
        im.paste(art, (x, y), art)
        records.append(dict(who=who, active=active, box=[x, y, x + art.width, y + art.height]))
        # 吹き出しの枠に重なる下の端は描き直さない（吹き出しが上に来るように）
        cut = art.height if bottom != BUST_BOTTOM else max(1, BUBBLE[1] - y)
        layer.append(dict(who=who, face=face, height=BUST_ACTIVE if active else BUST_IDLE, dim=not active, at=[x, y], cut=cut))
    active_box = next((r["box"] for r in records if r["active"]), None)
    fan = fan_mood(line)
    if fan and active_box:
        fan_effect(im, fan[1], active_box, elapsed)
        im.info["fan_expr"] = dict(face=fan[0], effect=fan[1], reason=fan[2], line=line)
    im.info["duo_portraits"] = records
    im.info["duo_layer"] = layer      # 札の演出（video_common.short_effects）のあとに描き直す
    return records



# ------------------------------------------------------------------ 日本人選手寄りの表情（COLLESPO_EXPR=fan）
# 本人 10/12「通常は普通でいい。日本人選手寄りの表情変化が欲しい。山本の先発の時はキラキラしたり」。
# 日本人選手の名前が出る台詞だけに感情を乗せる（ほかの話題は今までどおり）。理由はその台詞の中の言葉。
# 目や顔の絵は描き換えない（10/9 本人 NG）。キラキラ・汗は顔の外に重ねる効果としてコードで描く。
# ジト目は使わない（10/8 本人 NG）。jitome は困り眉の組み合わせ。
EXPR = os.environ.get("COLLESPO_EXPR", "")
FAN_RULES = (  # 上から順に見る。(表情, 効果, 言葉)
    ("surprise", "burst", ("自己最多", "初めて", "初の", "新記録", "記録を")),
    ("pose-smile", "sparkle", ("本塁打", "ホームラン", "勝ち投手", "完封", "好投", "無失点", "適時打", "決勝打",
                               "白星", "セーブ", "ゴール", "得点を", "アシスト", "マルチ安打", "猛打賞")),
    ("jitome", "sweat", ("無安打", "0安打", "敗戦投手", "黒星", "降板", "失点", "敗れ", "敗退", "出場なし")),
    ("smile", "sparkle", ("先発", "登板予定", "出場予定", "スタメン", "期待")),
)


@functools.lru_cache(maxsize=1)
def fan_names():
    """日本人選手の呼び方（フルネームと新聞の名字）。名簿は notability_engine と press_names の1か所から。"""
    names = set()
    try:
        import press_names
        for full, short in press_names.SURNAME.items():
            names.update((full, short))
    except Exception:
        pass
    try:
        import notability_engine as ne
        names.update(p["name_jp"] for p in ne.JP_PLAYERS_MLB if p.get("name_jp"))
    except Exception:
        pass
    return tuple(sorted((n for n in names if len(n) >= 2), key=len, reverse=True))


def fan_mood(line):
    """(表情, 効果, 理由) か None。COLLESPO_EXPR=fan のときだけ。日本人選手の名前が無い台詞は None。"""
    if EXPR != "fan" or not line:
        return None
    text = str(line)
    who = next((n for n in fan_names() if n in text), None)
    if not who:
        return None
    for face, effect, words in FAN_RULES:
        hit = next((w for w in words if w in text), None)
        if hit:
            return face, effect, f"{who}・{hit}"
    return None


def _star(draw, cx, cy, r, fill):
    k = r * 0.28
    draw.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
                  (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def fan_effect(im, effect, box, elapsed):
    """立ち絵の頭のまわりに、小さな効果を重ねる（顔そのものは描き換えない）。"""
    x0, y0, x1, _ = box
    w = x1 - x0
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if effect in ("sparkle", "burst"):
        spots = ((0.10, 0.10, 26), (0.86, 0.06, 20), (0.95, 0.30, 14), (0.02, 0.34, 16))
        if effect == "burst":
            spots += ((0.50, -0.02, 30), (0.70, 0.18, 18), (0.26, 0.20, 18))
        for i, (fx, fy, r) in enumerate(spots):
            pulse = 0.55 + 0.45 * math.sin(elapsed * math.pi * 2 / 0.9 + i * 1.7)
            a = int(255 * max(0.0, pulse))
            _star(d, x0 + fx * w, y0 + fy * w, r * (0.8 + 0.3 * pulse), (255, 236, 150, a))
            _star(d, x0 + fx * w, y0 + fy * w, r * 0.45, (255, 255, 255, a))
    elif effect == "sweat":
        cx, cy = x0 + 0.86 * w, y0 + 0.16 * w + 6 * math.sin(elapsed * math.pi * 2 / 1.4)
        d.ellipse((cx - 11, cy, cx + 11, cy + 24), fill=(140, 200, 255, 230))
        d.polygon([(cx - 10, cy + 8), (cx + 10, cy + 8), (cx, cy - 16)], fill=(140, 200, 255, 230))
        d.ellipse((cx - 4, cy + 8, cx + 2, cy + 15), fill=(255, 255, 255, 220))
    im.alpha_composite(layer) if im.mode == "RGBA" else im.paste(layer, (0, 0), layer)

def bubble(im, speaker, text):
    """横いっぱいの吹き出し（白地・話者の色の枠・名前の札）。数字は濃い金色。3行まで、入らなければ字を小さく。"""
    if not text:
        return
    x0, y0, x1, y1 = BUBBLE
    color = COLORS[speaker]
    base = im.convert("RGBA")
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 6, y0 + 10, x1 + 6, y1 + 10), radius=28, fill=(0, 0, 0, 110))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=(250, 247, 238), outline=color, width=6)
    f = r3.font(28); w = d.textlength(NAMES[speaker], font=f) + 40
    d.rounded_rectangle((x0 + 28, y0 - 24, x0 + 28 + w, y0 + 24), radius=24, fill=color)
    d.text((x0 + 28 + w / 2, y0), NAMES[speaker], font=f, fill=(255, 255, 255), anchor="mm")
    room = y1 - y0 - 44
    for size in (48, 44, 40, 36, 33):
        rows = r3._caption_lines(d, text, size, x1 - x0 - 80)
        lh = round(size * 1.36)
        if len(rows) <= 3 and len(rows) * lh <= room:
            break
    y = y0 + 30 + (room - min(3, len(rows)) * lh) // 2
    for row in rows[:3]:
        x = x0 + 40
        for part, isnum in row:
            fnt = r3.num_font(round(size * 1.15)) if isnum else r3.font(size)
            d.text((x, y + size), part, font=fnt, fill=(196, 132, 16) if isnum else (30, 30, 34), anchor="ls")
            x += d.textlength(part, font=fnt)
        y += lh
    im.paste(base.convert(im.mode))
    r3.record_box(im, "caption", (x0, y0, x1, y1), text)
    # 配置の検査（v3_rules）は、字幕の右端をここから読む
    im.info["duo_caption"] = dict(box=list(BUBBLE), speaker=speaker, font_size=size, rows=min(3, len(rows)))


def presenter(im, t, cast=("metan",)):
    """v4 の立ち絵と吹き出し（1人でも2人でも同じ形）。読んでいる文は r3._CAPTION から。"""
    ctx = r3._CAPTION
    clock = r3._PROGRAM_CLOCK[0]
    elapsed = (clock - ctx["start"]) if clock is not None else t
    line = r3.current_sentence(elapsed, ctx["text"], ctx["duration"]) if ctx["text"] else ""
    speaker = "zundamon" if ctx.get("speaker") == 3 else "metan"
    if speaker not in cast:
        cast = tuple(cast) + (speaker,)
    place_busts(im, speaker, line, elapsed, ctx["duration"] or 1, cast)
    if line and not ctx.get("hide_caption"):
        bubble(im, speaker, line)
    r3.progress(ImageDraw.Draw(im))
