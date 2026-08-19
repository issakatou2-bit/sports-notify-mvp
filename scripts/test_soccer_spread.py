#!/usr/bin/env python3
"""
サッカーの選び方を、実際の日程で確かめる。

なぜ要るのか:
  「5大リーグが同じ日に48試合ある」と仮定して回したら、
  3枠の6割がブンデスリーガになった。それを見て偏りを直そうとしたが、
  実際の日程で回すと偏っていなかった。開幕日が12日ずれていて
  (2026年はラ・リーガ8/16、ブンデス8/28)、試合も日にちに散るので、
  そもそも1日に5リーグ揃うことがない。

  作ったデータで出した結論は、作った前提の結論でしかない。
  data/soccer_preview.json に本物の日程があるので、そちらで測る。

見るもの:
  ・1つのリーグに枠が偏っていないか
  ・試合が1〜2しか無い日に、枠が空いてしまわないか

使い方:
  python3 scripts/test_soccer_spread.py
"""

import json
import pathlib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    SOCCER_GAME_RULES,
    SOCCER_LEAGUE_NAME_JP,
    SOCCER_MIN_NOTABLE,
    Game,
    _spread_across_leagues,
    score_game,
)

JST = timezone(timedelta(hours=9))
PREVIEW = "data/soccer_preview.json"

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok' if ok else 'NG'}  {label}: {got}")


def load_days() -> dict:
    try:
        d = json.loads(pathlib.Path(PREVIEW).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    days = defaultdict(list)
    for c in d.get("competitions", []):
        lg = SOCCER_LEAGUE_NAME_JP.get(c.get("code") or "", c.get("code") or "")
        seen = set()
        for m in (c.get("openers") or []) + (c.get("early") or []):
            key = (m.get("utc"), m.get("home"), m.get("away"))
            if key in seen or not m.get("utc"):
                continue
            seen.add(key)
            try:
                t = datetime.fromisoformat(m["utc"].replace("Z", "+00:00"))
            except ValueError:
                continue
            days[t.astimezone(JST).strftime("%Y-%m-%d")].append(
                (lg, m.get("home", ""), m.get("away", "")))
    return days


def main() -> int:
    days = load_days()
    if not days:
        print("[info] 日程データが無いため、この検査は飛ばします")
        return 0

    tally, short_days, empty = Counter(), 0, 0
    for day, games in sorted(days.items()):
        scored = []
        for lg, h, a in games:
            g = Game(game_id="", league=lg, home_team_id="", away_team_id="",
                     home_team_name=h, away_team_name=a)
            reasons = []
            for rule in SOCCER_GAME_RULES:
                reasons += rule(g)
            scored.append({"league": lg, "score": score_game(reasons)})
        scored.sort(key=lambda x: -x["score"])
        picked = _spread_across_leagues(scored, SOCCER_MIN_NOTABLE)
        for p in picked:
            tally[p["league"]] += 1
        # 試合が足りている日は、必ず3枠埋まっていること
        if len(games) >= SOCCER_MIN_NOTABLE and len(picked) < SOCCER_MIN_NOTABLE:
            empty += 1
        if len(games) < SOCCER_MIN_NOTABLE:
            short_days += 1
            if len(picked) != len(games):
                empty += 1

    total = sum(tally.values())
    print(f"{len(days)}日 / 選ばれた枠 {total}")
    for lg, n in tally.most_common():
        print(f"    {lg:16s} {n:3d}枠  {n / total * 100:4.1f}%")
    print(f"  試合が3つ未満の日: {short_days}日")

    check("枠が空いた日", empty, 0)
    # 1つのリーグが半分を超えたら、選び方か重みのどちらかが偏っている
    top = tally.most_common(1)[0][1] if tally else 0
    check("いちばん多いリーグが全体の半分未満", top * 2 < total, True)

    print("\nALL OK" if not fails else f"\n{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
