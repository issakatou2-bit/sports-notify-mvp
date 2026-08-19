#!/usr/bin/env python3
"""
球団ごとの殿堂入り選手を集める。

なぜ要るのか:
  球団の回は、創設年と本拠地と地区で終わっていた。その球団を
  その球団たらしめているのは、そこで何が起きたかの方で、
  数字だけでは球団の見分けがつかない。

  「レジェンドは自動では作れない」と言ったのは調べ足らずだった。
  MLB公式APIに殿堂入りの一覧(354人)があり、1人ずつに球団IDが
  付いている。誰がどの球団の代表かを、こちらで決めなくてよい。

なぜ1度だけ動かすのか:
  殿堂入りは年に1回しか増えない。毎日取りに行く理由が無いので、
  取ってコミットして使う。新しい殿堂入りが出た年に回し直せばよい。

通算成績について:
  1人ずつ people/{id}/stats を引く。球団あたり3人に絞っても
  90人ぶんの通信になるので、日次の流れには置かない。

出力: data/team_legends.json

使い方:
  python3 scripts/team_legends.py --per-team 3
"""

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import MLB_TEAM_NAME_JP  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}


def career(pid: int, position: str = "", timeout: int = 25) -> dict:
    """
    通算成績。打者なら打率と本塁打、投手なら勝利と奪三振。

    守備位置で先に決める。打撃から見ていたら、投手にも打席が
    あるので先に当たってしまい、トム・シーバーの通算成績が
    「打率.154 12本塁打」になっていた。投げた方が本業。
    """
    order = (("pitching", "hitting") if "Pitcher" in (position or "")
             else ("hitting", "pitching"))
    for group in order:
        try:
            r = requests.get(f"{API}/people/{pid}/stats",
                             params={"stats": "career", "group": group},
                             headers=UA, timeout=timeout).json()
        except Exception:  # noqa: BLE001
            continue
        for st in r.get("stats", []):
            for sp in st.get("splits", []):
                s = sp.get("stat") or {}
                if group == "hitting" and s.get("gamesPlayed"):
                    if not s.get("atBats"):
                        continue
                    return {"type": "batter",
                            "line": f"通算 打率{s.get('avg')}　"
                                    f"{s.get('homeRuns')}本塁打　"
                                    f"{s.get('hits')}安打",
                            "hr": s.get("homeRuns") or 0}
                if group == "pitching" and s.get("wins") is not None:
                    if not s.get("inningsPitched"):
                        continue
                    return {"type": "pitcher",
                            "line": f"通算 {s.get('wins')}勝　"
                                    f"防御率{s.get('era')}　"
                                    f"{s.get('strikeOuts')}奪三振",
                            "hr": 0}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/team_legends.json")
    ap.add_argument("--per-team", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    try:
        aw = requests.get(f"{API}/awards/MLBHOF/recipients",
                          headers=UA, timeout=60).json().get("awards") or []
    except Exception as e:  # noqa: BLE001
        print(f"[error] 殿堂入りを取れませんでした: {e}", file=sys.stderr)
        return 1
    print(f"[info] 殿堂入り {len(aw)}人")

    by_team = {}
    for a in aw:
        tid = str(((a.get("team") or {}).get("id")) or "")
        p = a.get("player") or {}
        if not tid or not p.get("id"):
            continue
        by_team.setdefault(tid, []).append({
            "id": p["id"], "name": p.get("nameFirstLast", ""),
            "position": ((p.get("primaryPosition") or {}).get("name") or ""),
            "year": a.get("season", ""),
        })

    out, looked = {}, 0
    for tid, people in by_team.items():
        if tid not in MLB_TEAM_NAME_JP:
            continue
        # 殿堂入りが古い順に入っているので、新しい方から採る。
        # 名前を知っている人に当たりやすい。
        people = sorted(people, key=lambda x: str(x.get("year")),
                        reverse=True)[:args.per_team]
        rows = []
        for p in people:
            c = career(p["id"], p.get("position", ""))
            looked += 1
            time.sleep(args.sleep)
            if not c:
                continue
            rows.append({"name": p["name"], "position": p["position"],
                         "hof_year": p["year"], "line": c["line"],
                         "type": c["type"]})
        if rows:
            out[tid] = {"team": MLB_TEAM_NAME_JP[tid], "players": rows}

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "MLB Stats API (Hall of Fame recipients)",
        "teams": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[info] {len(out)}球団 / {looked}人を調べました -> {p}\n")
    for tid, v in list(out.items())[:4]:
        print(f"  {v['team']}")
        for r in v["players"]:
            print(f"     {r['name']:24s} {r['hof_year']}年殿堂入り  {r['line']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
