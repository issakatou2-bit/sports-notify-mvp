"""
アプリ登録用のアイコン(1024×1024)を作る。

なぜ必要か:
  TikTokの開発者登録では1024×1024のアイコンが必須だが、
  手元にあるのは512pxのものだけだった。拡大するとぼやけるので、
  同じ意匠でこのサイズから描き直す。

日次で変える必要は無いので、手で1回動かして出力をコミットして使う。
ワークフローからは呼ばない。

使い方:
  python3 scripts/generate_app_icon.py --out web/icons/app-icon-1024.png
"""

import argparse
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageFont

S = 1024

BG = (11, 14, 20)
ACCENT = (255, 176, 32)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
]
_FONT_FILE = None


def _resolve_font() -> str:
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE
    for p in FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            _FONT_FILE = p
            return p
    r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                       capture_output=True, text=True, check=True)
    _FONT_FILE = r.stdout.strip()
    return _FONT_FILE


def font(size: int):
    path = _resolve_font()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        for i in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=i)
            except OSError:
                continue
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="web/icons/app-icon-1024.png")
    args = parser.parse_args()

    im = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(im)

    # 動画やOGP画像と同じ斜めのアクセント。並んだときに同じ物だと分かるように
    for i in range(-1, 5):
        x = i * 260 - 60
        d.polygon([(x, S), (x + 110, S), (x + 300, 0), (x + 190, 0)],
                  fill=(14, 18, 26))

    # 小さく表示されても読めるよう、頭文字を大きく置く
    f = font(420)
    text = "コレ"
    tw = d.textlength(text, font=f)
    d.text(((S - tw) / 2, 210), text, font=f, fill=ACCENT)

    f2 = font(150)
    sub = "スポ"
    sw = d.textlength(sub, font=f2)
    d.text(((S - sw) / 2, 640), sub, font=f2, fill=JP)

    d.rectangle([0, S - 40, S, S], fill=ACCENT)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)
    print(f"[info] アプリアイコンを生成しました: {out} "
          f"({S}×{S}, {out.stat().st_size / 1024:.0f}KB / 上限5MB)")


if __name__ == "__main__":
    main()
