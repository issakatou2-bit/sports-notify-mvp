#!/usr/bin/env python3
"""
YouTubeチャンネルのバナー画像を作って設定する。

なぜ要るのか:
  チャンネルにバナーが1枚も無かった。ページを開いたときに
  いちばん面積を取る場所が空のままで、何のチャンネルなのかが
  アイコンと名前だけで伝わることになる。

  中身は毎日出しているものの一覧にする。実際に出しているものを
  書くだけなので、キャッチコピーを考える必要が無く、
  枠が増えたときも post_common.DAILY_LINEUP から作り直せる。

サイズについて:
  2048×1152 で作る。YouTubeはこの1枚をテレビ・PC・スマホで
  それぞれ違う範囲に切って使う。どの端末でも必ず見える範囲は
  中央の 1235×338 だけなので、文字はそこへ収める。

使い方:
  python3 scripts/channel_banner.py --out build/banner.png
  python3 scripts/channel_banner.py --write     # 実際に設定する
"""

import argparse
import functools
import os
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import post_common  # noqa: E402

W, H = 2048, 1152
# どの端末でも切られずに残る範囲(YouTubeの仕様)
SAFE_W, SAFE_H = 1235, 338

BG = (11, 14, 20)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]


@functools.lru_cache(maxsize=16)
def font(size: int):
    env = os.environ.get("COLLESPO_FONT")
    if env and pathlib.Path(env).exists():
        return ImageFont.truetype(env, size)
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            return ImageFont.truetype(r.stdout.strip(), size)
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError("日本語フォントが見つかりません")


def build() -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # 動画と同じ斜めの帯。チャンネルと動画で見た目を揃える。
    for i in range(-2, 10):
        x = i * 420
        d.polygon([(x, H), (x + 190, H), (x + 520, 0), (x + 330, 0)],
                  fill=(14, 18, 26))

    x0, y0 = (W - SAFE_W) // 2, (H - SAFE_H) // 2
    d.text((x0, y0 + 8), "コレスポ", font=font(112), fill=ACCENT)
    d.text((x0 + 6, y0 + 146),
           "MLBと欧州サッカーの注目試合を、理由つきで毎日",
           font=font(44), fill=TEXT)

    # 出している枠を並べる。実際に出しているものだけ。
    names = [name for _, name, _, _ in post_common.DAILY_LINEUP]
    line = "　".join(names[:4])
    line2 = "　".join(names[4:])
    d.text((x0 + 6, y0 + 226), line, font=font(34), fill=DIM)
    if line2:
        d.text((x0 + 6, y0 + 274), line2, font=font(34), fill=DIM)

    # 安全域の下に細い線。切られる位置の目印ではなく、単なる区切り。
    d.rectangle([x0, y0 + SAFE_H - 6, x0 + SAFE_W, y0 + SAFE_H - 2], fill=JP)
    return im


def upload(path: pathlib.Path) -> int:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build as gbuild
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("[warn] Google APIライブラリが無いためスキップします")
        return 0
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return 0
    creds = Credentials(None, refresh_token=token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=secret)
    yt = gbuild("youtube", "v3", credentials=creds, cache_discovery=False)
    try:
        r = yt.channelBanners().insert(
            media_body=MediaFileUpload(str(path), mimetype="image/png"),
            body={}).execute()
        url = r.get("url")
        if not url:
            print("[error] バナーのURLが返りませんでした", file=sys.stderr)
            return 1
        ch = yt.channels().list(part="brandingSettings",
                                id="UCpZ_j8X8uOex5VvKwwTJj3Q").execute()
        bs = (ch.get("items") or [{}])[0].get("brandingSettings") or {}
        bs.setdefault("image", {})["bannerExternalUrl"] = url
        yt.channels().update(part="brandingSettings",
                             body={"id": "UCpZ_j8X8uOex5VvKwwTJj3Q",
                                   "brandingSettings": bs}).execute()
    except HttpError as e:
        print(f"[error] 設定に失敗しました: {e}", file=sys.stderr)
        return 1
    print("バナーを設定しました")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/banner.png")
    ap.add_argument("--write", action="store_true",
                    help="作った画像をチャンネルへ設定する")
    args = ap.parse_args()

    im = build()
    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p)
    print(f"[info] バナーを作りました({W}×{H}) -> {p}")
    if args.write:
        return upload(p)
    print("(--write を付けるとチャンネルへ設定します)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
