#!/usr/bin/env python3
"""
動画に英語のタイトルと説明文を持たせる。

なぜ要るのか:
  視聴の35.8%が日本以外から来ている。自動吹き替えを有効にしたので
  音声は英語で聞けるようになったが、タイトルと説明文が日本語のままだと、
  英語圏の人には検索でも一覧でも引っかからない。音声だけ英語にしても、
  そこへ辿り着く経路が無い。

  YouTubeは1本の動画に複数言語のタイトル・説明文を持たせられる。
  視聴者の設定言語に応じて表示が切り替わる。動画は1本のままでよい。

  日本語版は一切変えない。英語を足すだけ。

必要な権限:
  youtube スコープ(再生リストと同じ)。videos.update を使う。
  1本あたり50ユニット。1日5本で250、割り当て10,000に対して2.5%。

使い方:
  python3 scripts/localize_videos.py --recent 5
  python3 scripts/localize_videos.py --backfill      # 過去分すべて
  python3 scripts/localize_videos.py --video VIDEO_ID --dry-run
"""

import argparse
import json
import os
import pathlib
import sys

import token_log  # noqa: E402

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
TOKEN_URI = "https://oauth2.googleapis.com/token"
STORE = "data/localized.json"


def client():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    # scopes は渡さない(渡すと invalid_scope になる。playlists.py と同じ)
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def load_store() -> dict:
    p = pathlib.Path(STORE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_store(d: dict) -> None:
    p = pathlib.Path(STORE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def translate(ai, title: str, description: str) -> tuple:
    """
    日本語のタイトルと説明文を英語にする。

    訳し方をAIに任せるのは、文面が毎日変わるため。数字や固有名詞は
    元の文に入っているものだけを使わせ、足させない。
    """
    prompt = (
        "以下は日本のスポーツ情報チャンネルの動画タイトルと説明文です。"
        "英語圏の視聴者向けに英訳してください。\n\n"
        f"[TITLE]\n{title}\n\n"
        f"[DESCRIPTION]\n{description[:1500]}\n\n"
        "条件:\n"
        "- 出力は次の形式のみ。前置きや説明は不要\n"
        "  TITLE: <英語のタイトル>\n"
        "  DESC:\n"
        "  <英語の説明文>\n"
        "- タイトルは95文字以内。検索されやすい語を前に置く\n"
        "- 選手名・球団名は英語圏で通用する正式表記にする"
        "(大谷翔平 -> Shohei Ohtani、ドジャース -> Dodgers)\n"
        "- 数字・成績・日付は元の文にあるものだけを使い、足さない\n"
        # 「注目試合」を Highlights と訳した例があった。これは翌日の試合の
        # 予告で、プレー集ではない。期待して開いた人がすぐ離れるうえ、
        # 内容と違うことを書いていることになる。
        "- 動画の種類を変えないこと。特に次を守る:\n"
        "    「◯◯の注目試合」= これから行われる試合の予告。"
        " Highlights / Recap とは絶対に訳さない"
        "(Games to Watch, Preview のような語を使う)\n"
        "    「成績」「ランキング」= 終わった試合の集計\n"
        "    「現地で最も注目された試合」= 現地での注目度の集計\n"
        "- 元の文に無い語(Highlights, Full Game, Live など)を足さない\n"
        "- #Shorts は残す\n"
        "- URLはそのまま残す"
    )
    resp = ai.messages.create(model=MODEL, max_tokens=1600,
                              messages=[{"role": "user", "content": prompt}])
    token_log.record("localize", MODEL, resp)
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("訳が途中で切れました")
    text = "".join(b.text for b in resp.content if b.type == "text")

    title_en, desc_en, mode = "", [], None
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title_en = line[6:].strip()
            mode = None
        elif line.startswith("DESC:"):
            mode = "desc"
        elif mode == "desc":
            desc_en.append(line)
    return title_en[:100], "\n".join(desc_en).strip()


# 実行ページに出す行。訳したものを順に溜めていく。
REPORT: list = []


def localize(yt, ai, video_id: str, store: dict, dry: bool = False) -> bool:
    res = yt.videos().list(part="snippet,localizations", id=video_id).execute()
    items = res.get("items") or []
    if not items:
        print(f"[warn] {video_id} が見つかりません")
        return False
    v = items[0]
    sn = v["snippet"]

    if (v.get("localizations") or {}).get("en"):
        return False

    try:
        title_en, desc_en = translate(ai, sn.get("title", ""),
                                      sn.get("description", ""))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {video_id} の英訳に失敗: {e}")
        return False
    if not title_en:
        print(f"[warn] {video_id} のタイトルが訳せませんでした")
        return False

    print(f"  {sn.get('title','')[:44]}")
    print(f"    -> {title_en[:60]}")
    REPORT.append((sn.get("title", ""), title_en, desc_en))
    if dry:
        return False

    # localizations を効かせるには、元の言語を明示する必要がある。
    # 指定が無いと「どれが原文か」が決まらず、切り替えが働かない。
    body = {
        "id": video_id,
        "snippet": {
            "title": sn.get("title"),
            "description": sn.get("description"),
            "categoryId": sn.get("categoryId"),
            "tags": sn.get("tags") or [],
            "defaultLanguage": "ja",
        },
        "localizations": dict(v.get("localizations") or {},
                              en={"title": title_en, "description": desc_en}),
    }
    try:
        yt.videos().update(part="snippet,localizations", body=body).execute()
    except HttpError as e:
        print(f"[warn] {video_id} を更新できませんでした: {e}")
        return False
    store[video_id] = {"title_en": title_en}
    return True


def recent_ids(limit: int) -> list:
    """記録から、新しい順に動画IDを返す。"""
    try:
        rec = json.loads(pathlib.Path(
            "data/published_videos.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = []
    for kind, days in rec.items():
        for day, e in days.items():
            if e.get("video_id"):
                rows.append((day, e["video_id"]))
    rows.sort(reverse=True)
    return [v for _, v in rows[:limit]]


def all_ids(yt) -> list:
    res = yt.channels().list(part="contentDetails", mine=True).execute()
    pid = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    out, token = [], None
    while True:
        r = yt.playlistItems().list(part="snippet", playlistId=pid,
                                    maxResults=50, pageToken=token).execute()
        for it in r.get("items", []):
            vid = ((it.get("snippet") or {}).get("resourceId") or {}
                   ).get("videoId")
            if vid:
                out.append(vid)
        token = r.get("nextPageToken")
        if not token:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="この動画だけ")
    ap.add_argument("--recent", type=int, default=0,
                    help="記録から新しい順にこの本数")
    ap.add_argument("--backfill", action="store_true",
                    help="チャンネルの全動画")
    ap.add_argument("--limit", type=int, default=60,
                    help="1回で処理する上限(割り当ての保険)")
    ap.add_argument("--dry-run", action="store_true",
                    help="更新せず、訳だけ出す")
    args = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or anthropic is None:
        print("[info] ANTHROPIC_API_KEY未設定のためスキップします")
        return 0
    yt = client()
    if yt is None:
        return 0
    ai = anthropic.Anthropic(api_key=key)
    store = load_store()

    if args.video:
        ids = [args.video]
    elif args.backfill:
        ids = all_ids(yt)
    else:
        ids = recent_ids(args.recent or 5)

    # 既に英語が入っているものは飛ばす。API側でも確認するが、
    # 記録があるぶんは問い合わせ自体を省ける。
    ids = [v for v in ids if v not in store][:args.limit]
    if not ids:
        print("[info] 英語を足す動画はありません")
        return 0

    print(f"[info] 対象 {len(ids)}本\n")
    done = 0
    for vid in ids:
        try:
            if localize(yt, ai, vid, store, args.dry_run):
                done += 1
        except HttpError as e:
            if e.resp.status == 403:
                print("[error] 権限が足りません。youtube スコープが要ります")
                break
            print(f"[warn] {vid}: {e}")

    if not args.dry_run:
        save_store(store)
    print(f"\n[info] {done}本に英語を足しました")

    # 実行ページにも出す。ログを開かないと結果が分からないのでは、
    # 確認のたびにジョブを掘ることになる。
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and REPORT:
        head = ("訳の確認（更新はしていません）" if args.dry_run
                else f"{done}本に英語を足しました")
        lines = [f"## {head}", ""]
        for ja, en, desc in REPORT:
            lines += [f"**{ja}**", "", f"→ {en}", "",
                      "<details><summary>説明文</summary>", "",
                      "```", desc[:900], "```", "", "</details>", ""]
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
