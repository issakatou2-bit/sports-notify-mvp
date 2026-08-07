"""
日本人選手の「直近7日間」の打撃成績を取得し、OPS順に並べる。

なぜ週間なのか:
  シーズン通算の成績は、既にどこでも見られるうえ、1週間ではほとんど動かない。
  一方「今週は誰が打っていたか」は毎週変わり、週次まとめの題材として
  ちょうどよく、検索需要のある選手名と結びつく。

なぜ日本人選手に絞るのか:
  コレスポの読者は日本語話者が中心で、選手名で検索されるのは日本人選手。
  全打者を対象にすると、名前を見ても誰か分からないランキングになる。

APIについて:
  /people/{id}/stats?stats=byDateRange で期間を区切った成績が取れる。
  選手ごとに1回呼ぶので、対象は日本人選手(十数名)に限る。
  取得できなかった選手は黙って除外する(0で埋めると打っていないのか
  データが無いのか区別できなくなるため)。

出力: data/weekly_ops.json (リポジトリへコミットし、週次まとめが読む)

使い方:
  python3 scripts/weekly_ops.py --out data/weekly_ops.json
"""

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import JP_PLAYERS_MLB  # noqa: E402
from notability_engine import MLB_TEAM_ABBR as TEAM_ABBR  # noqa: E402

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# ランキングに載せる最低打席数。1打席2安打のような選手が
# OPS上位を占めると、実感と食い違うランキングになる。
MIN_PA = 5

# 表示する人数
TOP_N = 5


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def resolve_player_id(name_en: str, season: str):
    """英語名から player_id を引く。見つからなければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/sports/1/players",
            params={"season": season}, timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 選手一覧の取得に失敗しました: {e}", file=sys.stderr)
        return None
    for p in resp.json().get("people", []):
        if p.get("fullName") == name_en:
            return str(p.get("id"))
    return None


def fetch_range_hitting(player_id: str, start: str, end: str, season: str):
    """期間を区切った打撃成績。打席が無ければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={
                "stats": "byDateRange",
                "group": "hitting",
                "startDate": start,
                "endDate": end,
                "season": season,
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None

    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            stat = split.get("stat") or {}
            pa = stat.get("plateAppearances") or stat.get("atBats")
            if not pa:
                continue
            return {
                "pa": int(_f(pa)),
                "ab": int(_f(stat.get("atBats"))),
                "hits": int(_f(stat.get("hits"))),
                "hr": int(_f(stat.get("homeRuns"))),
                "rbi": int(_f(stat.get("rbi"))),
                "avg": stat.get("avg"),
                "obp": stat.get("obp"),
                "slg": stat.get("slg"),
                "ops": stat.get("ops"),
            }
    return None


# リーグ全体のランキングに載せる最低打席数。
# 日本人選手より高くしているのは、母数が150名以上あり、少ない打席で
# 数字が跳ねた選手が上位を埋めてしまうため。
MIN_PA_LEAGUE = 15
TOP_N_LEAGUE = 5


def fetch_league_week(start: str, end: str, season: str) -> list:
    """
    MLB全体の期間打撃成績を、1回の呼び出しで取る。

    日本人選手だけだと「今週いちばん打った選手」が分からない。
    ジャッジやシュワーバーのような、日本でも名前が通っている選手が
    上位に来れば、それ自体が見どころになる。
    選手ごとに引くと150回以上の呼び出しになるが、
    このエンドポイントはリーグ全体をまとめて返してくれる。
    """
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/stats",
            params={"stats": "byDateRange", "group": "hitting", "sportId": 1,
                    "startDate": start, "endDate": end,
                    "season": season, "limit": 400},
            timeout=40,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] リーグ全体の成績取得に失敗しました: {e}", file=sys.stderr)
        return []

    rows = []
    for st in resp.json().get("stats", []):
        for sp in st.get("splits", []):
            p = sp.get("player") or {}
            s = sp.get("stat") or {}
            t = sp.get("team") or {}
            pa = s.get("plateAppearances") or s.get("atBats")
            if not pa or int(_f(pa)) < MIN_PA_LEAGUE:
                continue
            if s.get("ops") is None:
                continue
            team_id = str(t.get("id", ""))
            rows.append({
                "name": p.get("fullName", ""),
                "player_id": str(p.get("id", "")),
                "team_id": team_id,
                "team": TEAM_ABBR.get(team_id) or t.get("abbreviation") or "",
                "pa": int(_f(pa)),
                "hits": int(_f(s.get("hits"))),
                "hr": int(_f(s.get("homeRuns"))),
                "rbi": int(_f(s.get("rbi"))),
                "ops": s.get("ops"),
            })
    rows.sort(key=lambda r: -_f(r.get("ops")))
    return rows


def build(days: int = 7, season: str = None) -> dict:
    season = season or str(datetime.now(timezone.utc).year)
    end = date.today()
    start = end - timedelta(days=days - 1)
    s, e = start.isoformat(), end.isoformat()
    print(f"[info] 対象期間: {s} 〜 {e}")

    # 選手一覧は1回だけ引いて使い回す(選手ごとに引くと十数回になる)
    try:
        resp = requests.get(f"{MLB_API_BASE}/sports/1/players",
                            params={"season": season}, timeout=30)
        resp.raise_for_status()
        by_name = {p.get("fullName"): str(p.get("id"))
                   for p in resp.json().get("people", [])}
    except Exception as ex:
        print(f"[warn] 選手一覧の取得に失敗しました: {ex}", file=sys.stderr)
        by_name = {}

    rows = []
    for p in JP_PLAYERS_MLB:
        pid = by_name.get(p["name_en"])
        if not pid:
            continue
        stat = fetch_range_hitting(pid, s, e, season)
        if not stat or stat["pa"] < MIN_PA:
            continue
        rows.append({
            "name": p["name_jp"],
            "name_en": p["name_en"],
            "player_id": pid,
            **stat,
        })

    rows.sort(key=lambda r: -_f(r.get("ops")))
    print(f"[info] 規定打席({MIN_PA}打席)を満たした日本人打者: {len(rows)}名")
    for r in rows[:TOP_N]:
        print(f"   {r['name']}  OPS {r['ops']}  {r['hits']}安打 "
              f"{r['hr']}本塁打 ({r['pa']}打席)")

    league = fetch_league_week(s, e, season)
    print(f"[info] MLB全体({MIN_PA_LEAGUE}打席以上): {len(league)}名")
    for r in league[:TOP_N_LEAGUE]:
        print(f"   {r['name']} ({r['team']})  OPS {r['ops']}  "
              f"{r['hits']}安打 {r['hr']}本塁打")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "start": s,
        "end": e,
        "min_pa": MIN_PA,
        "min_pa_league": MIN_PA_LEAGUE,
        "players": rows,
        "league": league[:TOP_N_LEAGUE],
    }


def load(path: str, since: str = None, until: str = None) -> list:
    """
    週次まとめ側から読む。期間が指定されていて、記録された期間と
    食い違う場合は、古い週の数字を今週として出さないよう空を返す。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if until and (data.get("end") or "") < until:
        print(f"[info] 週間OPSが古いため使いません "
              f"(記録={data.get('end')} / 必要={until})")
        return []
    return data.get("players") or []


def load_league(path: str, until: str = None) -> list:
    """MLB全体の上位。日本人選手ランキングと同じく、古い週の数字は使わない。"""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if until and (data.get("end") or "") < until:
        return []
    return data.get("league") or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/weekly_ops.json")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--season", default=None)
    args = parser.parse_args()

    data = build(days=args.days, season=args.season)
    if not data["players"]:
        print("[info] 該当する選手がいないため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[info] 週間OPSを出力しました({len(data['players'])}名) -> {out}")


if __name__ == "__main__":
    main()
