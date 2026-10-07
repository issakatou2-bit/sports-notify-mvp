#!/usr/bin/env python3
"""ポストシーズンのシリーズの状況（2勝0敗・0勝2敗）を、過去の同じ状況から見る話題。

なぜ要るのか:
  10/4、本人「過去の結果から、DSで先に1勝したチームが突破する確率とか、そういう
  ショートもやりたい」。10/5、松井裕樹のパドレスが地区シリーズで0勝2敗になった。
  次に負ければ敗退の試合の前に「0勝2敗から勝ち上がったのは何チームか」を出す。

何を言うか（全部 MLB 公式の過去の試合結果から集計。**予想はしない**）:
  - いまのシリーズ（勝敗・次の試合の日本時間と場所）
  - 1995年からの地区シリーズで、同じ状況（2勝0敗）になったチームの数と、
    そこから勝ち上がった数。0勝2敗の側なら「ひっくり返した数」と最近の例
  - 0勝2敗の側が敵地で2連敗していれば、その中での数

日本人選手のいる球団のシリーズだけ。次の試合が始まったら出さない。
数え方: 延期・中止の行（勝者の無い行）は数えない（同じ試合の本番の行が別にある）。
10/5、ヒロの集計（124シリーズ・2勝0敗70・突破63）と、この数え方で一致を確かめた。

出力: data/ps_odds_topics.json（generated_topics 経由で、シーズンまとめの枠）

画面: 新デザイン「電光掲示板」（review_render_v3、style="v3"）。表紙の材料（v3）は
ps_v3_cover.odds_v3 が、この話題の項目・題から作る（例: 「63」「/70」）。作れなければ v2 のまま。
"""

import argparse
import collections
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_v3_cover  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
OUT = "data/ps_odds_topics.json"
JST = timezone(timedelta(hours=9))
FIRST_SEASON = 1995          # 地区シリーズが始まった年（1981年の特別な年は除く）
ROUNDS = {"D": "地区シリーズ"}

# 昔の名前（日本語の球団名は今の名前で持っているので、年で変わるものだけ）
OLD_NAMES = {
    "Cleveland Indians": "インディアンス", "Florida Marlins": "マーリンズ",
    "Montreal Expos": "エクスポズ", "Tampa Bay Devil Rays": "デビルレイズ",
    "Anaheim Angels": "エンゼルス", "Los Angeles Angels of Anaheim": "エンゼルス",
}


def _get(path: str, **params) -> dict:
    import requests
    r = requests.get(API + path, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def team_jp(team_id, name_en: str = "") -> str:
    if name_en in OLD_NAMES:
        return OLD_NAMES[name_en]
    import notability_engine as ne
    return ne.MLB_TEAM_NAME_JP.get(str(team_id), name_en)


def season_series(schedule: dict) -> list:
    """1シーズンの schedule（gameType 1つ）から、シリーズごとの試合の並び。

    返す行: {"teams": (id, id), "games": [(日時, 勝者id, 本拠地id)], "names": {id: 英語名}}
    """
    by = collections.defaultdict(dict)
    names = {}
    for day in schedule.get("dates") or []:
        for g in day.get("games") or []:
            a, h = g["teams"]["away"], g["teams"]["home"]
            winner = (a["team"]["id"] if a.get("isWinner") else
                      h["team"]["id"] if h.get("isWinner") else None)
            if winner is None:
                continue          # 延期・中止の行。本番の行が同じ gamePk で別にある
            key = tuple(sorted([a["team"]["id"], h["team"]["id"]]))
            by[key][g["gamePk"]] = (g.get("gameDate") or "", winner, h["team"]["id"])
            names[a["team"]["id"]] = a["team"].get("name", "")
            names[h["team"]["id"]] = h["team"].get("name", "")
    return [{"teams": k, "games": sorted(v.values()), "names": names} for k, v in by.items()]


def history(round_code: str, last_season: int, get=_get) -> list:
    """FIRST_SEASON〜last_season のそのラウンドのシリーズ（年つき）。"""
    out = []
    for season in range(FIRST_SEASON, last_season + 1):
        for s in season_series(get("/schedule", sportId=1, gameType=round_code, season=season)):
            out.append({**s, "season": season})
    return out


def summarize(rows: list) -> dict:
    """2勝0敗になったシリーズの集計。"""
    up = done = away2 = away2_back = 0
    backs = []
    for r in rows:
        order = [w for _, w, _ in r["games"]]
        if len(order) < 3 or order[0] != order[1]:
            continue
        lead = order[0]
        trail = next(t for t in r["teams"] if t != lead)
        wins = collections.Counter(order)
        winner = max(wins, key=wins.get)
        up += 1
        if winner == lead:
            done += 1
        lost_away = all(home != trail for _, _, home in r["games"][:2])
        if lost_away:
            away2 += 1
        if winner == trail:
            backs.append({"season": r["season"],
                          "team": team_jp(trail, r["names"].get(trail, "")),
                          "over": team_jp(lead, r["names"].get(lead, "")),
                          "lost_away": lost_away})
            if lost_away:
                away2_back += 1
    backs.sort(key=lambda b: -b["season"])
    return {"up": up, "held": done, "back": len(backs), "away2": away2,
            "away2_back": away2_back, "backs": backs}


def jst_label(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST)
    return f"{t.month}月{t.day}日{t.hour}時" + (f"{t.minute}分" if t.minute else "")


def next_game(series_games: list, now: datetime):
    """いまのシリーズの、まだ終わっていない次の試合（schedule の行）。"""
    for g in sorted(series_games, key=lambda g: g.get("gameDate") or ""):
        if (g.get("status") or {}).get("abstractGameState") == "Final":
            continue
        return g
    return None


def story(row: dict, summary: dict, games_now: list, now: datetime, first: int, last: int) -> dict:
    """シリーズ1つの話題（新デザインの表紙 v3 つき）。2勝0敗・0勝2敗でなければ空。"""
    t = _story(row, summary, games_now, now, first, last)
    return ps_v3_cover.apply(t) if t else t


def _story(row: dict, summary: dict, games_now: list, now: datetime, first: int, last: int) -> dict:
    """シリーズ1つの話題。2勝0敗・0勝2敗でなければ空。"""
    if row.get("over") or row.get("played") != 2 or len(row.get("teams") or []) != 2:
        return {}
    a, b = row["teams"]
    if sorted([a["wins"], b["wins"]]) != [0, 2]:
        return {}
    lead, trail = (a, b) if a["wins"] == 2 else (b, a)
    if not (lead.get("players") or trail.get("players")):
        return {}
    nxt = next_game(games_now, now)
    if not nxt or not nxt.get("gameDate"):
        return {}
    start = datetime.fromisoformat(nxt["gameDate"].replace("Z", "+00:00"))
    if start <= now:
        return {}                 # 次の試合が始まったら、もう出さない
    home = team_jp(nxt["teams"]["home"]["team"]["id"])
    rnd = ROUNDS.get(row.get("round"), row.get("round_jp") or "シリーズ")
    years = f"{first}〜{last}年の{rnd}"
    s = summary
    # 主役は日本人選手のいる側（両方にいれば0勝2敗の側）
    subject = trail if trail.get("players") else lead
    jp = "・".join(subject["players"][:2])
    items = [("いまのシリーズ",
              f"{lead['name']} 2勝0敗 {trail['name']}　第{nxt.get('seriesGameNumber') or 3}戦は"
              f"日本時間{jst_label(nxt['gameDate'])}　{home}の本拠地")]
    if subject is trail:
        items.append(("0勝2敗から勝ち上がったチーム", f"{s['up']}チーム中{s['back']}チーム（{years}）"))
        lost_away = all(g["teams"]["home"]["team"]["id"] != trail["id"]
                        for g in sorted(games_now, key=lambda g: g.get("gameDate") or "")
                        if (g.get("status") or {}).get("abstractGameState") == "Final")
        if lost_away and s["away2"]:
            items.append(("敵地で2連敗してから", f"{s['away2']}チーム中{s['away2_back']}チーム"))
        recent = [f"{x['season']}年の{x['team']}" for x in s["backs"][:3]]
        if recent:
            items.append(("最近の例", "、".join(recent) + "（どれも3連勝で突破）"))
        head = f"{jp}の{trail['name']}が{rnd}0勝2敗"
        tail = f"ここから勝ち上がったのは{s['up']}チーム中{s['back']}"
        intro = (f"{trail['name']}は{rnd}で{lead['name']}に0勝2敗。{first}年から、"
                 f"0勝2敗から勝ち上がったのは{s['up']}チーム中{s['back']}チームです。")
        state = "0-2"
    else:
        items.append(("2勝0敗から勝ち上がったチーム", f"{s['up']}チーム中{s['held']}チーム（{years}）"))
        if s["backs"]:
            last_back = s["backs"][0]
            items.append(("ひっくり返された例",
                          f"{s['back']}回　最近は{last_back['season']}年（{last_back['team']}が"
                          f"{last_back['over']}に）"))
        head = f"{jp}の{lead['name']}が{rnd}2勝0敗"
        tail = f"ここから勝ち上がったのは{s['up']}チーム中{s['held']}"
        intro = (f"{lead['name']}は{rnd}で{trail['name']}に2勝0敗。{first}年から、"
                 f"2勝0敗のチームが勝ち上がったのは{s['up']}チーム中{s['held']}チームです。")
        state = "2-0"
    import notability_engine as ne
    key = "season_odds_" + re.sub(r"[^0-9A-Za-z]", "_", row["key"]) + "_" + state.replace("-", "_")
    return {
        "key": key,
        "label": f"{rnd}の" + ("0勝2敗" if state == "0-2" else "2勝0敗"),
        "hook": head,
        "heading": f"{lead['name']} 対 {trail['name']}　{rnd}",
        "intro": intro,
        "intro_as_is": True,
        "style": "v2",
        "team_id": subject["id"],
        "abbr": ne.MLB_TEAM_ABBR.get(str(subject["id"]), ""),
        "title": f"【MLB】{head}｜{tail} #Shorts",
        "items": items,
        "japanese": [],
        "ps_ended": True,
        "story": True,
        "odds": True,
        "series_key": row["key"],
        "next_game": nxt["gameDate"],
        "counted": {k: v for k, v in s.items() if k != "backs"},
    }


def build(ps: dict, summaries: dict, games_by_series: dict, now: datetime, first: int, last: int) -> list:
    out = []
    for row in ps.get("series") or []:
        if row.get("round") not in summaries:
            continue
        t = story(row, summaries[row["round"]], games_by_series.get(row["key"]) or [],
                  now, first, last)
        if t:
            out.append(t)
    return out


def current_games(row: dict, season: int, get=_get) -> list:
    ids = {t["id"] for t in row.get("teams") or []}
    d = get("/schedule", sportId=1, gameType=row["round"], season=season)
    return [g for day in d.get("dates") or [] for g in day.get("games") or []
            if {g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"]} == ids]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--postseason", default="data/postseason.json")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        ps = json.loads(pathlib.Path(args.postseason).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] PSの材料を読めません({e})")
        return 0
    season = int(ps.get("season") or now.year)
    last = season - 1
    topics = []
    try:
        summaries = {r: summarize(history(r, last)) for r in ROUNDS}
        games = {row["key"]: current_games(row, season) for row in ps.get("series") or []
                 if row.get("round") in ROUNDS and not row.get("over") and row.get("played") == 2}
        topics = build(ps, summaries, games, now, FIRST_SEASON, last)
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] 過去のシリーズを集計できません({e})", file=sys.stderr)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": now.isoformat(),
         "source": "MLB Stats API（過去のポストシーズンの試合結果）", "topics": topics},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print("  " + t["title"])
        for a, b in t["items"]:
            print(f"     {a} | {b}")
        print(f"     集計 | {t['counted']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
