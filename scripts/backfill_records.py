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
#
# 9/23に、公開済みの全タイトルを通して作り直した。8月の規則のままで、
# 長編11本を「コメント欄の回」（題に「MLB公式コメント欄を読み解く」が
# 入る）、順位争い3本を「欧州サッカーの日次」と取り違え、進出争い22本・
# 現地の報道33本は見分けられていなかった。**取り違えると、欠けた記録を
# 別の枠に書き込む。**具体的なものから先に置く。
PATTERNS = [
    ("longform", r"【海外の反応】|コメント欄を読み解く|成績と進出争い"),
    ("soccer_race", r"順位争い【欧州サッカー】"),
    ("daily_soccer", r"欧州サッカー|注目試合【サッカー】"),
    ("verdict", r"答え合わせ"),
    ("weekly", r"1週間を振り返る|今週の日本人選手"),
    ("morning_postseason", r"ポストシーズン進出争い"),
    ("morning_press", r"現地メディア|番記者の投稿|現地はこう報じた"),
    ("morning_voices", r"現地のファンは何と言った|コメント欄"),
    ("morning_local", r"現地で最も(?:注目された|見られた)試合|現地での注目度"
                      r"|再生回数ランキングと話題のチーム"),
    ("morning_player", r"通算成績[・･]"),
    ("morning", r"勝利貢献スコア|日本人選手の成績まとめ|の日本人選手 #Shorts"),
    ("daily", r"注目試合"),
]


def uploads_entries(days: int = 15) -> list:
    """RSSが取れない日の取り直し。形は feed_entries と同じ。"""
    import os
    key = os.environ.get("YOUTUBE_API_KEY") or ""
    if not key:
        return []
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import channel_feeds
    out = []
    for v in channel_feeds.fetch_uploads(key, CHANNEL_ID, hours=24 * days):
        try:
            t = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append((t.astimezone(JST), v["video_id"], v["title"]))
    out.sort()
    return out


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

    # **取れないことと、間違っていることは別。**
    # YouTube の一覧は GitHub の実行環境から 404 が返る日がある
    # （手元からは同じURLが200で返る）。台帳を埋める道具なので、
    # 取れない日は何もしないのが正しく、健康診断ごと赤にする理由はない。
    # ただし黙ると気づけないので、理由は必ず残す。
    try:
        entries = feed_entries()
    except Exception as e:                           # noqa: BLE001
        print(f"[warn] チャンネルのRSSを取れません（{e}）。")
        # 9/19から毎日404なので、鍵があればアップロード一覧で取り直す
        # （1回1ユニット。channel_feeds と同じ取り方）。
        entries = uploads_entries()
        if not entries:
            print("[warn] 今回は台帳を触りません。続けて落ちるようなら経路を疑う。")
            return 0
        print(f"[info] アップロード一覧から{len(entries)}本")

    added = []
    for when, vid, title in entries:
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
