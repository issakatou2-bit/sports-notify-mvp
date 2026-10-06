#!/usr/bin/env python3
"""ポストシーズンの流れ（連勝・敵地での勝ち）を、日本人選手のいる球団について。

なぜ要るのか:
  10/6、本人「CWSの勢い、敵地4連勝とかもトピックとして上げたい。コメント欄とかも使いつつ」。
  ホワイトソックスはこのポストシーズン4勝0敗、4試合すべて敵地（アストロズで2勝・
  ガーディアンズで2勝）。1試合ずつの「試合の話題」では、この流れが見えない。

何を言うか（全部 MLB 公式の試合結果・成績表・順位表から。盛らない）:
  - このポストシーズンの勝敗と、敵地・本拠地の内訳（連勝が MIN_STREAK 以上のとき）
  - 1試合ずつのスコア、得点と失点の合計
  - 昨季までの歩み（2年以上続けて100敗以上、または3年以上続けて負け越しのときだけ）
  - 日本人選手のこのポストシーズンの通算（試合の成績表を足す）
  - 次の試合（日本時間・本拠地か敵地か・勝てば突破か）
  - ハイライトのコメントと番記者の投稿（その球団の試合のものだけ。出典つき）

次の試合が始まったら出さない。同じシリーズの間は1回だけ（キーにシリーズを入れる）。
出力: data/ps_momentum_topics.json（generated_topics 経由で、シーズンまとめの枠）
"""

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_game_story as gs  # noqa: E402
import ps_odds  # noqa: E402

API = "https://statsapi.mlb.com/api"
OUT = "data/ps_momentum_topics.json"
PS_TYPES = ("F", "D", "L", "W")
MIN_STREAK = 3


def _get(path: str, **params) -> dict:
    import requests
    r = requests.get(API + path, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def team_games(schedule: dict, tid: int) -> list:
    """その球団のこのポストシーズンの試合（終わったもの・これからのもの）。日時の順。"""
    out = []
    for day in schedule.get("dates") or []:
        for g in day.get("games") or []:
            a, h = g["teams"]["away"], g["teams"]["home"]
            if tid not in (a["team"]["id"], h["team"]["id"]) or g.get("gameType") not in PS_TYPES:
                continue
            out.append(g)
    return sorted(out, key=lambda g: g.get("gameDate") or "")


def finals(games: list) -> list:
    """勝者のある試合だけ（延期の行は数えない）。"""
    return [g for g in games if g["teams"]["away"].get("isWinner") or g["teams"]["home"].get("isWinner")]


def streak(games: list, tid: int) -> dict:
    """終わった試合の、最後からの連勝と、その中の敵地・本拠地。"""
    done = finals(games)
    n = road = 0
    opponents = []
    for g in reversed(done):
        me = "away" if g["teams"]["away"]["team"]["id"] == tid else "home"
        if not g["teams"][me].get("isWinner"):
            break
        n += 1
        if me == "away":
            road += 1
        opp = g["teams"]["home" if me == "away" else "away"]["team"]
        opponents.append((opp["id"], opp.get("name", ""), me))
    wins = sum(1 for g in done if g["teams"]["away" if g["teams"]["away"]["team"]["id"] == tid
                                            else "home"].get("isWinner"))
    return {"streak": n, "road": road, "wins": wins, "losses": len(done) - wins,
            "opponents": list(reversed(opponents)), "games": done}


def score_line(g: dict, tid: int) -> str:
    me = "away" if g["teams"]["away"]["team"]["id"] == tid else "home"
    other = "home" if me == "away" else "away"
    return f"{g['teams'][me].get('score')}対{g['teams'][other].get('score')}"


def history_line(records: list):
    """昨季までの歩み。records は [(年, 勝, 敗)] の新しい順。言えることが無ければ None。"""
    hundred = []
    for y, w, l in records:
        if l >= 100:
            hundred.append((y, w, l))
        else:
            break
    if len(hundred) >= 2:
        worst = max(hundred, key=lambda r: r[2])
        start = min(r[0] for r in hundred)
        return (f"{start}年から{len(hundred)}年続けて100敗以上"
                f"（{worst[0]}年は{worst[1]}勝{worst[2]}敗）")
    losing = []
    for y, w, l in records:
        if l > w:
            losing.append(y)
        else:
            break
    if len(losing) >= 3:
        return f"{min(losing)}年から{len(losing)}年続けて負け越し"
    return None


def clinches(schedule: dict, tid: int) -> list:
    """その年のシリーズで、その球団が突破を決めた試合 [(日付, シリーズ名, 本拠地か)]。

    シリーズは (gameType, seriesDescription) でまとめる。勝者の無い行（延期・引き分け）は数えない。
    まだ終わっていない試合のあるシリーズは数えない。
    """
    groups = {}
    for g in team_games(schedule, tid):
        groups.setdefault((g.get("gameType"), g.get("seriesDescription") or ""), []).append(g)
    out = []
    for (_, desc), games in groups.items():
        if any((g.get("status") or {}).get("abstractGameState") != "Final" for g in games):
            continue
        done = finals(games)
        if not done:
            continue
        me = lambda g: "away" if g["teams"]["away"]["team"]["id"] == tid else "home"  # noqa: E731
        wins = sum(1 for g in done if g["teams"][me(g)].get("isWinner"))
        if wins * 2 <= len(done) or not done[-1]["teams"][me(done[-1])].get("isWinner"):
            continue
        out.append(((done[-1].get("gameDate") or "")[:10], desc, me(done[-1]) == "home"))
    return out


def last_home_clinch(tid: int, season: int, get=None, first: int = 1903):
    """本拠地でシリーズ突破を最後に決めた (年, シリーズ名)。見つからなければ None（言わない）。"""
    get = get or _get
    for y in range(season, first - 1, -1):
        sched = get("/v1/schedule", sportId=1, season=y, gameType=",".join(PS_TYPES), teamId=tid)
        home = [c for c in clinches(sched, tid) if c[2]]
        if home:
            return y, max(home)[1]
    return None


SERIES_JP = {"World Series": "ワールドシリーズ優勝"}


def home_clinch_line(found, season: int):
    """「勝てば」の一言。20年以上空いているときだけ（それより近いなら珍しくない）。"""
    if not found or season - found[0] < 20:
        return None
    y, desc = found
    name = SERIES_JP.get(desc)
    if not name:
        name = ("リーグ優勝決定シリーズ" if "Championship" in desc else
                "地区シリーズ" if "Division" in desc else
                "ワイルドカードシリーズ" if "Wild Card" in desc else "ポストシーズン")
    return f"本拠地でのシリーズ突破は、{y}年の{name}以来{season - y}年ぶり"


def jp_lines(boxes: list, tid: int, jp: dict) -> list:
    """日本人選手のこのポストシーズンの通算（試合の成績表を足す）。出場した選手だけ。"""
    tot = {}
    for box in boxes:
        side = "away" if box["teams"]["away"]["team"]["id"] == tid else "home"
        for p in (box["teams"][side].get("players") or {}).values():
            name = p["person"]["fullName"]
            if name not in jp:
                continue
            t = tot.setdefault(name, {"g": 0, "ab": 0, "h": 0, "hr": 0, "rbi": 0, "outs": 0, "er": 0, "so": 0})
            b = p.get("stats", {}).get("batting") or {}
            pi = p.get("stats", {}).get("pitching") or {}
            played = False
            if b.get("plateAppearances"):
                t["ab"] += b.get("atBats") or 0
                t["h"] += b.get("hits") or 0
                t["hr"] += b.get("homeRuns") or 0
                t["rbi"] += b.get("rbi") or 0
                played = True
            if pi.get("inningsPitched"):
                whole, _, part = str(pi["inningsPitched"]).partition(".")
                t["outs"] += int(whole) * 3 + int(part or 0)
                t["er"] += pi.get("earnedRuns") or 0
                t["so"] += pi.get("strikeOuts") or 0
                played = True
            if played:
                t["g"] += 1
    out = []
    for name, t in tot.items():
        if not t["g"]:
            continue
        if t["ab"] or not t["outs"]:
            line = f"{t['g']}試合で{t['ab']}打数{t['h']}安打"
            if t["hr"]:
                line += f"　{t['hr']}本塁打"
            if t["rbi"]:
                line += f"　{t['rbi']}打点"
        else:
            ip = f"{t['outs'] // 3}回" + ({1: "と3分の1", 2: "と3分の2"}.get(t["outs"] % 3, ""))
            line = f"{t['g']}試合で{ip}　自責{t['er']}　{t['so']}奪三振"
        out.append((jp[name], line))
    return out


def story(team: dict, series: dict, games: list, boxes: list, last_feed: dict, records: list,
          now: datetime, voices: dict, quotes: list, table: dict, jp: dict, current: str = "",
          home_clinch=None) -> dict:
    tid = team["id"]
    s = streak(games, tid)
    if s["streak"] < MIN_STREAK or not team.get("players"):
        return {}
    nxt = next((g for g in games if not (g["teams"]["away"].get("isWinner") or g["teams"]["home"].get("isWinner"))
                and (g.get("status") or {}).get("abstractGameState") != "Final"), None)
    if not nxt or not nxt.get("gameDate"):
        return {}
    start = datetime.fromisoformat(nxt["gameDate"].replace("Z", "+00:00"))
    if start <= now:
        return {}
    name = team["name"]
    jpn = "・".join(team["players"][:2])
    n, road = s["streak"], s["road"]
    if road == n:
        where = f"{n}試合すべて敵地"
        opp = {}
        for oid, oname, _ in s["opponents"]:
            k = ps_odds.team_jp(oid, oname)
            opp[k] = opp.get(k, 0) + 1
        detail = "・".join(f"{k}で{v}勝" for k, v in opp.items())
        where_body = f"{where}（{detail}）"
    else:
        where = f"敵地で{road}勝"
        where_body = f"敵地で{road}勝・本拠地で{n - road}勝"
    rec = f"{s['wins']}勝{s['losses']}敗"
    items = [("このポストシーズン", f"{rec}　{n}連勝　{where_body}")]
    streak_games = s["games"][-n:]
    runs_for = sum(int(g["teams"]["away" if g["teams"]["away"]["team"]["id"] == tid else "home"].get("score") or 0)
                   for g in streak_games)
    runs_against = sum(int(g["teams"]["home" if g["teams"]["away"]["team"]["id"] == tid else "away"].get("score") or 0)
                       for g in streak_games)
    items.append((f"{n}試合のスコア", "・".join(score_line(g, tid) for g in streak_games)
                  + f"　得点{runs_for}・失点{runs_against}"))
    hist = history_line(records)
    if hist:
        items.append(("ここまでの歩み", hist + (f"　今季は{current}" if current else "")))
    for jname, line in jp_lines(boxes, tid, jp):
        items.append((f"{jname}のポストシーズン", line))
    home = nxt["teams"]["home"]["team"]["id"] == tid
    need = series.get("need") or 0
    my_wins = next((t["wins"] for t in series.get("teams") or [] if t["id"] == tid), 0)
    clinch = "　勝てば突破" if need and my_wins == need - 1 else ""
    items.append(("次の試合", f"日本時間{ps_odds.jst_label(nxt['gameDate'])}　"
                             f"{'本拠地' if home else '敵地'}で{series.get('round_jp') or ''}"
                             f"第{nxt.get('seriesGameNumber') or (s['wins'] + s['losses'] + 1)}戦{clinch}"))
    season = int((nxt.get("gameDate") or "0000")[:4])
    rare = home_clinch_line(home_clinch, season) if clinch and home else None
    if rare:
        items.append(("勝てば", rare))
    # 声（最後の試合の後のもの）
    after = (s["games"][-1].get("gameDate") or "")[:19]
    words = gs.team_words(last_feed) if last_feed else {}
    voice = source = None
    if last_feed:
        v = gs.pick_voice(voices, last_feed, after, words, table, jp, team["players"])
        if v:
            items.append(("ハイライトのコメント欄から", gs.quoted(v["said"])))
            voice = v
        q = gs.pick_reporter(quotes, name, after, words, table, jp, team["players"])
        if q:
            items.append((f"{name}の番記者の投稿から", gs.quoted(q["said"])))
            source = q
    import notability_engine as ne
    head = f"{jpn}の{name}がポストシーズン{n}連勝"
    hook2 = f"勝てば本拠地で{season - home_clinch[0]}年ぶりの突破" if rare else where
    title = f"【MLB】{head}｜{hook2} #Shorts"
    intro = f"{jpn}の{name}は、このポストシーズン{n}連勝。" + (
        f"{n}試合すべて敵地での勝利です。" if road == n else f"そのうち{road}勝は敵地です。")
    # 新デザイン（電光掲示板、review_render_v3）の表紙に置くもの。読み上げには使わない。
    short = {"F": "WCS", "D": "地区S", "L": "リーグ優勝決定S", "W": "WS"}
    chips = []
    for g in streak_games:
        me = "away" if g["teams"]["away"]["team"]["id"] == tid else "home"
        opp = g["teams"]["home" if me == "away" else "away"]["team"]
        num = g.get("seriesGameNumber")
        chips.append({"label": f"{short.get(g.get('gameType'), '')}{f'第{num}戦' if num else ''}　"
                               f"{'敵地' if me == 'away' else '本拠地'}{ps_odds.team_jp(opp['id'], opp.get('name', ''))}",
                      "score": score_line(g, tid).replace("対", "-"), "win": True})
    next_line = dict(items)["次の試合"]
    v3 = {"who": f"{jpn}の{name}", "big": str(n), "unit": "連勝", "sub": f"ポストシーズン {rec}",
          "tag": where, "chips": chips[-4:],
          "ticker": "次の試合　" + (next_line.replace("　勝てば突破", "") + f"　{hook2}" if rare else next_line)}
    key = "season_momentum_" + re.sub(r"[^0-9A-Za-z]", "_", series.get("key") or str(tid)) + f"_{tid}"
    return {
        "key": key, "label": f"{name}の{n}連勝", "hook": head,
        "heading": f"{name}　ポストシーズン{rec}", "intro": intro, "intro_as_is": True,
        "style": "v3", "v3": v3, "team_id": tid, "abbr": ne.MLB_TEAM_ABBR.get(str(tid), ""),
        "title": title, "items": items, "japanese": [], "ps_ended": True, "story": True,
        "momentum": True, "source": source, "voice": voice, "series_key": series.get("key"),
        "next_game": nxt["gameDate"], "streak": n, "road": road,
        "home_clinch": list(home_clinch) if rare else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--postseason", default="data/postseason.json")
    ap.add_argument("--voices", default="data/local_voices.json")
    ap.add_argument("--quotes", default="data/ps_quotes.json")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    def load(path, key=None, default=None):
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            return d.get(key) if key else d
        except (OSError, json.JSONDecodeError):
            return default
    ps = load(args.postseason, default={}) or {}
    voices = load(args.voices, default={}) or {}
    quotes = load(args.quotes, "posts", []) or []
    previous = {t["key"]: t for t in (load(args.out, "topics", []) or [])}
    import notability_engine as ne
    jp = {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}
    table = (load("data/player_kana.json", "names", {}) or {})
    season = int(ps.get("season") or now.year)
    topics = []
    try:
        sched = _get("/v1/schedule", sportId=1, season=season, gameType=",".join(PS_TYPES), hydrate="team")
        for row in ps.get("series") or []:
            if row.get("over"):
                continue
            for team in row.get("teams") or []:
                games = team_games(sched, team["id"])
                if streak(games, team["id"])["streak"] < MIN_STREAK or not team.get("players"):
                    continue
                done = finals(games)
                boxes = [_get(f"/v1/game/{g['gamePk']}/boxscore") for g in done[-streak(games, team['id'])['streak']:]]
                last_feed = _get(f"/v1.1/game/{done[-1]['gamePk']}/feed/live")
                records = []
                for y in range(season - 1, season - 6, -1):
                    st = _get("/v1/standings", leagueId="103,104", season=y, standingsTypes="regularSeason")
                    r = next((t for rec in st.get("records") or [] for t in rec.get("teamRecords") or []
                              if t["team"]["id"] == team["id"]), None)
                    if r:
                        records.append((y, r["wins"], r["losses"]))
                cur = _get("/v1/standings", leagueId="103,104", season=season, standingsTypes="regularSeason")
                me = next((t for rec in cur.get("records") or [] for t in rec.get("teamRecords") or []
                           if t["team"]["id"] == team["id"]), None)
                current = f"{me['wins']}勝{me['losses']}敗" if me else ""
                # 次が本拠地で勝てば突破の試合のときだけ、過去の本拠地での突破を遡る（年に1回ずつ呼ぶ）
                nxt = next((g for g in games if (g.get("status") or {}).get("abstractGameState") != "Final"), None)
                need = row.get("need") or 0
                mine = next((x["wins"] for x in row.get("teams") or [] if x["id"] == team["id"]), 0)
                found = None
                if nxt and need and mine == need - 1 and nxt["teams"]["home"]["team"]["id"] == team["id"]:
                    old = next((x for x in previous.values() if x.get("team_id") == team["id"]
                                and x.get("home_clinch")), None)
                    found = tuple(old["home_clinch"]) if old else last_home_clinch(team["id"], season)
                t = story(team, row, games, boxes, last_feed, records, now, voices, quotes, table, jp, current,
                          found)
                if t:
                    old = previous.get(t["key"]) or {}
                    # 声は取れた日のものを残す（翌日にはハイライトの一覧から外れていることがある）
                    if not t.get("voice") and old.get("voice"):
                        t["voice"] = old["voice"]
                        t["items"].insert(-1 if t["items"][-1][0].endswith("番記者の投稿から") else len(t["items"]),
                                          ("ハイライトのコメント欄から", gs.quoted(old["voice"]["said"])))
                    topics.append(t)
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] 流れの話題を作れません({e})", file=sys.stderr)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": now.isoformat(),
         "source": "MLB Stats API（試合結果・成績表・順位表）・ハイライトのコメント・番記者の投稿",
         "topics": topics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print("  " + t["title"])
        for a, b in t["items"]:
            print(f"     {a} | {b}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
