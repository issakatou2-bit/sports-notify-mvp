#!/usr/bin/env python3
"""
出来上がった動画をTikTokへ投稿する。

    TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=... TIKTOK_REFRESH_TOKEN=... \
      python3 scripts/post_tiktok.py \
        --video build/short/collespo_short.mp4 \
        --title "8/12の注目試合" --kind daily

流れ:
  1. リフレッシュトークンでアクセストークンを取る(24時間有効)
  2. creator_info で、いまこのアカウントに何ができるかを聞く
  3. init で投稿枠を作り、返ってきたURLへ動画を送る
  4. status を見て、受理されたことを確かめる

直接投稿と受信箱について:

  審査前は「受信箱(inbox)」にしか送れない。ここは TikTok アプリの
  プロフィール内の「下書き」ではなく、アプリの通知欄に届く
  システムメッセージのこと。そこから開いて投稿する。
  (最初これを「下書き」と書いていたため、探す場所を間違わせた)
  審査が通るまで video.publish は付与されないので、その間は
  受信箱にしか送れない。両方に対応してあり、使える方を選ぶ。
  審査後は何も変えずに直接投稿へ切り替わる。

公開範囲について:
  審査前のクライアントは、TikTok側の制限で SELF_ONLY 以外を選べない。
  creator_info が返す選択肢の中から選ぶので、こちらで決め打ちしない。
"""

import argparse
import json
import os
import pathlib
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from tiktok_auth import refresh as refresh_token  # noqa: E402

API = "https://open.tiktokapis.com/v2"

# 5MB未満の動画は分割せず1回で送る決まり。コレスポのショートは1MB前後なので
# 常にこちら側に入るが、資産動画が長くなった場合に備えて分割にも対応する。
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024

# 望ましい順。creator_info が許した中から、最初に見つかったものを使う。
PRIVACY_PREFERENCE = [
    "PUBLIC_TO_EVERYONE",
    "FOLLOWER_OF_CREATOR",
    "MUTUAL_FOLLOW_FRIENDS",
    "SELF_ONLY",
]


def _post(url: str, token: str, payload: dict) -> dict:
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        data=json.dumps(payload),
        timeout=60,
    )
    return _check(r, url)


def _check(r, url: str) -> dict:
    try:
        data = r.json()
    except json.JSONDecodeError:
        raise RuntimeError(f"{url}: 応答を解釈できません: {r.text[:300]}")
    err = (data.get("error") or {})
    # 正常時も error.code は "ok" で入ってくる
    if err.get("code") and err["code"] != "ok":
        raise RuntimeError(
            f"{url}: {err.get('code')} / {err.get('message', '')}".strip()
        )
    if r.status_code >= 400:
        raise RuntimeError(f"{url}: HTTP {r.status_code}: {r.text[:300]}")
    return data.get("data", data)


def creator_info(token: str) -> dict:
    return _post(f"{API}/post/publish/creator_info/query/", token, {})


def pick_privacy(info: dict, want: str | None) -> str:
    options = info.get("privacy_level_options") or []
    if not options:
        # 取れなければ最も安全な方に倒す。公開してから気づくのが最悪なので。
        return "SELF_ONLY"
    if want and want in options:
        return want
    for p in PRIVACY_PREFERENCE:
        if p in options:
            return p
    return options[0]


def chunks(size: int) -> tuple:
    """(chunk_size, total_chunk_count) を返す。"""
    if size < MIN_CHUNK:
        return size, 1
    n = max(1, size // MAX_CHUNK)
    c = size // n
    if c > MAX_CHUNK:
        n += 1
        c = size // n
    return c, n


def init_upload(token: str, video: pathlib.Path, title: str,
                privacy: str, direct: bool, info: dict) -> dict:
    size = video.stat().st_size
    chunk_size, count = chunks(size)
    source = {
        "source": "FILE_UPLOAD",
        "video_size": size,
        "chunk_size": chunk_size,
        "total_chunk_count": count,
    }

    if not direct:
        # 受信箱へ送る。post_info は受け付けないので送らない。
        return _post(f"{API}/post/publish/inbox/video/init/", token,
                     {"source_info": source})

    post_info = {
        "title": title[:2200],
        "privacy_level": privacy,
        "disable_duet": False,
        "disable_stitch": False,
        "disable_comment": bool(info.get("comment_disabled")),
        "video_cover_timestamp_ms": 1000,
        # 広告・タイアップではないので、どちらも立てない。
        # 立てると別途の開示表示が必要になる。
        "brand_content_toggle": False,
        "brand_organic_toggle": False,
    }
    return _post(f"{API}/post/publish/video/init/", token,
                 {"post_info": post_info, "source_info": source})


def upload_file(upload_url: str, video: pathlib.Path) -> None:
    size = video.stat().st_size
    chunk_size, count = chunks(size)
    with video.open("rb") as f:
        for i in range(count):
            start = i * chunk_size
            # 最後の塊は端数を全部飲み込む
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(body)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                data=body,
                timeout=300,
            )
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(
                    f"アップロード失敗 ({i + 1}/{count}): "
                    f"HTTP {r.status_code} {r.text[:200]}"
                )
            print(f"  送信 {i + 1}/{count} ({len(body):,} バイト)")


def wait_status(token: str, publish_id: str, tries: int = 12) -> dict:
    """
    受理されたかを確かめる。TikTok側の処理は非同期なので少し待つ。
    確認できないまま終わると、失敗したのか処理中なのか分からなくなる。
    """
    last = {}
    for i in range(tries):
        time.sleep(5)
        last = _post(f"{API}/post/publish/status/fetch/", token,
                     {"publish_id": publish_id})
        st = last.get("status")
        print(f"  状態: {st}")
        if st in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return last
        if st == "FAILED":
            raise RuntimeError(
                f"TikTok側で失敗しました: {last.get('fail_reason', '')}"
            )
    print("[warn] 完了を確認できませんでした(処理中の可能性があります)")
    return last


# YouTube用のタイトルに付けている #Shorts は、TikTokでは意味を持たない。
# 代わりに、その動画の題材に合うタグを足す。
TAGS_MLB = "#MLB #大リーグ #野球 #コレスポ"
TAGS_SOCCER = "#サッカー #海外サッカー #プレミアリーグ #コレスポ"


# 題材の判定に使う語。
#
# 「リーグ」だけで拾ってはいけない。MLBのタイトルには
# 「ア・リーグ」「ナ・リーグ」「インターリーグ」が普通に出てくるので、
# 部分一致だとMLBの動画に #サッカー が付く。実際そうなっていた。
# リーグ名は必ず最後まで書いて突き合わせる。
SOCCER_WORDS = ("サッカー", "プレミアリーグ", "ラ・リーガ", "ラリーガ",
                "セリエA", "ブンデスリーガ", "リーグ・アン",
                "チャンピオンズリーグ", "欧州")
MLB_WORDS = ("【MLB】", "MLB", "大リーグ", "メジャーリーグ")


def caption(title: str) -> str:
    """YouTubeのタイトルを、TikTokの説明文に作り替える。"""
    t = title.replace("#Shorts", "").replace("#shorts", "").strip()

    # 見出しの【サッカー】が最も確かな手掛かりなので先に見る。
    if "【サッカー】" in t:
        tags = TAGS_SOCCER
    elif any(w in t for w in MLB_WORDS):
        tags = TAGS_MLB
    elif any(w in t for w in SOCCER_WORDS):
        tags = TAGS_SOCCER
    else:
        # どちらとも決まらないものはMLB扱い。本数が圧倒的に多い。
        tags = TAGS_MLB
    return f"{t}\n\n{tags}"


def title_from_record(path: str, kind: str) -> str | None:
    """
    その日のYouTube投稿の記録からタイトルを借りる。

    同じ動画に別々のタイトルを付けると、どちらが何だったのか
    後から突き合わせられなくなる。作る場所を1つにしておく。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    today = time.strftime("%Y-%m-%d")
    return ((data.get(kind) or {}).get(today) or {}).get("title")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", help="省略時は --title-from から借りる")
    ap.add_argument("--title-from", default="data/published_videos.json",
                    help="YouTube投稿の記録。同じタイトルを使う")
    ap.add_argument("--kind", default="daily", help="記録用の区分")
    ap.add_argument("--privacy", default=None,
                    help="公開範囲。省略時は許可された中から選ぶ")
    ap.add_argument("--record", default="data/published_tiktok.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="投稿せず、権限と公開範囲の確認だけ行う")
    args = ap.parse_args()

    video = pathlib.Path(args.video)
    if not video.exists():
        print(f"[error] 動画がありません: {video}")
        return 1

    title = args.title or title_from_record(args.title_from, args.kind)
    if not title:
        print(f"[error] タイトルがありません。--title を指定するか、"
              f"{args.title_from} に今日の{args.kind}の記録が要ります")
        return 1
    text = caption(title)
    print(f"説明文:\n{text}\n")

    key = os.environ.get("TIKTOK_CLIENT_KEY")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    rt = os.environ.get("TIKTOK_REFRESH_TOKEN")
    if not (key and secret and rt):
        print("[error] TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / "
              "TIKTOK_REFRESH_TOKEN が要ります")
        return 1

    try:
        tok = refresh_token(key, secret, rt)
    except RuntimeError as e:
        print(f"[error] トークンを更新できません: {e}")
        print("       https://collespo.com/tiktok/ から取り直してください")
        return 1

    token = tok["access_token"]
    scopes = (tok.get("scope") or "").split(",")
    direct = "video.publish" in scopes
    print(f"権限: {tok.get('scope')}")
    print("投稿方法:", "直接投稿" if direct else
          "受信箱へ送信(審査前のため。TikTokアプリの通知から投稿します)")

    # 返ってきたリフレッシュトークンは、渡したものと違う場合がある。
    # 次回はこちらを使う必要があるので、必ず表示する。
    if tok.get("refresh_token") and tok["refresh_token"] != rt:
        print("::warning::リフレッシュトークンが更新されました。"
              "期限切れを避けるため、Secretsの TIKTOK_REFRESH_TOKEN を"
              "新しい値に置き換えてください")

    # creator_info は直接投稿のためのAPIで、video.publish が要る。
    # 受信箱しか許されていない状態で呼ぶと scope_not_authorized で落ちる。
    # 受信箱では公開範囲も題名もTikTokアプリ側で決めるので、そもそも要らない。
    info: dict = {}
    privacy = None
    if direct:
        try:
            info = creator_info(token)
        except RuntimeError as e:
            print(f"[error] アカウント情報を取得できません: {e}")
            return 1
        privacy = pick_privacy(info, args.privacy)
        print(f"アカウント: {info.get('creator_nickname', '?')}")
        print(f"選べる公開範囲: {info.get('privacy_level_options')}")
        print(f"使う公開範囲: {privacy}")
    else:
        print("公開範囲: TikTokアプリで投稿するときに決めます")

    if args.dry_run:
        print("\n--dry-run のため、ここで終了します")
        return 0

    print(f"\n投稿: {video.name} ({video.stat().st_size:,} バイト)")
    res = init_upload(token, video, text, privacy, direct, info)
    publish_id = res.get("publish_id")
    upload_url = res.get("upload_url")
    if not upload_url:
        print(f"[error] アップロード先が返りませんでした: {res}")
        return 1

    upload_file(upload_url, video)
    status = wait_status(token, publish_id)

    rec = pathlib.Path(args.record)
    rec.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if rec.exists():
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data.setdefault(args.kind, {})[time.strftime("%Y-%m-%d")] = {
        "publish_id": publish_id,
        "title": title,
        "privacy": privacy,
        "direct": direct,
        "status": status.get("status"),
        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    rec.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n完了しました ({rec})")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

