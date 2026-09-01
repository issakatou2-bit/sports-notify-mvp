#!/usr/bin/env python3
"""
ポストシーズン進出争いの状況を、MLB公式の順位表から組み立てる。

なぜこの枠なのか:
  9月は、試合そのものより**「あと何回で決まるか」**が主題になる。
  マジックナンバーは毎日1つずつ減る数字で、減った理由も明快
  （自分が勝つか、相手が負けるか）。順位とゲーム差は
  「いまどこにいるか」しか言わないが、こちらは「終わりまでの距離」を言う。

  そして**日本の視聴者に説明が要る概念**でもある。
  ワイルドカード、マジックナンバー、敗退確定（E）。
  用語集も資産動画もあるので、そこは繋げられる。

取れるもの（実際に叩いて確かめた。全部 /standings が返す）:
  magicNumber                 あと何勝（または相手の何敗）で地区優勝
  eliminationNumber           あと何敗で地区優勝が消えるか
  wildCardGamesBack           ワイルドカード枠との差
  wildCardEliminationNumber   WC争いからの敗退数
  clinched / divisionChamp    決定済みか

  「-」は「その数字が意味を持たない」という意味で返ってくる。
  数字が入っていないことと0であることは違うので、そのまま持ち回す。

2026年のポストシーズン:
  各リーグ12球団中6球団。地区優勝3つ＋ワイルドカード3つ。
  上位2つの地区優勝はワイルドカードシリーズを免除（bye）。
  3位の地区優勝 vs 第6シード、第4 vs 第5 がワイルドカードシリーズ。

出力: data/postseason.json

使い方:
  python3 scripts/postseason.py --out data/postseason.json
"""

import argparse
import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

MLB_API = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))

LEAGUE_JP = {103: "アメリカン・リーグ", 104: "ナショナル・リーグ"}
LEAGUE_SHORT = {103: "ア・リーグ", 104: "ナ・リーグ"}
DIVISION_JP = {
    200: "ア・西", 201: "ア・東", 202: "ア・中",
    203: "ナ・西", 204: "ナ・東", 205: "ナ・中",
}


def _get(url: str, timeout: int = 25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _num(v):
    """「-」や None を数字にしない。**0と区別する。**

    MLBの順位表は、その数字が意味を持たないとき「-」を返す。
    0に丸めると「マジック0＝優勝決定」と読めてしまう。
    """
    if v is None or v == "-" or v == "":
        return None
    if v == "E":
        return "E"           # 敗退確定。数字ではないが意味がある
    try:
        return int(v)
    except (TypeError, ValueError):
        return str(v)


def team_jp(team_id, name_en: str) -> str:
    """球団の日本語名。辞書は**IDで引く**（名前ではない）。

    最初 name_en で引いていて、30球団すべてが英語のまま出た。
    MLB_TEAM_NAME_JP の鍵は文字列のチーム ID。
    """
    try:
        from notability_engine import MLB_TEAM_NAME_JP
        return MLB_TEAM_NAME_JP.get(str(team_id)) or name_en
    except Exception:                            # noqa: BLE001
        return name_en


def fetch(season: str) -> list:
    """全球団の、その日の状況。"""
    d = _get(f"{MLB_API}/standings?leagueId=103,104&season={season}"
             f"&standingsTypes=regularSeason&hydrate=team")
    out = []
    for rec in d.get("records") or []:
        lid = (rec.get("league") or {}).get("id")
        did = (rec.get("division") or {}).get("id")
        for t in rec.get("teamRecords") or []:
            team = t.get("team") or {}
            out.append({
                "id": team.get("id"),
                "name": team_jp(team.get("id"), team.get("name") or ""),
                "name_en": team.get("name") or "",
                "league": lid,
                "league_jp": LEAGUE_SHORT.get(lid, ""),
                "division": DIVISION_JP.get(did, ""),
                "w": t.get("wins"), "l": t.get("losses"),
                "pct": (t.get("leagueRecord") or {}).get("pct"),
                "div_rank": _num(t.get("divisionRank")),
                "gb": _num(t.get("gamesBack")),
                "magic": _num(t.get("magicNumber")),
                "elim": _num(t.get("eliminationNumber")),
                "wc_gb": _num(t.get("wildCardGamesBack")),
                "wc_elim": _num(t.get("wildCardEliminationNumber")),
                "clinched": bool(t.get("clinched")),
                "div_champ": bool(t.get("divisionChamp")),
                "wc_clinched": bool(t.get("wildCardClinched")),
                "run_diff": t.get("runDifferential"),
                "streak": (t.get("streak") or {}).get("streakCode"),
            })
    return out


def race(teams: list) -> dict:
    """リーグごとに、いまの並びを組み立てる。

    地区優勝3つ＋ワイルドカード3つ。並べ方は勝率順で、
    公式の順位そのものではなく**「今日終わったらこうなる」**を
    こちらで組む。組み方を画面に出せる形にしておく。
    """
    out = {}
    for lid in (103, 104):
        ls = [t for t in teams if t["league"] == lid]
        # 地区ごとの首位
        leaders, rest = [], []
        for div in sorted({t["division"] for t in ls}):
            ds = sorted([t for t in ls if t["division"] == div],
                        key=lambda t: (-(t["w"] or 0), t["l"] or 0))
            if ds:
                leaders.append(ds[0])
                rest += ds[1:]
        leaders.sort(key=lambda t: (-(t["w"] or 0), t["l"] or 0))
        rest.sort(key=lambda t: (-(t["w"] or 0), t["l"] or 0))
        wc = rest[:3]
        chasing = rest[3:6]          # 追いかけている3球団まで
        out[lid] = {
            "league_jp": LEAGUE_JP[lid],
            "league_short": LEAGUE_SHORT[lid],
            "leaders": leaders,
            "wildcards": wc,
            "chasing": chasing,
            # 今日終わったらこの組み合わせ。
            # 上位2つの地区優勝は免除、3位 vs 第6、第4 vs 第5。
            "bracket": ([{"bye": leaders[0]}, {"bye": leaders[1]}]
                        if len(leaders) >= 2 else [])
                       + ([{"home": leaders[2], "away": wc[2]}]
                          if len(leaders) >= 3 and len(wc) >= 3 else [])
                       + ([{"home": wc[0], "away": wc[1]}]
                          if len(wc) >= 2 else []),
            "clinched": [t for t in ls if t["clinched"] or t["div_champ"]],
            "eliminated": [t for t in ls
                           if t["elim"] == "E" and t["wc_elim"] == "E"],
        }
    return out


def headline(data: dict) -> str:
    """その日いちばん短い一言。動画の1枚目に出す。

    優先順:
      1. 今日決まった球団があれば、それ
      2. マジックが1桁の球団があれば、いちばん小さいもの
      3. ワイルドカード最終枠の差
    """
    best = None
    for r in data.values():
        for t in r["leaders"]:
            m = t.get("magic")
            if isinstance(m, int) and (best is None or m < best[0]):
                best = (m, t)
    done = [t for r in data.values() for t in r["clinched"]]
    if done:
        return f"{done[0]['name']} 進出決定"
    if best and best[0] <= 15:
        return f"{best[1]['name']} マジック{best[0]}"
    if best:
        return f"{best[1]['name']} マジック{best[0]}"
    return "ポストシーズン進出争い"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="")
    ap.add_argument("--out", default="data/postseason.json")
    args = ap.parse_args()

    import os
    season = args.season or os.environ.get("MLB_SEASON") or str(
        datetime.now(JST).year)

    try:
        teams = fetch(season)
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] 順位表を取れません({e})。作りません")
        return 0
    if not teams:
        print("[info] 順位表が空です")
        return 0

    data = race(teams)
    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "headline": headline(data),
        "leagues": {str(k): v for k, v in data.items()},
    }
    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                 encoding="utf-8")

    print(f"[info] {out['headline']}")
    for lid, r in data.items():
        print(f"--- {r['league_jp']} ---")
        for t in r["leaders"]:
            m = t["magic"]
            tag = ("決定" if t["clinched"] or t["div_champ"]
                   else (f"M{m}" if isinstance(m, int) else "-"))
            print(f"  首位 {t['division']}  {t['name']:<12} "
                  f"{t['w']}勝{t['l']}敗  {tag}")
        for i, t in enumerate(r["wildcards"], 1):
            gb = t["wc_gb"]
            print(f"  WC{i}      {t['name']:<12} {t['w']}勝{t['l']}敗  "
                  + ("枠内" if gb is None else f"差{gb}"))
        for t in r["chasing"]:
            print(f"  追う      {t['name']:<12} {t['w']}勝{t['l']}敗  "
                  f"差{t['wc_gb']}")
        if r["eliminated"]:
            print("  敗退確定  " + "、".join(t["name"]
                                             for t in r["eliminated"]))
    print(f"[info] -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
