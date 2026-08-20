#!/usr/bin/env python3
"""
同じ検索語で、実際に誰が出てくるのかを測る。

推測でなく実測にする理由:
  「日本語のMLBショートは誰が強いか」を頭の中で並べても、
  それは自分の思い込みの順位でしかない。視聴者が打つであろう
  言葉で検索して、上位に出た順に数字を取る。出てきた顔ぶれが
  想像と違うなら、想像のほうが間違っている。

取るもの:
  ・検索語ごとの上位チャンネル(誰が実際に出てくるか)
  ・そのチャンネルの登録者数・総再生数・投稿本数
  ・直近の投稿間隔(どれくらいの頻度で出しているか)
  ・直近の動画の再生数の中央値(平均ではない。1本の当たりで歪むので)
  ・尺の分布(ショート主体か、長尺も出しているか)

使う単位:
  search.list      100 × 検索語の数
  channels.list      1 × 1回(50件まとめて)
  playlistItems      1 × チャンネル数
  videos.list        1 × チャンネル数
  検索語5つで約 520。日次の残りで十分収まる。

使い方:
  YOUTUBE_API_KEY=... python3 scripts/competitors.py
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"

# 視聴者が実際に打ちそうな言葉。自分の動画のタイトルに寄せない。
QUERIES = [
    "MLB 日本人選手",
    "大谷翔平 ハイライト",
    "メジャーリーグ 速報",
    "MLB まとめ",
    "海外サッカー ハイライト 日本語",
]

MINE = "コレスポ"


def get(path, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = API + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def iso_seconds(s):
    m = re.match(r"PT(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def discover(queries, per_query):
    """検索語ごとに、上位に出たチャンネルを順に拾う。"""
    rank = collections.defaultdict(list)      # channel_id -> [(語, 順位)]
    title = {}
    for q in queries:
        try:
            res = get("search", part="snippet", q=q, type="video",
                      maxResults=per_query, relevanceLanguage="ja",
                      regionCode="JP", order="relevance")
        except Exception as e:
            print("  検索できず %s: %s" % (q, str(e)[:100]))
            continue
        for i, it in enumerate(res.get("items", []), 1):
            sn = it.get("snippet", {})
            cid = sn.get("channelId")
            if not cid:
                continue
            title.setdefault(cid, sn.get("channelTitle", ""))
            rank[cid].append((q, i))
    return rank, title


def measure(cids):
    """チャンネルの数字と、直近の出し方を取る。"""
    out = {}
    for i in range(0, len(cids), 50):
        chunk = cids[i:i + 50]
        res = get("channels", part="snippet,statistics,contentDetails",
                  id=",".join(chunk), maxResults=50)
        for c in res.get("items", []):
            st = c.get("statistics", {})
            out[c["id"]] = {
                "name": c["snippet"]["title"],
                "subs": int(st.get("subscriberCount") or 0),
                "views": int(st.get("viewCount") or 0),
                "videos": int(st.get("videoCount") or 0),
                "uploads": (c.get("contentDetails", {})
                            .get("relatedPlaylists", {}).get("uploads")),
            }
    return out


def recent(uploads_playlist, want=25):
    """直近の投稿。間隔と、尺と、再生数の中央値を見る。"""
    try:
        res = get("playlistItems", part="contentDetails",
                  playlistId=uploads_playlist, maxResults=want)
    except Exception:
        return None
    ids = [it["contentDetails"]["videoId"] for it in res.get("items", [])]
    if not ids:
        return None
    try:
        vres = get("videos", part="statistics,contentDetails,snippet",
                   id=",".join(ids), maxResults=50)
    except Exception:
        return None

    views, secs, days = [], [], []
    now = dt.datetime.now(dt.timezone.utc)
    for v in vres.get("items", []):
        views.append(int(v.get("statistics", {}).get("viewCount") or 0))
        secs.append(iso_seconds(v.get("contentDetails", {}).get("duration")))
        pub = v.get("snippet", {}).get("publishedAt")
        if pub:
            days.append((now - dt.datetime.fromisoformat(
                pub.replace("Z", "+00:00"))).total_seconds() / 86400)
    if not views:
        return None

    days.sort()
    span = (days[-1] - days[0]) if len(days) > 1 else 0
    shorts = sum(1 for s in secs if 0 < s <= 60)
    return {
        "n": len(views),
        "median_views": int(statistics.median(views)),
        "per_day": round((len(days) - 1) / span, 2) if span > 0 else None,
        "shorts_share": round(shorts / len(secs), 2) if secs else 0,
        "median_sec": int(statistics.median(secs)) if secs else 0,
        "newest_days_ago": round(days[0], 1) if days else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=25)
    ap.add_argument("--top", type=int, default=12,
                    help="測るチャンネル数。多いほど単位を使う")
    ap.add_argument("--out", default="data/competitors.json")
    args = ap.parse_args()

    if not os.environ.get("YOUTUBE_API_KEY"):
        print("YOUTUBE_API_KEY がありません")
        return 1

    print("=== 検索語ごとに、誰が出てくるか ===")
    rank, titles = discover(QUERIES, args.per_query)
    if not rank:
        print("何も取れませんでした")
        return 1

    # 何語で出てきたか、そのうち何番目だったか。
    # 複数の語で上位に出るチャンネルほど、その分野の面を取っている。
    def strength(cid):
        hits = rank[cid]
        return (len({q for q, _ in hits}), -min(r for _, r in hits))

    order = sorted(rank, key=strength, reverse=True)[:args.top]
    stats = measure(order)

    rows = []
    for cid in order:
        s = stats.get(cid)
        if not s:
            continue
        s["id"] = cid
        s["queries"] = sorted({q for q, _ in rank[cid]})
        s["best_rank"] = min(r for _, r in rank[cid])
        s["recent"] = recent(s.pop("uploads")) if s.get("uploads") else None
        s["mine"] = MINE in s["name"]
        rows.append(s)

    print()
    print("%-28s %9s %10s %7s %8s %7s %6s"
          % ("チャンネル", "登録者", "総再生", "本数", "直近中央", "本/日", "短尺"))
    for r in rows:
        rc = r.get("recent") or {}
        print("%-28s %9s %10s %7s %8s %7s %5s%%"
              % (r["name"][:26],
                 f"{r['subs']:,}", f"{r['views']:,}", f"{r['videos']:,}",
                 f"{rc.get('median_views', 0):,}",
                 rc.get("per_day") if rc.get("per_day") is not None else "-",
                 int((rc.get("shorts_share") or 0) * 100)))

    print("\n=== 検索語ごとの上位3 ===")
    for q in QUERIES:
        top = sorted(((min(r for qq, r in rank[c] if qq == q), c)
                      for c in rank if any(qq == q for qq, _ in rank[c])))[:3]
        print("  %-24s %s" % (q, " / ".join(
            titles.get(c, c)[:18] for _, c in top) or "(なし)"))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"queries": QUERIES, "channels": rows},
                  f, ensure_ascii=False, indent=2)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## 同じ検索語で出てくる相手\n\n")
            f.write("|チャンネル|登録者|総再生|本数|直近の中央値|本/日|短尺|出た語|\n")
            f.write("|---|--:|--:|--:|--:|--:|--:|---|\n")
            for r in rows:
                rc = r.get("recent") or {}
                mark = " ←自分" if r["mine"] else ""
                f.write("|%s%s|%s|%s|%s|%s|%s|%d%%|%s|\n" % (
                    r["name"], mark, f"{r['subs']:,}", f"{r['views']:,}",
                    f"{r['videos']:,}", f"{rc.get('median_views', 0):,}",
                    rc.get("per_day") if rc.get("per_day") is not None else "-",
                    int((rc.get("shorts_share") or 0) * 100),
                    "、".join(r["queries"])))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
