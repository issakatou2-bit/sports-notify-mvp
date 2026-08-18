#!/usr/bin/env python3
"""
読み上げ原稿から字幕を作り、動画に付ける。

なぜ要るのか:
  字幕なしで見られている割合が70%。ショートは音を切って見る人が多く、
  そこへ何も出していないと、読み上げの中身がまるごと届かない。
  画面の文字だけでは、ナレーションで補っている部分が落ちる。

  作るのに新しい材料は要らない。読み上げの本文と、その音声の実測長は
  どちらも既にある(narration の text と、合成した音声の manifest)。
  同じものから字幕を組めば、音声と字幕がずれようがない。

  自動生成の字幕に任せない理由:
    VOICEVOXの音声をYouTubeが聞き取り直すことになる。選手名や球団名は
    確実に崩れる。こちらは元の文字を持っているので、渡す方が正確。

必要な権限:
  youtube スコープ。captions.insert は400ユニット/本と重いので、
  1日に付けるのは日次の1本に絞る(4本付けても1,600で枠内だが、
  他の処理と合わせて余裕を残す)。

使い方:
  python3 scripts/captions.py --narration public/narration.json \
      --audio-dir build/audio --kind daily
"""

import argparse
import json
import os
import pathlib
import sys
import tempfile

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"

# 1行に収める文字数。縦型の画面で2行に折り返して読める幅。
LINE_CHARS = 20

# 1つの字幕を出しておく最短の秒数。短すぎると読む前に消える。
MIN_CUE = 1.2


def srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_text(text: str) -> list:
    """
    読点と句点で区切る。読み上げの息継ぎと同じ場所で切れるので、
    音と字幕のかたまりが揃う。
    """
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "。！？":
            out.append(cur.strip())
            cur = ""
        elif ch == "、" and len(cur) >= LINE_CHARS:
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return [x for x in out if x]


def wrap_line(text: str) -> str:
    """長い1文を2行に折る。1行に詰めると画面からはみ出す。"""
    if len(text) <= LINE_CHARS:
        return text
    mid = len(text) // 2
    # 読点があればそこで折る。無ければ中央で折る。
    for i in range(mid, min(len(text) - 1, mid + 8)):
        if text[i] in "、。 ":
            return text[:i + 1] + "\n" + text[i + 1:]
    return text[:mid] + "\n" + text[mid:]


def build_srt(narration: dict, manifest: list) -> str:
    """
    原稿と音声の実測長から字幕を組む。

    1セグメント=1画面ぶんの音声なので、その中の文を文字数で按分する。
    実際の発話位置とは厳密には一致しないが、画面が切り替わる境目では
    必ず合う。ずれても1画面の中に収まる。
    """
    dur = {m["index"]: float(m.get("duration") or 0) for m in manifest}
    cues, t = [], 0.0
    for i, seg in enumerate(narration.get("segments") or []):
        d = dur.get(i, 0.0)
        if d <= 0:
            continue
        parts = split_text(seg.get("text") or "")
        if not parts:
            t += d
            continue
        total_chars = sum(len(p) for p in parts)
        at = t
        for p in parts:
            share = d * (len(p) / total_chars) if total_chars else d
            end = at + max(MIN_CUE, share)
            cues.append((at, min(end, t + d), wrap_line(p)))
            at = end
            if at >= t + d:
                break
        t += d

    lines = []
    for n, (start, end, text) in enumerate(cues, 1):
        lines += [str(n), f"{srt_time(start)} --> {srt_time(end)}", text, ""]
    return "\n".join(lines)


def client():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    # scopes は渡さない(渡すと invalid_scope になる。他と同じ)
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def video_id_for(kind: str, day: str, record: str) -> str:
    try:
        rec = json.loads(pathlib.Path(record).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return ((rec.get(kind) or {}).get(day) or {}).get("video_id") or ""


def main() -> int:
    from datetime import datetime, timedelta, timezone

    ap = argparse.ArgumentParser()
    ap.add_argument("--narration", default="public/narration.json")
    ap.add_argument("--audio-dir", default="build/audio")
    ap.add_argument("--kind", default="daily")
    ap.add_argument("--record", default="data/published_videos.json")
    ap.add_argument("--date", help="既定は今日のJST")
    ap.add_argument("--out", help="SRTの書き出し先(指定すると投稿しない)")
    args = ap.parse_args()

    try:
        narration = json.loads(
            pathlib.Path(args.narration).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[info] 原稿を読めないため字幕は付けません: {e}")
        return 0
    mpath = pathlib.Path(args.audio_dir) / "manifest.json"
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))["segments"]
    except (json.JSONDecodeError, OSError, KeyError):
        print(f"[info] 音声manifestが無いため字幕は付けません: {mpath}")
        return 0

    srt = build_srt(narration, manifest)
    if not srt.strip():
        print("[info] 字幕にする本文がありません")
        return 0
    cues = srt.count(" --> ")
    print(f"[info] 字幕 {cues}件を組みました")

    if args.out:
        p = pathlib.Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(srt, encoding="utf-8")
        print(f"[info] 書き出しました -> {p}")
        return 0

    day = args.date or datetime.now(
        timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    vid = video_id_for(args.kind, day, args.record)
    if not vid:
        print(f"[info] {day} の {args.kind} が記録に無いため付けません")
        return 0

    yt = client()
    if yt is None:
        return 0

    # 既に付いていれば何もしない。二重に付けると選択肢が2つ並ぶ。
    try:
        have = yt.captions().list(part="snippet", videoId=vid).execute()
        for it in have.get("items", []):
            if (it["snippet"].get("language") == "ja"
                    and it["snippet"].get("name") == "コレスポ"):
                print(f"[info] {vid} には既に字幕が付いています")
                return 0
    except HttpError as e:
        print(f"[warn] 既存の字幕を確認できませんでした: {e}", file=sys.stderr)

    with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False,
                                     encoding="utf-8") as f:
        f.write(srt)
        tmp = f.name
    try:
        yt.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": vid, "language": "ja",
                              "name": "コレスポ", "isDraft": False}},
            media_body=MediaFileUpload(tmp, mimetype="text/plain"),
        ).execute()
        print(f"[info] {vid} に日本語字幕を付けました({cues}件)")
    except HttpError as e:
        print(f"[warn] 字幕を付けられませんでした: {e}", file=sys.stderr)
        return 0
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
