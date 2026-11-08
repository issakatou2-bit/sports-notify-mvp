"""チャンネル紹介文を置き換える。

既定は先頭1行だけ。--full で data/channel_description.txt の全文に置き換える
（11/8 本人了承の刷新。Studio は名前の変更で本人確認を求め保存できないため、説明は API で）。
既定は表示のみ。--write を付けたときだけ反映する。
キーワードなど他の設定は、読んだ値をそのまま戻す。
"""
import argparse
import os
import sys

OLD_FIRST_LINE = "今日の一戦を、もっと面白く。"
NEW_FIRST_LINE = "MLBと欧州サッカーをもっと面白く。"
TOKEN_URI = "https://oauth2.googleapis.com/token"
CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"


def replace_first_line(description):
    """先頭が想定どおりの時だけ置き換える。違えば None を返して触らない。"""
    if not description:
        return None
    first, sep, rest = description.partition("\n")
    if first.strip() != OLD_FIRST_LINE:
        return None
    return NEW_FIRST_LINE + sep + rest


FULL_TEXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "channel_description.txt")


def replace_full(description, text):
    """今の紹介文が想定どおり（前回の先頭行か、すでに新しい全文）の時だけ全文を返す。"""
    text = (text or "").strip()
    if not description or not text:
        return None
    if description.strip() == text:
        return text
    if description.partition("\n")[0].strip() != NEW_FIRST_LINE:
        return None
    return text


def client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
                        token_uri=TOKEN_URI,
                        client_id=os.environ["YOUTUBE_CLIENT_ID"],
                        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"])
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="実際に反映する(既定は表示のみ)")
    ap.add_argument("--full", action="store_true", help="data/channel_description.txt の全文に置き換える")
    args = ap.parse_args()

    yt = client()
    r = yt.channels().list(part="brandingSettings", id=CHANNEL_ID).execute()
    items = r.get("items") or []
    if not items:
        print("[error] チャンネルが取れませんでした", file=sys.stderr)
        return 1
    bs = items[0].get("brandingSettings") or {}
    ch = bs.get("channel") or {}
    if args.full:
        with open(FULL_TEXT, encoding="utf-8") as f:
            new = replace_full(ch.get("description"), f.read())
    else:
        new = replace_first_line(ch.get("description"))
    if new is None:
        print("[error] 先頭の行が想定と違うので変更しません", file=sys.stderr)
        return 1
    print("変更前:", (ch.get("description") or "").partition("\n")[0])
    print("変更後:", new.partition("\n")[0])
    if not args.write:
        print("(--write を付けると反映します)")
        return 0
    ch["description"] = new
    bs["channel"] = ch
    yt.channels().update(part="brandingSettings",
                         body={"id": CHANNEL_ID, "brandingSettings": bs}).execute()
    print("反映しました")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
