"""確定した勝者だけを進めるPS組み合わせ表。描画・投稿とは独立した確認用材料。"""
import argparse
import json
from datetime import datetime
from pathlib import Path

VERSION = "ps-bracket-preview-20261004"
NEED = {"F": 2, "D": 3, "L": 4, "W": 4}
LEAGUES = ((103, "ア・リーグ"), (104, "ナ・リーグ"))


def build(data):
    if data.get("phase") != "postseason":
        return None
    season = str(data.get("season") or "")
    if not season.isdigit() or not data.get("date") or not data.get("updated_at"):
        raise ValueError("シーズン・材料日付・取得日時が必要")
    # 時差を含む取得日時であること。古い材料かどうかは制作側で判断する。
    if datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("取得日時のタイムゾーン不明")
    teams, seeds = {}, {}
    for key, t in (data.get("teams") or {}).items():
        if not t.get("seed"):
            continue
        seed, league = int(t["seed"]), t.get("league")
        if league not in (103, 104) or not 1 <= seed <= 6:
            raise ValueError("PSシードのリーグ・順位が不正")
        slot = (league, seed)
        if slot in seeds:
            raise ValueError("同じリーグに同じシードが複数")
        tid = int(key)
        if t.get("clinched") is not True:
            raise ValueError("進出未確定の球団をPSの確定枠へ入れない")
        teams[tid] = {"id": tid, "name": t["name"], "players": [], "league": league}
        seeds[slot] = tid
    if len(seeds) != 12:
        raise ValueError("両リーグの6シードが未確認")
    sources = {}
    for s in data.get("series") or []:
        rnd = s.get("round")
        if rnd not in NEED:
            continue
        rows = s.get("teams") or []
        for t in rows:
            if t["id"] in teams:
                teams[t["id"]]["players"] = list(t.get("players") or [])
        if s.get("waiting") or len(rows) != 2:
            continue
        ids = frozenset(t["id"] for t in rows)
        if len(ids) != 2 or not ids.issubset(teams):
            raise ValueError("シリーズの球団がシードと不一致")
        if rnd != "W" and len({teams[tid]["league"] for tid in ids}) != 1:
            raise ValueError("WS以外で両リーグを混ぜない")
        if rnd == "W" and len({teams[tid]["league"] for tid in ids}) != 2:
            raise ValueError("WSは両リーグの優勝球団の対戦")
        key = (rnd, ids)
        if key in sources:
            raise ValueError("同じシリーズが二重に存在")
        wins = {t["id"]: t.get("wins") for t in rows}
        if any(type(w) is not int or w < 0 or w > NEED[rnd] for w in wins.values()):
            raise ValueError("シリーズ勝数が不正")
        if sum(wins.values()) != s.get("played"):
            raise ValueError("終了試合数と勝数の合計が不一致")
        winners = [tid for tid, w in wins.items() if w == NEED[rnd]]
        if s.get("over"):
            if len(winners) != 1 or s.get("winner") != winners[0]:
                raise ValueError("突破確定と勝数・勝者が不一致")
        elif winners or s.get("winner") is not None:
            raise ValueError("進行中のシリーズに確定勝者がある")
        sources[key] = s

    used, matches = set(), {}

    def match(key, rnd, ids, parents=()):
        s = sources.get((rnd, frozenset(ids))) if all(ids) else None
        if s:
            used.add((rnd, frozenset(ids)))
        wins = {t["id"]: t["wins"] for t in s["teams"]} if s else {}
        m = {"key": key, "round": rnd, "need": NEED[rnd], "parents": list(parents),
             "teams": [dict(teams[tid], wins=wins.get(tid, 0)) if tid else
                       {"id": None, "name": "未定", "players": [], "wins": None} for tid in ids],
             "over": bool(s and s["over"]), "winner": s.get("winner") if s else None}
        matches[key] = m
        return m

    leagues, conditional = [], []
    for league, label in LEAGUES:
        prefix = "AL" if league == 103 else "NL"
        wc = [match(prefix+"-F1", "F", [seeds[(league, 4)], seeds[(league, 5)]]),
              match(prefix+"-F2", "F", [seeds[(league, 3)], seeds[(league, 6)]])]
        ds = [match(prefix+"-D1", "D", [seeds[(league, 1)], wc[0]["winner"]], [wc[0]["key"]]),
              match(prefix+"-D2", "D", [seeds[(league, 2)], wc[1]["winner"]], [wc[1]["key"]])]
        lcs = match(prefix+"-L", "L", [s["winner"] for s in ds], [s["key"] for s in ds])
        leads = []
        for s in ds:
            if s["over"]:
                leads.append(s["winner"])
            elif all(t["id"] for t in s["teams"]) and s["teams"][0]["wins"] != s["teams"][1]["wins"]:
                leads.append(max(s["teams"], key=lambda t: t["wins"])["id"])
            else:
                leads.append(None)
        conditional.append({"league": label, "confirmed": all(s["over"] for s in ds),
                            "teams": [dict(teams[t]) if t else None for t in leads]})
        leagues.append({"id": league, "label": label, "wc": wc, "ds": ds, "lcs": lcs})
    ws = match("WS", "W", [l["lcs"]["winner"] for l in leagues], [l["lcs"]["key"] for l in leagues])
    if set(sources) != used:
        raise ValueError("公式シリーズの相手が、前段の確定勝者またはシードと不一致")
    return {"version": VERSION, "season": season, "date": data["date"],
            "source_at": data["updated_at"], "source_url": "https://www.mlb.com/postseason",
            "leagues": leagues, "ws": ws, "conditional_lcs": conditional}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="data/postseason.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    model = build(json.loads(Path(args.source).read_text(encoding="utf-8")))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "ready" if model else "outside_postseason", "bracket": model},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print("組み合わせ表の材料を保存。投稿機能はありません。")


if __name__ == "__main__":
    main()
