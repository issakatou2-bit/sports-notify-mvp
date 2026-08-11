#!/usr/bin/env python3
"""
TikTokの認可コードをリフレッシュトークンに交換する。手元で1回だけ実行する。

    TIKTOK_CLIENT_KEY=xxx TIKTOK_CLIENT_SECRET=yyy \
      python3 scripts/tiktok_auth.py --code "<認可コード>"

前提:
  https://collespo.com/tiktok/ で「TikTokでログイン」を押し、
  戻ってきた画面に出る認可コードを控えてあること。

なぜブラウザではなくここでやるのか:
  トークン交換には client_secret が要る。サイトはGitHub Pagesの静的配信
  なので、そこに secret を置くと誰でも読めてしまう。認可コードだけを
  画面に出し、交換は手元で行う。

出力された refresh token は、GitHubリポジトリの Secrets に
TIKTOK_REFRESH_TOKEN として登録する。有効期限は365日だが、
post_tiktok.py が投稿のたびに新しいものへ更新するので、
実際にはそこから伸びていく(ただし更新後の値はSecretsへ自動反映
されないため、期限が近づいたらこの手順をもう一度行う)。
"""

import argparse
import json
import os
import sys

import requests

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://collespo.com/tiktok/callback.html"


def exchange(client_key: str, client_secret: str, code: str,
             redirect_uri: str) -> dict:
    # 認可コードはURLエンコードされた状態で渡ってくることがある。
    # TikTok側はデコード済みの値を期待するので、ここで戻す。
    from urllib.parse import unquote
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": unquote(code),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    return _parse(resp)


def refresh(client_key: str, client_secret: str, refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    return _parse(resp)


def _parse(resp) -> dict:
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise RuntimeError(f"TikTokの応答を解釈できません: {resp.text[:300]}")

    # 失敗はHTTP 200で返ってくることがある。本文のerrorを見る。
    if data.get("error"):
        raise RuntimeError(
            f"TikTok: {data.get('error')} / "
            f"{data.get('error_description', '')}".strip()
        )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    if not data.get("access_token"):
        raise RuntimeError(f"access_tokenが含まれていません: {resp.text[:300]}")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="認可コード(初回の交換に使う)")
    ap.add_argument("--refresh-token",
                    help="既存のリフレッシュトークン(疎通確認に使う)")
    ap.add_argument("--redirect-uri", default=REDIRECT_URI)
    args = ap.parse_args()

    key = os.environ.get("TIKTOK_CLIENT_KEY")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not key or not secret:
        print("[error] TIKTOK_CLIENT_KEY と TIKTOK_CLIENT_SECRET を"
              "環境変数に設定してください")
        return 1
    if not args.code and not args.refresh_token:
        print("[error] --code か --refresh-token のどちらかが要ります")
        return 1

    try:
        if args.code:
            data = exchange(key, secret, args.code, args.redirect_uri)
        else:
            data = refresh(key, secret, args.refresh_token)
    except RuntimeError as e:
        print(f"[error] {e}")
        if "authorization_code" in str(e) or "invalid_grant" in str(e):
            print("       認可コードは一度きり・数分で失効します。"
                  "https://collespo.com/tiktok/ からやり直してください")
        return 1

    print("\n=== 交換できました ===")
    print(f"open_id        : {data.get('open_id')}")
    print(f"scope          : {data.get('scope')}")
    print(f"access_token   : 有効期限 {data.get('expires_in')}秒")
    print(f"refresh_token  : 有効期限 {data.get('refresh_expires_in')}秒"
          f" (約{int(data.get('refresh_expires_in', 0)) // 86400}日)")
    print("\n--- 次の値を GitHub Secrets の TIKTOK_REFRESH_TOKEN に登録 ---")
    print(data["refresh_token"])
    print("--- ここまで ---")
    print("\nあわせて TIKTOK_CLIENT_KEY と TIKTOK_CLIENT_SECRET も"
          "Secretsに登録してください")

    scopes = (data.get("scope") or "").split(",")
    if "video.publish" not in scopes:
        print("\n[warn] video.publish が許可されていません。"
              "審査が通るまでは付与されないため、これは想定どおりです。"
              "その間は下書き投稿(video.upload)のみ行えます")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
