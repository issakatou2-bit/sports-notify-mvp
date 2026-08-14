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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="認可コード")
    ap.add_argument("--redirect-uri", default=REDIRECT_URI)
    args = ap.parse_args()

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
