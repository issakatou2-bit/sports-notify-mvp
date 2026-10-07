#!/usr/bin/env python3
"""ポストシーズンで日本人投手が圧巻の投球をした試合の、投手ひとりに絞った話題。

なぜ要るのか:
  10/7、本人「今日の山本の圧巻の投球もショートにしたい」。試合の話題（ps_game_story）は
  試合全体の話で、投手の中身（球種・空振り・最速・三振を取った球）までは言えない。

何を言うか（全部 MLB 公式の成績表と試合経過〔投球ごとの記録〕から。盛らない）:
  - きょうの投球（回・安打・失点・奪三振・四球・球数）、勝ち負け
  - 空振りの数、見逃しと空振りのストライクの数
  - 最速（マイルをキロに直す）
  - 球種ごとの数と、三振を取った球
  - 試合の結果とシリーズの勝敗、次の試合
選ぶ条件: 6回以上で自責1以下、または9奪三振以上。試合が終わって36時間以内。
出力: data/ps_spotlight_topics.json（generated_topics 経由で、シーズンまとめの枠。v3）
"""

import argparse
import collections
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_odds  # noqa: E402

API = "https://statsapi.mlb.com/api"
OUT = "data/ps_spotlight_topics.json"
PS_TYPES = "F,D,L,W"
ROUND_JP = {"F": "ワイルドカードシリーズ", "D": "地区シリーズ", "L": "リーグ優勝決定シリーズ", "W": "ワールドシリーズ"}
PITCH_JP = {"Four-Seam Fastball": "フォーシーム", "Splitter": "スプリット", "Curveball": "カーブ",
            "Cutter": "カッター", "Sinker": "シンカー", "Slider": "スライダー", "Sweeper": "スイーパー",
            "Changeup": "チェンジアップ", "Knuckle Curve": "ナックルカーブ", "Slurve": "スラーブ",
            "Two-Seam Fastball": "ツーシーム", "Forkball": "フォーク", "Split-Finger": "スプリット"}
WINDOW_HOURS = 36


def _get(path, **params):
    import requests
    r = requests.get(API + path, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def notable(line: dict) -> bool:
    ip = str(line.get("inningsPitched") or "0")
    whole, _, part = ip.partition(".")
    outs = int(whole) * 3 + int(part or 0)
    return (outs >= 18 and (line.get("earnedRuns") or 0) <= 1) or (line.get("strikeOuts") or 0) >= 9


def pitch_stats(feed: dict, pid: int) -> dict:
    """投球ごとの記録から、空振り・見逃しと空振りのストライク・最速・球種・三振の球。"""
    types, ks = collections.Counter(), collections.Counter()
    whiff = csw = 0
    top = 0.0
    for play in feed["liveData"]["plays"]["allPlays"]:
        if play["matchup"]["pitcher"]["id"] != pid:
            continue
        last = None
        for ev in play.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            d = ev.get("details") or {}
            kind = (d.get("type") or {}).get("description")
            if kind:
                types[kind] += 1
                last = kind
            call = (d.get("call") or {}).get("description", "")
            if "Swinging Strike" in call or call == "Foul Tip":
                whiff += 1
            if "Called Strike" in call or "Swinging Strike" in call:
                csw += 1
            top = max(top, float((ev.get("pitchData") or {}).get("startSpeed") or 0))
        if (play.get("result") or {}).get("eventType") == "strikeout" and last:
            ks[last] += 1
    return {"types": types, "ks": ks, "whiff": whiff, "csw": csw, "top_mph": top}


def _jp_pitch(name):
    return PITCH_JP.get(name)


def story(game: dict, box: dict, feed: dict, pid: int, name_jp: str, nxt=None) -> dict:
    side = next(s for s in ("away", "home") if str(pid) in {k[2:] for k in box["teams"][s]["players"]})
    p = box["teams"][side]["players"][f"ID{pid}"]
    line = p["stats"]["pitching"]
    tid = box["teams"][side]["team"]["id"]
    opp = box["teams"]["home" if side == "away" else "away"]["team"]
    team_jp = ps_odds.team_jp(tid, box["teams"][side]["team"].get("name", ""))
    opp_jp = ps_odds.team_jp(opp["id"], opp.get("name", ""))
    ps = pitch_stats(feed, pid)
    if any(_jp_pitch(k) is None for k in ps["types"]):
        return {}                                              # 日本語にできない球種がある日は出さない
    ip = str(line["inningsPitched"]).replace(".0", "")
    ip_jp = ip if "." not in ip else ip.replace(".1", "回と3分の1").replace(".2", "回と3分の2")
    ip_jp = ip_jp if "回" in ip_jp else f"{ip_jp}回"
    rnd = ROUND_JP.get(game.get("gameType"), "ポストシーズン")
    num = game.get("seriesGameNumber")
    runs = feed["liveData"]["linescore"]["teams"]
    mine, theirs = runs[side]["runs"], runs["home" if side == "away" else "away"]["runs"]
    won = mine > theirs
    decision = "勝ち投手" if "(W" in (line.get("note") or "") else "負け投手" if "(L" in (line.get("note") or "") else ""
    kmh = round(ps["top_mph"] * 1.609344, 1)
    order = [k for k, _ in ps["types"].most_common()]
    mix = "・".join(f"{_jp_pitch(k)}{ps['types'][k]}" for k in order)
    kmix = "・".join(f"{_jp_pitch(k)}{v}" for k, v in ps["ks"].most_common())
    total = sum(ps["types"].values())
    items = [
        ("この試合の投球", f"{ip_jp}　{line['hits']}安打　{line['runs']}失点　{line['strikeOuts']}奪三振　"
                     f"{line['baseOnBalls']}四球（{line['numberOfPitches']}球）"),
        ("空振り", f"{ps['whiff']}回（{total}球中）　見逃しと空振りのストライクは{ps['csw']}球"),
        ("最速", f"{kmh}キロ（{ps['top_mph']:.1f}マイル）"),
        ("投げた球", mix),
        ("三振を取った球", kmix),
        ("試合", f"{team_jp} {mine}対{theirs} {opp_jp}　{rnd}第{num}戦" + (f"　{name_jp}が{decision}" if decision else "")),
    ]
    ticker = ""
    if nxt:
        items.append(("次の試合", f"日本時間{ps_odds.jst_label(nxt['gameDate'])}　{rnd}第{nxt.get('seriesGameNumber')}戦"))
        ticker = "次の試合　" + items[-1][1]
    import notability_engine as ne
    head = f"{name_jp}が{ip_jp}{line['runs']}失点{line['strikeOuts']}奪三振"
    chips = [{"label": f"三振の球　{_jp_pitch(k)}", "score": str(v), "win": False} for k, v in ps["ks"].most_common(3)]
    chips.append({"label": "球数", "score": str(line["numberOfPitches"]), "win": False})
    return {
        "key": f"season_spotlight_{game['gamePk']}_{pid}",
        "label": f"{name_jp}の投球", "hook": head,
        "heading": f"{name_jp}　{rnd}第{num}戦",
        "intro": f"{name_jp}は{rnd}第{num}戦で{ip_jp}を投げて{line['runs']}失点、"
                 f"{line['strikeOuts']}個の三振を奪いました。",
        "intro_as_is": True,
        "title": f"【MLB】{head}｜最速{kmh}キロ・空振り{ps['whiff']} #Shorts",
        "items": items, "japanese": [], "jp": name_jp,
        "style": "v3", "team_id": tid, "abbr": ne.MLB_TEAM_ABBR.get(str(tid), ""),
        "v3": {"who": f"{name_jp}　{team_jp}", "big": str(line["strikeOuts"]), "unit": "奪三振",
               "sub": f"{ip_jp}{line['runs']}失点" + (f"　{decision}" if decision else ""),
               "tag": f"最速{kmh}キロ　空振り{ps['whiff']}", "chips": chips, "ticker": ticker},
        "ps_ended": True, "story": True, "spotlight": True, "jp_first": True,
        "game_date": game.get("gameDate"), "won": won,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--game", type=int, help="試合を指定（確認用）")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    import notability_engine as ne
    jp = {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}
    topics = []
    try:
        season = now.year
        sched = _get("/v1/schedule", sportId=1, season=season, gameType=PS_TYPES)
        games = [g for d in sched.get("dates") or [] for g in d.get("games") or []]
        for g in games:
            if args.game and g["gamePk"] != args.game:
                continue
            if (g.get("status") or {}).get("abstractGameState") != "Final":
                continue
            start = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
            if not args.game and not (now - timedelta(hours=WINDOW_HOURS) <= start <= now):
                continue
            box = _get(f"/v1/game/{g['gamePk']}/boxscore")
            feed = None
            for side in ("away", "home"):
                for p in box["teams"][side]["players"].values():
                    name = p["person"]["fullName"]
                    line = (p.get("stats") or {}).get("pitching") or {}
                    if name not in jp or not line.get("inningsPitched") or not notable(line):
                        continue
                    feed = feed or _get(f"/v1.1/game/{g['gamePk']}/feed/live")
                    teams = {g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"]}
                    nxt = next((x for x in games if x.get("gameType") == g.get("gameType")
                                and {x["teams"]["away"]["team"]["id"], x["teams"]["home"]["team"]["id"]} == teams
                                and x["gameDate"] > g["gameDate"]
                                and (x.get("status") or {}).get("abstractGameState") != "Final"), None)
                    t = story(g, box, feed, p["person"]["id"], jp[name], nxt)
                    if t:
                        topics.append(t)
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] 投手の話題を作れません({e})", file=sys.stderr)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": now.isoformat(), "source": "MLB Stats API（成績表・試合経過）", "topics": topics},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print("  " + t["title"])
        for a, b in t["items"]:
            print(f"     {a} | {b}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
