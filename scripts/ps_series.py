#!/usr/bin/env python3
"""ポストシーズンの、シリーズごとの現在地。

なぜ要るのか:
  20:00の「進出争い」は、レギュラーシーズンが終わると話すことが
  無くなり、その日から出なくなる作り（race_is_over）だった。
  ところがその翌日からが、1年でいちばん見られる短期決戦になる。
  短期決戦で知りたいのは順位やマジックではなく、
  **何勝何敗で、あと何勝で勝ち抜けか、負けたら終わりか**。

  このファイルは材料だけを作る。話し方と画面は generate_morning_short。

勝敗の数え方:
  **終わった試合の勝者を数える。**APIの seriesStatus も勝敗を返すが、
  どちらの球団から見た数字かが試合ごとに変わるので使わない。
  行う予定のない「必要なら第5戦」も日程には載っているので、
  勝ち抜けが決まったシリーズの残り試合は数えない。
"""

import json
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))

# 試合種別 → (呼び名, 何回戦目)
ROUNDS = {
    "F": ("ワイルドカードシリーズ", 1),
    "D": ("地区シリーズ", 2),
    "L": ("リーグ優勝決定シリーズ", 3),
    "W": ("ワールドシリーズ", 4),
}
LEAGUE_JP = {103: "ア・リーグ", 104: "ナ・リーグ"}


def _get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "collespo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def season_dates(season: str) -> dict:
    """PSの始まりと終わり。取れなければ空。"""
    try:
        s = (_get(f"{API}/seasons/{season}?sportId=1").get("seasons")
             or [{}])[0]
    except Exception:                                  # noqa: BLE001
        return {}
    start, end = s.get("postSeasonStartDate"), s.get("postSeasonEndDate")
    if not (start and end):
        return {}
    return {"start": start, "end": end}


def fetch(season: str, start: str, end: str) -> list:
    """PSの試合（ワイルドカード〜ワールドシリーズ）を日付の範囲で。"""
    url = (f"{API}/schedule?sportId=1&season={season}&startDate={start}"
           f"&endDate={end}&gameType=F,D,L,W&hydrate=team")
    out = []
    for d in _get(url).get("dates") or []:
        out.extend(d.get("games") or [])
    return out


def series_key(game_type: str, a: int, b: int) -> str:
    lo, hi = sorted((int(a), int(b)))
    return f"{game_type}:{lo}-{hi}"


def _jp_day(iso: str) -> str:
    """試合開始（UTC）を日本の日付に。"""
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    t = t.astimezone(JST)
    return f"{t.month}月{t.day}日"


def build(games: list, names: dict = None, players: dict = None) -> list:
    """シリーズの一覧。回戦の早い順、同じ回戦ならア・リーグから。

    names:   {team_id: 日本語の球団名}
    players: {team_id: [日本人選手の名前]}
    """
    names = names or {}
    players = players or {}
    by = {}
    for g in games:
        gt = g.get("gameType")
        if gt not in ROUNDS:
            continue
        a = ((g.get("teams") or {}).get("away") or {})
        h = ((g.get("teams") or {}).get("home") or {})
        aid = (a.get("team") or {}).get("id")
        hid = (h.get("team") or {}).get("id")
        if not (aid and hid):
            continue
        key = series_key(gt, aid, hid)
        s = by.setdefault(key, {
            "key": key, "round": gt, "round_jp": ROUNDS[gt][0],
            "stage": ROUNDS[gt][1],
            "league": (a.get("team") or {}).get("league", {}).get("id"),
            "best_of": int(g.get("gamesInSeries") or 0),
            "wins": {aid: 0, hid: 0}, "played": 0,
            "upcoming": [], "_seen": set(), "_names": {},
        })
        s["_names"][aid] = (a.get("team") or {}).get("name", "")
        s["_names"][hid] = (h.get("team") or {}).get("name", "")
        s["best_of"] = max(s["best_of"], int(g.get("gamesInSeries") or 0))
        pk = g.get("gamePk")
        if pk in s["_seen"]:
            continue                 # 同じ試合が2度載る日（中断・再開）
        s["_seen"].add(pk)
        state = ((g.get("status") or {}).get("abstractGameState") or "")
        if state == "Final":
            for side, tid in ((a, aid), (h, hid)):
                if side.get("isWinner"):
                    s["wins"][tid] += 1
                    s["played"] += 1
        else:
            s["upcoming"].append((g.get("gameDate") or "",
                                  int(g.get("seriesGameNumber") or 0)))

    out = []
    for s in by.values():
        need = s["best_of"] // 2 + 1 if s["best_of"] else 0
        winner = next((t for t, w in s["wins"].items() if need and w >= need),
                      None)
        teams = sorted(s["wins"], key=lambda t: (-s["wins"][t], t))
        nxt = None
        if winner is None and s["upcoming"]:
            when, num = sorted(s["upcoming"])[0]
            nxt = {"day": _jp_day(when), "game": num}
        out.append({
            "key": s["key"], "round": s["round"], "round_jp": s["round_jp"],
            "stage": s["stage"],
            # ワールドシリーズはア・ナの対戦なので、リーグは付けない
            "league_jp": ("" if s["round"] == "W"
                          else LEAGUE_JP.get(s["league"], "")),
            "best_of": s["best_of"], "need": need, "played": s["played"],
            "over": winner is not None, "winner": winner,
            "next": nxt,
            "teams": [{"id": t,
                       "name": names.get(t) or names.get(str(t))
                       or s["_names"].get(t, ""),
                       "wins": s["wins"][t],
                       "players": list(players.get(t)
                                       or players.get(str(t)) or [])}
                      for t in teams],
        })
    out.sort(key=lambda x: (x["stage"], x["league_jp"] != "ア・リーグ",
                            x["key"]))
    return out


def _next_round(s: dict) -> str:
    if s["round"] == "W":
        return "ワールドシリーズ制覇"
    nxt = {1: "地区シリーズ", 2: "リーグ優勝決定シリーズ",
           3: "ワールドシリーズ"}[s["stage"]]
    return f"{nxt}へ"


def text(s: dict, with_round: bool = True) -> str:
    """1シリーズを1文で。**勝敗は必ず勝っている側から言う。**

    with_round=False は、見出しで回戦名をもう言っている画面のため。
    """
    t = s["teams"]
    rnd = f"{s['round_jp']} " if with_round else ""
    if len(t) < 2:
        return ""
    a, b = t[0], t[1]
    rec = f"{a['wins']}勝{b['wins']}敗"
    if s["over"]:
        if s["round"] == "W":
            return f"{a['name']}が{rec}で{b['name']}を破り、ワールドシリーズ制覇"
        return f"{a['name']}が{rec}で{b['name']}を破り、{_next_round(s)}"
    if s["played"] == 0:
        day = (s.get("next") or {}).get("day") or ""
        return (f"{rnd}{a['name']}対{b['name']}"
                + (f"、{day}に第1戦" if day else ""))
    if a["wins"] == b["wins"]:
        return f"{rnd}{a['name']}対{b['name']}は{rec}のタイ"
    if a["wins"] == s["need"] - 1:
        # **あと1勝なのは勝っている側。**負けている側から見れば後が無い。
        return f"{rnd}{a['name']}が{rec}とし、突破に王手"
    return f"{rnd}{a['name']}が{rec}でリード"


def jp_text(s: dict) -> str:
    """日本人選手のいる球団の側から、1文で。

    **その球団から見た勝敗で言う。**負けている側を勝っている側の数字で
    言うと、「2勝1敗」がどちらの話か分からなくなる。
    """
    t = s["teams"]
    mine = next((x for x in t if x["players"]), None)
    if mine is None or len(t) < 2:
        return ""
    opp = t[1] if mine is t[0] else t[0]
    who = f"{'・'.join(mine['players'])}の{mine['name']}"
    rec = f"{mine['wins']}勝{opp['wins']}敗"
    if s["over"]:
        if s["winner"] == mine["id"]:
            won = ("ワールドシリーズ制覇" if s["round"] == "W"
                   else _next_round(s))
            return f"{who}は{rec}で{opp['name']}を破り、{won}"
        return f"{who}は{s['round_jp']}で{opp['name']}に{rec}で敗れ、敗退"
    if s["played"] == 0:
        day = (s.get("next") or {}).get("day") or ""
        return (f"{who}は{s['round_jp']}で{opp['name']}と対戦"
                + (f"。{day}に第1戦" if day else ""))
    out = f"{who}は{s['round_jp']}で{opp['name']}に{rec}"
    if mine["wins"] == s["need"] - 1:
        out += "、突破に王手"
    if opp["wins"] == s["need"] - 1:
        out += "、負ければ敗退"
    return out


def elimination_game(s: dict) -> bool:
    """次の試合で決着しうるか（どちらかが王手）。"""
    return (not s["over"] and s["need"] > 0
            and any(x["wins"] == s["need"] - 1 for x in s["teams"]))


def changes(now: list, before: list) -> list:
    """昨日から動いたシリーズ。**この枠の主題は差分。**"""
    prev = {s["key"]: s for s in (before or [])}
    out = []
    for s in now:
        p = prev.get(s["key"])
        jp = any(x["players"] for x in s["teams"])
        if p is None:
            kind = "start"
        elif s["played"] == p.get("played") and s["over"] == p.get("over"):
            continue
        else:
            kind = "advance" if s["over"] else "game"
        # 日本人選手のいるシリーズは、**その球団の側から**言う。
        # 勝っている側から言うと「ブリュワーズが2勝0敗」になり、
        # カブスが負ければ終わりだということが見出しから消える。
        out.append({"key": s["key"], "kind": kind,
                    "text": jp_text(s) if jp else text(s),
                    "jp": jp, "stage": s["stage"]})
    # 決着 → 試合 → 開幕、同じなら日本人選手のいるシリーズを先に
    order = {"advance": 0, "game": 1, "start": 2}
    out.sort(key=lambda c: (order[c["kind"]], not c["jp"], -c["stage"]))
    return out


def headline(series: list, moved: list) -> str:
    """見出し。動いたものから、日本人選手のいるシリーズを優先して。"""
    if moved:
        return moved[0]["text"]
    live = [s for s in series if not s["over"]]
    live.sort(key=lambda s: (not any(x["players"] for x in s["teams"]),
                             -s["stage"]))
    return text(live[0]) if live else ""


def active(series: list) -> bool:
    return any(not s["over"] for s in (series or []))


def in_postseason(dates: dict, today: date = None) -> bool:
    today = today or datetime.now(JST).date()
    try:
        return date.fromisoformat(dates["start"]) <= today
    except (KeyError, TypeError, ValueError):
        return False
