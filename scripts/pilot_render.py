"""独立番組用の図解とモーション。実写は確認済み素材台帳から取得する。"""
import functools
import html
import json
import math
import os
import pathlib
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

from pilot_series import episode_key, segment_voice, voice_credits

W, H, FPS = 1920, 1080, 30
PAPER, INK, TEAL, CORAL = "#f3f0e7", "#172b36", "#127d79", "#dc5946"
MUTED, LINE, WHITE, GOLD = "#65737a", "#d4d7cf", "#fffdf7", "#e8c46a"


@functools.lru_cache(maxsize=80)
def font(size, bold=True):
    options = [os.environ.get("PILOT_FONT_BOLD" if bold else "PILOT_FONT_REGULAR", ""),
               f"/usr/share/fonts/opentype/noto/NotoSansCJK-{'Bold' if bold else 'Regular'}.ttc",
               f"C:/Windows/Fonts/{'meiryob' if bold else 'meiryo'}.ttc"]
    for path in options:
        if path and pathlib.Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError("日本語フォントを設定してください")


def text(d, xy, content, size=44, fill=INK, bold=True, max_width=None):
    f = font(size, bold)
    if max_width and d.textlength(content, font=f) > max_width:
        raise ValueError(f"文字が画面をはみ出します: {content}")
    d.text(xy, content, font=f, fill=fill, anchor="lt")


def wrap(content, size, width):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f = font(size, False)
    if d.textlength(content, font=f) <= width:
        return [content]
    # 句読点だけの2行目を避け、2行の長さと文の切れ目を両立する。
    candidates = []
    for i in range(1, len(content)):
        if content[i] in "、。！？）」』】" or content[i - 1] in "（「『【":
            continue
        left, right = d.textlength(content[:i], font=f), d.textlength(content[i:], font=f)
        if max(left, right) <= width:
            cost = abs(left - right) + (0 if content[i - 1] in "、。" else size * 3)
            candidates.append((cost, i))
    if candidates:
        _, i = min(candidates)
        return [content[:i], content[i:]]
    lines, current = [], ""
    for char in content:
        if d.textlength(current + char, font=font(size, False)) > width and current:
            lines.append(current)
            current = ""
        current += char
    if current:
        lines.append(current)
    return lines


def arrow(d, start, end, color=TEAL, progress=1., width=7):
    x, y = start
    xx, yy = x + (end[0] - x) * progress, y + (end[1] - y) * progress
    d.line((x, y, xx, yy), fill=color, width=width)
    if progress > .92:
        angle = math.atan2(yy - y, xx - x)
        d.polygon([(xx, yy),
                   (xx - 22 * math.cos(angle - .5), yy - 22 * math.sin(angle - .5)),
                   (xx - 22 * math.cos(angle + .5), yy - 22 * math.sin(angle + .5))], fill=color)


def roundbox(d, box, color=WHITE, outline=None, radius=22):
    d.rounded_rectangle(box, radius=radius, fill=color, outline=outline, width=3)


def club(d, center, label="A", color=TEAL, size=92):
    x, y = center
    d.polygon([(x - size, y - size), (x + size, y - size),
               (x + size, y + size * .25), (x, y + size),
               (x - size, y + size * .25)], fill=color)
    f = font(round(size))
    width = d.textlength(label, font=f)
    text(d, (x - width / 2, y - size * .65), label, round(size), WHITE)


def headline(d, content):
    text(d, (96, 166), content, 72, max_width=1728)


def artwork(data, segment, motion=1.):
    if data.get("visual_style") == "baseball-hits-v1":
        import pilot_baseball
        return pilot_baseball.artwork(data, segment, motion)
    image = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(image)
    # 雑誌の見開きのような余白と、固定された番組の見出し。
    text(d, (96, 58), "観戦の見取り図", 34)
    text(d, (1588, 62), "COLLESPO / 01", 25, MUTED)
    d.line((96, 124, 1824, 124), fill=INK, width=2)
    text(d, (96, 818), segment["chapter"], 27, TEAL)
    scene, phase = segment["scene"], segment["phase"]
    if scene == "hook":
        text(d, (99, 198), "同じクラブが出ているのに。", 42, MUTED)
        if phase == 0:
            text(d, (89, 315), "CLで負けた。", 126)
            text(d, (92, 494), "リーグの順位も下がる？", 104)
            d.line((97, 661, 97 + 1440 * motion, 661), fill=CORAL, width=13)
            text(d, (100, 714), "勝ち点の「行き先」を見てみよう。", 40, TEAL)
        else:
            text(d, (87, 333), "勝ち点は、別々。", 145, TEAL)
            text(d, (99, 566), "ひとつのクラブ。ふたつの大会。", 61)
            text(d, (102, 701), "国内リーグ     /     チャンピオンズリーグ", 44, MUTED)
    elif scene == "fork":
        headline(d, "クラブは同じ。争う場所が違う。")
        club(d, (960, 366), size=72)
        text(d, (880, 453), "クラブA", 36)
        arrow(d, (858, 398), (522, 531), TEAL, motion)
        arrow(d, (1062, 398), (1398, 531), CORAL, motion)
        for x, label, sub, color, active in [(156, "国内リーグ", "そのリーグの順位を争う", TEAL, phase >= 1),
                                            (1044, "CL", "欧州のクラブによる別大会", CORAL, phase >= 2)]:
            roundbox(d, (x, 548, x + 720, 775), WHITE, color if active else LINE)
            d.rectangle((x + 28, 585, x + 38, 732), fill=color)
            text(d, (x + 68, 575), label, 68, color)
            if x == 156 and data.get("domestic_examples"):
                text(d, (x + 68, 680), "イングランド：プレミアリーグ", 31, max_width=626)
                text(d, (x + 68, 726), "スペイン：ラ・リーガ", 31, max_width=626)
            else:
                text(d, (x + 68, 687), sub, 38, max_width=626)
    elif scene == "points":
        headline(d, "勝ち点は、その大会の順位表へ。")
        for x, label, result, number, color in [(96, "国内リーグ", "この試合に勝った", "+3", TEAL),
                                                (1032, "CL", "この試合に負けた", "+0", CORAL)]:
            roundbox(d, (x, 303, x + 792, 780), WHITE)
            d.rectangle((x, 327, x + 9, 747), fill=color)
            text(d, (x + 46, 340), label, 57, color)
            text(d, (x + 48, 440), result if x == 96 or phase >= 1 else "次に戦う別の大会", 39, MUTED)
            if x == 96 or phase >= 1:
                text(d, (x + 42, 514), number, 160, color)
                text(d, (x + 334, 590), "勝ち点", 48)
                text(d, (x + 48, 718), "この勝ち点は減らない" if x == 96 and phase >= 1 else "それぞれの順位表に記録", 34)
        if phase >= 1:
            # 逆方向へ数字が移動しないことを、区切りで示す。
            d.line((960, 352, 960, 742), fill=LINE, width=4)
            d.ellipse((929, 501, 991, 563), fill=PAPER, outline=CORAL, width=5)
            d.line((939, 553, 981, 511), fill=CORAL, width=5)
    elif scene == "grid":
        headline(d, "36クラブ。全員とは戦わない。")
        big = str(data["facts"]["clubs"] if phase <= 1 else data["facts"]["opponents"])
        text(d, (90, 319), big, 237, TEAL)
        text(d, (112, 607), "クラブが1つの順位表に" if phase <= 1 else "つの異なる対戦相手", 52)
        text(d, (113, 705), "男子CL / 2026–27" if phase <= 2 else "ホーム4試合 ＋ アウェー4試合", 37, MUTED)
        points = [(1093 + (i % 6) * 109, 351 + (i // 6) * 82) for i in range(36)]
        home, away, own = [0, 5, 7, 12], [18, 21, 30, 35], 14
        if phase >= 2:
            for idx in home + away:
                arrow(d, points[own], points[idx], TEAL if idx in home else CORAL, motion, 3)
        for i, (x, y) in enumerate(points):
            color = TEAL if phase >= 2 and i in home else CORAL if phase >= 2 and i in away else LINE
            if i == own:
                club(d, (x, y), size=30)
            else:
                d.ellipse((x - 22, y - 22, x + 22, y + 22), fill=color, outline=PAPER, width=3)
        if phase >= 3:
            text(d, (1068, 812), "● ホーム4", 27, TEAL)
            text(d, (1360, 812), "● アウェー4", 27, CORAL)
    elif scene == "ladder":
        headline(d, "注目したい、ふたつの境目。")
        for i, (rank, label, color) in enumerate([
                ("1–8位", "ラウンド16へ直接進出", TEAL),
                ("9–24位", "プレーオフへ", "#986819"),
                ("25–36位", "敗退", MUTED)]):
            y = 310 + i * 155
            roundbox(d, (104, y, 1816, y + 128), WHITE, color if phase >= 1 else LINE)
            text(d, (149, y + 27), rank, 60, color, max_width=560)
            text(d, (732, y + 33), label, 52, max_width=1030)
        if phase >= 3:
            for y in (452, 607):
                d.line((105, y, 105 + 1710 * motion, y), fill=CORAL, width=5)
        text(d, (113, 786), "リーグフェーズ終了時点の順位 / 男子CL 2026–27", 29, MUTED)
    elif scene == "national":
        headline(d, "代表戦では、所属するチームが変わる。")
        for x, label, color in [(440, "所属クラブ", TEAL), (1460, "国・地域の代表", CORAL)]:
            d.ellipse((x - 65, 346, x + 65, 476), fill=color)
            roundbox(d, (x - 121, 494, x + 121, 675), color, radius=50)
            text(d, (x - (142 if x == 440 else 224), 715), label, 55)
        if phase == 0:
            arrow(d, (672, 517), (1228, 517), CORAL, motion, 12)
            text(d, (814, 424), "代表に招集", 44, CORAL)
        else:
            arrow(d, (1228, 517), (672, 517), TEAL, motion, 12)
            text(d, (787, 424), "クラブへ戻る", 44, TEAL)
        text(d, (755, 604), "同じ選手を、違う大会で追う", 29, MUTED)
    elif scene == "checklist":
        headline(d, "次の試合は、この3つで見てみる。" if phase == 0 else "クラブ名の前に、大会名。")
        items = [("01", "大会", "何を争う試合？"), ("02", "時点", "いつの順位？"), ("03", "相手", "次は誰と戦う？")]
        for i, (num, label, sub) in enumerate(items):
            x, y = 96 + i * 596, 325 + round((1 - motion) * (24 + i * 13))
            roundbox(d, (x, y, x + 540, y + 430), WHITE)
            text(d, (x + 38, y + 30), num, 50, CORAL)
            text(d, (x + 37, y + 139), label, 110, TEAL)
            text(d, (x + 37, y + 338), sub, 38, max_width=466)
    elif scene == "end":
        d.rectangle((0, 124, W, 870), fill=INK)
        text(d, (98, 232), "次の一戦が、", 107, WHITE)
        text(d, (98, 391), "少し違って見える。", 110, GOLD)
        text(d, (106, 596), "図と原典は、概要欄の観戦ガイドへ。", 49, WHITE)
        text(d, (109, 716), "原典：UEFA大会規則 2026/27 第3条・第17条", 31, "#c2cfd1")
        text(d, (109, 783), "音声：" + voice_credits(data) + "  /  図・構成：コレスポ", 27, "#c2cfd1", max_width=1730)
    return image


def frame(data, segment, motion=1., progress=0.):
    image = artwork(data, segment, motion)
    d = ImageDraw.Draw(image)
    # 話者名とブランドを固定位置へ。立ち絵がなくても声の切替が分かる。
    d.rectangle((1490, 48, 1840, 105), fill=PAPER)
    text(d, (1520, 58), "コレスポ / " + data["episode"], 30, INK)
    if data.get("voices"):
        voice = segment_voice(data, segment)
        d.rectangle((1190, 48, 1480, 105), fill=PAPER)
        text(d, (1240, 63), voice["name"], 26,
             "#527a39" if segment.get("speaker") == "zundamon" else "#9a4e70", max_width=230)
    if segment["scene"].startswith("bb_") and segment["scene"] != "bb_end":
        note = ("資料写真：2024.04.24 / David · CC BY 2.0 / 切り抜き・ズーム" if segment["scene"] == "bb_photo"
                else "図は架空のイニングです。大谷選手の写真の試合を再現したものではありません。")
        text(d, (98, 853), note, 22, MUTED, max_width=1730)
    elif segment["scene"] not in {"end", "bb_end"}:
        note = "図は説明用の模式図" if segment["scene"] in {"hook", "fork", "national"} else "男子CL 2026–27 / リーグフェーズの模式図" if segment["scene"] == "points" else "男子CL 2026–27 / 原典は概要欄"
        text(d, (98, 853), note, 18, MUTED, max_width=1050)
    d.rectangle((0, 878, W, H), fill=INK)
    lines = wrap(segment["text"], 46, 1712)
    if len(lines) > 2:
        raise ValueError("字幕が2行を超えます: " + segment["text"])
    y = 931 if len(lines) == 1 else 905
    for line in lines:
        text(d, (104, y), line, 46, WHITE, False, 1712)
        y += 66
    d.rectangle((0, 1074, round(W * min(1, progress)), 1079), fill=GOLD)
    return image


def thumbnail(data=None):
    if data and data.get("visual_style") == "baseball-hits-v1":
        import pilot_baseball
        return pilot_baseball.thumbnail(data)
    image = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(image)
    text(d, (90, 70), "観戦の見取り図 / 01", 42, "#8bd4c2")
    text(d, (76, 225), "CLで負けると", 144, WHITE)
    text(d, (81, 429), "リーグも下がる？", 146, GOLD)
    d.line((98, 670, 1740, 670), fill="#3e555e", width=3)
    for x, label, sub, color in [(99, "国内リーグ", "勝ち点", "#8bd4c2"), (1039, "CL", "勝ち点", "#ed9984")]:
        roundbox(d, (x, 741, x + 776, 924), "#223e47")
        text(d, (x + 37, 769), label, 55, color)
        text(d, (x + 509, 786), sub, 36, WHITE)
    text(d, (901, 789), "≠", 80, GOLD)
    text(d, (100, 997), "コレスポ  /  ひとつの疑問を、図でほどく。", 31, "#bdcbcd")
    return image


def preview(data, out):
    out = pathlib.Path(out)
    directory = out / "frames"
    directory.mkdir(parents=True, exist_ok=True)
    import pilot_media
    pilot_media.prepare(data, out)
    selections = [0, 3, 6, 11, 15, 18]
    board = Image.new("RGB", (1440, 89), "#dedbd3")
    d = ImageDraw.Draw(board)
    text(d, (28, 22), f"観戦の見取り図 / 第{int(data['episode'])}回・構成と画面", 34)
    for i, segment in enumerate(data["segments"]):
        image = frame(data, segment, 1., i / len(data["segments"]))
        image.save(directory / f"{i:02d}.png")
    # 6画面を3段で見られるサイズにする。
    large = Image.new("RGB", (1440, 1366), "#dedbd3")
    large.paste(board.crop((0, 0, 1440, 89)), (0, 0))
    for n, i in enumerate(selections):
        image = Image.open(directory / f"{i:02d}.png")
        large.paste(image.resize((672, 378), Image.Resampling.LANCZOS), (32 + n % 2 * 704, 89 + n // 2 * 420))
    large.save(out / "storyboard.jpg", quality=94)
    cover = thumbnail(data)
    cover.save(out / "thumbnail.png")
    if data.get("media_ids"):
        cover.save(out / "thumbnail.jpg", quality=92, optimize=True)
    print("全画面の文字量と図を検査し、一覧と表紙を保存しました")


def render(data, out):
    out = pathlib.Path(out)
    manifest = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    if manifest["episode_key"] != episode_key(data):
        raise ValueError("音声と原稿の版が違います")
    preview(data, out)
    duration = manifest["duration"]
    ffmpeg = os.environ.get("PILOT_FFMPEG", "ffmpeg")
    command = [ffmpeg, "-y", "-nostats", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(out / "narration.wav"),
               "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
               "-movflags", "+faststart", "-shortest", str(out / "episode.mp4")]
    with (out / "render.log").open("wb") as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            index, previous = 0, None
            for number in range(math.ceil(duration * FPS)):
                at = number / FPS
                while index + 1 < len(manifest["segments"]) and at >= manifest["segments"][index + 1]["start"]:
                    index += 1
                segment = manifest["segments"][index]
                local = at - segment["start"]
                if index != previous:
                    cached = frame(data, segment)
                    previous = index
                    print(f"映像 {index + 1}/{len(manifest['segments'])}: {at:.1f}秒", flush=True)
                if segment["scene"] == "bb_photo":
                    image = frame(data, segment, min(1., local / segment["duration"]), at / duration)
                elif local < .8:
                    motion = 1 - (1 - min(1., local / .8)) ** 3
                    image = frame(data, segment, motion, at / duration)
                else:
                    image = cached.copy()
                    ImageDraw.Draw(image).rectangle((0, 1074, round(W * at / duration), 1079), fill=GOLD)
                process.stdin.write(image.tobytes())
            process.stdin.close()
            if process.wait(timeout=180):
                raise RuntimeError("動画の書き出しが失敗しました。render.logを確認してください")
        except BaseException:
            process.kill()
            process.wait()
            raise
    page = f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>非公開試作｜観戦の見取り図</title><style>body{{background:#172b36;color:#fffdf7;font:18px/1.8 system-ui;margin:32px auto;max-width:1120px;padding:0 20px}}video,img{{width:100%;height:auto}}a{{color:#8bd4c2}}h1{{font-size:28px}}</style>
<p>コレスポ / 非公開試作</p><h1>{html.escape(data['title'])}</h1><video controls preload="metadata" poster="thumbnail.png" src="episode.mp4"><track kind="captions" src="captions.vtt" srclang="ja" label="日本語"></video>
<p>内容・テンポ・図の伝わり方を見て改善するための試作です。</p><p><a href="episode.mp4">動画</a> / <a href="captions.srt">字幕</a> / <a href="episode.json">台本と出典</a></p><img src="storyboard.jpg" alt="6つの主要画面"></html>'''
    (out / "review.html").write_text(page, encoding="utf-8")
    srt = (out / "captions.srt").read_text(encoding="utf-8")
    (out / "captions.vtt").write_text("WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt), encoding="utf-8")
