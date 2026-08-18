#!/usr/bin/env python3
"""
その日のMLB全体で、いちばん活躍した選手を選ぶ。

なぜ日本人選手だけではないのか:
  「今日の1人」を日本人選手の名簿から選ぶ作りにしていたが、
  それはこの枠の趣旨ではなかった。MLB全体を見て、その日いちばん
  活躍した選手を紹介する枠。日本人選手が該当する日はそうなるし、
  しない日は他の選手になる。

  実際、8/17は Pete Crow-Armstrong が先頭打者本塁打とサヨナラ本塁打で
  154点、大谷が140点だった。名簿で絞ると、この日の1位が出てこない。

どう選ぶか:
  その日の全試合の box score を読み、出場した全員に
  morning_recap.contribution() を当てる。日本人選手の成績で使っている
  式をそのまま使うので、物差しが2つに分かれない。

  15試合ぶんの呼び出しで、400人前後を採点できる。

出力: data/best_of_day.json

使い方:
  python3 scripts/best_of_day.py --date 2026-08-17
"""

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import morning_recap as mr  # noqa: E402
from notability_engine import JP_PLAYERS_MLB, MLB_TEAM_NAME_JP  # noqa: E402

MLB_API = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))

# 何人ぶん残すか。1位だけだと、僅差の2位が見えない。
KEEP = 8


def _jp_names() -> set:
    return {p["name_en"] for p in JP_PLAYERS_MLB}


def batting_row(name: str, team: str, s: dict) -> dict:
    return {"type": "batter", "name": name, "team": team,
            "ab": s.get("atBats", 0), "pa": s.get("plateAppearances", 0),
            "hits": s.get("hits", 0), "hr": s.get("homeRuns", 0),
            "tb": s.get("totalBases", 0), "rbi": s.get("rbi", 0),
            "bb": s.get("baseOnBalls", 0), "so": s.get("strikeOuts", 0),
            "doubles": s.get("doubles", 0), "triples": s.get("triples", 0),
            "hbp": s.get("hitByPitch", 0), "sb": s.get("stolenBases", 0)}


def pitching_row(name: str, team: str, s: dict) -> dict:
    return {"type": "pitcher", "name": name, "team": team,
            "ip": s.get("inningsPitched"), "er": s.get("earnedRuns", 0),
            "hits": s.get("hits", 0), "so": s.get("strikeOuts", 0),
            "bb": s.get("baseOnBalls", 0), "gs": s.get("gamesStarted", 0),
            "saves": s.get("saves", 0),
            "save_opp": s.get("saveOpportunities", 0),
            "blown": s.get("blownSaves", 0), "holds": s.get("holds", 0)}


def collect(day: str, sleep: float = 0.15) -> list:
    """その日の全出場選手を採点して、点数の高い順に返す。"""
    try:
        r = requests.get(f"{MLB_API}/schedule",
                         params={"sportId": 1, "date": day}, timeout=25)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 日程を取れませんでした: {e}", file=sys.stderr)
        return []
    games = [g for d in r.json().get("dates", []) for g in d.get("games", [])]
    print(f"[info] {day} の試合: {len(games)}")

    rows = []
    for g in games:
        try:
            b = requests.get(f"{MLB_API}/game/{g['gamePk']}/boxscore",
                             timeout=25).json()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {g.get('gamePk')}: {e}", file=sys.stderr)
            continue
        for side_key in ("away", "home"):
            side = (b.get("teams") or {}).get(side_key) or {}
            team_id = str(((side.get("team") or {}).get("id")) or "")
            team = MLB_TEAM_NAME_JP.get(team_id,
                                        (side.get("team") or {}).get("name", ""))
            for p in (side.get("players") or {}).values():
                st = p.get("stats") or {}
                name = (p.get("person") or {}).get("fullName", "")
                if not name:
                    continue
                bat = st.get("batting") or {}
                if bat.get("plateAppearances"):
                    row = batting_row(name, team, bat)
                    rows.append((mr.contribution(row), row))
                pit = st.get("pitching") or {}
                try:
                    ip = float(pit.get("inningsPitched") or 0)
                except (TypeError, ValueError):
                    ip = 0.0
                if ip > 0:
                    row = pitching_row(name, team, pit)
                    rows.append((mr.contribution(row), row))
        time.sleep(sleep)

    rows.sort(key=lambda x: -x[0])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="米国日付。既定は日本時間の昨日")
    ap.add_argument("--out", default="data/best_of_day.json")
    args = ap.parse_args()

    # 米国日付Dの試合は日本時間の翌日午前に終わる。
    # 日本の「今日の朝」に対応するのは、米国日付では前日。
    day = args.date or (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    rows = collect(day)
    if not rows:
        print("[info] 出場記録がありません")
        return 0

    jp = _jp_names()
    out = []
    for score, row in rows[:KEEP]:
        out.append({
            "name": row["name"], "team": row["team"],
            "type": row["type"], "score": score,
            "headline": mr.headline(row),
            "is_japanese": row["name"] in jp,
            "stats": {k: v for k, v in row.items()
                      if k not in ("type", "name", "team")},
        })

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "date": day,
        "date_jst": mr.jst_label(day),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scored": len(rows),
        "players": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[info] {len(rows)}人を採点しました\n")
    for i, x in enumerate(out, 1):
        mark = " ★日本人選手" if x["is_japanese"] else ""
        print(f"{i:2d}. {x['score']:4d}  {x['name'][:24]:24s} "
              f"{x['headline']}{mark}")
    print(f"\n[info] 書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
