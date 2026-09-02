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
        # 地区の首位は**公式の順位**を使う。
        #
        # 勝敗だけで決めると、同率のときにこちらが勝手に選ぶことになる。
        # MLBは直接対決などで先に順位を付けているので、それに従う。
        # divisionRank が無い日だけ、勝敗で並べる。
        leaders, rest = [], []
        for div in sorted({t["division"] for t in ls}):
            ds = sorted([t for t in ls if t["division"] == div],
                        key=lambda t: (t["div_rank"] if isinstance(
                            t["div_rank"], int) else 99,
                            -(t["w"] or 0), t["l"] or 0))
            if ds:
                leaders.append(ds[0])
                rest += ds[1:]
        leaders.sort(key=lambda t: (-(t["w"] or 0), t["l"] or 0))
        rest.sort(key=lambda t: (-(t["w"] or 0), t["l"] or 0))
        wc = rest[:3]
        chasing = rest[3:6]          # 追いかけている3球団まで
        # 同率がいるか。いれば画面に断りを出す。
        # 勝敗が並んだ2球団のどちらが上かは、直接対決で決まる。
        # こちらはそれを計算していないので、「入れ替わりうる」と書く。
        seeds = leaders[:3] + wc
        ties = any(a["w"] == b["w"] and a["l"] == b["l"]
                   for a, b in zip(seeds, seeds[1:]))
        out[lid] = {
            "ties": ties,
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


def japanese(data: dict, teams: list = None,
             roster_path: str = "data/roster_snapshot.json") -> list:
    """日本人選手のいる球団が、いまどこにいるか。

    なぜこの1枚を足すのか:
      28日を測ったら、題に日本人選手の名前がある動画は
      468回/本、無い動画は168回/本だった。2.8倍。
      順位表は「見たい人が見るもの」だが、
      **「大谷のドジャースは第何シードか」は誰でも分かる。**
      同じ材料の、入口を変えただけの1枚。

    所属は名簿(roster_snapshot.json)から引く。
    APIを叩き直さない。**その日の朝に取ったものが既にある。**
    名簿に無い選手（故障者リストや傘下）は出さない。
    「いない」ことを書くより、確かなものだけを並べる。
    """
    try:
        from notability_engine import JP_PLAYERS_MLB
        import textkey
        ros = json.loads(pathlib.Path(roster_path).read_text(
            encoding="utf-8")).get("players") or {}
    except Exception:                                # noqa: BLE001
        return []
    by_name = {textkey.key(v.get("name") or ""): v for v in ros.values()}

    # 球団ID -> その球団にいる日本人選手
    where = {}
    for p in JP_PLAYERS_MLB:
        r = by_name.get(textkey.key(p.get("name_en") or ""))
        if not r or not r.get("team_id"):
            continue
        where.setdefault(str(r["team_id"]), []).append(p.get("name_jp"))

    # 球団ID -> いまの立ち位置
    seat = {}
    for lid, r in data.items():
        seeds = (r.get("leaders") or [])[:3] + (r.get("wildcards") or [])[:3]
        for i, t in enumerate(seeds, 1):
            seat[str(t.get("id"))] = (t, i,
                                      "地区首位" if i <= 3 else "ワイルドカード")
        for t in r.get("chasing") or []:
            seat.setdefault(str(t.get("id")), (t, None, "追う"))
    # 圏内にも追う位置にもいない球団。**ここも数に入れる。**
    # 「日本人選手のいる11球団のうち6球団」と言うのに、
    # 分母から静かに落ちている球団があってはいけない。
    for t in teams or []:
        seat.setdefault(str(t.get("id")), (t, None, "圏外"))

    out = []
    for tid, names in where.items():
        t, seed, route = seat.get(tid, (None, None, "圏外"))
        if t is None:
            continue                    # 順位表に無い球団は出さない
        out.append({
            "team_id": int(tid), "team": t.get("name"),
            "league": t.get("league"), "league_jp": t.get("league_jp"),
            "seed": seed, "route": route,
            "w": t.get("w"), "l": t.get("l"),
            "magic": t.get("magic"), "wc_gb": t.get("wc_gb"),
            "clinched": bool(t.get("clinched") or t.get("div_champ")),
            "players": names,
        })
    # 進出に近い順。圏内はシード順、圏外は名前の数が多い順
    # （多いほうが視聴者の見たい球団に当たりやすい）。
    ORDER = {"地区首位": 0, "ワイルドカード": 0, "追う": 1, "圏外": 2}
    out.sort(key=lambda x: (ORDER.get(x["route"], 3), x["seed"] or 99,
                            -len(x["players"])))
    return out


def diff(now: dict, before: dict) -> list:
    """昨日との違い。**この枠の主題はここ。**

    順位表は毎日出しても、変わらない日は見る理由が無い。
    逆に1行入れ替わった日は、それがその日いちばんの出来事になる。
    「昨日と同じ」と言えることにも意味があるので、
    **変化が無いことも結果として返す**（空の配列で返る）。

    見るもの:
      ・進出圏に入った / 出た
      ・マジックが減った
      ・進出が決まった / 敗退が決まった
    """
    out = []
    if not before:
        return out

    def seats(d):
        s = {}
        for lid, r in (d.get("leagues") or {}).items():
            for t in (r.get("leaders") or [])[:3] + (r.get("wildcards") or []):
                s[str(t.get("id"))] = t
        return s

    a, b = seats(now), seats(before)
    for tid, t in a.items():
        if tid not in b:
            out.append({"kind": "in", "name": t.get("name"),
                        "text": f"{t.get('name')}が進出圏内に入った"})
    for tid, t in b.items():
        if tid not in a:
            out.append({"kind": "out", "name": t.get("name"),
                        "text": f"{t.get('name')}が進出圏内から出た"})

    # マジックの減り方。減っていない日は出さない。
    for tid, t in a.items():
        m, pm = t.get("magic"), (b.get(tid) or {}).get("magic")
        if isinstance(m, int) and isinstance(pm, int) and m < pm:
            out.append({"kind": "magic", "name": t.get("name"),
                        "text": f"{t.get('name')}のマジックが"
                                f"{pm}から{m}へ"})

    def flags(d, key):
        return {str(t.get("id")): t
                for lid, r in (d.get("leagues") or {}).items()
                for t in (r.get(key) or [])}

    for tid, t in flags(now, "clinched").items():
        if tid not in flags(before, "clinched"):
            out.append({"kind": "clinch", "name": t.get("name"),
                        "text": f"{t.get('name')}が進出決定"})
    for tid, t in flags(now, "eliminated").items():
        if tid not in flags(before, "eliminated"):
            out.append({"kind": "elim", "name": t.get("name"),
                        "text": f"{t.get('name')}が敗退決定"})
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
    p = pathlib.Path(args.out)

    # 前日ぶんを取っておく。**差分がこの枠の主題。**
    # 同じ日に2回走らせても上書きしないよう、日付で見る。
    prev_path = p.with_name(p.stem + "_prev.json")
    before = {}
    today = datetime.now(JST).date().isoformat()
    if p.exists():
        try:
            old_data = json.loads(p.read_text(encoding="utf-8"))
            if str(old_data.get("date") or "") != today:
                prev_path.write_text(json.dumps(old_data, ensure_ascii=False,
                                                indent=2), encoding="utf-8")
            before = old_data if str(old_data.get("date")) != today else {}
        except (OSError, json.JSONDecodeError):
            pass
    if not before and prev_path.exists():
        try:
            before = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            before = {}

    changes = diff({"leagues": {str(k): v for k, v in data.items()}}, before)
    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "season": season,
        "headline": headline(data),
        "changes": changes,
        "prev_date": str(before.get("date") or ""),
        "japanese": japanese(data, teams),
        "leagues": {str(k): v for k, v in data.items()},
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                 encoding="utf-8")

    print(f"[info] {out['headline']}")
    jp = out["japanese"]
    if jp:
        inside = [x for x in jp if x["seed"]]
        print(f"[info] 日本人選手のいる{len(jp)}球団のうち"
              f"{len(inside)}球団が進出圏内")
        for x in jp[:6]:
            tag = f"第{x['seed']}シード" if x["seed"] else x["route"]
            print("    %-8s %-12s %s" % (tag, x["team"],
                                         "・".join(x["players"])))
    if changes:
        print("[info] 昨日からの変化 %d件" % len(changes))
        for c in changes[:6]:
            print("    " + c["text"])
    elif before:
        print("[info] 昨日から変化はありません")
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
