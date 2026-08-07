"""
SNS共有用のOGP画像(1200×630)を作る。

なぜ必要か:
  Bluesky・Xへ毎日リンクを投稿しているのに、og:image が無いため
  リンクカードが出ず、タイムライン上ではただのURLとして流れていた。
  カードが出るかどうかでクリック率は大きく変わる。

日次で変える必要は無い(内容が日付に依存しない)ので、
このスクリプトは手で1回動かし、出力をリポジトリへコミットして使う。
ワークフローからは呼ばない。

使い方:
  python3 scripts/generate_og_image.py --out web/icons/og-image.png
"""

import argparse
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageFont

# OGPの推奨サイズ。1.91:1 で、主要SNSがこの比率で切り抜く
W, H = 1200, 630

BG = (11, 14, 20)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
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
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            _FONT_FILE = r.stdout.strip()
            return _FONT_FILE
    except Exception:
        pass
    raise RuntimeError("日本語フォントが見つかりません")


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
    parser.add_argument("--out", default="web/icons/og-image.png")
    args = parser.parse_args()

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # 動画と同じ斜めのアクセント。チャネル間で見た目を揃えるため
    for i in range(-1, 6):
        x = i * 260
        d.polygon([(x, H), (x + 110, H), (x + 300, 0), (x + 190, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 14, W, H], fill=ACCENT)

    d.text((80, 120), "コレスポ", font=font(110), fill=ACCENT)
    d.text((80, 270), "今日の注目試合を、理由つきで", font=font(52), fill=TEXT)

    d.text((80, 380), "MLB ・ 欧州サッカー", font=font(38), fill=JP)

    # 毎日19時という約束は、このサービスの中心なので必ず入れる
    d.rounded_rectangle([80, 452, 340, 528], 14, fill=ACCENT)
    d.text((108, 470), "毎日 19時", font=font(42), fill=BG)

    d.text((372, 478), "collespo.com", font=font(38), fill=DIM)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)
    print(f"[info] OGP画像を生成しました: {out} ({W}×{H}, "
          f"{out.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
