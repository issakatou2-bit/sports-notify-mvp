#!/usr/bin/env python3
"""
Threadsの認可コードを、長期アクセストークンに交換する。

client_secret を使うので、ブラウザ側ではなく手元で実行する。
静的サイト(GitHub Pages)にsecretを置かずに済ませるため、TikTokと同じ形。

流れ:
  1. https://collespo.com/threads/ で「Threadsでログイン」
  2. 戻ってきた画面に出る認可コードをコピー
  3. このスクリプトで交換する(短期→長期の2段階を自動で通す)
  4. 出てきた user_id と長期トークンを GitHub Secrets に登録

使い方:
  THREADS_APP_ID=xxx THREADS_APP_SECRET=yyy \
    python3 scripts/threads_auth.py --code "..."
"""

import argparse
import os
import sys

import requests

AUTH_HOST = "https://graph.threads.net"
REDIRECT_URI = "https://collespo.com/threads/callback.html"


def _check(r, label: str) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"{label}: 応答を解釈できません: {r.text[:200]}")
    if "error" in data:
        e = data["error"]
        if isinstance(e, dict):
            raise RuntimeError(
                f"{label}: {e.get('type', '')} / "
                f"{e.get('message', '')}".strip(" /"))
        raise RuntimeError(f"{label}: {e}")
    if r.status_code >= 400:
        raise RuntimeError(f"{label}: HTTP {r.status_code} {r.text[:200]}")
    return data


def exchange(app_id: str, secret: str, code: str, redirect: str) -> dict:
    """認可コード → 短期トークン(1時間)"""
    # 認可コードの末尾に #_ が付いて戻ることがある。そのまま送ると弾かれる。
    code = code.split("#")[0]
    r = requests.post(
        f"{AUTH_HOST}/oauth/access_token",
        data={"client_id": app_id, "client_secret": secret,
              "grant_type": "authorization_code", "redirect_uri": redirect,
              "code": code},
        timeout=30)
    return _check(r, "短期トークンの取得")


def to_long_lived(secret: str, short_token: str) -> dict:
    """短期トークン → 長期トークン(60日)"""
    r = requests.get(
        f"{AUTH_HOST}/access_token",
        params={"grant_type": "th_exchange_token", "client_secret": secret,
                "access_token": short_token},
        timeout=30)
    return _check(r, "長期トークンへの交換")


def whoami(token: str) -> dict:
    """トークンから user_id を引く。投稿先の指定に要る。"""
    r = requests.get("https://graph.threads.net/v1.0/me",
                     params={"fields": "id,username", "access_token": token},
                     timeout=30)
    return _check(r, "アカウント情報の取得")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="認可コード(認可ページから来た場合)")
    ap.add_argument("--token",
                    help="開発者ポータルの『ユーザートークン生成ツール』で"
                         "作った長期トークン。これがあれば --code は要らない")
    ap.add_argument("--redirect-uri", default=REDIRECT_URI)
    args = ap.parse_args()

    # ポータルでトークンを直接発行できる場合は、認可の往復が丸ごと要らない。
    # secret も使わないので、手元に置く値が1つ減る。
    if args.token:
        try:
            me = whoami(args.token)
        except RuntimeError as e:
            print(f"[error] {e}")
            print("       トークンが正しいか、アカウントが公開かを確認してください")
            return 1
        print("\n=== 確認できました ===")
        print(f"アカウント : @{me.get('username', '?')}")
        print("\n--- GitHub Secrets に登録 ---")
        print(f"THREADS_USER_ID       = {me.get('id')}")
        print(f"THREADS_ACCESS_TOKEN  = {args.token}")
        print("--- ここまで ---")
        print("\n投稿のたびに自動で延長されるので、"
              "毎日動いている限り切れません")
        return 0

    if not args.code:
        print("[error] --token か --code のどちらかが要ります")
        return 1

    app_id = os.environ.get("THREADS_APP_ID")
    secret = os.environ.get("THREADS_APP_SECRET")
    if not (app_id and secret):
        print("[error] THREADS_APP_ID と THREADS_APP_SECRET が要ります")
        print("       Meta開発者ポータルの『Threads app ID』の方を使います")
        print("       (Facebookアプリ側のIDとは別物です)")
        return 1

    try:
        short = exchange(app_id, secret, args.code, args.redirect_uri)
        print("[info] 短期トークンを取得しました")
        long_ = to_long_lived(secret, short["access_token"])
    except RuntimeError as e:
        print(f"[error] {e}")
        return 1

    days = int(long_.get("expires_in", 0)) // 86400
    print("\n=== 交換できました ===")
    print(f"user_id      : {short.get('user_id')}")
    print(f"access_token : 有効期限 約{days}日")
    print("\n--- GitHub Secrets に登録 ---")
    print(f"THREADS_USER_ID       = {short.get('user_id')}")
    print(f"THREADS_ACCESS_TOKEN  = {long_.get('access_token')}")
    print("--- ここまで ---")
    print("\n投稿のたびに自動で延長されるので、毎日動いている限り切れません")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
