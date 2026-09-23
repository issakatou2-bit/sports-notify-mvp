#!/usr/bin/env python3
"""欧州5大リーグの日本人選手の、所属クラブの直近の結果。

なぜ要るのか:
  MLBのポストシーズンが終わると（10/31）、夕方のMLBの枠は材料が無くなる。
  欧州は5月まで続く。MLBでいちばん強い枠は「日本人選手の成績」なので、
  同じ入口を欧州でも作る。

何が言えて、何が言えないか（**ここを取り違えない**）:
  ・クラブの結果（スコア・勝敗・相手）…5大リーグすべて。football-data.org
  ・選手本人の出場時間・得点・アシスト…**プレミアリーグだけ。**
    プレミア公式のファンタジー用データ（節ごとの成績）から取る。
  ・それ以外のリーグの選手本人のことは**何も言わない。**
    無料で取れる公式の出どころが無い。ESPNは403、ブンデスの有志データは
    リーグ戦に「103分」の得点が入っているなど、確かさに不安がある。
    「クラブが勝った」を「選手が活躍した」と読ませない。

出力: data/soccer_jp_week.json

使い方:
  python3 scripts/soccer_jp_week.py --out data/soccer_jp_week.json
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

JST = timezone(timedelta(hours=9))
LEAGUES = {"PL": "プレミアリーグ", "PD": "ラ・リーガ", "BL1": "ブンデスリーガ",
           "SA": "セリエA", "FL1": "リーグ・アン"}
# 直近の週末を見る。金曜から月曜の試合が月曜・火曜の夕方に揃う。
WINDOW_DAYS = 4
FPL = "https://fantasy.premierleague.com/api"


def _get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "collespo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_matches(api_key: str, today) -> dict:
    """{大会: [終わった試合]}。1大会1回の呼び出し（無料枠は1分10回）。"""
    import notability_engine as ne
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    out = {}
    for code in LEAGUES:
        try:
            r = ne._football_data_get(
                f"{ne.FOOTBALL_DATA_BASE}/competitions/{code}/matches",
                {"X-Auth-Token": api_key},
                params={"status": "FINISHED", "dateFrom": start,
                        "dateTo": today.isoformat()})
            out[code] = r.json().get("matches") or []
        except Exception as e:                          # noqa: BLE001
            print(f"[warn] {code} の試合を取れません({e})", file=sys.stderr)
    return out


def resolve(elements: list, name_en: str):
    """名簿の選手を、プレミア公式の選手IDに。**決まらなければ None。**

    姓だけで引くと、同じ姓の選手がいたときに別人の成績を言う。
    姓で1人に絞れなければ名でも照合し、それでも決まらなければ
    引かない（本人のことを言わないだけで、クラブの結果は出る）。
    """
    sur = _surname(name_en)
    first = (name_en or "").split()[0] if name_en else ""
    cands = [e for e in elements
             if sur and sur in ((e.get("web_name") or "").strip(),
                                (e.get("second_name") or "").strip())]
    if len(cands) > 1:
        cands = [e for e in cands
                 if first and (e.get("first_name") or "").startswith(first)]
    return cands[0].get("id") if len(cands) == 1 else None


def fpl_stats(matchdays: set, roster: list = None) -> dict:
    """プレミアの日本人選手の、その節の出場時間・得点・アシスト。

    {(名前, 節): {"minutes", "goals", "assists"}}。取れなければ空で、
    その場合は選手本人のことを言わない（クラブの結果だけになる）。
    """
    if not matchdays:
        return {}
    if roster is None:
        import notability_engine as ne
        roster = ne.JP_PLAYERS_SOCCER
    try:
        boot = _get(f"{FPL}/bootstrap-static/")
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] プレミアの公式データを取れません({e})", file=sys.stderr)
        return {}
    elements = boot.get("elements") or []
    ids = {p["name_jp"]: resolve(elements, p.get("name_en"))
           for p in roster if p.get("league") == "PL"}
    out = {}
    for md in sorted(matchdays):
        try:
            live = {x["id"]: x.get("stats") or {}
                    for x in _get(f"{FPL}/event/{md}/live/").get("elements")
                    or []}
        except Exception as e:                          # noqa: BLE001
            print(f"[warn] プレミア第{md}節の成績を取れません({e})",
                  file=sys.stderr)
            continue
        for name, pid in ids.items():
            st = live.get(pid) if pid else None
            if st is not None:
                out[(name, md)] = {"minutes": st.get("minutes") or 0,
                                   "goals": st.get("goals_scored") or 0,
                                   "assists": st.get("assists") or 0}
    return out


def _surname(name_en: str) -> str:
    parts = (name_en or "").split()
    return parts[-1] if parts else ""


def _day_jp(utc: str) -> str:
    try:
        t = datetime.fromisoformat((utc or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    t = t.astimezone(JST)
    return f"{t.month}月{t.day}日"


def build(matches: dict, fpl: dict = None, out_now: set = None,
          players_for=None, club_jp=None) -> list:
    """日本人選手1人1行。直近の1試合だけ。

    クラブ名の照合は自前でしない。API の表記は揺れる（"Brighton & Hove
    Albion FC" など）ので、検査のある jp_players_for_club に任せる。
    """
    import notability_engine as ne
    fpl = fpl or {}
    out_now = out_now or set()
    players_for = players_for or ne.jp_players_for_club
    club_jp = club_jp or ne.club_name_jp
    rows = {}
    for code, ms in matches.items():
        for m in sorted(ms, key=lambda x: x.get("utcDate") or ""):
            ft = ((m.get("score") or {}).get("fullTime") or {})
            if ft.get("home") is None or ft.get("away") is None:
                continue
            for side, other in (("homeTeam", "awayTeam"),
                                ("awayTeam", "homeTeam")):
                team = (m.get(side) or {}).get("name") or ""
                opp = (m.get(other) or {}).get("name") or ""
                home = side == "homeTeam"
                gf, ga = ((ft["home"], ft["away"]) if home
                          else (ft["away"], ft["home"]))
                for p in players_for(team):
                    if p.get("league") != code:
                        continue
                    row = {
                        "name": p["name_jp"], "club": p.get("team_jp")
                        or club_jp(team), "league": code,
                        "league_jp": LEAGUES[code], "opp": club_jp(opp),
                        "home": home, "gf": gf, "ga": ga,
                        "result": ("勝ち" if gf > ga else
                                   "負け" if gf < ga else "引き分け"),
                        "day": _day_jp(m.get("utcDate")),
                        "utc": m.get("utcDate") or "",
                        "matchday": m.get("matchday"),
                        "out": p["name_jp"] in out_now,
                        "stats": None,
                    }
                    if code == "PL":
                        row["stats"] = fpl.get(
                            (p["name_jp"], m.get("matchday")))
                    old = rows.get(p["name_jp"])
                    if old is None or row["utc"] > old["utc"]:
                        rows[p["name_jp"]] = row
    out = list(rows.values())
    # 得点 → 勝ち → 引き分け → 負け、同じならリーグ・名前順
    rank = {"勝ち": 0, "引き分け": 1, "負け": 2}
    league = list(LEAGUES)
    out.sort(key=lambda r: (-((r["stats"] or {}).get("goals") or 0),
                            -((r["stats"] or {}).get("assists") or 0),
                            rank[r["result"]], league.index(r["league"]),
                            r["name"]))
    return out


def player_part(r: dict) -> str:
    """選手本人のこと。**言えるのはプレミアの公式データがあるときだけ。**"""
    st = r.get("stats")
    if st is None:
        return ""
    if not st["minutes"]:
        return "負傷で離脱中" if r.get("out") else "出場なし"
    bits = [f"{st['minutes']}分出場"]
    if st["goals"]:
        bits.append(f"{st['goals']}得点")
    if st["assists"]:
        bits.append(f"{st['assists']}アシスト")
    return "・".join(bits)


def sat_out(r: dict) -> bool:
    """出ていないと**分かっている**か。分からないリーグは False。"""
    st = r.get("stats")
    return bool(r.get("out") or (st is not None and not st["minutes"]))


def line(r: dict) -> str:
    """1行。主語はクラブ。選手は「誰のクラブか」の印。"""
    where = "ホーム" if r["home"] else "アウェー"
    res = {"勝ち": "勝利", "負け": "敗戦", "引き分け": "引き分け"}[r["result"]]
    s = (f"{r['name']}の{r['club']}、{where}で{r['opp']}に"
         f"{r['gf']}-{r['ga']}の{res}")
    me = player_part(r)
    return s + (f"（{r['name']}は{me}）" if me else "")


def headline(rows: list) -> str:
    """見出し。プレミアで得点した選手がいれば本人、いなければクラブの勝ち。"""
    for r in rows:
        st = r.get("stats") or {}
        if st.get("goals"):
            return f"{r['name']}が{st['goals']}得点、{r['club']}は{r['result']}"
    # **出ていないと分かっている選手の名前は題に出さない。**
    # 「ブライトンの試合、三笘薫が所属」と出していたが、三笘は負傷で
    # 1分も出ていなかった（9/11の指摘と同じ形の誤り）。
    win = [r for r in rows if r["result"] == "勝ち" and not sat_out(r)]
    if win:
        return f"{win[0]['name']}の{win[0]['club']}が勝利"
    return f"欧州の日本人選手{len(rows)}人の週末" if rows else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/soccer_jp_week.json")
    args = ap.parse_args()
    key = os.environ.get("FOOTBALL_DATA_API_KEY") or ""
    if not key:
        print("[info] FOOTBALL_DATA_API_KEY が無いので作りません")
        return 0
    today = datetime.now(JST).date()
    matches = fetch_matches(key, today)
    mds = {m.get("matchday") for m in matches.get("PL") or []
           if m.get("matchday")}
    try:
        import soccer_availability as sa
        out_now = set(sa.unavailable(sa.load()))
    except Exception:                                   # noqa: BLE001
        out_now = set()
    rows = build(matches, fpl_stats(mds), out_now)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(),
            "date": today.isoformat(), "window_days": WINDOW_DAYS,
            "headline": headline(rows), "rows": rows}
    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    print(f"[info] {data['headline']} / {len(rows)}人 -> {p}")
    for r in rows[:10]:
        print("   " + line(r))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
