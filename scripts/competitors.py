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
import pathlib
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

    views, secs, days, times, titles = [], [], [], [], []
    now = dt.datetime.now(dt.timezone.utc)
    for v in vres.get("items", []):
        views.append(int(v.get("statistics", {}).get("viewCount") or 0))
        secs.append(iso_seconds(v.get("contentDetails", {}).get("duration")))
        pub = v.get("snippet", {}).get("publishedAt")
        titles.append(v.get("snippet", {}).get("title") or "")
        if pub:
            t = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
            times.append(t)
            days.append((now - t).total_seconds() / 86400)
    if not views:
        return None

    # 直近25本の中央値は、投稿頻度が違う相手同士では比べられない。
    #
    # 月に1本の相手の「直近25本」は2年分で、1日8本の相手の
    # 「直近25本」は3日分になる。前者は貯める時間が桁違いに長い。
    # 1回目の測定でこれに気づかず、頻度の低いチャンネルが強く見えた。
    #
    # なので1日あたりの再生に直したものと、同じ窓(30日)に出た分だけの
    # 中央値も一緒に出す。比べてよいのはこちら。
    per_video_day = [v / max(1.0, d) for v, d in zip(views, days)]
    fresh = [v for v, d in zip(views, days) if d <= 30]

    order = sorted(range(len(days)), key=lambda i: days[i])
    span = (max(days) - min(days)) if len(days) > 1 else 0
    shorts = sum(1 for s in secs if 0 < s <= 60)
    return {
        "n": len(views),
        "median_views": int(statistics.median(views)),
        "median_views_per_day": round(statistics.median(per_video_day), 1),
        "median_views_30d": (int(statistics.median(fresh))
                             if fresh else None),
        "n_30d": len(fresh),
        "span_days": round(span, 1),
        "per_day": round((len(days) - 1) / span, 2) if span > 0 else None,
        "shorts_share": round(shorts / len(secs), 2) if secs else 0,
        "median_sec": int(statistics.median(secs)) if secs else 0,
        "newest_days_ago": round(min(days), 1) if days else None,
        # RSSが塞がれていても癖は測れる。APIが公開時刻を返している。
        "times": [times[i] for i in order if i < len(times)],
        "titles": [titles[i] for i in order if i < len(titles)],
    }


def rss(channel_id):
    """チャンネルのRSS。直近15本の公開時刻とタイトル。

    使えるときは使う。ただしランナー(データセンターのIP)からは
    404が返ることがあり、実際1回目の測定では全チャンネルで空になった。
    取れなければ空を返して、呼ぶ側がAPIで取った分で代用する。
    """
    url = ("https://www.youtube.com/feeds/videos.xml?channel_id="
           + channel_id)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (collespo)"})
    try:
        x = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception:
        return [], []
    pub = re.findall("<published>(.*?)</published>", x)
    tit = re.findall("<media:title>(.*?)</media:title>", x)
    out = []
    for p in pub:
        try:
            out.append(dt.datetime.fromisoformat(p))
        except ValueError:
            pass
    return out, tit


def automation(times, titles):
    """自動投稿の仕掛けがあるか。決めつけずに、根拠になる数字を並べる。

    見ているもの:
      秒のばらつき
        予約公開はその分の00秒ちょうどに出る。手で上げると、
        変換が終わった時刻——つまり任意の秒——になる。
      投稿間隔のばらつき
        毎日同じ時刻に出しているなら、間隔は24時間に張り付く。
      タイトルの型
        差し込みで作っていれば、先頭の言い回しの種類が本数より
        ずっと少なくなる。

    これは推定であって証明ではない。予約公開を手で毎日入れている人も
    いるし、型のあるタイトルを手書きする人もいる。数字を出して、
    読む側が判断できるようにする。
    """
    if len(times) < 4:
        return {}
    times = sorted(times)
    secs = [t.second for t in times]
    gaps = [(times[i + 1] - times[i]).total_seconds() / 3600
            for i in range(len(times) - 1)]
    heads = {t.split("｜")[0][:12] for t in titles} if titles else set()

    on_the_minute = sum(1 for s in secs if s == 0) / len(secs)
    return {
        "n": len(times),
        "sec_spread": round(statistics.pstdev(secs), 1),
        "on_the_minute": round(on_the_minute, 2),
        "gap_hours_median": round(statistics.median(gaps), 1) if gaps else None,
        "gap_spread": round(statistics.pstdev(gaps), 1) if len(gaps) > 1 else None,
        "title_shapes": (round(len(heads) / len(titles), 2)
                         if titles else None),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=25)
    ap.add_argument("--top", type=int, default=12,
                    help="測るチャンネル数。多いほど単位を使う")
    ap.add_argument("--out", default="data/competitors.json")
    ap.add_argument("--stamp", default="",
                    help="この回の名前。既定は日時(ランナーが渡す)")
    args = ap.parse_args()

    if not args.stamp:
        args.stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M")

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

        # 「同じことをやっているのか」は登録者数では分からない。
        # 出し方の癖を見る。RSSが取れればそちら(15本)、
        # 塞がれていればAPIで取った分(25本)で測る。
        rt, rti = rss(cid)
        if len(rt) < 4 and s.get("recent"):
            rt = s["recent"].get("times") or []
            rti = s["recent"].get("titles") or []
        s["auto"] = automation(rt, rti)
        if s.get("recent"):
            s["recent"].pop("times", None)
            s["recent"].pop("titles", None)
        rows.append(s)

    print()
    print("  「直近中央」は投稿頻度が違う相手同士では比べられない。")
    print("  月1本の相手の直近25本は2年分、1日8本の相手は3日分になる。")
    print("  比べてよいのは「30日中央(本数)」と「再生/日」のほう。")
    print()
    print("%-24s %8s %8s %10s %6s %6s %5s"
          % ("チャンネル", "登録者", "直近中央", "30日中央(本)",
             "再生/日", "本/日", "短尺"))
    for r in rows:
        rc = r.get("recent") or {}
        m30 = rc.get("median_views_30d")
        print("%-24s %8s %8s %7s(%2s) %6s %6s %4s%%"
              % (r["name"][:22], f"{r['subs']:,}",
                 f"{rc.get('median_views', 0):,}",
                 f"{m30:,}" if m30 is not None else "-",
                 rc.get("n_30d", 0),
                 rc.get("median_views_per_day", "-"),
                 rc.get("per_day") if rc.get("per_day") is not None else "-",
                 int((rc.get("shorts_share") or 0) * 100)))

    print()
    print("=== 出し方の癖 ===")
    print("  秒ばらつきが0に近く、00秒率が1に近く、間隔が24hに張り付き、")
    print("  型の数/本 が小さいほど、差し込みで作って予約公開している。")
    print()
    print("%-26s %4s %8s %7s %8s %8s"
          % ("チャンネル", "本", "秒ばらつき", "00秒率", "間隔中央", "型/本"))
    for r in rows:
        a = r.get("auto") or {}
        if not a:
            continue
        print("%-26s %4s %7s秒 %7s %7sh %8s"
              % (r["name"][:24], a["n"], a["sec_spread"],
                 a["on_the_minute"], a["gap_hours_median"],
                 a["title_shapes"]))

    print("\n=== 検索語ごとの上位3 ===")
    for q in QUERIES:
        top = sorted(((min(r for qq, r in rank[c] if qq == q), c)
                      for c in rank if any(qq == q for qq, _ in rank[c])))[:3]
        print("  %-24s %s" % (q, " / ".join(
            titles.get(c, c)[:18] for _, c in top) or "(なし)"))

    # 過去の回を残して、動いた分を出す。
    #
    # 1回目と2回目で顔ぶれが3分の1入れ替わり、SPOTVNOWの中央値は
    # 32,837から11,992になった。同じ日の同じ検索語で、である。
    # 検索の順位はその程度に動くものなので、1回の結果を測定だと
    # 思ってはいけない。並べて初めて、どれが動かない事実か分かる。
    prev = {}
    try:
        store = json.loads(pathlib.Path(args.out).read_text(encoding="utf-8"))
        runs = store.get("runs") or {}
        if runs:
            prev = {c["name"]: c for c in runs[sorted(runs)[-1]]["channels"]}
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        store, runs = {}, {}

    if prev:
        print("\n=== 前回から動いた分 ===")
        now_names = {r["name"] for r in rows}
        for r in rows:
            p = prev.get(r["name"])
            if not p:
                print("  新しく出てきた: %s" % r["name"])
                continue
            a = (r.get("recent") or {}).get("median_views") or 0
            b = (p.get("recent") or {}).get("median_views") or 0
            if b and abs(a - b) / b > 0.2:
                print("  %-24s 直近中央 %s → %s (%+d%%)"
                      % (r["name"][:22], f"{b:,}", f"{a:,}",
                         round((a - b) / b * 100)))
        for name in prev:
            if name not in now_names:
                print("  消えた: %s" % name)

    runs[args.stamp] = {"queries": QUERIES, "channels": rows}
    for old in sorted(runs)[:-10]:
        del runs[old]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"runs": runs}, f, ensure_ascii=False, indent=2)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## 同じ検索語で出てくる相手\n\n")
            f.write("**「直近の中央値」は頻度の違う相手同士では比べられない**"
                    "——月1本の相手の直近25本は2年分、1日8本の相手は3日分で、"
                    "貯める時間が桁違いになる。比べてよいのは"
                    "「30日中央」と「再生/日」。\n\n")
            f.write("|チャンネル|登録者|直近中央|30日中央|30日の本数|"
                    "再生/日|本/日|短尺|出た語|\n")
            f.write("|---|--:|--:|--:|--:|--:|--:|--:|---|\n")
            for r in rows:
                rc = r.get("recent") or {}
                m30 = rc.get("median_views_30d")
                mark = " ←自分" if r["mine"] else ""
                f.write("|%s%s|%s|%s|%s|%s|%s|%s|%d%%|%s|\n" % (
                    r["name"], mark, f"{r['subs']:,}",
                    f"{rc.get('median_views', 0):,}",
                    f"{m30:,}" if m30 is not None else "-",
                    rc.get("n_30d", 0),
                    rc.get("median_views_per_day", "-"),
                    rc.get("per_day") if rc.get("per_day") is not None else "-",
                    int((rc.get("shorts_share") or 0) * 100),
                    "、".join(r["queries"])))

            f.write("\n### 出し方の癖\n\n")
            f.write("秒のばらつきが0に近く、00秒率が1に近く、間隔が24hに"
                    "張り付き、型の数が小さいほど、差し込みで作って予約公開"
                    "している。推定であって証明ではない。\n\n")
            f.write("|チャンネル|本|秒ばらつき|00秒率|間隔中央|型の数/本|\n")
            f.write("|---|--:|--:|--:|--:|--:|\n")
            for r in rows:
                a = r.get("auto") or {}
                if not a:
                    continue
                f.write("|%s%s|%s|%s秒|%s|%sh|%s|\n" % (
                    r["name"], " ←自分" if r["mine"] else "", a["n"],
                    a["sec_spread"], a["on_the_minute"],
                    a["gap_hours_median"], a["title_shapes"]))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
