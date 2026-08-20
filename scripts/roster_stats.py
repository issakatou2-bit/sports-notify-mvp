#!/usr/bin/env python3
"""
コメント欄で扱う試合の、両チームの在籍選手と今季成績を集める。

なぜ要るのか:
  ファンのコメントに出てくる名前を、その日の出場者と照合していた。
  だが実際のコメントを読むと、出ていない選手の話もよくある:

    「Sanchezのために祈る。降格するからじゃない」
    「幸いなことに10回にDiazを出さなくて済んだ」

  名前が挙がるのは、たいてい所属している選手だからで、
  その日出たかどうかは関係が無い。出場者だけを見ていると、
  こういうコメントは何とも繋がらない。

何を出すか:
  その日出た選手には、その日の成績(best_of_day)。
  出ていない選手には、今季の成績。どちらの数字なのかは
  画面に書き分ける。

  直近5試合ではなく今季にしているのは、1人ずつ引くと
  40人ぶんの通信になるため。今季なら1リクエストで揃う。

出力: data/roster_stats.json

使い方:
  python3 scripts/roster_stats.py --buzz data/mlb_buzz.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import MLB_TEAM_NAME_JP  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}
JST = timezone(timedelta(hours=9))


def team_id_of(name_jp: str) -> str:
    for tid, jp in MLB_TEAM_NAME_JP.items():
        if jp == name_jp:
            return tid
    return ""


def season_line(person: dict) -> tuple:
    """(種別, 今季の1行)。成績が無ければ ("", "")。"""
    for st in (person.get("stats") or []):
        group = ((st.get("group") or {}).get("displayName") or "")
        for sp in st.get("splits", []):
            s = sp.get("stat") or {}
            if group == "hitting" and s.get("atBats"):
                return ("batter",
                        f"今季 打率{s.get('avg')}　{s.get('homeRuns')}本塁打　"
                        f"{s.get('rbi')}打点")
            if group == "pitching" and s.get("inningsPitched"):
                return ("pitcher",
                        f"今季 {s.get('wins')}勝{s.get('losses')}敗　"
                        f"防御率{s.get('era')}　{s.get('strikeOuts')}奪三振")
    return ("", "")


def roster(team_id: str, season: str) -> list:
    try:
        r = requests.get(
            f"{API}/teams/{team_id}/roster",
            params={"rosterType": "active", "season": season,
                    "hydrate": "person(stats(type=season))"},
            headers=UA, timeout=30).json()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {team_id} の在籍を取れません: {e}", file=sys.stderr)
        return []
    out = []
    for x in r.get("roster", []):
        p = x.get("person") or {}
        name = p.get("fullName")
        if not name:
            continue
        kind, line = season_line(p)
        if not line:
            continue
        out.append({"name": name, "team": MLB_TEAM_NAME_JP.get(team_id, ""),
                    "type": kind, "line": line})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buzz", default="data/mlb_buzz.json")
    ap.add_argument("--out", default="data/roster_stats.json")
    ap.add_argument("--season", default=None)
    ap.add_argument("--videos", type=int, default=4,
                    help="コメントを集めた動画の本数(local_voicesと揃える)")
    args = ap.parse_args()

    season = args.season or str(datetime.now(JST).year)
    try:
        vids = json.loads(pathlib.Path(args.buzz).read_text(
            encoding="utf-8")).get("videos") or []
    except (OSError, json.JSONDecodeError):
        vids = []
    if not vids:
        print("[info] 対象の試合がありません")
        return 0

    # コメントは上位4本の動画から集めている。1本目だけ見ていたので、
    # 他の3試合について書かれたコメントは何とも繋がらなかった。
    # 実際、8/20のコメントに出てきた Sanchez も Diaz も、
    # 1本目のブルージェイズ・レイズには在籍していない。
    teams = []
    for v in vids[:args.videos]:
        res = v.get("result") or {}
        for key in ("home_jp", "away_jp"):
            if res.get(key) and res[key] not in teams:
                teams.append(res[key])
    ids = [(x, team_id_of(x)) for x in teams]
    ids = [(x, i) for x, i in ids if i]
    if not ids:
        print(f"[info] 球団を特定できません: {teams}")
        return 0

    players = []
    for name_jp, tid in ids:
        got = roster(tid, season)
        print(f"[info] {name_jp}: {len(got)}人")
        players += got

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "teams": [t for t, _ in ids],
        "players": players,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(players)}人を書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
