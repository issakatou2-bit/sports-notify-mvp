#!/usr/bin/env python3
"""
型ごとの週次レポート（公開後24時間・7日）を作る。

なぜ要るのか:
  分析ページで「PS の試合の話題が最強」「900〜1,000回で止まる回が多い」と
  分かったが、それを毎週同じものさしで見直す仕組みが無い。型（枠）ごとに、
  公開から同じ日数たったときの再生を並べれば、変えたことが効いたかを
  週ごとに比べられる。

材料（どれも読むだけ）:
  data/analytics.json        日ごとの保存。各日に直近28日の動画別の数字
                             （上位200本まで）
  data/published_videos.json 枠ごとの公開の記録（video_id・公開日時）
  data/published_assets.json 殿堂入り・試合の話題などの公開の記録

近似について（レポートにも書く）:
  analytics.json は日ごとの保存なので、「公開後24時間」「公開後7日」の
  ちょうどの値は無い。さらに YouTube の集計には数日の遅れがあり、保存日 D の
  数字には D の数日前までの再生しか入っていない（2026-09 の材料では、公開日の
  3日後の保存で初めて載る回が多い）。そこで、回が初めて載る保存日と公開日の差の
  中央値を「遅れ（日）」とみなし、保存日 − 遅れ を「その保存に入っている最後の日」
  とする。公開日（日本時間）から N 日たった日が入っている、いちばん早い保存の値を
  使う（N=1 を「24時間」、N=7 を「7日」と呼ぶ）。
  保存は上位200本までなので、載っていない回は「不明」にし、0 として数えない。

使い方:
  python3 weekly_report.py --data path/to/data --out docs/weekly/2026-10-05.md
  python3 weekly_report.py --data path/to/data --end 2026-10-05   # 週の終わりの日
  （--end を省くと、最新の保存日 − 遅れ ＝ 材料に入っている最後の日 で終わる週）
"""

import argparse
import json
import pathlib
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# published_videos.json の区分 → 型の名前。時刻は公開記録（日本時間）で多い時刻。
KIND_LABEL = {
    "morning": "17:00 成績",
    "morning_voices": "17:30 コメント",
    "morning_press": "18:00 報道",
    "morning_local": "18:00 報道",
    "daily": "19:00 予告",
    "morning_postseason": "20:00 情勢",
    "longform": "長編",
    "daily_soccer": "欧州サッカー",
    "soccer_race": "欧州サッカー",
    "morning_player": "選手",
    "weekly": "週のまとめ",
    "verdict": "週のまとめ",
}
# published_assets.json のキーの頭 → 型の名前
ASSET_PREFIX = [
    ("legend_", "殿堂入り"),
    ("season_game_", "試合の話題"),
    ("season_story_", "試合の話題"),
    ("season_player_", "試合の話題"),
]
ASSET_OTHER = "解説（常設）"

TYPE_ORDER = ["試合の話題", "17:00 成績", "17:30 コメント", "18:00 報道",
              "19:00 予告", "20:00 情勢", "殿堂入り", "長編", "欧州サッカー",
              "選手", "週のまとめ", ASSET_OTHER]

THRESHOLD = 1000  # 「1,000回を越えた本数」


def load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_time(s: str):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(JST)


def asset_label(key: str) -> str:
    for prefix, label in ASSET_PREFIX:
        if key.startswith(prefix):
            return label
    return ASSET_OTHER


def published_items(videos: dict, assets: dict) -> list:
    """公開した回の一覧。[{id, type, published(JST), title}]"""
    items, seen = [], set()
    for kind, by_day in (videos or {}).items():
        if not isinstance(by_day, dict):
            continue
        label = KIND_LABEL.get(kind, kind)
        for rec in by_day.values():
            if not isinstance(rec, dict) or not rec.get("video_id"):
                continue
            # 予約公開は publish_at が実際に出た時刻
            t = parse_time(rec.get("publish_at") or rec.get("published_at"))
            if t is None or rec["video_id"] in seen:
                continue
            seen.add(rec["video_id"])
            items.append({"id": rec["video_id"], "type": label,
                          "published": t, "title": rec.get("title", "")})
    for key, rec in ((assets or {}).get("assets") or {}).items():
        if not isinstance(rec, dict) or not rec.get("video_id"):
            continue
        if rec.get("privacy") not in (None, "public"):
            continue
        t = parse_time(rec.get("publish_at") or rec.get("published_at"))
        if t is None or rec["video_id"] in seen:
            continue
        seen.add(rec["video_id"])
        items.append({"id": rec["video_id"], "type": asset_label(key),
                      "published": t, "title": rec.get("title") or key})
    return items


def snapshots(analytics: dict) -> list:
    """[(保存日, 範囲の始め, {video_id: 行})] を日付順に。（遅れはまだ引かない）"""
    out = []
    for day, snap in sorted(((analytics or {}).get("days") or {}).items()):
        try:
            d = date.fromisoformat(day)
            start = date.fromisoformat((snap.get("range") or [day])[0])
        except ValueError:
            continue
        rows = {r.get("video"): r for r in snap.get("videos") or []
                if r.get("video")}
        out.append((d, start, rows))
    return out


def estimate_lag(items: list, snaps: list, default: int = 0) -> int:
    """回が初めて載る保存日と公開日の差の中央値（日）。"""
    gaps = []
    for it in items:
        pub = it["published"].date()
        for d, start, rows in snaps:
            if d >= pub and it["id"] in rows:
                gaps.append((d - pub).days)
                break
    return int(statistics.median(gaps)) if gaps else default


def shift(snaps: list, lag: int) -> list:
    """保存日を「入っている最後の日」にずらす。"""
    return [(d - timedelta(days=lag), start, rows) for d, start, rows in snaps]


def value_after(snaps: list, vid: str, pub_day: date, days: int):
    """公開日から days 日たった日以降で、いちばん早い保存の行。

    戻り値: (行 or None, 使った保存日 or None)。
    保存の範囲が公開日より後から始まる保存は使わない（公開直後の再生が
    範囲の外になり、少なく出るため）。
    """
    target = pub_day + timedelta(days=days)
    for d, start, rows in snaps:
        if d < target or start > pub_day:
            continue
        return rows.get(vid), d
    return None, None


def latest_value(snaps: list, vid: str, pub_day: date):
    for d, start, rows in reversed(snaps):
        if start <= pub_day:
            return rows.get(vid), d
    return None, None


def median(xs):
    return statistics.median(xs) if xs else None


def summarize(items: list, snaps: list, week_end: date) -> dict:
    """週（week_end を含む7日）に公開した回を、型ごとにまとめる。"""
    week_start = week_end - timedelta(days=6)
    groups = {}
    for it in items:
        pub_day = it["published"].date()
        if not (week_start <= pub_day <= week_end):
            continue
        r1, d1 = value_after(snaps, it["id"], pub_day, 1)
        r7, d7 = value_after(snaps, it["id"], pub_day, 7)
        rl, dl = latest_value(snaps, it["id"], pub_day)
        g = groups.setdefault(it["type"], [])
        g.append({**it, "v1": r1.get("views") if r1 else None, "d1": d1,
                  "v7": r7.get("views") if r7 else None, "d7": d7,
                  "vl": rl.get("views") if rl else None, "dl": dl,
                  "pct": rl.get("averageViewPercentage") if rl else None,
                  "subs": rl.get("subscribersGained") if rl else None})
    out = {}
    for t, rows in groups.items():
        v1 = [r["v1"] for r in rows if r["v1"] is not None]
        v7 = [r["v7"] for r in rows if r["v7"] is not None]
        vl = [r["vl"] for r in rows if r["vl"] is not None]
        pct = [r["pct"] for r in rows if r["pct"] is not None]
        subs = [r["subs"] for r in rows if r["subs"] is not None]
        out[t] = {
            "n": len(rows),
            "n1": len(v1), "med1": median(v1),
            "n7": len(v7), "med7": median(v7),
            "nl": len(vl), "medl": median(vl), "max": max(vl) if vl else None,
            "pct": round(statistics.mean(pct), 1) if pct else None,
            "subs": sum(subs) if subs else None,
            "over": sum(1 for x in vl if x >= THRESHOLD),
            "rows": sorted(rows, key=lambda r: r["published"]),
        }
    return out


def fmt(x, digits=0):
    if x is None:
        return "—"
    if isinstance(x, float) and digits:
        return f"{x:.{digits}f}"
    return f"{round(x):,}"


def diff(a, b):
    if a is None or b is None:
        return "—"
    d = round(a - b)
    return f"{d:+,}"


def type_key(t):
    return (TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER), t)


def render(this: dict, prev: dict, week_end: date, latest: date, lag: int = 0, older=None) -> str:
    ws = week_end - timedelta(days=6)
    lines = [
        f"# 型ごとの週次レポート（{ws.isoformat()}〜{week_end.isoformat()} に公開した回）",
        "",
        f"材料：`data/analytics.json`（最新の保存 {latest.isoformat() if latest else 'なし'}）、"
        "`data/published_videos.json`、`data/published_assets.json`。",
        "",
        f"**近似の注意**：保存は日ごとで、YouTube の集計には遅れがあります（この材料では約{lag}日。"
        "回が初めて保存に載る日と公開日の差の中央値）。「24時間」は公開日の翌日までが入った"
        "いちばん早い保存、「7日」は公開日の7日後までが入ったいちばん早い保存の再生回数です。"
        "公開の時刻によっては、実際の24時間より長め・短めになります。保存は上位200本までなので、"
        "載っていない回は「—」（不明）で、0 としては数えていません。「最新」は最新の保存の値です。",
        "",
        "| 型 | 本数 | 24時間 中央値 | 7日 中央値 | 最新 中央値 | 最新 最高 | 平均視聴率 | 登録 | 1,000回越え | 前週比（24時間 中央値） |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in sorted(set(this) | set(prev), key=type_key):
        s = this.get(t)
        p = prev.get(t) or {}
        if not s:
            lines.append(f"| {t} | 0 | — | — | — | — | — | — | — | （前週 {p.get('n', 0)} 本） |")
            continue
        med7 = fmt(s["med7"]) + (f"（{s['n7']}本）" if s["n7"] < s["n"] else "")
        lines.append(
            f"| {t} | {s['n']} | {fmt(s['med1'])} | {med7} | {fmt(s['medl'])} | {fmt(s['max'])} | "
            f"{fmt(s['pct'], 1) + '%' if s['pct'] is not None else '—'} | {fmt(s['subs'])} | "
            f"{s['over']} | {diff(s['med1'], p.get('med1'))} |")
    if older is not None:
        # 月曜実行では対象週が「前週」。その一つ前が「2週前」。
        old_end=week_end-timedelta(days=7);old_start=old_end-timedelta(days=6)
        lines += ['',f'## 2週前に公開した回の7日の値（{old_start}〜{old_end}）','',
                  '| 型 | 公開本数 | 7日を観測した本数 | 7日 中央値 |','|---|---|---|---|']
        for t in sorted(older,key=type_key):
            s=older[t];lines.append(f"| {t} | {s['n']} | {s['n7']} | {fmt(s['med7'])} |")
        if not older:lines.append('対象の公開記録がありません。')
    lines += ["", "「7日 中央値」の（N本）は、まだ7日たっていない回を除いた本数です。"
              "「最新」は公開からの日数が回ごとにちがうので、24時間・7日とそのままは比べられません。", "",
              "## 回ごとの数字", ""]
    for t in sorted(this, key=type_key):
        lines += [f"### {t}", "", "| 公開（日本時間） | 題 | 24時間 | 7日 | 最新 |", "|---|---|---|---|---|"]
        for r in this[t]["rows"]:
            title = re.sub(r"\s*#Shorts\s*$", "", r["title"])[:50].replace("|", "｜")
            lines.append(f"| {r['published'].strftime('%m/%d %H:%M')} | {title} | "
                         f"{fmt(r['v1'])} | {fmt(r['v7'])} | {fmt(r['vl'])} |")
        lines.append("")
    return "\n".join(lines)


def build(data_dir: pathlib.Path, week_end: date = None, lag: int = None) -> str:
    analytics = load(data_dir / "analytics.json")
    raw = snapshots(analytics)
    items = published_items(load(data_dir / "published_videos.json"),
                            load(data_dir / "published_assets.json"))
    lag = estimate_lag(items, raw) if lag is None else lag
    snaps = shift(raw, lag)
    latest = raw[-1][0] if raw else None
    if week_end is None:
        # 既定は「材料に入っている最後の日」で終わる週
        week_end = (latest - timedelta(days=lag)) if latest else date.today()
    this = summarize(items, snaps, week_end)
    prev = summarize(items, snaps, week_end - timedelta(days=7))
    older=prev
    return render(this, prev, week_end, latest, lag, older)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--end", help="週の終わりの日（YYYY-MM-DD）。省くと最新の保存日")
    ap.add_argument("--out", help="書き出す先（省くと画面に出す）")
    ap.add_argument("--lag", type=int, help="集計の遅れ（日）。省くと材料から推定")
    a = ap.parse_args(argv)
    end = date.fromisoformat(a.end) if a.end else None
    md = build(pathlib.Path(a.data), end, a.lag)
    if a.out:
        p = pathlib.Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md + "\n", encoding="utf-8")
        print(f"書きました: {p}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
