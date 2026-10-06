#!/usr/bin/env python3
"""シーズンを終えた球団と日本人選手の「シーズンまとめ」の材料。

なぜ要るのか:
  10/3、本人から「今シーズンが終了した球団のシーズンまとめショートを
  載せ始めたい。個人・球団単位それぞれで」。

  レギュラーシーズンで終わった18球団と、ポストシーズンで敗退した球団は、
  もう数字が動かない。**動かない数字だけで作るので、作り置きでき、
  あとから見られても古くならない**（資産動画と同じ性質）。

何を載せるか（全部公式APIの数字。台詞はAIに書かせない）:
  球団: 最終成績と地区順位、ポストシーズンの結末、球団内の1位
        （本塁打・打率（規定打席）・奪三振・勝利）、日本人選手の成績
  個人: 今季の成績、自己最多になった項目、球団内・リーグ内の順位、
        球団の結末

  **まだ戦っている球団は作らない。**終わっていない数字をまとめと呼ばない。
  終わったかどうかは data/postseason.json（ps_series の勝ち抜け）で決める。

  打率・OPS・防御率は規定到達者の中だけで比べる。数打席の選手の
  .400 を「チーム1位」と言わない。

出力: data/season_topics.json（generated_topics が読む、資産動画と同じ形）
使い方:
  python3 scripts/season_topics.py
  python3 scripts/season_topics.py --only 112      # カブスと所属選手だけ
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

API = "https://statsapi.mlb.com/api/v1"
SEASON = "2026"
OUT = "data/season_topics.json"
LEAGUE_JP = {103: "ア・リーグ", 104: "ナ・リーグ"}


def _get(path: str, **params) -> dict:
    import requests
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- 終わったか

def finished_teams(ps: dict) -> dict:
    """{球団ID: 結末の文}。まだ戦っている球団は入らない。

    レギュラーシーズンが終わっている（phase が settled/postseason）ことが
    前提。進出しなかった球団は「ポストシーズン進出ならず」。
    """
    if ps.get("phase") not in ("settled", "postseason"):
        return {}
    teams = ps.get("teams") or {}
    series = ps.get("series") or []
    alive, out = set(), {}
    entered = set()
    for s in series:
        ids = [t["id"] for t in s.get("teams") or []]
        entered.update(ids)
        if not s.get("over"):
            alive.update(ids)
    # 免除されて次の回を待っている球団も、まだ戦っている。
    for k, t in teams.items():
        if t.get("seed") and int(k) not in entered:
            alive.add(int(k))
    for s in series:
        if not s.get("over") or len(s.get("teams") or []) < 2:
            continue
        for t in s["teams"]:
            if t["id"] == s.get("winner") or t["id"] in alive:
                continue
            opp = next(x for x in s["teams"] if x["id"] != t["id"])
            if s.get("round") == "W":
                text = "ワールドシリーズで敗れ、準優勝"
            else:
                text = (f"{s['round_jp']}で敗退（{opp['name']}に"
                        f"{t['wins']}勝{opp['wins']}敗）")
            out[t["id"]] = text
    # ワールドシリーズを勝った球団
    for s in series:
        if s.get("round") == "W" and s.get("over") and s.get("winner"):
            out[s["winner"]] = "ワールドシリーズ制覇"
    for k, t in teams.items():
        tid = int(k)
        if tid not in alive and tid not in out and tid not in entered:
            out[tid] = "ポストシーズン進出ならず"
    return out


# ---------------------------------------------------------------- 数字

def roster_stats(team_id: int, group: str, pool: str = "ALL") -> list:
    """その球団での今季成績（レギュラーシーズン）。"""
    d = _get("stats", stats="season", group=group, season=SEASON,
             teamId=team_id, playerPool=pool, limit=100, gameType="R")
    return (d.get("stats") or [{}])[0].get("splits") or []


def top(splits: list, key: str, low: bool = False):
    """その項目の1位。同率で並んだら名前を出さない（どちらか決められない）。"""
    rows = [x for x in splits if x["stat"].get(key) not in (None, "-.--", ".---")]
    if not rows:
        return None
    val = (lambda x: float(x["stat"][key]))
    rows.sort(key=val, reverse=not low)
    if len(rows) > 1 and val(rows[0]) == val(rows[1]):
        return None
    if not low and val(rows[0]) <= 0:
        return None
    return rows[0]


def kana(name_en: str, table: dict) -> str:
    """カタカナ表記。手元の辞書に無ければWikidataで引き、無ければ英語のまま。"""
    if name_en not in table:
        try:
            import player_kana
            table[name_en] = player_kana.lookup(name_en)
        except Exception:                                # noqa: BLE001
            table[name_en] = ""
    return table.get(name_en) or name_en


def jp_roster() -> dict:
    """{英語名: 日本語名}。名簿は notability_engine のものを使う。"""
    import notability_engine as ne
    return {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}


def batting_line(st: dict) -> str:
    return (f"{st.get('gamesPlayed')}試合　打率{st.get('avg')}　"
            f"{st.get('homeRuns')}本塁打　{st.get('rbi')}打点　OPS{st.get('ops')}")


def innings(ip) -> str:
    """174.1 → 「174回と3分の1」。小数のまま読むと「174てん1回」になる。"""
    whole, _, part = str(ip or "0").partition(".")
    return f"{whole}回" + ({"1": "と3分の1", "2": "と3分の2"}.get(part, ""))


def pitching_line(st: dict) -> str:
    line = (f"{st.get('gamesPlayed')}登板　{st.get('wins')}勝{st.get('losses')}敗"
            f"　防御率{st.get('era')}　{innings(st.get('inningsPitched'))}"
            f"　{st.get('strikeOuts')}奪三振")
    if (st.get("saves") or 0) >= 5:
        line += f"　{st.get('saves')}セーブ"
    if (st.get("holds") or 0) >= 10:
        line += f"　{st.get('holds')}ホールド"
    return line


def _is_pitcher(person: dict) -> bool:
    return ((person.get("primaryPosition") or {}).get("abbreviation") == "P")


# ---------------------------------------------------------------- 球団

# 打席がこれより少なければ投手として扱う（代打・投手の打席だけの選手）
PITCHER_MAX_PA = 30


def jp_lines(hit_all: list, pit_all: list, jp: dict) -> list:
    """球団の回の日本人選手の1行。投手か打者かは、打席の数で決める。

    **打撃の一覧には投手も入っている。**10/6、メッツの回で千賀滉大（投手）に
    「31試合 打率.000」と打者の成績が出ていた（打撃の一覧を先に見ていたため）。
    打席がほとんど無い選手は投球の成績、両方に出る選手（大谷）は打撃と投球の両方。
    """
    japanese = []
    hit_by = {x["player"]["fullName"]: x for x in hit_all}
    pit_by = {x["player"]["fullName"]: x for x in pit_all}
    for full in dict.fromkeys([x["player"]["fullName"] for x in hit_all + pit_all]):
        jn = jp.get(full)
        if not jn or any(j["name"] == jn for j in japanese):
            continue
        h, p = hit_by.get(full), pit_by.get(full)
        pa = int((h or {}).get("stat", {}).get("plateAppearances") or 0)
        if p and (not h or pa < PITCHER_MAX_PA):
            line = pitching_line(p["stat"])
        else:
            line = batting_line(h["stat"])
            if p and float(p["stat"].get("inningsPitched") or 0) > 0:
                line += "　／　" + pitching_line(p["stat"])
        japanese.append({"name": jn, "line": line})
    return japanese


def team_topic(tid: int, info: dict, ending: str, kana_table: dict,
               jp: dict) -> dict:
    name = info["name"]
    hit_all = roster_stats(tid, "hitting")
    hit_q = roster_stats(tid, "hitting", "QUALIFIED")
    pit_all = roster_stats(tid, "pitching")
    league = LEAGUE_JP.get(info.get("league"), "")
    div = (info.get("division") or "").replace("ア・", "ア・リーグ").replace(
        "ナ・", "ナ・リーグ")
    champ = "（地区優勝）" if info.get("div_rank") == 1 else ""
    items = [("最終成績", f"{info['w']}勝{info['l']}敗　{div}地区"
                          f"{info['div_rank']}位{champ}"),
             ("ポストシーズン", ending)]
    # **カタカナが分からない選手の行は出さない。**英字のまま読み上げに
    # 渡すと1文字ずつ読まれる（generate_asset_video._say と同じ判断）。
    def who(x):
        name = kana(x["player"]["fullName"], kana_table)
        return "" if any(c.isascii() and c.isalpha() for c in name) else name
    for head, pool, k, fmt in (
            ("チーム本塁打1位", hit_all, "homeRuns", "{}本"),
            ("チーム打率1位（規定打席）", hit_q, "avg", "{}"),
            ("チーム奪三振1位", pit_all, "strikeOuts", "{}奪三振"),
            ("チーム勝利1位", pit_all, "wins", "{}勝")):
        row = top(pool, k)
        if row and who(row):
            items.append((head, f"{who(row)}　" + fmt.format(row["stat"][k])))
    japanese = jp_lines(hit_all, pit_all, jp)
    names = "・".join(j["name"] for j in japanese[:2])
    return {
        "key": f"season_team_{tid}",
        "label": f"{name}の{SEASON}年シーズン",
        "hook": ending if ending != "ポストシーズン進出ならず"
        else f"{info['w']}勝{info['l']}敗",
        "heading": f"{name}　{SEASON}年のまとめ",
        "intro": f"{name}の{SEASON}年シーズンを、MLB公式の数字で振り返ります。",
        "intro_as_is": True,
        "style": "v2",
        "title": (f"【MLB】{names}の{name}｜{SEASON}年シーズンまとめ #Shorts"
                  if names else
                  f"【MLB】{name}｜{SEASON}年シーズンまとめ　{info['w']}勝"
                  f"{info['l']}敗 #Shorts"),
        "items": items,
        "japanese": japanese,
        "team_id": tid,
        "abbr": __import__("notability_engine").MLB_TEAM_ABBR.get(str(tid), ""),
        "league_jp": league,
        # ポストシーズンで終わった球団は、終わった直後がいちばん探される。
        "ps_ended": ending != "ポストシーズン進出ならず",
    }


# ---------------------------------------------------------------- 個人

def league_rank(league_id: int, group: str, key: str, value: float,
                low: bool = False, pool: str = "ALL") -> int:
    """リーグ内の順位（同じ値は同じ順位）。取れなければ 0。"""
    try:
        d = _get("stats", stats="season", group=group, season=SEASON,
                 leagueId=league_id, playerPool=pool, limit=2000, gameType="R")
    except Exception:                                    # noqa: BLE001
        return 0
    vals = [float(x["stat"][key]) for x in
            (d.get("stats") or [{}])[0].get("splits") or []
            if x["stat"].get(key) not in (None, "-.--", ".---")]
    better = [v for v in vals if (v < value if low else v > value)]
    return len(better) + 1 if vals else 0


def player_topic(name_en: str, name_jp: str, team_name: str, ending: str,
                 league_id: int, team_id: int = None) -> dict:
    found = _get("people/search", names=name_en).get("people") or []
    if not found:
        return {}
    pid = found[0]["id"]
    person = (_get(f"people/{pid}", hydrate="currentTeam").get("people")
              or [{}])[0]
    # **シーズン途中で移籍した選手は、最後にいた球団の回だけ。**
    # 10/3、ヌートバーがダイヤモンドバックスとカージナルスの両方で
    # 作られ、同じ鍵の個人の回が2つできた。
    if (person.get("currentTeam") or {}).get("id") not in (None, team_id):
        return {}
    pitcher = _is_pitcher(person)
    group = "pitching" if pitcher else "hitting"
    d = _get(f"people/{pid}/stats", stats="season,yearByYear", group=group,
             season=SEASON, gameType="R")
    # 移籍した年は「合計の行」と「球団ごとの行」が来る。合計を採るのは
    # mlb_splits に任せる（自前で読むと二重に数える。run_checks が見張る）。
    import mlb_splits
    by = {}
    for st in d.get("stats") or []:
        kind = (st.get("type") or {}).get("displayName")
        for sp in st.get("splits") or []:
            if (sp.get("sport") or {}).get("id", 1) != 1:
                continue
            by.setdefault((kind, sp.get("season") or SEASON), []).append(sp)
    season = mlb_splits.season_stat(by.get(("season", SEASON)) or [])
    clubs = [sp["team"]["id"] for sp in by.get(("season", SEASON)) or []
             if sp.get("team") and not sp.get("numTeams")]
    years = {yr: mlb_splits.season_stat(rows)
             for (kind, yr), rows in by.items()
             if kind == "yearByYear" and yr != SEASON}
    if not season or not season.get("gamesPlayed"):
        return {}
    # 移籍した年の成績は、球団ごとの行と合計の行が来る。言うのは合計。
    import notability_engine as ne
    head = "今季の成績"
    moved = ""
    if len(set(clubs)) > 1:
        head = f"今季の成績（{len(set(clubs))}球団の合計）"
        before = [ne.MLB_TEAM_NAME_JP.get(str(c), "") for c in clubs
                  if c != team_id]
        if before and all(before):
            moved = f"シーズン途中で{'・'.join(before)}から移籍。"
    items = [(head, pitching_line(season) if pitcher
              else batting_line(season))]
    # 自己最多（MLBで前の年があるときだけ）
    keys = (("wins", "勝"), ("strikeOuts", "奪三振"), ("saves", "セーブ"),
            ("holds", "ホールド")) if pitcher else (
            ("homeRuns", "本塁打"), ("hits", "安打"), ("rbi", "打点"),
            ("stolenBases", "盗塁"))
    best = []
    for k, label in keys:
        now = season.get(k) or 0
        past = [y.get(k, 0) for y in years.values()]
        if years and now >= 5 and now > max(past or [0]):
            best.append(f"{label}{now}")
    if best:
        items.append(("自己最多", "・".join(best) + "　いずれもMLBでの自己最多"))
    # 昨季との比較。MLBで前の年があるときだけ。**良くなったか悪く
    # なったかは言わない**（数字を並べれば分かる。言葉にすると盛る）。
    last = years.get(str(int(SEASON) - 1))
    if last:
        pairs = (("wins", "勝利"), ("strikeOuts", "奪三振")) if pitcher else (
                 ("homeRuns", "本塁打"), ("rbi", "打点"))
        bits = [f"{label} {last.get(k, 0)}から{season.get(k, 0)}"
                for k, label in pairs if k in last]
        if bits:
            items.append((f"昨季（{int(SEASON) - 1}年）から", "　".join(bits)))
    # リーグ内の順位（10位以内だけ言う）
    lname = LEAGUE_JP.get(league_id, "")
    ranks = []
    rank_keys = (("strikeOuts", "奪三振", False, "ALL"),
                 ("era", "防御率", True, "QUALIFIED")) if pitcher else (
                 ("homeRuns", "本塁打", False, "ALL"),
                 ("ops", "OPS", False, "QUALIFIED"))
    for k, label, low, pool in rank_keys:
        if season.get(k) in (None, "-.--", ".---"):
            continue
        r = league_rank(league_id, group, k, float(season[k]), low, pool)
        if 0 < r <= 10:
            ranks.append(f"{label}は{lname}{r}位")
    if ranks:
        items.append(("リーグの中で", "　".join(ranks)))
    # Savantの順位（端だけ。値の向きは savant.notable が書く）
    try:
        import savant
        rows = savant.fetch(int(SEASON), "pitcher" if pitcher else "batter")
        row = rows.get(str(pid)) or {}
        ext = savant.notable(row, limit=2,
                             kind="pitcher" if pitcher else "batter")
    except Exception:                                    # noqa: BLE001
        ext = []
    if ext:
        items.append(("Statcastで見ると", "　".join(statcast_phrase(x)
                                                   for x in ext)))
    items.append(("球団の結末", f"{team_name}は{ending}"))
    return {
        "key": f"season_player_{pid}",
        "label": f"{name_jp}の{SEASON}年シーズン",
        # 最初の画面の大きな文字。主な成績をそのまま。
        "hook": (f"{season.get('wins')}勝{season.get('losses')}敗　"
                 f"防御率{season.get('era')}" if pitcher else
                 f"打率{season.get('avg')}　{season.get('homeRuns')}本塁打"),
        "intro_as_is": True,
        "style": "v2",
        "heading": f"{name_jp}　{SEASON}年のまとめ",
        "intro": f"{team_name}の{name_jp}。{moved}{SEASON}年シーズンを、"
                 f"MLB公式の数字で振り返ります。",
        "title": f"【MLB】{name_jp}｜{SEASON}年シーズンまとめ　{team_name} #Shorts",
        "items": items,
        "jp": name_jp,
        "player_id": pid,
        "ps_ended": ending != "ポストシーズン進出ならず",
    }


def statcast_phrase(x: dict) -> str:
    """読み上げで向きが一言で分かる形。

    値が小さいほど良い項目（三振率・与四球率など）は、Savantの順位を
    そのまま言うと「三振率はリーグ下位1%」が三振の少なさに聞こえる。
    値の大きさで言い、Savantの評価も添える（長編の材料と同じ言い方）。

    10/6、「被期待wOBAの高さはリーグ上位1%」が良い数字に聞こえると
    指摘された（菅野・今井・千賀）。「上位」は良し悪しに聞こえるので使わず、
    「高い方から1%（Savantの評価は下位）」と言う。
    """
    import savant
    v = x["percentile"]
    if x["key"] not in savant.INVERSE.get(x["kind"], ()):
        return f"{x['label']}は{x['side']}"
    if v >= 100:
        return f"{x['label']}はリーグで最も低い"
    if v <= 0:
        return f"{x['label']}はリーグで最も高い"
    if x["high"]:
        return f"{x['label']}はリーグで低い方から{100 - v}%（Savantの評価は上位）"
    return f"{x['label']}はリーグで高い方から{v}%（Savantの評価は下位）"


# ---------------------------------------------------------------- リーグ

LEADER_CATS = {
    "hitting": (("homeRuns", "本塁打", "{}本"), ("battingAverage", "打率", "{}"),
                ("runsBattedIn", "打点", "{}打点"), ("stolenBases", "盗塁", "{}盗塁")),
    "pitching": (("wins", "勝利", "{}勝"), ("earnedRunAverage", "防御率", "{}"),
                 ("strikeouts", "奪三振", "{}奪三振"), ("saves", "セーブ", "{}セーブ")),
}


def league_topics(ps: dict, kana_table: dict, jp: dict) -> list:
    """リーグごとの部門1位（レギュラーシーズン）。

    **「タイトル」とは呼ばない。**MLBが表彰する打撃部門は首位打者などに
    限られ、日本の「本塁打王」のような公式の称号は無い。言うのは
    「部門1位」まで。同率1位は全員の名前を出す。
    """
    if ps.get("phase") not in ("settled", "postseason"):
        return []
    teams = ps.get("teams") or {}
    out = []
    for lid, lname in LEAGUE_JP.items():
        for group, cats in LEADER_CATS.items():
            d = _get("stats/leaders", season=SEASON, leagueId=lid, limit=5,
                     gameTypes="R",
                     leaderCategories=",".join(c for c, _, _ in cats))
            items, names = [], []
            for cat, label, fmt in cats:
                blk = next((b for b in d.get("leagueLeaders") or []
                            if b.get("leaderCategory") == cat
                            and b.get("statGroup") == group), None)
                firsts = [x for x in (blk or {}).get("leaders") or []
                          if x.get("rank") == 1]
                if not firsts:
                    continue
                who = []
                for x in firsts:
                    en = x["person"]["fullName"]
                    name = jp.get(en) or kana(en, kana_table)
                    if any(c.isascii() and c.isalpha() for c in name):
                        who = []
                        break                 # 読めない名前が混じる行は出さない
                    club = (teams.get(str((x.get("team") or {}).get("id")))
                            or {}).get("name", "")
                    who.append(f"{name}（{club}）" if club else name)
                if who:
                    items.append((f"{label}1位", "・".join(who) + "　"
                                  + fmt.format(firsts[0]["value"])))
                    names += [w.split("（")[0] for w in who]
            if len(items) < 3:
                continue
            kind = "打撃" if group == "hitting" else "投手"
            jps = [n for n in names if n in jp.values()]
            out.append({
                "key": f"season_league_{lid}_{group}",
                "label": f"{lname} {kind}部門の1位（{SEASON}年）",
                "hook": f"{lname}　{kind}部門の1位",
                "heading": f"{lname}　{kind}部門1位",
                "intro": f"{SEASON}年レギュラーシーズン、{lname}の{kind}部門で"
                         f"1位になった選手です。MLB公式の数字で見ます。",
                "intro_as_is": True,
        "style": "v2",
                "title": (f"【MLB】{'・'.join(jps[:2]) + 'も' if jps else ''}"
                          f"{lname} {kind}部門の1位｜{SEASON}年シーズンまとめ #Shorts"),
                "items": items,
                "ps_ended": False,
            })
    return out


# ---------------------------------------------------------------- 全体

def build(ps: dict, only: int = 0) -> list:
    ended = finished_teams(ps)
    teams = ps.get("teams") or {}
    try:
        kana_table = json.loads(pathlib.Path("data/player_kana.json")
                                .read_text(encoding="utf-8")).get("names") or {}
    except (OSError, json.JSONDecodeError):
        kana_table = {}
    jp = jp_roster()
    out = []
    if not only:
        try:
            out += league_topics(ps, kana_table, jp)
        except Exception as e:                              # noqa: BLE001
            print(f"[warn] リーグの部門1位を作れません({e})", file=sys.stderr)
    for tid, ending in sorted(ended.items()):
        if only and tid != only:
            continue
        info = teams.get(str(tid)) or {}
        if not info:
            continue
        try:
            t = team_topic(tid, info, ending, kana_table, jp)
        except Exception as e:                              # noqa: BLE001
            print(f"[warn] {info.get('name')} を作れません({e})", file=sys.stderr)
            continue
        out.append(t)
        for j in t["japanese"]:
            en = next((k for k, v in jp.items() if v == j["name"]), "")
            try:
                p = player_topic(en, j["name"], info["name"], ending,
                                 info.get("league"), tid)
            except Exception as e:                          # noqa: BLE001
                print(f"[warn] {j['name']} を作れません({e})", file=sys.stderr)
                continue
            if p:
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--postseason", default="data/postseason.json")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--only", type=int, default=0)
    args = ap.parse_args()
    try:
        ps = json.loads(pathlib.Path(args.postseason).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] ポストシーズンの材料を読めません({e})")
        return 0
    topics = build(ps, args.only)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": datetime.now(timezone.utc).isoformat(),
         "source": "MLB Stats API（レギュラーシーズン）",
         "topics": topics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print(f"  {t['key']:24s} {t['title']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
