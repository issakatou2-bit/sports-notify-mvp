"""共通テーマのPS組み合わせ表。確認用PNG/動画部品のみ、公開機能なし。"""
from pathlib import Path
import sys
from PIL import Image, ImageDraw
from ps_brand_components import TOKENS, THEME, TEAM_SECONDARY_COLORS, text, font
from ps_render_template import background, SAFE_RIGHT, SAFE_BOTTOM, _prepared_presenter
from video_common import ease_out, lift_color
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import notability_engine as ne  # noqa: E402
T = TOKENS["stadium"]


def prepare(model, index):
    league = model["leagues"][index]
    fixed = Image.new("RGBA", (1080, 1920))
    d = ImageDraw.Draw(fixed)
    trace, pieces, lines = [], [], []

    def put(draw, x, y, value, size=36, width=864, color=None):
        box = text(draw, (x, y), str(value), size, color or T["ink"], width=width, minimum=24)
        if box[0] < 72 or box[2] > SAFE_RIGHT or box[1] < 140 or box[3] > SAFE_BOTTOM:
            raise ValueError("安全域を超える文字: " + str(value))
        trace.append({"text": str(value), "box": list(box)})

    d.text((72, 170), "コレスポ", font=font(44), fill=T["accent"])
    put(d, 72, 258, league["label"] + "の勝ち上がり", 58)
    put(d, 72, 342, model["date"].replace("-", "/") + " 時点", 30, color=T["muted"])
    for x, name, width in ((72, "WCS", 180), (290, "DS　先に3勝", 485), (804, "LCS", 132)):
        put(d, x, 405, name, 32, width=width, color=T["muted"])

    def box(match, x, y, width, height, compact=False):
        layer = Image.new("RGBA", fixed.size)
        q = ImageDraw.Draw(layer)
        q.rounded_rectangle((x, y, x+width, y+height), radius=14, fill=T["panel"], outline=T["line"], width=2)
        for i, row in enumerate(match["teams"]):
            ry = y+16+i*(64 if compact else 77)
            tid = str(row["id"])
            label = ne.MLB_TEAM_ABBR.get(tid, "未定")
            color = ne.MLB_TEAM_COLOR.get(tid, T["line"])
            q.rectangle((x+8, ry+7, x+14, ry+46), fill=lift_color(color))
            q.rectangle((x+14, ry+7, x+18, ry+46), fill=TEAM_SECONDARY_COLORS.get(tid, T["muted"]))
            put(q, x+24, ry, label, 32, width=80, color=T["accent"])
            if not compact:
                put(q, x+110, ry+1, row["name"], 36, width=width-170)
            put(q, x+width-44, ry, "—" if row["wins"] is None else row["wins"], 36, width=38)
        state = ("突破確定" if match["over"] else "相手待ち" if any(t["id"] is None for t in match["teams"]) else
                 "開始前" if sum(t["wins"] for t in match["teams"]) == 0 else "進行中")
        put(q, x+24, y+height-48, state, 26,
            width=width-36, color=T["accent"] if match["over"] else T["muted"])
        bounds = layer.getbbox()
        pieces.append((layer.crop(bounds), bounds[:2], len(pieces)*0.12))

    for i in range(2):
        y = 466+i*342
        wc, ds = league["wc"][i], league["ds"][i]
        box(wc, 72, y+10, 180, 191, compact=True)
        box(ds, 290, y, 484, 217)
        lines.append({"points": [(254, y+105), (288, y+105)], "confirmed": wc["over"]})
        lines.append({"points": [(776, y+105), (790, y+105), (790, 748), (802, 748)], "confirmed": ds["over"]})
        players = sorted({n for t in ds["teams"] for n in t["players"]})
        if players:
            put(d, 290, y+230, "所属：" + "・".join(players), 28, width=484, color=T["muted"])
    lcs = league["lcs"]
    layer = Image.new("RGBA", fixed.size)
    q = ImageDraw.Draw(layer)
    q.rounded_rectangle((804, 676, 936, 824), radius=12, fill=T["panel"], outline=T["line"])
    for i, row in enumerate(lcs["teams"]):
        label = ne.MLB_TEAM_ABBR.get(str(row["id"]), "未定")
        put(q, 816, 691+i*62, label + (" " + str(row["wins"]) if row["id"] else ""), 32, width=114)
    bounds = layer.getbbox()
    pieces.append((layer.crop(bounds), bounds[:2], 0.45))
    lines.append({"points": [(870, 884), (870, 1170)], "confirmed": lcs["over"]})
    put(d, 804, 838, "先に4勝", 26, width=132, color=T["muted"])
    ws = model["ws"]
    d.rounded_rectangle((290, 1172, 936, 1280), radius=12, fill=T["panel"], outline=T["line"])
    put(d, 308, 1184, "WS　" + ("優勝確定" if ws["over"] else "先に4勝"), 30, width=610, color=T["accent"])
    a, b = [ne.MLB_TEAM_ABBR.get(str(t["id"]), "未定") + (" " + str(t["wins"]) if t["id"] else "") for t in ws["teams"]]
    put(d, 308, 1230, "ア・リーグ " + a + "　対　ナ・リーグ " + b, 32, width=610)
    put(d, 300, 1372, "実線＝突破確定　点線＝勝者待ち", 26, width=620, color=T["muted"])
    put(d, 300, 1415, "所属の表示は出場を意味しません", 26, width=620, color=T["muted"])
    put(d, 300, 1486, "出典：MLB公式の日程・結果", 26, width=620, color=T["muted"])
    sprite = _prepared_presenter((ROOT/"assets/portraits/collespo-20260923/metan/3-black/base.png").read_bytes(),
                                 tuple(THEME["presenter"]["crop"]), tuple(THEME["presenter"]["max_size"]))
    fixed.alpha_composite(sprite, (24, SAFE_BOTTOM-sprite.height))
    return {"fixed": fixed, "pieces": pieces, "lines": lines, "trace": trace}


def frame(prepared, seconds):
    im = background(seconds=seconds).convert("RGBA")
    im.alpha_composite(prepared["fixed"])
    for layer, (x, y), delay in prepared["pieces"]:
        e = ease_out(max(0, min(1, (seconds-delay)/0.25)))
        if e == 1:
            im.alpha_composite(layer, (x, y))
        elif e > 0:
            moving = layer.copy()
            moving.putalpha(layer.getchannel("A").point([round(a*e) for a in range(256)]))
            im.alpha_composite(moving, (x-round(8*(1-e)), y))
    d = ImageDraw.Draw(im)
    for line in prepared["lines"]:
        points = line["points"]
        progress = ease_out(max(0, min(1, (seconds-0.7)/0.35))) if line["confirmed"] else 1
        total = sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a, b in zip(points, points[1:]))
        remain = total*progress
        for a, b in zip(points, points[1:]):
            length = abs(b[0]-a[0])+abs(b[1]-a[1])
            if length == 0 or remain <= 0:
                continue
            ratio = min(1, remain/length)
            end = (round(a[0]+(b[0]-a[0])*ratio), round(a[1]+(b[1]-a[1])*ratio))
            if line["confirmed"]:
                d.line((a, end), fill=T["accent"], width=4)
            else:
                for offset in range(0, length, 12):
                    lo, hi = offset/length, min(offset+6, length)/length
                    d.line(((round(a[0]+(b[0]-a[0])*lo), round(a[1]+(b[1]-a[1])*lo)),
                            (round(a[0]+(b[0]-a[0])*hi), round(a[1]+(b[1]-a[1])*hi))), fill=T["muted"], width=2)
            remain -= length
    return im.convert("RGB")
