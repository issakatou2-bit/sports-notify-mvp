"""
「昨夜の日本人選手」の結果を集めて、朝のショート用データを作る。

なぜこれをやるのか:
  MLBは日本の朝に終わる。個々の選手のニュースは大量にあるが、
  日本人選手を一覧で見られるものは意外と少なく、しかも
  「昨日◯◯どうだった?」は毎朝ほぼ確実に検索される。
  19時の予告(これから)とは別に、朝の枠(終わったこと)を取れる。

  予告と違って結果は確定しているので、推測が一切入らない。
  取れなかった選手は黙って落とす(0で埋めると、出ていないのか
  データが無いのか区別できなくなる)。

出力: data/morning_recap.json

使い方:
  python3 scripts/morning_recap.py --out data/morning_recap.json
"""

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import JP_PLAYERS_MLB  # noqa: E402

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_day_hitting(player_id: str, day: str, season: str):
    """その日の打撃成績。出場していなければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "byDateRange", "group": "hitting",
                    "startDate": day, "endDate": day, "season": season},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            s = split.get("stat") or {}
            ab = int(_f(s.get("atBats")))
            pa = int(_f(s.get("plateAppearances"))) or ab
            if not pa:
                continue
            return {
                "type": "batter", "pa": pa, "ab": ab,
                "hits": int(_f(s.get("hits"))),
                "hr": int(_f(s.get("homeRuns"))),
                "rbi": int(_f(s.get("rbi"))),
                "runs": int(_f(s.get("runs"))),
                "so": int(_f(s.get("strikeOuts"))),
                "bb": int(_f(s.get("baseOnBalls"))),
                "avg": s.get("avg"),
            }
    return None


def fetch_day_pitching(player_id: str, day: str, season: str):
    """その日の投球成績。登板していなければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "byDateRange", "group": "pitching",
                    "startDate": day, "endDate": day, "season": season},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            s = split.get("stat") or {}
            ip = s.get("inningsPitched")
            if not ip or _f(ip) <= 0:
                continue
            return {
                "type": "pitcher", "ip": ip,
                "er": int(_f(s.get("earnedRuns"))),
                "hits": int(_f(s.get("hits"))),
                "so": int(_f(s.get("strikeOuts"))),
                "bb": int(_f(s.get("baseOnBalls"))),
                "wins": int(_f(s.get("wins"))),
                "losses": int(_f(s.get("losses"))),
            }
    return None


def headline(row: dict) -> str:
    """1行の見出し。数字をそのまま並べるだけで、評価はしない。"""
    if row["type"] == "pitcher":
        bits = [f"{row['ip']}回", f"{row['so']}奪三振", f"自責{row['er']}"]
        if row.get("wins"):
            bits.append("勝ち投手")
        elif row.get("losses"):
            bits.append("負け投手")
        return "　".join(bits)
    bits = [f"{row['ab']}打数{row['hits']}安打"]
    if row.get("hr"):
        bits.append(f"{row['hr']}本塁打")
    if row.get("rbi"):
        bits.append(f"{row['rbi']}打点")
    return "　".join(bits)


def build(day: str = None, season: str = None) -> dict:
    """
    対象日は「日本時間の昨日」ではなく、アメリカの試合日。
    MLBの1日は日本時間の朝までかかるので、JSTの朝に走らせるときは
    前日(米国日付)を見るのが正しい。
    """
    season = season or str(datetime.now(timezone.utc).year)
    target = day or (datetime.now(JST).date() - timedelta(days=1)).isoformat()
    print(f"[info] 対象日(米国日付): {target}")

    try:
        resp = requests.get(f"{MLB_API_BASE}/sports/1/players",
                            params={"season": season}, timeout=30)
        resp.raise_for_status()
        by_name = {p.get("fullName"): str(p.get("id"))
                   for p in resp.json().get("people", [])}
    except Exception as e:
        print(f"[warn] 選手一覧の取得に失敗しました: {e}", file=sys.stderr)
        return {"date": target, "players": []}

    rows = []
    for p in JP_PLAYERS_MLB:
        pid = by_name.get(p["name_en"])
        if not pid:
            continue
        stat = fetch_day_pitching(pid, target, season) or \
            fetch_day_hitting(pid, target, season)
        if not stat:
            continue
        rows.append({"name": p["name_jp"], "name_en": p["name_en"],
                     "player_id": pid, **stat,
                     "headline": headline({"name": p["name_jp"], **stat})})

    # 投手を先に、打者は安打数の多い順。出場者が少ない日でも形になる並びにする
    rows.sort(key=lambda r: (r["type"] != "pitcher", -r.get("hits", 0)))

    print(f"[info] 出場していた日本人選手: {len(rows)}名")
    for r in rows:
        print(f"   {r['name']}  {r['headline']}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": target,
        "players": rows,
    }


def load(path: str, day: str = None) -> list:
    """朝のショート側から読む。日付が食い違う場合は使わない。"""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if day and data.get("date") != day:
        print(f"[info] 記録が別の日({data.get('date')})なので使いません")
        return []
    return data.get("players") or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/morning_recap.json")
    parser.add_argument("--date", default=None, help="米国日付 YYYY-MM-DD")
    parser.add_argument("--season", default=None)
    args = parser.parse_args()

    data = build(day=args.date, season=args.season)
    if not data["players"]:
        print("[info] 出場した日本人選手がいないため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[info] 朝のまとめを出力しました({len(data['players'])}名) -> {out}")


if __name__ == "__main__":
    main()
