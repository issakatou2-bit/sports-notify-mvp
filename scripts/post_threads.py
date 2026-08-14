#!/usr/bin/env python3
"""
Threadsへ注目試合を自動投稿する。

なぜThreadsを足すのか:
  TikTokは、直接投稿の承認に「投稿前に本人が確認する画面」を要求する。
  毎日タップが要る仕組みは続かない、というのがこの企画の前提なので、
  そこが要件になっていない配信先を1つ増やす。Threadsの投稿APIには
  その要求が無く、1日250投稿まで出せる。

本文の組み立ては post_common.py を使う。Blueskyと同じ材料から作るので、
文面の直しが片方だけに入る、ということが起きない。

前提:
  - 環境変数 THREADS_USER_ID
  - 環境変数 THREADS_ACCESS_TOKEN (長期トークン。60日で失効するが、
    このスクリプトが投稿のたびに自動で延長する)

使い方:
  THREADS_USER_ID=xxx THREADS_ACCESS_TOKEN=yyy python3 scripts/post_threads.py

投稿の流れ(Threadsは2段階):
  1. コンテナを作る   POST /v1.0/{user-id}/threads
  2. 公開する         POST /v1.0/{user-id}/threads_publish
"""

import argparse
import os
import sys
import time

import requests

import post_common

API = "https://graph.threads.net/v1.0"
GRAPH = "https://graph.threads.net"

# Threadsの本文上限は500文字。URLとタグの分を見て少し余裕を持たせる。
MAX_CHARS = 480

# 動画コンテナは、作った直後に公開すると処理が終わっておらず失敗する。
# 公式は平均30秒待つよう案内している。テキストのみなら待たなくてよい。
VIDEO_WAIT_SEC = 30


def _post(path: str, params: dict) -> dict:
    r = requests.post(f"{API}/{path}", data=params, timeout=60)
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"{path}: 応答を解釈できません: {r.text[:200]}")
    if "error" in data:
        e = data["error"]
        raise RuntimeError(
            f"{path}: {e.get('type')} / {e.get('message', '')}".strip())
    if r.status_code >= 400:
        raise RuntimeError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
    return data


def create_container(user_id: str, token: str, text: str,
                     video_url: str = "") -> str:
    params = {"access_token": token, "text": text[:500]}
    if video_url:
        params["media_type"] = "VIDEO"
        params["video_url"] = video_url
    else:
        params["media_type"] = "TEXT"
    data = _post(f"{user_id}/threads", params)
    cid = data.get("id")
    if not cid:
        raise RuntimeError(f"コンテナIDが返りませんでした: {data}")
    return cid


def publish(user_id: str, token: str, creation_id: str) -> str:
    data = _post(f"{user_id}/threads_publish",
                 {"access_token": token, "creation_id": creation_id})
    return data.get("id", "")


def refresh_token(token: str) -> dict:
    """
    長期トークンを延長する。有効期限は60日で、24時間以上経っていれば
    延ばせる。投稿のたびに延ばしておけば、毎日動いている限り切れない。

    延ばせなかった場合も投稿自体は成功しているので、警告だけ出す。
    """
    r = requests.get(f"{GRAPH}/refresh_access_token",
                     params={"grant_type": "th_refresh_token",
                             "access_token": token}, timeout=30)
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "不明"))
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="notable_games.json")
    ap.add_argument("--video-url", default="",
                    help="公開URL上のmp4。指定すると動画付きで投稿する")
    ap.add_argument("--dry-run", action="store_true",
                    help="送信せず、投稿する本文だけを表示する")
    args = ap.parse_args()

    user_id = os.environ.get("THREADS_USER_ID")
    token = os.environ.get("THREADS_ACCESS_TOKEN")

    games = post_common.load_notable_games(args.games, limit=3)
    if not games:
        print("[info] 今日は注目試合が無いため投稿をスキップします")
        return 0

    body, hashtags, site_url = post_common.build_post(games, MAX_CHARS)
    # Threadsはタグやリンクの装飾が要らない。本文にそのまま並べる。
    text = body + "\n" + " ".join(f"#{t}" for t in hashtags) + "\n" + site_url

    print("投稿する本文:")
    print("-" * 40)
    print(text)
    print("-" * 40)
    print(f"({len(text)}文字)")

    if args.dry_run:
        print("\n--dry-run のため送信しません")
        return 0

    if not (user_id and token):
        print("[info] THREADS_USER_ID/THREADS_ACCESS_TOKEN未設定のため"
              "スキップします")
        return 0

    try:
        cid = create_container(user_id, token, text, args.video_url)
        print(f"[info] コンテナを作りました: {cid}")
        if args.video_url:
            print(f"[info] 動画の処理を待ちます({VIDEO_WAIT_SEC}秒)")
            time.sleep(VIDEO_WAIT_SEC)
        pid = publish(user_id, token, cid)
        print(f"[info] Threadsに投稿しました: {pid}")
    except RuntimeError as e:
        print(f"[warn] Threads投稿に失敗しました: {e}", file=sys.stderr)
        return 1

    try:
        info = refresh_token(token)
        days = int(info.get("expires_in", 0)) // 86400
        print(f"[info] トークンを延長しました(残り約{days}日)")
        # 返ってきた値が渡したものと違う場合は、次回はそちらが要る。
        if info.get("access_token") and info["access_token"] != token:
            print("::warning::Threadsのトークンが更新されました。Secretsの "
                  "THREADS_ACCESS_TOKEN を新しい値に置き換えてください")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] トークンを延長できませんでした: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
