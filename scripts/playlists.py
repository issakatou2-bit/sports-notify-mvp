#!/usr/bin/env python3
"""
投稿した動画を、種類ごとの再生リストへ入れる。

なぜ要るのか:
  ショートの視聴からチャンネル登録に至る割合は、一般に0.3〜0.8%とされる。
  コレスポは28日で3,712回の視聴に対して登録+2人、つまり0.054%で、
  下限のさらに6分の1しかない。

  ショートを見た人は「次々に流す」状態にあり、その場では登録しない。
  そこから残ってもらうために名前が挙がるのが再生リストで、
  「この人は同じものを毎日出している」が一覧で見えることが効く。
  53本がバラバラに並んでいるだけの状態では、それが伝わらない。

必要な権限:
  再生リストの操作には youtube スコープが要る。投稿だけの
  youtube.upload では足りないので、取り直しが必要になる。
  取り直していない場合はこのスクリプトは何もせずに終わる。

使い方:
  python3 scripts/playlists.py --sync
  python3 scripts/playlists.py --add VIDEO_ID --kind morning
"""

import argparse
import json
import os
import pathlib
import sys

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"
# 再生リストの作成・追加には youtube スコープが要る。
# ここでは記録のために置いてあるだけで、更新要求には渡さない
# (渡すと invalid_scope になる。理由は client() のコメント)。
NEEDED = "https://www.googleapis.com/auth/youtube"
SCOPES = [NEEDED]

VIDEOS_PATH = "data/published_videos.json"
STORE = "data/playlists.json"

# 種類ごとの再生リスト。説明は「毎日ここに増える」ことが伝わる書き方にする。
PLAYLISTS = {
    "morning": (
        "日本人選手の成績｜毎日更新",
        "MLBの日本人選手が、その日どれだけ効いたかを勝利貢献スコア順に。"
        "毎日16時30分に追加しています。計算方法は https://collespo.com/score.html"),
    "morning_local": (
        "現地での注目度｜毎日更新",
        "現地でどの試合が見られ、どのチームが語られたかを数字で。毎日18時に追加しています。"),
    "morning_press": (
        "現地メディアの声｜毎日更新",
        "現地の番記者の投稿と見出しを翻訳して紹介します。毎日21時に追加しています。"),
    "morning_voices": (
        "現地のファンは何と言ったか｜毎日更新",
        "その日いちばん見られたMLB公式ハイライトのコメント欄を翻訳して紹介します。"
        "賛否と高評価の数つき。毎日17時30分に追加しています。"),
    "daily": (
        "明日の注目試合（MLB）｜毎日更新",
        "翌日のMLBから3試合を、なぜ注目なのかの理由つきで。毎日19時に追加しています。"),
    "daily_soccer": (
        "今夜の注目試合（欧州サッカー）｜毎日更新",
        "その夜の欧州5大リーグとCLから、注目カードを理由つきで。毎日20時に追加しています。"),
    "weekly": (
        "週間まとめと答え合わせ",
        "1週間の振り返りと、注目試合に選んだカードが実際どうなったかの確認。毎週日曜。"),
    "asset": (
        "はじめての人へ｜用語と仕組み",
        "日付に関係なく使える解説。順位表の読み方、指標の意味、球場の特徴など。"),
}


def client():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    # scopes は渡さない。更新要求に scope が乗ると、付与済みと一致しない
    # 場合に invalid_scope で弾かれる。実際、youtube だけを渡して
    # (トークンは youtube.upload と youtube の2つを持っている)落ちた。
    # 権限はトークン側にあるので、こちらから指定する必要は無い。
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    print(f"[info] トークン: ...{token[-8:]}")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def creds_of(yt):
    """build() した後から資格情報を取り出す。"""
    return getattr(getattr(yt, '_http', None), 'credentials', None)


def granted_scopes(creds) -> list:
    """
    いま使っているトークンが実際に持っている権限を、Googleに聞く。

    権限が足りないときに「取り直してください」とだけ出しても、
    取り直したのに直らない場合に何も分からない。実際、取り直した後も
    Secretsが古いままで同じエラーが出た。何が入っているかを見せる。
    """
    import urllib.error
    import urllib.request

    if creds is None:
        return []
    try:
        from google.auth.transport.requests import Request
        if not creds.token:
            creds.refresh(Request())
        with urllib.request.urlopen(
                "https://oauth2.googleapis.com/tokeninfo"
                f"?access_token={creds.token}", timeout=20) as r:
            return (json.load(r).get("scope") or "").split()
    except Exception as e:  # noqa: BLE001
        # ここが分からなくても本題(権限不足)は伝わるので、握って続ける。
        print(f"[warn] 権限の確認に失敗しました: {e}")
        return []


def load_store() -> dict:
    p = pathlib.Path(STORE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_store(data: dict) -> None:
    p = pathlib.Path(STORE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_playlist(yt, store: dict, kind: str) -> str:
    """その種類の再生リストIDを返す。無ければ作る。"""
    if store.get(kind, {}).get("id"):
        return store[kind]["id"]
    title, desc = PLAYLISTS[kind]
    res = yt.playlists().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": desc,
                          "defaultLanguage": "ja"},
              "status": {"privacyStatus": "public"}}).execute()
    pid = res["id"]
    store[kind] = {"id": pid, "title": title, "videos": []}
    print(f"[info] 再生リストを作りました: {title} ({pid})")
    return pid


def add_video(yt, store: dict, kind: str, video_id: str) -> bool:
    if kind not in PLAYLISTS:
        print(f"[info] {kind} に対応する再生リストはありません")
        return False
    pid = ensure_playlist(yt, store, kind)
    if video_id in store[kind].get("videos", []):
        return False
    try:
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": pid,
                              "resourceId": {"kind": "youtube#video",
                                             "videoId": video_id}}}).execute()
    except HttpError as e:
        # 既に入っている、動画が非公開など。1本の失敗で全体を止めない。
        print(f"[warn] {video_id} を追加できませんでした: {e}")
        return False
    store[kind].setdefault("videos", []).append(video_id)
    return True


# タイトルから種類を見分ける。
#
# data/published_videos.json に残っているのは11本だけで、
# チャンネルには53本ある(記録が4日間止まっていた分が抜けている)。
# 過去分を入れるには、チャンネルにある動画そのものを見るしかない。
#
# 順番に意味がある。「注目試合」は複数の種類のタイトルに出てくるので、
# より限定的なものから先に判定する。
TITLE_RULES = [
    ("morning_press", ("現地メディアは何と言っている", "番記者の投稿と現地の見出し")),
    ("morning_local", ("現地で最も注目された試合", "現地での注目度",
                       "現地で最も見られた試合")),
    ("morning", ("勝利貢献スコア", "日本人選手の成績")),
    ("weekly", ("週間ダイジェスト", "1週間を振り返", "今週の注目試合",
                "答え合わせ")),
    ("daily_soccer", ("の注目試合【サッカー】", "注目試合｜サッカー")),
    ("daily", ("の注目試合【MLB】", "の注目試合", "注目試合")),
]


def classify(title: str) -> str:
    """タイトルから種類を決める。当てはまらなければ資産動画とみなす。"""
    for kind, needles in TITLE_RULES:
        if any(n in title for n in needles):
            return kind
    return "asset"


def uploads_playlist_id(yt) -> str:
    res = yt.channels().list(part="contentDetails", mine=True).execute()
    items = res.get("items") or []
    if not items:
        raise RuntimeError("チャンネルが取得できませんでした")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def all_uploads(yt) -> list:
    """チャンネルの全動画を、古い順に返す。"""
    pid = uploads_playlist_id(yt)
    out, token = [], None
    while True:
        res = yt.playlistItems().list(
            part="snippet", playlistId=pid, maxResults=50,
            pageToken=token).execute()
        for item in res.get("items", []):
            sn = item.get("snippet") or {}
            vid = (sn.get("resourceId") or {}).get("videoId")
            if vid:
                out.append({"id": vid, "title": sn.get("title", ""),
                            "at": sn.get("publishedAt", "")})
        token = res.get("nextPageToken")
        if not token:
            break
    out.sort(key=lambda x: x["at"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true",
                    help="記録にある動画を、まとめて再生リストへ入れる")
    ap.add_argument("--backfill", action="store_true",
                    help="チャンネルの全動画をタイトルから分類して入れる")
    ap.add_argument("--dry-run", action="store_true",
                    help="追加せず、どう分類されるかだけ出す")
    ap.add_argument("--add", help="この動画IDを追加する")
    ap.add_argument("--kind", help="--add と一緒に使う種類")
    args = ap.parse_args()

    yt = client()
    if yt is None:
        return 0
    store = load_store()

    try:
        if args.add:
            if not args.kind:
                print("[error] --add には --kind が要ります")
                return 1
            ok = add_video(yt, store, args.kind, args.add)
            print(f"[info] {'追加しました' if ok else '追加していません(既出か失敗)'}")
        elif args.backfill:
            videos = all_uploads(yt)
            print(f"[info] チャンネルの動画 {len(videos)}本\n")
            counts, added = {}, 0
            for v in videos:
                kind = classify(v["title"])
                counts[kind] = counts.get(kind, 0) + 1
                if args.dry_run:
                    print(f"  {kind:<14} {v['title'][:56]}")
                    continue
                if add_video(yt, store, kind, v["id"]):
                    added += 1
                    print(f"  {kind:<14} {v['title'][:56]}")
            print()
            for k, n in sorted(counts.items(), key=lambda x: -x[1]):
                title = PLAYLISTS.get(k, (k,))[0]
                print(f"  {title:<34} {n}本")
            if not args.dry_run:
                print(f"\n[info] {added}本を追加しました")
        elif args.sync:
            try:
                videos = json.loads(
                    pathlib.Path(VIDEOS_PATH).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"[error] {VIDEOS_PATH} を読めません: {e}")
                return 1
            added = 0
            # 古い順に入れる。再生リストは追加順に並ぶので、
            # 上から順に見ていくと時系列になる形にしておく。
            for kind in PLAYLISTS:
                for day in sorted(videos.get(kind, {})):
                    vid = videos[kind][day].get("video_id")
                    if vid and add_video(yt, store, kind, vid):
                        added += 1
                        print(f"  {kind} {day} -> {vid}")
            print(f"[info] {added}本を追加しました")
        else:
            print("[info] --sync か --add を指定してください")
    except HttpError as e:
        # スコープが足りない場合はここに来る。何が要るのかを出す。
        if "insufficientPermissions" in str(e) or e.resp.status == 403:
            print()
            print("[error] 権限が足りません。")
            have = granted_scopes(creds_of(yt))
            if have:
                print("       いま使われているトークンが持っている権限:")
                for sc in have:
                    print(f"         {sc}")
                if NEEDED not in have:
                    print()
                    print(f"       {NEEDED} がありません。")
                    print("       取り直したのにこう出る場合は、GitHub Secrets の")
                    print("       YOUTUBE_REFRESH_TOKEN がまだ古い値のままです。")
            else:
                print("       トークンの権限を確認できませんでした。")
            print()
            print("       取り直しは次のコマンドです:")
            print("         py -3 scripts/youtube_auth.py \\")
            print("           --client-secret path/to/client_secret.json")
            return 1
        raise

    save_store(store)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
