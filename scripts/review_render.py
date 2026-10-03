"""シーズンまとめ・PSの話題の画面（新デザイン、10/3 改善案G）。

PS予告と同じ色・書体・安全域・立ち絵の置き方で描く。中身（材料）は
generate_asset_video と同じ items / japanese をそのまま使い、読み上げの
組み立ても変えない（画面だけを差し替える）。

材料に style="v2" があるときだけ generate_asset_video から呼ばれる。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from ps_brand_components import TOKENS, TEAM_SECONDARY_COLORS, font
from ps_render_template import background, SAFE_BOTTOM, SAFE_RIGHT
from video_common import ease_out, lift_color

T = TOKENS["stadium"]
W, H = 1080, 1920
LEFT, TOP = 72, 170
PORTRAITS = "assets/portraits/collespo-20260923/"


NO_HEAD = "、。，．：:）」』・ー％%"


def _tokens(text):
    """折り返してよい単位。全角スペース・読点の後で区切り、数字や英字の
    並び（3.77、.280、45本）は切らない。"""
    out, cur = [], ""
    for c in str(text):
        cur += c
        if c in "　、：" or (c == " " and cur.strip()):
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def _wrap(d, text, size, width, max_lines=4):
    f = font(size)
    lines, line = [], ""
    for tok in _tokens(text):
        if d.textlength((line + tok).rstrip("　 "), font=f) <= width:
            line += tok
            continue
        if line:
            lines.append(line.rstrip("　 "))
            line = ""
        # 1つの単位が幅を超えるときだけ、文字で折る（行頭禁則つき）
        for c in tok:
            if d.textlength(line + c, font=f) > width and line and c not in NO_HEAD:
                lines.append(line)
                line = c
            else:
                line += c
    if line.strip():
        lines.append(line.rstrip("　 "))
    if len(lines) > max_lines and size > 30:
        return _wrap(d, text, size - 4, width, max_lines)
    return lines[:max_lines], size


def _lines(d, text, size, width, max_lines=4):
    return _wrap(d, text, size, width, max_lines)


def _header(d, label, page=None):
    d.text((LEFT, TOP), "コレスポ", font=font(40), fill=T["accent"])
    d.text((LEFT + 190, TOP + 10), label, font=font(28), fill=T["muted"])
    if page:
        d.text((SAFE_RIGHT, TOP + 6), page, font=font(36, True), fill=T["accent"], anchor="ra")


def _badge(d, x, y, team_id, abbr):
    import notability_engine as ne
    c = ne.MLB_TEAM_COLOR.get(str(team_id)) or T["line"]
    d.rounded_rectangle((x, y, x + 150, y + 76), radius=12, fill=c,
                        outline=TEAM_SECONDARY_COLORS.get(str(team_id)) or lift_color(c), width=4)
    d.text((x + 75, y + 38), abbr, font=font(40, True), fill="#ffffff", anchor="mm")


def _presenter(im, root, which="left"):
    path = root / PORTRAITS / ("zundamon/C-cheer/base-black-brow-candidate.png" if which == "left"
                               else "metan/3-black/base.png")
    sp = Image.open(path).convert("RGBA").crop((130, 0, 930, 660))
    sp.thumbnail((240, 230))
    x = 24 if which == "left" else SAFE_RIGHT - sp.width
    im.paste(sp, (x, SAFE_BOTTOM - sp.height), sp)


def _slide(p, i):
    """行ごとに少し遅れて左から入る（PS予告と同じ考え方）。"""
    q = max(0.0, min(1.0, p * 1.6 - i * 0.18))
    return ease_out(q)


def intro(p, spec, root, kind_label):
    im = background(seconds=p * 3).convert("RGB")
    d = ImageDraw.Draw(im)
    _header(d, kind_label)
    y = 330
    if spec.get("team_id") and spec.get("abbr"):
        _badge(d, LEFT, y, spec["team_id"], spec["abbr"])
        y += 110
    hook = spec.get("hook") or spec.get("label", "")
    lines, size = _lines(d, hook, 92, SAFE_RIGHT - LEFT, 4)
    e = _slide(p, 0)
    for k, line in enumerate(lines):
        d.text((LEFT - round(56 * (1 - e)), y + k * (size + 18)), line,
               font=font(size), fill=T["ink"] if k else T["accent"])
    y += len(lines) * (size + 18) + 30
    d.text((LEFT, y), spec.get("label", ""), font=font(40), fill=T["muted"])
    _presenter(im, root, "left")
    return im


def list_page(p, spec, items, start, count, page, pages, root, kind_label):
    im = background(seconds=p * 3).convert("RGB")
    d = ImageDraw.Draw(im)
    _header(d, kind_label, f"{page}/{pages}")
    heading = spec.get("heading") or spec.get("label", "")
    hl, hs = _lines(d, heading, 56, SAFE_RIGHT - LEFT, 2)
    for k, line in enumerate(hl):
        d.text((LEFT, 250 + k * (hs + 10)), line, font=font(hs), fill=T["ink"])
    y = 250 + len(hl) * (hs + 10) + 50
    for i, (head, body) in enumerate(items[start:start + count]):
        e = _slide(p, i + 1)
        if e <= 0:
            continue
        dx = -round(56 * (1 - e))
        d.line((LEFT, y - 22, SAFE_RIGHT, y - 22), fill=T["line"], width=2)
        d.rectangle((LEFT - 22 + dx, y, LEFT - 14 + dx, y + 60), fill=T["accent"])
        d.text((LEFT + dx, y), head, font=font(38), fill=T["muted"])
        # 引用は言葉が主役。行数を増やして、字を小さくしすぎない。
        quote = "番記者" in head or str(body).startswith("「")
        lines, size = _lines(d, body, 52 if quote else 66, SAFE_RIGHT - LEFT, 9 if quote else 4)
        for k, line in enumerate(lines):
            d.text((LEFT + dx, y + 56 + k * (size + 14)), line, font=font(size),
                   fill=T["accent"] if k == 0 else T["ink"])
        y += 60 + len(lines) * (size + 14) + 80
    quoted = any("番記者" in h for h, _ in items[start:start + count])
    d.text((300, SAFE_BOTTOM - 70), "出典：番記者の投稿（原文とリンクは説明欄）" if quoted
           else "出典：MLB公式（Stats API）", font=font(26), fill=T["muted"])
    _presenter(im, root, "right" if page % 2 == 0 else "left")
    return im


def people(p, spec, rows, heading, root, kind_label):
    im = background(seconds=p * 3).convert("RGB")
    d = ImageDraw.Draw(im)
    _header(d, kind_label)
    d.text((LEFT, 250), heading, font=font(64), fill=T["accent"])
    d.text((LEFT, 340), spec.get("label", ""), font=font(32), fill=T["muted"])
    y = 450
    for i, r in enumerate(rows[:3]):
        e = _slide(p, i + 1)
        if e <= 0:
            continue
        dx = -round(56 * (1 - e))
        d.line((LEFT, y - 20, SAFE_RIGHT, y - 20), fill=T["line"], width=2)
        d.text((LEFT + dx, y), r.get("name", ""), font=font(64), fill=T["ink"])
        lines, size = _lines(d, r.get("line", ""), 46, SAFE_RIGHT - LEFT, 3)
        for k, line in enumerate(lines):
            d.text((LEFT + dx, y + 84 + k * (size + 10)), line, font=font(size), fill=T["accent"])
        y += 84 + len(lines) * (size + 10) + 60
    _presenter(im, root, "left")
    return im
