"""CIで使う同梱字体が実際に日本語を描けるか確認する（通信不要）。"""
from pathlib import Path

from PIL import ImageFont

FONT = Path(__file__).resolve().parents[1] / "assets/fonts/soccer-v5/NotoSansJP-VF.ttf"


def check(path=FONT):
    font = ImageFont.truetype(str(path), 32)
    missing = bytes(font.getmask("\U0010ffff"))
    for char in "日本語カタカナ球場":
        mask = font.getmask(char)
        if not mask.getbbox() or bytes(mask) == missing:
            raise RuntimeError(f"日本語を描けない字体です: {path} ({char})")


if __name__ == "__main__":
    check()
    print("ok 同梱の日本語字体")
