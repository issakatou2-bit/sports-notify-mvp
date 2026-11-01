#!/usr/bin/env python3
"""ポストシーズンの話題（決着したシリーズの「何が起きたか」）。

なぜ要るのか:
  10/3、本人「PSに関連した話題も拾っていきたい。たとえばCHCは打線が全く
  機能せずSDに敗退、PCAも見どころ作れず、みたいなのを。事実を並べて、
  ハイライトのコメントや記事を拾って」。速報（勝った・負けた）だけでは
  一過性になる。シリーズを集計して、何が起きたかを数字で言う。

何を言うか（全部 MLB 公式の成績表から集計。言い方は数字が条件を満たした
ときだけ選ぶ。盛らない）:
  - 打線の沈黙: シリーズの1試合平均得点が、今季の半分未満
  - 主力の不振: 今季の本塁打1位・2位が、シリーズで6打数以上・打率.150未満
  - 勝った側の主役: シリーズで4安打以上 / 2本塁打以上 / 4打点以上
  - 日本人選手のシリーズの成績（両方の球団）
  - 現地の声: 番記者の投稿（ps_quotes.py が貯めたもの）から1つ。出典つき。
    英字の名前をカタカナにできない引用は使わない（読み上げが崩れる）

出力: data/ps_story_topics.json（generated_topics 経由で、シーズンまとめと
同じ描画・題・説明。シーズンまとめの枠で先に出す）
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

API = "https://statsapi.mlb.com/api/v1"
SEASON = "2026"
OUT = "data/ps_story_topics.json"
ROUND_SHORT = {"F": "WCS", "D": "地区シリーズ", "L": "リーグ優勝決定シリーズ",
               "W": "ワールドシリーズ"}


def _get(path: str, **params) -> dict:
    import requests
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def series_games(row: dict, start: str, end: str) -> list:
    """そのシリーズの終わった試合（日付順）。"""
    ids = {t["id"] for t in row["teams"]}
    tid = row["teams"][0]["id"]
    d = _get("schedule", sportId=1, gameType=row["round"], teamId=tid,
             startDate=start, endDate=end)
    out = []
    for dt in d.get("dates") or []:
        for g in dt.get("games") or []:
            teams = {g["teams"][s]["team"]["id"] for s in ("home", "away")}
            if teams == ids and g["status"].get("abstractGameState") == "Final":
                out.append(g)
    return sorted(out, key=lambda g: g.get("gameDate") or "")


def tally(games: list) -> dict:
    """{球団ID: {R,H,AB,HR,SO, players:{名前:{AB,H,HR,RBI,SO,IP,ER,K}}}}"""
    tot = {}
    for g in games:
        bx = _get(f"game/{g['gamePk']}/boxscore")
        for side in ("home", "away"):
            t = bx["teams"][side]
            a = tot.setdefault(t["team"]["id"], {"R": 0, "H": 0, "AB": 0, "HR": 0,
                                                 "SO": 0, "scores": [], "players": {}})
            bs = t["teamStats"]["batting"]
            for k, kk in (("R", "runs"), ("H", "hits"), ("AB", "atBats"),
                          ("HR", "homeRuns"), ("SO", "strikeOuts")):
                a[k] += bs.get(kk, 0) or 0
            opp = bx["teams"]["away" if side == "home" else "home"]
            a["scores"].append((bs.get("runs", 0), opp["teamStats"]["batting"].get("runs", 0)))
            for p in t["players"].values():
                name = p["person"]["fullName"]
                b = p["stats"].get("batting") or {}
                pi = p["stats"].get("pitching") or {}
                if not b and not pi:
                    continue
                q = a["players"].setdefault(name, {"AB": 0, "H": 0, "HR": 0, "RBI": 0,
                                                   "SO": 0, "outs": 0, "ER": 0, "K": 0,
                                                   "id": p["person"]["id"]})
                q["AB"] += b.get("atBats", 0) or 0
                q["H"] += b.get("hits", 0) or 0
                q["HR"] += b.get("homeRuns", 0) or 0
                q["RBI"] += b.get("rbi", 0) or 0
                q["SO"] += b.get("strikeOuts", 0) or 0
                ip = str(pi.get("inningsPitched") or "0")
                whole, _, part = ip.partition(".")
                q["outs"] += int(whole or 0) * 3 + int(part or 0)
                q["ER"] += pi.get("earnedRuns", 0) or 0
                q["K"] += pi.get("strikeOuts", 0) or 0
    return tot


def avg_text(h: int, ab: int) -> str:
    if not ab:
        return ".---"
    v = h / ab
    return ("%.3f" % v).lstrip("0") if v < 1 else "%.3f" % v


def season_team(tid: int) -> dict:
    import mlb_splits
    d = _get(f"teams/{tid}/stats", stats="season", group="hitting", season=SEASON)
    return mlb_splits.season_stat((d.get("stats") or [{}])[0].get("splits") or [])


def season_hr_leaders(tid: int, n: int = 2) -> list:
    d = _get("stats", stats="season", group="hitting", season=SEASON, teamId=tid,
             playerPool="ALL", limit=100, gameType="R")
    # 球団で絞った一覧なので、移籍した選手もこの球団での数字だけ。
    # 合計の行（numTeams）が混じったら使わない。
    rows = [x for x in (d.get("stats") or [{}])[0].get("splits") or [] if not x.get("numTeams")]
    rows.sort(key=lambda x: -(x["stat"].get("homeRuns") or 0))
    return [(x["player"]["fullName"], x["stat"].get("homeRuns") or 0) for x in rows[:n]
            if (x["stat"].get("homeRuns") or 0) >= 15]


# ---------------------------------------------------------------- 名前

def kana_of(name_en: str, table: dict, jp: dict) -> str:
    if name_en in jp:
        return jp[name_en]
    if name_en not in table:
        try:
            import player_kana
            table[name_en] = player_kana.lookup(name_en)
        except Exception:                                    # noqa: BLE001
            table[name_en] = ""
    return table.get(name_en) or ""


LATIN = re.compile(r"[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+)*")


def speakable(text: str, table: dict, jp: dict) -> str:
    """訳文の英字の名前をカタカナに。できない名前が残れば空（使わない）。

    **1語だけの英字は、辞書（選手名の表・日本人選手）にあるときだけ変える。**
    10/6、ファンのコメント「60 yrs a Sox fan」の「Sox」を人名として引きに行き、
    「ボストン・レッドソックス」と読み替えた（ホワイトソックスの試合の声）。
    1語は球団の愛称・地名・普通の単語のことが多く、人名の検索に向かない。
    日本人選手は姓だけでも分かる（Murakami → 村上宗隆）。
    """
    surnames = {}
    for en, ja in jp.items():
        last = en.split()[-1]
        surnames[last] = None if last in surnames else ja   # 同じ姓が2人なら使わない

    def sub(m):
        word = m.group(0)
        if " " not in word.strip():
            if word in table and table[word]:
                return table[word]
            return surnames.get(word) or word
        k = kana_of(word, table, jp)
        return k or word
    out = LATIN.sub(sub, text or "")
    return "" if re.search(r"[A-Za-z]{2,}", out) else out


# ---------------------------------------------------------------- 話題

def story(row: dict, games: list, tot: dict, kana_table: dict, jp: dict,
          quotes: list) -> dict:
    win = next(t for t in row["teams"] if t["id"] == row["winner"])
    lose = next(t for t in row["teams"] if t["id"] != row["winner"])
    W, L = tot.get(win["id"]), tot.get(lose["id"])
    if not W or not L:
        return {}
    n = len(games)
    rnd = ROUND_SHORT.get(row["round"], row.get("round_jp", ""))
    scores = "、".join(f"{a}対{b}" for a, b in L["scores"])
    items = [("シリーズの結果", f"{win['name']}が{win['wins']}勝{lose['wins']}敗"
                             f"（{lose['name']}から見て {scores}）")]
    angles = []
    # 打線の沈黙
    st = season_team(lose["id"])
    rpg = (st.get("runs") or 0) / max(1, st.get("gamesPlayed") or 1)
    if n and L["R"] / n < rpg / 2:
        items.append((f"{lose['name']}の得点", f"{n}試合で計{L['R']}点　"
                      f"今季は1試合平均{rpg:.1f}点"))
        items.append((f"{lose['name']}のチーム打率",
                      f"{n}試合で{avg_text(L['H'], L['AB'])}（{L['AB']}打数{L['H']}安打）"
                      f"　三振{L['SO']}"))
        angles.append("打線が沈黙")
    # 主力の不振
    for name, hr in season_hr_leaders(lose["id"]):
        p = L["players"].get(name)
        if not p or p["AB"] < 6 or p["H"] / p["AB"] >= 0.150:
            continue
        who = kana_of(name, kana_table, jp)
        if not who:
            continue
        items.append((who, f"{p['AB']}打数{p['H']}安打　{p['SO']}三振"
                           f"（今季{hr}本塁打）"))
        angles.append(f"{who.split('・')[-1]}")
    # 勝った側の主役
    hero = None
    for name, p in sorted(W["players"].items(),
                          key=lambda x: (-(x[1]["HR"] * 3 + x[1]["H"] + x[1]["RBI"]))):
        if p["H"] >= 4 or p["HR"] >= 2 or p["RBI"] >= 4:
            who = kana_of(name, kana_table, jp)
            if who:
                hero = (who, p)
                break
    if hero:
        who, p = hero
        items.append((f"{win['name']}の主役", f"{who}　{p['AB']}打数{p['H']}安打"
                      + (f"　{p['HR']}本塁打" if p["HR"] else "")
                      + (f"　{p['RBI']}打点" if p["RBI"] else "")))
    # 日本人選手
    japanese = []
    for team, T in ((win, W), (lose, L)):
        for name, p in T["players"].items():
            if name not in jp:
                continue
            if p["outs"]:
                ip = f"{p['outs'] // 3}回" + ({1: "と3分の1", 2: "と3分の2"}.get(p["outs"] % 3, ""))
                line = f"{ip}　自責{p['ER']}　{p['K']}奪三振"
            elif p["AB"]:
                line = f"{p['AB']}打数{p['H']}安打" + (f"　{p['HR']}本塁打" if p["HR"] else "") \
                       + (f"　{p['RBI']}打点" if p["RBI"] else "")
            else:
                continue
            japanese.append({"name": jp[name], "line": f"{line}（{team['name']}）"})
    # 現地の声（番記者の投稿。出典つき）
    q = pick_quote(quotes, lose["name"], kana_table, jp)
    source = None
    if q:
        said = q["said"] if "「" in q["said"] else f"「{q['said']}」"
        items.append((f"{lose['name']}の番記者の投稿から", said))
        source = q
    if not angles and not hero:
        return {}
    # 題: 負けた側に切り口があればそちらから、無ければ勝った側の主役から。
    slump = [a for a in angles if a != "打線が沈黙"]
    if angles:
        head = f"{lose['name']}、" + ("打線が沈黙" if "打線が沈黙" in angles else "")
        if slump:
            both = "打線が沈黙" in angles
            head += ("、" if both else "") + "・".join(slump[:2]) + ("も不発" if both else "が不発")
        tail = f"{win['name']}に{lose['wins']}勝{win['wins']}敗で{rnd}敗退"
    else:
        who, p = hero
        head = (f"{win['name']}、{who.split('・')[-1]}が{p['H']}安打"
                + (f"{p['HR']}本塁打" if p["HR"] else ""))
        tail = f"{lose['name']}に{win['wins']}勝{lose['wins']}敗で{rnd}突破"
    jp_names = [j["name"] for j in japanese][:2]
    key = "season_story_" + re.sub(r"[^0-9A-Za-z]", "_", row["key"])
    return {
        "key": key,
        "label": f"{lose['name']}の{rnd}",
        "hook": head,
        "heading": f"{win['name']} 対 {lose['name']}　{rnd}",
        "intro": f"{row.get('round_jp') or rnd}、{win['name']}が{win['wins']}勝{lose['wins']}敗で{lose['name']}を破りました。"
                 f"{lose['name']}に何が起きたのか、公式の数字で見ます。",
        "intro_as_is": True,
        "style": "v3",
        "team_id": lose["id"],
        "abbr": __import__("notability_engine").MLB_TEAM_ABBR.get(str(lose["id"]), ""),
        "title": (f"【MLB】{head}｜{tail}"
                  + (f"　{'・'.join(jp_names)}" if jp_names else "") + " #Shorts"),
        "items": items,
        "japanese": japanese,
        "japanese_lead": "このシリーズの日本人選手は、",
        "ps_ended": True,
        "story": True,
        "source": source,
        "series_key": row["key"],
    }


QUOTE_WORDS = ("season", "series", "postseason", "playoff", "lost", "over",
               "slip", "end", "offense", "swept")


def pick_quote(quotes: list, team: str, table: dict, jp: dict):
    """その球団の番記者の投稿から1つ。引用符を含み、シーズンや敗退の話を優先。"""
    rows = [x for x in quotes if x.get("team") == team and x.get("jp")
            and ("“" in x.get("text", "") or '"' in x.get("text", ""))]
    rows.sort(key=lambda x: (-sum(w in x.get("text", "").lower() for w in QUOTE_WORDS),
                             -(x.get("likes") or 0)))
    for x in rows:
        said = speakable(x["jp"], table, jp)
        if said and len(said) <= 90:
            return {"said": said, "author": x.get("author"), "outlet": x.get("outlet"),
                    "text": x.get("text"), "url": _bsky_url(x), "at": x.get("at")}
    return None


def _bsky_url(x: dict) -> str:
    m = re.match(r"at://([^/]+)/app\.bsky\.feed\.post/(.+)", x.get("uri") or "")
    return f"https://bsky.app/profile/{x.get('handle')}/post/{m.group(2)}" if m else ""


def build(ps: dict, quotes: list) -> list:
    import notability_engine as ne
    jp = {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}
    try:
        kana_table = json.loads(pathlib.Path("data/player_kana.json")
                                .read_text(encoding="utf-8")).get("names") or {}
    except (OSError, json.JSONDecodeError):
        kana_table = {}
    start = ps.get("ps_start") or f"{SEASON}-09-28"
    end = datetime.now(timezone.utc).date().isoformat()
    out = []
    for row in ps.get("series") or []:
        if not row.get("over") or not row.get("winner") or len(row.get("teams") or []) < 2:
            continue
        try:
            games = series_games(row, start, end)
            if not games:
                continue
            t = story(row, games, tally(games), kana_table, jp, quotes)
        except Exception as e:                              # noqa: BLE001
            print(f"[warn] {row.get('key')} を作れません({e})", file=sys.stderr)
            continue
        if t:
            out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--postseason", default="data/postseason.json")
    ap.add_argument("--quotes", default="data/ps_quotes.json")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    try:
        ps = json.loads(pathlib.Path(args.postseason).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] PSの材料を読めません({e})")
        return 0
    try:
        quotes = json.loads(pathlib.Path(args.quotes).read_text(encoding="utf-8")).get("posts") or []
    except (OSError, json.JSONDecodeError):
        quotes = []
    topics = build(ps, quotes)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": datetime.now(timezone.utc).isoformat(),
         "source": "MLB Stats API（試合の成績表）・番記者の投稿", "topics": topics},
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
