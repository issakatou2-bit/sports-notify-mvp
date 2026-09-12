"""実写と塁状況の図を使う第2回。写真は過去資料、得点例は架空と明示。"""
import functools

from PIL import Image, ImageDraw, ImageOps

import pilot_media
from pilot_render import W, H, INK, PAPER, TEAL, CORAL, GOLD, MUTED, WHITE, LINE, text, roundbox, arrow


@functools.lru_cache(maxsize=12)
def photo_image(asset_id):
    asset = pilot_media.catalog()[asset_id]
    path = pilot_media.file_path(asset)
    pilot_media.verify_file(path, asset)
    with Image.open(path) as original:
        if original.width * original.height > 24_000_000:
            raise ValueError("素材画像が大きすぎます")
        return ImageOps.exif_transpose(original).convert("RGB")


def photo_panel(image, asset_id, box, progress=0.):
    source = photo_image(asset_id)
    x, y, xx, yy = box
    w, h = xx - x, yy - y
    # 小さなズームだけ。生成AIによる補完・人物の変形は行わない。
    zoom = 1 + .035 * max(0., min(1., progress))
    fitted = ImageOps.fit(source, (round(w * zoom), round(h * zoom)), Image.Resampling.BICUBIC, centering=(.5, .38))
    left, top = (fitted.width - w) // 2, (fitted.height - h) // 2
    image.paste(fitted.crop((left, top, left + w, top + h)), (x, y))


def diamond(d, center, occupied=(), motion=1., advance=None):
    x, y = center
    coords = {0: (x, y + 174), 1: (x + 190, y), 2: (x, y - 174), 3: (x - 190, y), 4: (x, y + 174)}
    d.polygon([coords[i] for i in range(4)], fill="#ddc5a0", outline=INK, width=4)
    d.polygon([(x, y + 132), (x + 145, y), (x, y - 132), (x - 145, y)], fill="#bad0ae")
    d.ellipse((x - 13, y - 13, x + 13, y + 13), fill=PAPER)
    for base in range(4):
        bx, by = coords[base]
        d.polygon([(bx, by - 13), (bx + 13, by), (bx, by + 13), (bx - 13, by)], fill=WHITE, outline=INK)
        if base in occupied:
            d.ellipse((bx - 27, by - 27, bx + 27, by + 27), fill=CORAL, outline=WHITE, width=4)
            text(d, (bx - 10, by - 15), "●", 24, WHITE)
    for a, b in (advance or []):
        arrow(d, coords[a], coords[b], CORAL, motion, 8)


def artwork(data, segment, motion=1.):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    text(d, (96, 58), "観戦の見取り図", 34)
    text(d, (1588, 62), "COLLESPO / 02", 25, MUTED)
    d.line((96, 124, 1824, 124), fill=INK, width=2)
    scene, phase = segment["scene"], segment["phase"]
    if scene == "bb_photo":
        photo_panel(im, segment["media_id"], (960, 168, 1824, 792), motion)
        d = ImageDraw.Draw(im)
        if phase == 0:
            for y, line in [(209, "同じ2安打。"), (355, "なぜ得点は"), (502, "違う？")]:
                text(d, (91, y), line, 111, TEAL if y == 502 else INK, max_width=840)
            text(d, (98, 716), "本数の先に、試合の流れ。", 47, MUTED, max_width=830)
        elif phase == 1:
            for y, line in [(230, "何本打ったか。"), (353, "どう進んだか。")]:
                text(d, (96, y), line, 86, max_width=825)
            text(d, (100, 532), "数字の「中身」を見る。", 64, TEAL, max_width=800)
            text(d, (100, 694), "写真：大谷翔平 / 2024.04.24", 35, MUTED)
        elif phase == 2:
            text(d, (98, 229), "2安打を、ほどく。", 87, max_width=820)
            for y, number, line in [(399, "01", "打球の結果"), (520, "02", "走者とアウト"), (641, "03", "次の打者")]:
                text(d, (100, y), number, 45, CORAL)
                text(d, (229, y - 8), line, 63, max_width=650)
        else:
            text(d, (94, 228), "数字の先に、", 95)
            text(d, (94, 367), "プレーが見える。", 92, TEAL, max_width=830)
            text(d, (102, 554), "次に2安打のニュースを見たら、", 44, max_width=810)
            text(d, (102, 631), "どんな2本だったか。", 58, max_width=810)
        text(d, (965, 763), "写真 / 2024年4月24日", 24, WHITE)
    elif scene == "bb_hits":
        text(d, (96, 167), "「2安打」でも、内訳は違う。", 76, max_width=1710)
        for x, name, desc, total, color in [(96, "A", "単打 ＋ 単打", "2", TEAL), (990, "B", "二塁打 ＋ 単打", "3", CORAL)]:
            roundbox(d, (x, 315, x + 830, 780), WHITE)
            text(d, (x + 40, 344), name, 57, color)
            text(d, (x + 145, 353), desc, 55, max_width=650)
            text(d, (x + 42, 463), "2", 155, color)
            text(d, (x + 196, 544), "安打", 58)
            text(d, (x + 44, 699), f"塁打は {total}" if phase else "どちらも、安打数は2。", 44, color, max_width=740)
            if phase:
                for i in range(int(total)):
                    bx = x + 417 + i * 100
                    d.rectangle((bx, 521, bx + 69, 590), fill=color)
    elif scene == "bb_inning":
        example = "A" if phase <= 3 else "B"
        color = TEAL if example == "A" else CORAL
        steps = {
            0: ("走者なしから始める。", 0, 0, (), 0, []),
            1: ("1本目の単打で、一塁へ。", 1, 0, (1,), 0, [(0, 1)]),
            2: ("次も単打。走者は一・二塁。", 2, 0, (1, 2), 0, [(1, 2), (0, 1)]),
            3: ("そのあと三者連続三振。", 2, 0, (), 3, []),
            4: ("1本目の二塁打で、二塁へ。", 1, 0, (2,), 0, [(0, 1), (1, 2)]),
            5: ("次の単打で、二塁走者が生還。", 2, 1, (1,), 0, [(2, 3), (3, 4), (0, 1)]),
            6: ("同じく三者連続三振で終了。", 2, 1, (), 3, []),
        }
        line, hits, runs, bases, outs, moves = steps[phase]
        text(d, (96, 167), line, 70, max_width=1730)
        roundbox(d, (96, 314, 831, 782), WHITE)
        text(d, (137, 344), "架空のイニング " + example, 49, color)
        text(d, (138, 457), str(hits), 149, color)
        text(d, (290, 524), "安打", 47)
        text(d, (469, 457), str(runs), 149, color)
        text(d, (617, 524), "得点", 47)
        text(d, (140, 695), "アウト", 40, MUTED)
        for i in range(3):
            x = 350 + i * 70
            d.ellipse((x, 699, x + 37, 736), fill=CORAL if i < outs else LINE)
        diamond(d, (1320, 526), bases, motion, moves)
        text(d, (1113, 752), "●は走者 / 矢印は進塁", 33, MUTED)
    elif scene == "bb_compare":
        text(d, (96, 167), "2安打で0点。2安打で1点。", 84, max_width=1710)
        for x, name, desc, runs, color in [(96, "A", "単打 → 単打 → 三者三振", 0, TEAL), (990, "B", "二塁打 → 単打 → 三者三振", 1, CORAL)]:
            roundbox(d, (x, 317, x + 830, 779), WHITE)
            text(d, (x + 40, 348), name, 62, color)
            text(d, (x + 41, 469), str(runs), 150, color)
            text(d, (x + 205, 541), "得点", 61)
            text(d, (x + 41, 701), desc, 37, max_width=750)
        if phase:
            text(d, (143, 816), "同じ単打でも、走者・打球・走塁・守備で結果は変わる。", 31, TEAL)
    elif scene == "bb_check":
        text(d, (96, 167), "「何安打？」の次に、この3つ。", 77, max_width=1710)
        for i, (label, sub) in enumerate([("種類", "単打？ 長打？"), ("走者", "どこにいた？"), ("アウト", "あと何人？")]):
            x = 96 + 596 * i
            roundbox(d, (x, 329, x + 540, 772), WHITE)
            text(d, (x + 36, 357), f"0{i + 1}", 49, CORAL)
            text(d, (x + 34, 491), label, 87, TEAL, max_width=470)
            text(d, (x + 36, 687), sub, 43, max_width=470)
    else:
        d.rectangle((0, 124, W, 870), fill=INK)
        text(d, (98, 235), "本数から、試合の中身へ。", 106, GOLD, max_width=1730)
        text(d, (108, 466), "原典と写真の出典は、概要欄に。", 62, WHITE)
        text(d, (109, 633), "写真：David / CC BY 2.0（切り抜き・ズーム）", 38, WHITE)
        text(d, (109, 722), "音声：VOICEVOX:四国めたん / 図・構成：コレスポ", 34, "#c2cfd1")
    if scene not in {"bb_end", "bb_compare"}:
        text(d, (96, 817), segment["chapter"], 27, TEAL)
    return im


def thumbnail(data):
    im = Image.new("RGB", (W, H), INK)
    photo_panel(im, data["media_ids"][1], (1020, 0, W, H), .5)
    d = ImageDraw.Draw(im)
    text(d, (92, 79), "観戦の見取り図 / 02", 41, "#8bd4c2")
    text(d, (81, 289), "同じ2安打。", 141, WHITE, max_width=940)
    text(d, (87, 517), "得点は違う？", 133, GOLD, max_width=940)
    text(d, (100, 813), "単打 ＋ 単打  /  二塁打 ＋ 単打", 42, WHITE, max_width=900)
    d.rectangle((1019, 914, W, H), fill=INK)
    text(d, (1060, 942), "大谷翔平の資料写真 / 2024.04.24", 32, WHITE, max_width=820)
    text(d, (1060, 1000), "David · CC BY 2.0 / 写真の試合の解説ではありません", 23, "#bdcbcd", max_width=820)
    text(d, (100, 1010), "コレスポ / 架空のイニングで図解", 32, "#bdcbcd")
    return im
