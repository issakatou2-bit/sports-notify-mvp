#!/usr/bin/env python3
"""
出したばかりの動画が、どれだけ回りだしたかを見る。

なぜ別に作るのか:
  維持率や視聴時間は YouTube Analytics API から取っているが、そちらは
  OAuth のトークンが要る。実際そのトークンが効かなくなって、数字が
  8/19で止まった。止まっている間、判断のもとが何も無くなる。

  再生数だけなら videos.list で取れる。こちらは APIキー1本で動き、
  50本まとめて1ユニットしか使わない。維持率は分からないが、
  「配られたのか、配られていないのか」はこれで分かる。
  そして今いちばん知りたいのはそこ。

  実測では、公開から3日以内に伸びるものは伸び、伸びないものは
  そのまま0のまま終わる。初動を見れば当日のうちに判断できる。

見るもの:
  ・その日ごとの本数と再生数
  ・枠ごとの中央値(同じ枠の日ごとのばらつき)
  ・「ほとんど配られていない」本数(10回未満)

使い方:
  YOUTUBE_API_KEY=... python3 scripts/early_views.py --days 7
"""

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import statistics
import sys
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"

# 記録の区分から、見やすい名前へ
def _labels() -> dict:
    """区分ごとの見出し。時刻は post_common が持っているものを使う。"""
    import sys as _s
    import pathlib as _p
    _s.path.insert(0, str(_p.Path(__file__).resolve().parent))
    import post_common
    out = {k: f"{at} {name}" for k, name, _, at in post_common.DAILY_LINEUP}
    out.update({"weekly": "週間", "asset": "資産動画",
                "morning_local": "(畳んだ枠) 現地の注目"})
    return out


KIND_LABEL = _labels()

# これ未満なら「ほとんど配られていない」とみなす。
# 実測で、フィードに乗った動画は初日から数十回は付く。
BARELY = 10


def get(path, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = API + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect(days: int) -> list:
    """直近 days 日に出した動画。(日付, 区分, 動画ID, 題)"""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = []
    for kind, rec in (load("data/published_videos.json") or {}).items():
        if not isinstance(rec, dict):
            continue
        for date, v in rec.items():
            if isinstance(v, dict) and v.get("video_id") and date >= cutoff:
                out.append((date, kind, v["video_id"], v.get("title", "")))

    # 資産動画は別の記録に入っている。日付は公開時刻から取る。
    for topic, v in (load("data/published_assets.json").get("assets")
                     or {}).items():
        if not isinstance(v, dict) or not v.get("video_id"):
            continue
        date = (v.get("published_at") or "")[:10]
        if date >= cutoff:
            out.append((date, "asset", v["video_id"], topic))
    return sorted(out)


def stats_for(ids: list) -> dict:
    """動画IDごとの再生数といいね。50本ずつまとめて引く。"""
    out = {}
    for i in range(0, len(ids), 50):
        try:
            res = get("videos", part="statistics",
                      id=",".join(ids[i:i + 50]), maxResults=50)
        except Exception as e:                       # noqa: BLE001
            print("[warn] 取れません: %s" % str(e)[:120])
            continue
        for it in res.get("items", []):
            st = it.get("statistics") or {}
            out[it["id"]] = {
                "views": int(st.get("viewCount") or 0),
                "likes": int(st.get("likeCount") or 0),
            }
    return out


def _same_age(store, rows, got, today):
    """前の回と、公開からの経過日数を揃えて中央値を比べる。

    前の回そのものではなく「そのとき何日目だったか」で揃える。
    暦の日で比べると、当日の夜と翌朝を突き合わせることになる。
    実際そこで20倍の差が出るので、揃えないと比べたことにならない。
    """
    runs = (store or {}).get("runs") or {}
    if not runs:
        return {}
    when = sorted(runs)[-1]
    last = runs[when]
    try:
        w = dt.datetime.strptime(when, "%Y-%m-%dT%H%M").replace(
            tzinfo=dt.timezone.utc).astimezone(
            dt.timezone(dt.timedelta(hours=9)))
    except ValueError:
        return {}
    label, was_day = w.strftime("%m/%d %H:%M"), w.date()

    def by_age(videos, base):
        out = collections.defaultdict(list)
        for v in videos:
            try:
                age = (base - dt.date.fromisoformat(v["date"])).days
            except (ValueError, KeyError, TypeError):
                continue
            out[age].append(v.get("views", 0))
        return out

    now_by = by_age([{"date": d, "views": got.get(v, {}).get("views", 0)}
                     for d, _, v, _ in rows], today)
    was_by = by_age(last.get("videos") or [], was_day)
    out = {}
    for age in sorted(set(now_by) & set(was_by)):
        if age > 3:
            continue      # 4日目以降はもう動かない
        out[age] = (statistics.median(now_by[age]),
                    statistics.median(was_by[age]), label)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="data/early_views.json")
    args = ap.parse_args()

    if not os.environ.get("YOUTUBE_API_KEY"):
        print("YOUTUBE_API_KEY がありません")
        return 1

    rows = collect(args.days)
    if not rows:
        print("直近%d日に出した動画がありません" % args.days)
        return 0
    got = stats_for([r[2] for r in rows])
    today = dt.date.today()

    print("=== 日ごと ===")
    by_date = collections.defaultdict(list)
    for date, kind, vid, title in rows:
        by_date[date].append((kind, vid, title))
    for date in sorted(by_date):
        vs = [got.get(v, {}).get("views", 0) for _, v, _ in by_date[date]]
        age = (today - dt.date.fromisoformat(date)).days
        print("  %s (%d日前) %2d本  合計%6d  中央%5.0f  10回未満%d本"
              % (date, age, len(vs), sum(vs),
                 statistics.median(vs) if vs else 0,
                 sum(1 for v in vs if v < BARELY)))

    print("\n=== 枠ごと(直近%d日) ===" % args.days)
    by_kind = collections.defaultdict(list)
    for date, kind, vid, title in rows:
        by_kind[kind].append(got.get(vid, {}).get("views", 0))
    for kind, vs in sorted(by_kind.items(),
                           key=lambda kv: -statistics.median(kv[1] or [0])):
        print("  %-18s %2d本  中央%6.0f  最大%6d  最小%5d"
              % (KIND_LABEL.get(kind, kind), len(vs),
                 statistics.median(vs), max(vs), min(vs)))

    # 同じ「公開からの経過日数」どうしで比べる。
    #
    # 公開当日の夜に見ると中央値が一桁になり、翌朝には178まで伸びる。
    # 同じ7本を、測った時刻が違うだけで20倍違って見える。
    # 「今日は初動が悪い」かどうかは、前の回の同じ経過日数と
    # 突き合わせないと言えない。
    prev = _same_age(load(args.out), rows, got, today)
    if prev:
        print("\n=== 前の回と、同じ経過日数どうしで ===")
        for age, (now_med, was_med, when) in sorted(prev.items()):
            mark = "→" if now_med == was_med else (
                "↑" if now_med > was_med else "↓")
            print("  公開から%d日: 中央 %6.0f  (%s は %6.0f) %s"
                  % (age, now_med, when, was_med, mark))

    print("\n=== ほとんど配られていない動画 ===")
    barely = [(d, k, t, got.get(v, {}).get("views", 0))
              for d, k, v, t in rows
              if got.get(v, {}).get("views", 0) < BARELY]
    if barely:
        for d, k, t, n in sorted(barely)[:12]:
            print("  %s %2d回  %-16s %s" % (d, n, KIND_LABEL.get(k, k),
                                            t[:44]))
        print("  計 %d本 / %d本" % (len(barely), len(rows)))
    else:
        print("  なし")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M")
    store = load(args.out)
    store.setdefault("runs", {})[stamp] = {
        "videos": [{"date": d, "kind": k, "id": v, "title": t,
                    **got.get(v, {})} for d, k, v, t in rows]
    }
    for old in sorted(store["runs"])[:-30]:
        del store["runs"][old]
    pathlib.Path(args.out).write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## 初動(直近%d日)\n\n" % args.days)
            f.write("維持率はAnalyticsが要るので出せない。"
                    "ここで見るのは「配られたかどうか」。\n\n")
            f.write("|日|経過|本数|合計再生|中央値|10回未満|\n")
            f.write("|---|--:|--:|--:|--:|--:|\n")
            for date in sorted(by_date, reverse=True):
                vs = [got.get(v, {}).get("views", 0)
                      for _, v, _ in by_date[date]]
                age = (today - dt.date.fromisoformat(date)).days
                f.write("|%s|%d日|%d|%d|%.0f|%d|\n"
                        % (date, age, len(vs), sum(vs),
                           statistics.median(vs) if vs else 0,
                           sum(1 for v in vs if v < BARELY)))
            f.write("\n|枠|本数|中央値|最大|最小|\n|---|--:|--:|--:|--:|\n")
            for kind, vs in sorted(by_kind.items(),
                                   key=lambda kv: -statistics.median(kv[1])):
                f.write("|%s|%d|%.0f|%d|%d|\n"
                        % (KIND_LABEL.get(kind, kind), len(vs),
                           statistics.median(vs), max(vs), min(vs)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
