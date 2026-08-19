#!/usr/bin/env python3
"""
チャンネル自体の検索まわりを整える。

なぜ要るのか:
  動画1本ずつのタグは直したが、チャンネルのキーワードは空のままだった。
  ここはチャンネル全体が何を扱っているかをYouTubeへ伝える欄で、
  1本ずつのタグとは別に見られる。既定の言語も未設定で、
  日本語の動画だと明示できていなかった。

何を入れるか:
  実際に検索で来ている語を根拠にする。直近28日の検索語は
  「mlb順位表」11回、「今永昇太」7回、「吉田正尚」7回、
  「大谷翔平 速報」5回。扱っていない言葉は入れない。
  詰め込みではなく、来ている人が打った言葉を並べる。

使い方:
  python3 scripts/channel_seo.py            # いまの設定と、変更案を見るだけ
  python3 scripts/channel_seo.py --write    # 実際に反映する
"""

import argparse
import os
import sys

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"
CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"

# 実際に検索で来ている語と、毎日扱っているものだけ。
# 空白で区切る。空白を含む語は引用符でくくる決まり。
KEYWORDS = " ".join([
    "MLB", "メジャーリーグ", "野球", "MLB速報", "MLB順位表",
    "注目試合", "日本人選手",
    "大谷翔平", "今永昇太", "吉田正尚", "鈴木誠也", "山本由伸",
    "千賀滉大", "佐々木朗希", "菅野智之", "ヌートバー",
    "欧州サッカー", "プレミアリーグ", "ラリーガ", "セリエA",
    "ブンデスリーガ", "リーグアン",
    "野球初心者", "コレスポ",
])

DEFAULT_LANGUAGE = "ja"


def client():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="実際に反映する(既定は表示のみ)")
    args = ap.parse_args()

    yt = client()
    if yt is None:
        return 0

    try:
        r = yt.channels().list(part="brandingSettings",
                               id=CHANNEL_ID).execute()
    except HttpError as e:
        print(f"[warn] 取得に失敗しました: {e}", file=sys.stderr)
        return 0
    items = r.get("items") or []
    if not items:
        print("[warn] チャンネルが取れませんでした", file=sys.stderr)
        return 0

    bs = items[0].get("brandingSettings") or {}
    ch = bs.get("channel") or {}
    print("いまの設定")
    print(f"  キーワード : {ch.get('keywords') or '(未設定)'}")
    print(f"  既定の言語 : {ch.get('defaultLanguage') or '(未設定)'}")
    print("\n変更案")
    print(f"  キーワード : {KEYWORDS}")
    print(f"  既定の言語 : {DEFAULT_LANGUAGE}")
    print(f"  ({len(KEYWORDS)}文字 / 上限500)")

    if not args.write:
        print("\n(--write を付けると反映します)")
        return 0

    # 説明文とタイトルは触らない。渡さないと消えるので、読んだものを戻す。
    ch["keywords"] = KEYWORDS
    ch["defaultLanguage"] = DEFAULT_LANGUAGE
    bs["channel"] = ch
    try:
        yt.channels().update(part="brandingSettings",
                             body={"id": CHANNEL_ID,
                                   "brandingSettings": bs}).execute()
    except HttpError as e:
        print(f"[error] 反映に失敗しました: {e}", file=sys.stderr)
        return 1
    print("\n反映しました")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
