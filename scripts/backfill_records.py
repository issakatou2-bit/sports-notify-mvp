#!/usr/bin/env python3
"""
チャンネルに出ている動画から、失われた投稿記録を作り直す。

なぜ要るのか:
  8/17と8/18の夕方の回は、6本すべて公開されているのに記録が1件も
  残らなかった。押し合いで rebase が拒まれ、記録だけが落ちていた。
  原因は直したが、既に落ちたぶんは戻らない。

  記録が無いと、その日のページから動画へ辿れず、健康診断も
  「実際に何本出たか」しか言えない。動画は実在するので、
  チャンネルの一覧から読み直して埋める。

  RSSなので鍵も割り当ても要らない。直近15本しか返らないので、
  埋められるのは数日ぶん。落ちてすぐ気付けば足りる。

使い方:
  python3 scripts/backfill_records.py            # 何が足りないかを見るだけ
  python3 scripts/backfill_records.py --write     # 記録に書く
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
RECORD = "data/published_videos.json"

# タイトルから区分を見分ける。
#
# 上から順に見て、最初に当たったものを採る。順番に意味がある:
# 「現地のファンは何と言ったか」と「現地メディアは何と言っているか」は
# よく似ているので、取り違えないよう長い方を先に置く。
PATTERNS = [
    ("weekly", r"MLBの1週間を振り返る"),
    ("daily_soccer", r"欧州サッカー"),
    ("daily", r"明日の注目試合|今夜の注目試合"),
    ("morning_press", r"現地メディアは何と言っている"),
    ("morning_voices", r"現地のファンは何と言った|コメント欄"),
    ("morning_local", r"現地で最も注目された試合"),
    ("morning_player", r"通算成績[・･]今季"),
    ("morning", r"勝利貢献スコア"),
]


def feed_entries() -> list:
    """チャンネルの直近の投稿。(公開日時JST, 動画ID, タイトル) の並び。"""
    req = urllib.request.Request(FEED, headers={"User-Agent": "collespo/1.0"})
    xml = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", e)
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        when = re.search(r"<published>(.*?)</published>", e)
        if not (vid and title and when):
            continue
        try:
            t = datetime.fromisoformat(when.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append((t.astimezone(JST), vid.group(1), title.group(1).strip()))
    out.sort()
    return out


def kind_of(title: str) -> str:
    for kind, pat in PATTERNS:
        if re.search(pat, title):
            return kind
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default=RECORD)
    ap.add_argument("--write", action="store_true",
                    help="実際に書き込む(既定は表示のみ)")
    args = ap.parse_args()

    p = pathlib.Path(args.record)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rec = {}

    added = []
    for when, vid, title in feed_entries():
        kind = kind_of(title)
        if not kind:
            print(f"(区分が分かりません) {title[:60]}")
            continue
        day = when.strftime("%Y-%m-%d")
        # 週次は日付ではなく回で1件なので、その日の記録として置く。
        if (rec.get(kind) or {}).get(day):
            continue
        rec.setdefault(kind, {})[day] = {
            "video_id": vid,
            "url": f"https://youtu.be/{vid}",
            "title": title,
            "published_at": when.astimezone(timezone.utc).isoformat(),
            # 予約公開の時刻は記録が無いと分からない。
            # 実際に公開された時刻をそのまま置く。嘘を書かない。
            "publish_at": when.astimezone(timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backfilled": True,
        }
        added.append((day, kind, vid, title))

    if not added:
        print("足りない記録はありません")
        return 0

    for day, kind, vid, title in added:
        print(f"{day}  {kind:16s} {vid}  {title[:52]}")
    print(f"\n{len(added)}件")

    if args.write:
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"書き込みました -> {p}")
    else:
        print("(--write を付けると記録に書きます)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
