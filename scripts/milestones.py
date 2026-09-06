#!/usr/bin/env python3
"""あと少しで届く節目を、日本人選手ごとに1つ選ぶ。

なぜ要るのか:
  この番組の動画は、どれも**その日で完結**している。今日の成績を
  読んで終わり。よく出来ていても、明日また見る理由にはならない。
  28日の実測で登録は+13人しかなく、再生の多さと釣り合っていない。

  「あと2本で30号」は、その1行だけで明日の理由になる。
  しかも毎日ひとりでに更新される。**新しい取材はいらない。**
  公式の通算成績と、年ごとの成績。どちらももう取れる。

  9/6のコメント欄でも、いちばん支持されたのは
  「30本トリオが完成したね」だった。**節目は現地でも話題になる。**

何を節目と呼ぶか:
  ・今季の区切り（30本塁打、100安打、150奪三振…）
  ・通算の区切り（通算300本塁打、通算1000安打…）
  ・自己最多（過去の最高を超えるまで）

  **予想はしない。**「あと3本」とだけ言う。届くかどうかは
  こちらには分からないし、外れたことを毎日言う番組になる。

投手の打撃成績は使わない:
  投手の hits / homeRuns は**打たれた数**で、打った数ではない。
  ここを取り違えると「佐々木朗希、あと少しで30本塁打」になる。
  種類ごとに見る項目を分けてある。

使い方:
  python3 scripts/milestones.py --recap data/morning_recap.json
"""

import argparse
import json
import pathlib
import sys
import urllib.request

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# (見出し, APIの項目, 区切り, ここまで近ければ出す)
#
# 「ここまで近ければ」は、残り試合で届きうる範囲。9月なら20試合前後
# なので、本塁打6本・安打15本あたりが上限。遠い節目を毎日出しても
# 「あと38本」では明日見る理由にならない。
SEASON_GOALS = {
    "hitting": (
        ("本塁打", "homeRuns", (10, 20, 25, 30, 35, 40, 45, 50, 60), 6),
        ("安打", "hits", (50, 100, 125, 150, 175, 200), 15),
        ("打点", "rbi", (50, 75, 100, 125), 12),
        ("盗塁", "stolenBases", (10, 20, 30, 40), 5),
        ("二塁打", "doubles", (20, 30, 40), 5),
    ),
    "pitching": (
        ("勝", "wins", (5, 10, 15, 20), 3),
        ("奪三振", "strikeOuts", (50, 100, 150, 200, 250, 300), 25),
        ("セーブ", "saves", (10, 20, 30, 40), 5),
        ("ホールド", "holds", (10, 20, 30), 5),
    ),
}

CAREER_GOALS = {
    "hitting": (
        ("通算本塁打", "homeRuns", (50, 100, 200, 300, 400, 500), 6),
        ("通算安打", "hits", (100, 500, 1000, 1500, 2000), 15),
        ("通算打点", "rbi", (100, 500, 1000), 12),
    ),
    "pitching": (
        ("通算勝利", "wins", (10, 50, 100, 150, 200), 3),
        ("通算奪三振", "strikeOuts", (100, 500, 1000, 1500, 2000), 25),
        ("通算セーブ", "saves", (50, 100, 200, 300), 5),
    ),
}


def _get(url: str):
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=25) as r:
        return json.load(r)


def _num(stat: dict, key: str):
    try:
        return int(stat.get(key))
    except (TypeError, ValueError):
        return None


def _next_goal(value: int, rungs: tuple, reach: int):
    """まだ届いていない区切りのうち、いちばん近いもの。遠ければ None。"""
    for g in rungs:
        if value < g:
            return (g, g - value) if g - value <= reach else None
    return None


def fetch(player_id: str, group: str, season: str = "2026") -> dict:
    """今季・通算・年ごと。1人につきAPIは1回。"""
    try:
        d = _get(f"{API}/people/{player_id}/stats?stats=season,career,"
                 f"yearByYear&season={season}&group={group}")
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] {player_id} の成績を取れません: {e}", file=sys.stderr)
        return {}
    out = {"season": {}, "career": {}, "years": []}
    for st in d.get("stats") or []:
        name = (st.get("type") or {}).get("displayName")
        sp = st.get("splits") or []
        if name == "yearByYear":
            out["years"] = [(s.get("season"), s.get("stat") or {}) for s in sp]
        elif name in ("season", "career") and sp:
            out[name] = sp[0].get("stat") or {}
    return out


def first_postseason(player: dict, postseason_path: str) -> dict:
    """ポストシーズン初出場が見えている選手。

    なぜこれを最優先にするか:
      「あと3本で35号」より、**「初めてのポストシーズンが見えてきた」**
      のほうが、その選手を追う理由になる。9月にしか出せない話でもある。

    出す条件は2つだけ。**どちらも公式で確かめられる。**
      ・その選手にポストシーズンの出場記録が1試合も無い
      ・いまその球団が進出圏内にいる（postseason.json の seed）

    「初出場する」とは書かない。書けるのは「初出場が見えている」まで。
    """
    pid = str(player.get("player_id") or "")
    name = player.get("name") or ""
    if not pid or not name:
        return {}
    try:
        rows = json.loads(pathlib.Path(postseason_path).read_text(
            encoding="utf-8")).get("japanese") or []
    except (OSError, json.JSONDecodeError):
        return {}
    seat = next((r for r in rows
                 if name in (r.get("players") or []) and r.get("seed")), None)
    if not seat:
        return {}
    group = "pitching" if player.get("type") == "pitcher" else "hitting"
    try:
        d = _get(f"{API}/people/{pid}/stats?stats=career&gameType=P"
                 f"&group={group}")
    except Exception:                            # noqa: BLE001
        return {}
    sp = (d.get("stats") or [{}])[0].get("splits") or []
    games = _num(sp[0].get("stat") or {}, "gamesPlayed") if sp else 0
    if games:
        return {}
    return {"name": name, "rank": -1, "gap": 0, "reach": 1,
            "kind": "ポストシーズン", "goal_text": "初出場が見えてきた",
            "prefix": "", "big": "圏内", "small": f"第{seat['seed']}シード",
            "text": f"ポストシーズン初出場が見えてきました。"
                    f"{seat.get('team')}はいま第{seat['seed']}シードです"}


def best_for(player: dict, season: str = "2026") -> dict:
    """その選手の、いちばん近い節目。無ければ空。

    近い順に選ぶ。**いちばん早く届くものが、いちばん見る理由になる。**
    同じくらい近いときは、自己最多 → 通算 → 今季の順で選ぶ。
    その順にしたのは、珍しさがその順だから。
    """
    pid = str(player.get("player_id") or "")
    if not pid:
        return {}
    group = "pitching" if player.get("type") == "pitcher" else "hitting"
    got = fetch(pid, group, season)
    if not got:
        return {}
    name = player.get("name") or ""
    cands = []

    for label, key, rungs, reach in SEASON_GOALS[group]:
        v = _num(got["season"], key)
        if v is None:
            continue
        hit = _next_goal(v, rungs, reach)
        if hit:
            cands.append({"name": name, "rank": 2, "gap": hit[1],
                          "reach": reach, "now": v, "goal": hit[0],
                          "unit": label, "kind": "今季",
                          "text": f"今季{hit[0]}{label}まで あと{hit[1]}"})

    for label, key, rungs, reach in CAREER_GOALS[group]:
        v = _num(got["career"], key)
        if v is None:
            continue
        hit = _next_goal(v, rungs, reach)
        if hit:
            cands.append({"name": name, "rank": 1, "gap": hit[1],
                          "reach": reach, "now": v, "goal": hit[0],
                          "unit": label.replace("通算", ""), "kind": "通算",
                          "text": f"{label}{hit[0]}まで あと{hit[1]}"})

    # 自己最多。**過去に2年以上ある選手だけ。**
    # 今年がMLB1年目の選手に「自己最多」は意味が無い。
    years = [(y, st) for y, st in got["years"] if y != str(season)]
    if years:
        for label, key, rungs, reach in SEASON_GOALS[group]:
            now = _num(got["season"], key)
            past = [_num(st, key) for _y, st in years]
            past = [x for x in past if x is not None]
            if now is None or not past:
                continue
            top = max(past)
            # 過去の最高そのものが小さいときは節目にしない。
            # 「自己最多の2ホールドまであと2」は誰の心も動かさない。
            # その種目のいちばん低い区切りに届いていることを条件にする。
            if top < rungs[0]:
                continue
            if 0 < top - now <= reach:
                cands.append({"name": name, "rank": 0, "gap": top - now,
                              "reach": reach, "now": now, "goal": top,
                              "unit": label, "kind": "自己最多",
                              "text": f"自己最多の{top}{label}まで "
                                      f"あと{top - now}"})
    if not cands:
        return {}
    # 単位が違うので、そのままの差では比べられない。
    # 「出す範囲」に対してどれだけ近いかで並べる。
    cands.sort(key=lambda c: (c["gap"] / c["reach"], c["rank"]))
    got = cands[0]
    # 画面はこの4つだけを見る。節目の種類が増えても描く側を触らずに済む。
    got.setdefault("goal_text", f"{got['goal']}{got['unit']}")
    got.setdefault("prefix", "あと")
    got.setdefault("big", str(got["gap"]))
    got.setdefault("small", f"いま{got['now']}")
    return got


def build(players: list, season: str = "2026", limit: int = 3,
          postseason_path: str = "data/postseason.json") -> list:
    """その日出た選手のうち、節目が近い順に。

    ポストシーズン初出場が見えている選手は先に見る。9月にしか
    出せない話で、数字の節目より追う理由になる。
    """
    out = []
    for p in players or []:
        got = first_postseason(p, postseason_path) or best_for(p, season)
        if got:
            out.append(got)
    out.sort(key=lambda c: (c["gap"] / c["reach"], c["rank"]))
    for c in out[:limit]:
        print(f"[info] {c['name']}: {c['text']}"
              + (f"（いま{c['now']}）" if "now" in c else ""))
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recap", default="data/morning_recap.json")
    ap.add_argument("--season", default="2026")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    try:
        data = json.loads(pathlib.Path(args.recap).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] {args.recap} を読めません: {e}", file=sys.stderr)
        return 0
    rows = build(data.get("players") or [], args.season)
    if not rows:
        print("[info] 近い節目はありませんでした")
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
