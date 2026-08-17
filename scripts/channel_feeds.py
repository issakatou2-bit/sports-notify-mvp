#!/usr/bin/env python3
"""
複数のチャンネルから、今日の動画とその反応を集める。

なぜ検索をやめたのか:
  これまでMLB公式のハイライトを YouTube の検索APIで探していた。
  検索は1回100ユニットで、1日の枠10,000のうち1%を1回で使う。
  しかも結果が読めない。「Game Highlights」で引いて、返ってきた中から
  チャンネル名が "MLB" のものだけを残す、という無駄な形になっていた。

  チャンネルを名指しすれば、RSSで同じことができる。0ユニット、鍵も不要。
  誰の場所を見にいくのかを、検索結果ではなくこちらが決められる。

  枠を使うのは、再生回数を引くとき(videos.list は50本で1ユニット)と、
  コメントを引くとき(commentThreads.list は1本1ユニット)だけになる。

何を集めるか:
  各チャンネルの直近の投稿から、その日の試合に関するものを選び、
  再生回数の多い順に並べる。コメントは local_voices.py が引く。

出力: data/channel_videos.json

使い方:
  python3 scripts/channel_feeds.py --out data/channel_videos.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import requests

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"

# 試合そのものを扱っている投稿だけを残す。
# チャンネルによって題の付け方が違うので、両方の言語で見る。
KEEP_PATTERNS = [
    r"highlights?", r"ハイライト", r"game", r"試合",
    r"vs\.?\s", r"×", r"全打席", r"好プレー", r"週間",
]

# 見出しだけの動画や、試合と関係のないものを外す。
SKIP_PATTERNS = [
    r"shorts?$", r"予告", r"cm", r"トレーラー", r"インタビュー全文",
]

# 何時間前までの投稿を見るか。
#
# 毎日投稿する公式ハイライトなら30時間で足りるが、チャンネルによって
# 頻度が違う。SPOTV NOWは週1本、球団公式は試合のある日だけ。
# 一律30時間にすると、その2つは毎日0件になる(実際そうなった)。
# 情報源ごとに指定できるようにして、既定だけ30にする。
LOOKBACK_HOURS = 30

# 1チャンネルから拾う上限。多すぎると、その日の話題が薄まる。
PER_CHANNEL = 6


def load_sources(path: str) -> list:
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] {path} を読めませんでした: {e}", file=sys.stderr)
        return []
    return d.get("channels") or []


def fetch_feed(channel_id: str, hours: int = LOOKBACK_HOURS) -> list:
    """
    そのチャンネルの直近の投稿。RSSなので枠を消費しない。

    APIの search を使うと1回100ユニットかかるが、ここは0。
    足すチャンネルを増やしても費用が増えない。
    """
    url = FEED.format(channel_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "collespo/1.0"})
        xml = urllib.request.urlopen(req, timeout=20).read().decode("utf-8",
                                                                   "replace")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {channel_id} のRSSを取れませんでした: {e}",
              file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", e)
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        pub = re.search(r"<published>(.*?)</published>", e)
        if not (vid and title and pub):
            continue
        try:
            when = datetime.fromisoformat(pub.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        out.append({"video_id": vid.group(1), "title": title.group(1),
                    "published_at": pub.group(1)})
    return out


def wanted(title: str) -> bool:
    low = title.lower()
    if any(re.search(p, low, re.I) for p in SKIP_PATTERNS):
        return False
    return any(re.search(p, low, re.I) for p in KEEP_PATTERNS)


def fetch_stats(api_key: str, video_ids: list) -> dict:
    """
    再生回数などをまとめて引く。50本で1ユニット。

    1本ずつ引くと本数ぶん枠を使う。まとめて渡せば、10チャンネルぶんでも
    1〜2ユニットで済む。
    """
    stats = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            r = requests.get(f"{YOUTUBE_API}/videos", params={
                "key": api_key, "part": "statistics,snippet",
                "id": ",".join(chunk)}, timeout=20)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 再生回数を取れませんでした: {e}", file=sys.stderr)
            continue
        for it in r.json().get("items", []):
            st = it.get("statistics") or {}
            stats[it["id"]] = {
                "views": int(st.get("viewCount") or 0),
                "likes": int(st.get("likeCount") or 0),
                "comments": int(st.get("commentCount") or 0),
            }
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="data/comment_sources.json")
    ap.add_argument("--out", default="data/channel_videos.json")
    ap.add_argument("--sport", default="mlb")
    args = ap.parse_args()

    channels = [c for c in load_sources(args.sources)
                if c.get("sport") == args.sport]
    if not channels:
        print(f"[info] {args.sport} の情報源が登録されていません")
        return 0

    rows = []
    for ch in channels:
        hours = int(ch.get("lookback_hours") or LOOKBACK_HOURS)
        items = [v for v in fetch_feed(ch["id"], hours) if wanted(v["title"])]
        items = items[:PER_CHANNEL]
        for v in items:
            v["channel"] = ch.get("label") or ch.get("name")
            v["lang"] = ch.get("lang", "en")
        rows.extend(items)
        print(f"[info] {ch.get('label')}: {len(items)}本 (直近{hours}時間)")

    if not rows:
        print("[info] 対象の動画がありませんでした")
        return 0

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        stats = fetch_stats(api_key, [r["video_id"] for r in rows])
        for r in rows:
            r.update(stats.get(r["video_id"], {}))
        # 反応の多い順。再生回数だけだと、公開直後のものが必ず下に来る。
        # コメント数を主にするのは、こちらが欲しいのが議論そのものだから。
        rows.sort(key=lambda r: (-(r.get("comments") or 0),
                                 -(r.get("views") or 0)))
    else:
        print("[info] YOUTUBE_API_KEY が無いため、再生回数は付けません")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sport": args.sport,
        "videos": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[info] 合計{len(rows)}本 -> {out}")
    for r in rows[:5]:
        c = r.get("comments")
        v = r.get("views")
        extra = f"  コメント{c}件 / {v:,}回" if c is not None else ""
        print(f"   [{r['channel']}] {r['title'][:48]}{extra}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
