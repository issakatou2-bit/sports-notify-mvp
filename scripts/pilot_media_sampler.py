"""確認済みの写真7枚と資料映像1本を、音声なしの比較見本にする。投稿処理は持たない。"""
import argparse
import html
import json
import os
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageOps

import pilot_media
from pilot_baseball import photo_image
from pilot_render import W, H, FPS, PAPER, INK, TEAL, MUTED, text

ITEMS = [
    ("ohtani-bat-2024", "MLB", ["大谷翔平", "打球を見る。"]),
    ("ohtani-follow-2024", "MLB", ["大谷翔平", "一打の中身へ。"]),
    ("mitoma-2022", "プレミアリーグ", ["三笘薫", "選手から入る。"]),
    ("bernabeu-2009", "ラ・リーガ", ["ベルナベウ", "改修前の姿。"]),
    ("courtois-presentation-2018", "ラ・リーガ", ["クルトワ", "加入時の映像。"]),
    ("allianz-2024", "ブンデスリーガ", ["アリアンツ", "アレーナ", "街とクラブ。"]),
    ("sansiro-2018", "セリエA", ["サン・シーロ", "舞台を知る。"]),
    ("monaco-louisii", "リーグ・アン", ["スタッド・", "ルイ2世", "風景が伝える。"]),
]


def frame(asset, competition, notes, source, progress=0., number=1):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    text(d, (80, 53), "写真と映像で、スポーツを近く。", 63, max_width=1500)
    text(d, (81, 139), "コレスポ / 素材・画面の比較見本（音声なし）", 27, MUTED)
    text(d, (1750, 145), f"0{number} / 08", 25, MUTED)
    box = (80, 196, 1416, 948)
    d.rectangle(box, fill=INK)
    # 映像は全体を残し、元のクラブ表記も隠さない。写真も縦横比を維持する。
    max_size = (box[2] - box[0], box[3] - box[1])
    zoom = 1. if asset["kind"] == "video" else .972 + .028 * progress
    fitted = ImageOps.contain(source, (round(max_size[0] * zoom), round(max_size[1] * zoom)), Image.Resampling.BICUBIC)
    im.paste(fitted, (box[0] + (max_size[0] - fitted.width) // 2, box[1] + (max_size[1] - fitted.height) // 2))
    d = ImageDraw.Draw(im)
    text(d, (1468, 218), competition, 37, TEAL, max_width=380)
    d.line((1468, 291, 1839, 291), fill=INK, width=2)
    for i, line in enumerate(notes):
        text(d, (1468, 343 + i * 78), line, 47, max_width=380)
    label = "資料映像・原音なし" if asset["kind"] == "video" else "過去の資料写真"
    text(d, (1470, 692), label, 28, TEAL, max_width=370)
    when = asset["captured_at"].split(" ")[0]
    text(d, (1470, 749), "撮影日不明" if when == "unknown" else when, 32, max_width=380)
    for i, line in enumerate(["当日の試合の", "映像ではありません。"]):
        text(d, (1470, 827 + 44 * i), line, 28, MUTED, max_width=380)
    text(d, (80, 976), f'{asset["author"]} / {asset["license"]}', 24, max_width=1780)
    text(d, (80, 1023), "出典・原本へのリンク・変更点は、付属の素材一覧をご覧ください。", 23, MUTED)
    return im


def ending():
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    for y, line in [(209, "実写で入り、"), (346, "図で、分かる。")]:
        text(d, (130, y), line, 116, TEAL if y > 300 else INK)
    text(d, (137, 604), "写真7枚 ＋ 資料映像1本", 66)
    for i, line in enumerate(["撮影時点を表示し、作者と出典を残します。", "映像はクラブ制作の2018年の加入紹介。原音は使用していません。", "最新の試合ハイライトを自由に転載できるという意味ではありません。"]):
        text(d, (140, 743 + i * 66), line, 35, MUTED, max_width=1650)
    return im


def render(out, ffmpeg):
    data = {"media_ids": [item[0] for item in ITEMS]}
    approved = {asset["id"]: asset for asset in pilot_media.prepare(data, out)}
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast",
               "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out / "media-sampler.mp4")]
    count = 0
    with (out / "render.log").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for number, (asset_id, competition, notes) in enumerate(ITEMS, 1):
                asset = approved[asset_id]
                decoder = None
                if asset["kind"] == "video":
                    clip = asset["clip"]
                    total = int(clip["duration"] * FPS)
                    decoder = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(clip["start"]),
                        "-i", str(pilot_media.file_path(asset)), "-t", str(clip["duration"]), "-an", "-vf", "scale=1280:720,fps=30",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE, stderr=log)
                else:
                    total = FPS * 5
                    source = photo_image(asset_id)
                try:
                    for i in range(total):
                        if decoder:
                            raw = decoder.stdout.read(1280 * 720 * 3)
                            if len(raw) != 1280 * 720 * 3:
                                raise ValueError("確認済み資料映像の区間を読み込めません")
                            source = Image.frombytes("RGB", (1280, 720), raw)
                        picture = frame(asset, competition, notes, source, i / max(1, total - 1), number)
                        if i == total // 2:
                            picture.save(out / f"sample-{number:02}.jpg", quality=92)
                        process.stdin.write(picture.tobytes())
                        count += 1
                finally:
                    if decoder:
                        decoder.stdout.close()
                        if decoder.wait(timeout=30):
                            raise RuntimeError("資料映像の取り込みに失敗しました")
                print(f"画面 {number}/8 完了", flush=True)
            end = ending()
            end.save(out / "sample-09.jpg", quality=92)
            raw = end.tobytes()
            for _ in range(FPS * 6):
                process.stdin.write(raw)
                count += 1
        finally:
            process.stdin.close()
            code = process.wait(timeout=60)
        if code:
            raise RuntimeError("素材比較動画の作成に失敗しました")
    rows = []
    for asset in approved.values():
        esc = html.escape
        rows.append(f'<li><a href="{esc(asset["source_page"], quote=True)}">{esc(asset["title"])}</a> — {esc(asset["author"])}'
                    f' / <a href="{esc(asset["license_url"], quote=True)}">{esc(asset["license"])}</a>'
                    f'<p>撮影時点: {esc(asset["captured_at"])} / 変更: {esc(asset["changes"])}</p></li>')
    (out / "review.html").write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>実写素材の比較見本</title>'
        '<style>body{max-width:1050px;margin:36px auto;padding:20px;background:#f3f0e7;color:#172b36;font:18px/1.8 sans-serif}video{width:100%}li{margin:24px 0}</style>'
        '<h1>写真と映像で、スポーツを近く。</h1><p>コレスポの素材・画面の比較見本。音声なし。過去の資料で、当日の試合映像ではありません。</p>'
        '<video controls preload="metadata" src="media-sampler.mp4"></video><h2>素材の出典・変更点</h2><ul>' + ''.join(rows) + '</ul></html>', encoding="utf-8")
    receipt = {"frames": count, "duration": count / FPS, "width": W, "height": H, "fps": FPS, "audio": False,
               "images": 7, "video_clips": 1, "published": False, "source_file": "media-sources.json"}
    (out / "sampler-result.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/media-sampler")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    render(out, os.environ.get("PILOT_FFMPEG", "ffmpeg"))


if __name__ == "__main__":
    main()
