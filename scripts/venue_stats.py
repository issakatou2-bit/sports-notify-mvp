"""
球場ごとの「実際に何点入っているか」を、その年の全試合から集計する。

なぜこれをやるのか:
  これまで球場の説明は「打者有利とされる」「本塁打が出にくい」といった、
  一般に言われていることの紹介に留まっていた。実際にどれだけ違うのかを
  数字で出せれば、同じ話がまったく別の説得力を持つ。

  実際に集計してみると、最も点が入る球場と最も入らない球場では
  1試合あたりの得点が2倍近く違う。これは体感で語られていたことの裏づけになる。

データの取り方:
  /schedule は日付範囲を指定すると、その期間の全試合の
  「球場名」と「両チームの最終スコア」をまとめて返す。
  1か月ぶんで約0.6MBなので、月単位に分けて取れば無理なく全期間を集計できる。
  試合ごとにboxscoreを引く必要は無い(それだと2000回以上の呼び出しになる)。

  本塁打数は/scheduleには含まれないため、ここでは扱わない。
  得点だけでも球場の性格は十分に表れる。

出力: data/venue_stats.json

使い方:
  python3 scripts/venue_stats.py --out data/venue_stats.json
"""

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# ランキングに載せる最低試合数。数試合しか行われていない球場
# (国際開催や臨時の球場)が上位に紛れ込むのを防ぐ。
MIN_GAMES = 20


def month_ranges(start: date, end: date):
    """月単位に区切る。1回のレスポンスを小さく保つため。"""
    cur = start
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        yield cur, min(nxt - timedelta(days=1), end)
        cur = nxt


def fetch_games(start: date, end: date) -> list:
    """期間内の確定した試合を [(球場名, 合計得点), ...] で返す"""
    out = []
    for s, e in month_ranges(start, end):
        try:
            resp = requests.get(
                f"{MLB_API_BASE}/schedule",
                params={"sportId": 1, "startDate": s.isoformat(),
                        "endDate": e.isoformat()},
                timeout=60,
            )
            resp.raise_for_status()
        except Exception as ex:
            print(f"[warn] {s}〜{e} の取得に失敗しました: {ex}", file=sys.stderr)
            continue

        n = 0
        for d in resp.json().get("dates", []):
            for g in d.get("games", []):
                # 中止・延期・進行中は集計に入れない
                if (g.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                venue = (g.get("venue") or {}).get("name")
                teams = g.get("teams") or {}
                hs = (teams.get("home") or {}).get("score")
                aws = (teams.get("away") or {}).get("score")
                if not venue or hs is None or aws is None:
                    continue
                out.append((venue, hs + aws))
                n += 1
        print(f"[info] {s}〜{e}: {n}試合")
    return out


def build(season: str = None, start: str = None) -> dict:
    season = season or str(datetime.now(timezone.utc).year)
    # 開幕は年によって前後するので、3月中旬から見ておけば取りこぼさない
    s = date.fromisoformat(start) if start else date(int(season), 3, 15)
    e = datetime.now(timezone.utc).date()

    games = fetch_games(s, e)
    if not games:
        print("[warn] 試合を1件も取得できませんでした")
        return {}

    agg = defaultdict(lambda: {"games": 0, "runs": 0})
    for venue, runs in games:
        agg[venue]["games"] += 1
        agg[venue]["runs"] += runs

    ranked = sorted(
        [(v, a) for v, a in agg.items() if a["games"] >= MIN_GAMES],
        key=lambda x: -(x[1]["runs"] / x[1]["games"]),
    )

    venues = {}
    for i, (v, a) in enumerate(ranked, 1):
        venues[v] = {
            "games": a["games"],
            "runs": a["runs"],
            "avg_runs": round(a["runs"] / a["games"], 2),
            "rank": i,
            "total": len(ranked),
        }

    print(f"\n[info] 集計できた球場: {len(venues)} / 全{len(agg)}")
    print(f"[info] 対象: {s} 〜 {e} の{len(games)}試合")
    for v, d in list(venues.items())[:3]:
        print(f"   {d['rank']:2d}位 {d['avg_runs']:5.2f}点  {v} ({d['games']}試合)")
    if venues:
        last = list(venues.items())[-1]
        print(f"   {last[1]['rank']:2d}位 {last[1]['avg_runs']:5.2f}点  {last[0]}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "start": s.isoformat(),
        "end": e.isoformat(),
        "total_games": len(games),
        "min_games": MIN_GAMES,
        "venues": venues,
    }


def load(path: str = "data/venue_stats.json") -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def describe(stats: dict, venue_en: str) -> str:
    """
    1球場ぶんの1文。数字が無ければ空を返す(無い数字は書かない)。
    何年の話かを必ず添える。年が変われば数字も変わるため。
    """
    v = (stats.get("venues") or {}).get(venue_en)
    if not v:
        return ""
    season = stats.get("season", "")
    parts = [f"{season}年シーズンの1試合平均は{v['avg_runs']}点"]
    if v["rank"] == 1:
        parts.append(f"MLB{v['total']}球場で最も点が入っています")
    elif v["rank"] == v["total"]:
        parts.append(f"MLB{v['total']}球場で最も点が入りません")
    else:
        parts.append(f"{v['total']}球場中{v['rank']}位です")
    return "、".join(parts) + f"({v['games']}試合)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/venue_stats.json")
    parser.add_argument("--season", default=None)
    parser.add_argument("--start", default=None, help="集計開始日 YYYY-MM-DD")
    args = parser.parse_args()

    data = build(season=args.season, start=args.start)
    if not data:
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[info] 球場別の集計を出力しました -> {out}")


if __name__ == "__main__":
    main()
