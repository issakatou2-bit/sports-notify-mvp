#!/usr/bin/env python3
"""
MLBの球団ごとに、資産動画1本ぶんの材料を作る。

なぜ要るのか:
  球場の25本に続く玉。球場と同じで、創設年も本拠地もリーグ・地区も
  公式APIから取れる。手で書き起こす部分が無いので、毎日1本という
  約束を続けられる。

  もう一つ、APIから作ることに実利がある。球団は移転する。
  2026年時点でアスレチックスの locationName は "Sacramento" で、
  本拠地はサッター・ヘルス・パーク(収容14,111人)。手書きの表なら
  こちらが気づいて直すまで古い内容を出し続けるが、APIを見ていれば
  移転した翌日から正しくなる。新球団が増えたときも同じ。

何を書くか:
  APIの数字と、既に持っている日本語名・地区名・ライバル関係だけ。
  「懐事情」や「球団の裏事情」のような、出典を示せない話は書かない。
  そこはAPIに無いので、こちらが作ったことになってしまう。

出力: data/team_topics.json

使い方:
  python3 scripts/team_topics.py
"""

import argparse
import functools
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    MLB_DIVISIONS,
    MLB_TEAM_COLOR,
    MLB_DIVISION_NAME_JP,
    MLB_RIVALRIES,
    MLB_TEAM_NAME_JP,
    MLB_VENUE_NOTES,
)

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}


def _venue_row(en: str):
    """球場の登録行。命名権で名前が伸びることがあるので部分一致も見る。"""
    row = MLB_VENUE_NOTES.get(en)
    if row:
        return row
    for k, v in MLB_VENUE_NOTES.items():
        if k in (en or ""):
            return v
    return None


def jp_venue(en: str) -> str:
    """球場の日本語名。"""
    row = _venue_row(en)
    return row[0] if row else (en or "")


def jp_where(en: str) -> str:
    """
    その球場のある場所。日本語の表記で返す。

    APIの locationName と state をつなぐと「CaliforniaSan Diego」に
    なってしまう。既に「カリフォルニア州サンディエゴ」の形で
    持っているので、そちらを使う。
    """
    row = _venue_row(en)
    return row[3] if row and len(row) > 3 else ""


def fetch() -> tuple:
    teams = requests.get(f"{API}/teams",
                         params={"sportId": 1, "hydrate": "league,division,venue"},
                         headers=UA, timeout=30).json().get("teams", [])
    vs = requests.get(f"{API}/venues",
                      params={"sportId": 1,
                              "hydrate": "location,fieldInfo"},
                      headers=UA, timeout=30).json().get("venues", [])
    venue = {v["id"]: v for v in vs}
    return teams, venue


def _geo_edge(tid: str, coord: dict, all_coords: list) -> str:
    """本拠地が地理の端なら、その言い方。端でなければ空。

    「MLBでいちばん北」は位置から決まるので、当てにいく余地がない。
    """
    lat, lon = coord.get("latitude"), coord.get("longitude")
    if lat is None or lon is None or len(all_coords) < 20:
        return ""
    lats = [a for a, _ in all_coords]
    lons = [b for _, b in all_coords]
    if lat >= max(lats):
        return "MLBでいちばん北にある球団"
    if lat <= min(lats):
        return "MLBでいちばん南にある球団"
    if lon <= min(lons):
        return "MLBでいちばん西にある球団"
    if lon >= max(lons):
        return "MLBでいちばん東にある球団"
    return ""


@functools.lru_cache(maxsize=64)
def _roster(tid: str, season: str) -> tuple:
    """その球団の現役名簿と、今シーズンの成績。

    1球団につき1回しか取らない。中心選手と日本人選手の両方が
    同じ名簿を見るので、分けて叩くと30球団で60回になる。
    """
    try:
        r = requests.get(
            f"{API}/teams/{tid}/roster",
            # 打者と投手の両方を明示して取る。
            #
            # group を書かないと、その選手の主なポジションのぶんしか
            # 返らない。大谷翔平は投手として登録されているので
            # 投球成績だけが返り、しかもその中の avg は**被打率**。
            # 打率だと思って読むと .180 が出る。
            params={"rosterType": "active",
                    "hydrate": f"person(stats(type=season,season={season},"
                               "group=[hitting,pitching]))"},
            headers=UA, timeout=30)
        r.raise_for_status()
        return tuple(r.json().get("roster") or [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {tid} の名簿を取れません: {e}", file=sys.stderr)
        return ()


def stars(tid: str, season: str = "") -> list:
    """いまその球団でいちばん打っている人と、いちばん抑えている人。

    指標は本塁打の最多と奪三振の最多にする。順位が一意に決まり、
    こちらが点数を作らずに済む。独自の指標を持ち込むと、
    「なぜこの選手なのか」を毎回説明しないと出せなくなる。

    同じ選手が複数行で返ることがある(移籍すると球団ごとに分かれる)。
    その球団での成績だけを見る。合算すると、他球団で挙げた数字を
    この球団のものとして出すことになる。
    """
    season = season or str(datetime.now(timezone.utc).year)
    bat, arm = None, None
    for row in _roster(tid, season):
        person = row.get("person") or {}
        name = person.get("fullName")
        if not name:
            continue
        for st in (person.get("stats") or []):
            grp = (st.get("group") or {}).get("displayName")
            for sp in (st.get("splits") or []):
                # その球団での分だけ。移籍組は他球団の行も返ってくる。
                if str((sp.get("team") or {}).get("id") or tid) != str(tid):
                    continue
                s = sp.get("stat") or {}
                if grp == "hitting":
                    hr = s.get("homeRuns") or 0
                    if hr and (bat is None or hr > bat[0]):
                        bat = (hr, name,
                               f"打率{s.get('avg', '')}　{hr}本塁打"
                               f"　{s.get('rbi', 0)}打点")
                elif grp == "pitching":
                    so = s.get("strikeOuts") or 0
                    if so and (arm is None or so > arm[0]):
                        arm = (so, name,
                               f"{s.get('wins', 0)}勝{s.get('losses', 0)}敗"
                               f"　防御率{s.get('era', '')}　{so}奪三振")

    out = []
    if bat:
        out.append({"name": bat[1], "line": bat[2], "why": "今季チーム最多本塁打"})
    if arm:
        out.append({"name": arm[1], "line": arm[2], "why": "今季チーム最多奪三振"})
    return out


def japanese_on(tid: str, season: str = "") -> list:
    """その球団にいる日本人選手と、今シーズンの成績。

    なぜ球団の回に入れるのか:
      28日の実測（171本）で、
        題に日本人選手の名前あり  45本 平均435回 登録+12
        なし                  126本 平均164回 登録+ 1
      2.65倍で、登録した13人のうち12人がこちらから来ている。

      球団の回は資産動画でいちばん見られている（16本平均207回）。
      そこに名前が入る球団が30のうち11ある。**同じ本数のまま、
      題に名前が入るだけで変わる。**

      名前を足すために内容を変えるのではない。その球団に
      その選手がいることは事実で、日本語で見る人がいちばん
      知りたいことでもある。今まで入れていなかったほうがおかしい。

    名簿は stars() と同じものを使う（1球団につき1回しか取らない）。
    """
    try:
        from notability_engine import JP_PLAYERS_MLB
    except ImportError:
        return []
    jp = {p["name_en"]: p for p in JP_PLAYERS_MLB}
    out = []
    for row in _roster(tid, season or str(datetime.now(timezone.utc).year)):
        person = row.get("person") or {}
        who = jp.get(person.get("fullName") or "")
        if not who:
            continue
        # 打者の成績と投手の成績、どちらを出すか。
        #
        # 二刀流がいるので、後から来たほうで上書きすると
        # 大谷翔平が「8勝2敗　防御率1.79」だけになる。
        # 表に打者か投手かが書いてあるので、それに従う。
        want = "pitching" if who.get("type") == "pitcher" else "hitting"
        lines = {}
        for st in (person.get("stats") or []):
            grp = (st.get("group") or {}).get("displayName")
            for sp in (st.get("splits") or []):
                if str((sp.get("team") or {}).get("id") or tid) != str(tid):
                    continue
                s = sp.get("stat") or {}
                if grp == "pitching" and s.get("inningsPitched"):
                    lines["pitching"] = (
                        f"{s.get('wins', 0)}勝{s.get('losses', 0)}敗"
                        f"　防御率{s.get('era', '')}")
                elif grp == "hitting" and s.get("atBats"):
                    lines["hitting"] = (
                        f"打率{s.get('avg', '')}　{s.get('homeRuns', 0)}本塁打"
                        f"　{s.get('rbi', 0)}打点")
        line = lines.get(want) or lines.get(
            "pitching" if want == "hitting" else "hitting") or ""
        out.append({"name": who["name_jp"], "line": line, "why": "日本人選手"})
    return out


def legends(tid: str, path: str = "data/team_legends.json") -> list:
    """その球団の殿堂入り。上位3人まで保存してある分をそのまま。

    人数の順位には使わない(3人で頭打ちなので、数として意味がない)。
    ここでは誰がいたかを紹介するだけなので、その用途では正しい。
    """
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    row = (d.get("teams") or {}).get(str(tid)) or {}
    return [{"name": p.get("name", ""), "line": p.get("line", ""),
             "hof_year": p.get("hof_year", "")}
            for p in (row.get("players") or []) if p.get("name")][:3]


def rivals_of(team_id: str) -> list:
    """同地区の相手。年に13試合ずつ当たる、いちばん近い4球団。"""
    div = MLB_DIVISIONS.get(str(team_id))
    if not div:
        return []
    return [MLB_TEAM_NAME_JP.get(tid, "")
            for tid, d in MLB_DIVISIONS.items()
            if d == div and str(tid) != str(team_id)]


def traditional_of(team_id: str) -> str:
    """伝統の一戦の相手。無ければ空。"""
    for pair in MLB_RIVALRIES:
        ids = [str(x) for x in pair]
        if str(team_id) in ids:
            other = [x for x in ids if x != str(team_id)]
            if other:
                return MLB_TEAM_NAME_JP.get(other[0], "")
    return ""


def build(t: dict, venue: dict, all_caps: list, all_years: list,
          all_teams: list) -> dict:
    tid = str(t["id"])
    jp = MLB_TEAM_NAME_JP.get(tid) or t.get("name", "")
    v = venue.get((t.get("venue") or {}).get("id")) or {}
    f = v.get("fieldInfo") or {}
    loc = v.get("location") or {}
    div = MLB_DIVISION_NAME_JP.get(MLB_DIVISIONS.get(tid, ""), "")
    year = t.get("firstYearOfPlay") or ""
    coord_of = (loc.get("defaultCoordinates") or {})
    all_coords = []
    for other in all_teams:
        ov = venue.get((other.get("venue") or {}).get("id")) or {}
        oc = ((ov.get("location") or {}).get("defaultCoordinates") or {})
        if oc.get("latitude") is not None:
            all_coords.append((oc["latitude"], oc["longitude"]))

    where = jp_where(v.get("name", "")) or (t.get("locationName") or
                                            loc.get("city") or "")
    city = t.get("locationName") or loc.get("city") or ""
    state = loc.get("state") or ""

    items = []
    if year:
        items.append((f"{year}年から",
                      f"{datetime.now(timezone.utc).year - int(year)}年めの"
                      "球団です"))
    items.append((f"本拠地は{where}",
                  f"球場は{jp_venue(v.get('name', ''))}"
                  + (f"、収容{f['capacity']:,}人" if f.get("capacity") else "")))
    if div:
        items.append((div, "この地区の相手とは、年に13試合ずつ戦います"))
    riv = rivals_of(tid)
    if riv:
        items.append(("同じ地区の4球団", "、".join(riv)))
    trad = traditional_of(tid)
    if trad:
        items.append(("伝統の一戦", f"{trad}との対戦がそう呼ばれています"))

    # 1枚目に出す、その球団でいちばん際立つ事実。
    #
    # 「いちばん古い部類」で済ませていたら、1890年以前の球団が
    # 5つ以上あって同じ言葉が並んだ。順位にすれば全部違う文になる。
    #
    # **日本人選手がいる球団は、その名前が先。**
    # 28日の実測で、題に名前があるものは平均435回、無いものは164回。
    # 創設年より、その球団に誰がいるかのほうが先に知りたいこと。
    jps = japanese_on(tid)
    if jps:
        items.insert(0, ("日本人選手",
                         "・".join(x["name"] for x in jps[:3]) + "が所属"))
    hook = ""
    if year and all_years:
        yr = sorted(all_years).index(int(year)) + 1
        if yr <= 5:
            hook = (f"{year}年創設　MLBで"
                    + ("いちばん古い" if yr == 1 else f"{yr}番目に古い"))
    if not hook and f.get("capacity") and all_caps:
        if f["capacity"] == min(all_caps):
            hook = f"本拠地の収容{f['capacity']:,}人　MLBでいちばん小さい"
        elif f["capacity"] == max(all_caps):
            hook = f"本拠地の収容{f['capacity']:,}人　MLBでいちばん大きい"
    # 殿堂入りの人数は使わない。
    #
    # data/team_legends.json は球団ごとに上位3人しか保存していない。
    # 27球団のうち21球団がちょうど3人で、これは実際の人数ではなく
    # 見本の数。「殿堂入り3人　MLBで最多」はヤンキースについて明確に
    # 嘘になる。数に見えるが数ではない値を、順位に使わない。

    # 収容人数の順位。こちらは全球団ぶん取れていて、上限も無い。
    if not hook and f.get("capacity") and len(all_caps) >= 25:
        rank = sorted(all_caps, reverse=True).index(f["capacity"]) + 1
        if rank <= 3:
            hook = f"本拠地の収容{f['capacity']:,}人　MLBで{rank}番目に大きい"
        elif rank >= len(all_caps) - 2:
            small = len(all_caps) - rank + 1
            hook = f"本拠地の収容{f['capacity']:,}人　MLBで{small}番目に小さい"

    # 地理の端。位置は全球団ぶん持っているので順位が出せる。
    if not hook:
        edge = _geo_edge(tid, coord_of, all_coords)
        if edge:
            hook = f"{edge}　本拠地は{where}"

    # 伝統の一戦。順位ではないが、その球団だけの事実で、年で変わらない。
    # 「1903年創設　本拠地はニューヨーク州ニューヨーク」より、
    # 「レッドソックスとの伝統の一戦」のほうが、その球団を表している。
    if not hook and trad:
        hook = f"{trad}との伝統の一戦で知られる球団"

    if not hook and year:
        hook = f"{year}年創設　本拠地は{where}"
    if not hook:
        hook = f"本拠地は{where}"

    # 日本人選手がいる球団は、その名前を先頭に付ける。
    # 題は「【MLB】{label}｜{hook}」の形なので、ここに入れば題に載る。
    # 28日の実測で、題に名前があるものは平均435回、無いものは164回。
    if jps:
        hook = "・".join(x["name"] for x in jps[:3]) + "が所属　" + hook

    # 地図に打つための座標。同地区の4球団ぶんも一緒に持たせる。
    # 画面側でAPIを叩き直さずに済む。
    coord = (loc.get("defaultCoordinates") or {})
    all_points = []
    for other in all_teams:
        ov = venue.get((other.get("venue") or {}).get("id")) or {}
        oc = ((ov.get("location") or {}).get("defaultCoordinates") or {})
        if oc.get("latitude"):
            all_points.append([round(oc["latitude"], 3),
                               round(oc["longitude"], 3)])
    near = []
    for other in all_teams:
        oid = str(other["id"])
        if oid == tid or MLB_DIVISIONS.get(oid) != MLB_DIVISIONS.get(tid):
            continue
        ov = venue.get((other.get("venue") or {}).get("id")) or {}
        oc = ((ov.get("location") or {}).get("defaultCoordinates") or {})
        if oc.get("latitude"):
            near.append({"name": MLB_TEAM_NAME_JP.get(oid, ""),
                         "abbr": other.get("abbreviation", ""),
                         "lat": oc["latitude"], "lon": oc["longitude"]})

    return {
        "key": "team_" + t.get("teamCode", tid),
        # その球団の色。画面のアクセントに使う。
        # 30球団ぶんが同じオレンジだと、どの回も同じ絵に見える。
        "color": MLB_TEAM_COLOR.get(tid),
        "map": {
            "lat": coord.get("latitude"), "lon": coord.get("longitude"),
            "city": city, "state": state,
            "abbr": t.get("abbreviation", ""),
            "division": MLB_DIVISION_NAME_JP.get(MLB_DIVISIONS.get(tid, ""), ""),
            "near": near,
            # 30球団ぶんの位置。「MLBは30球団」と言うところで打つ。
            "all": all_points,
        },
        "label": jp,
        "heading": jp,
        "hook": hook,
        # 創設年と収容人数だけでは、その球団の「顔」が出てこない。
        # 殿堂入りと、いま実際に打って抑えている選手を添える。
        "legends": legends(tid),
        "stars": stars(tid),
        "japanese": jps,
        "where": where,
        "intro": f"{jp}。{where}を本拠地にする球団です。数字で見ていきます。",
        "items": [list(x) for x in items],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/team_topics.json")
    args = ap.parse_args()

    teams, venue = fetch()
    caps = [((venue.get((t.get("venue") or {}).get("id")) or {})
             .get("fieldInfo") or {}).get("capacity")
            for t in teams]
    caps = [c for c in caps if c]

    years = [int(t["firstYearOfPlay"]) for t in teams
             if (t.get("firstYearOfPlay") or "").isdigit()]
    topics = [build(t, venue, caps, years, teams) for t in teams]
    topics = [x for x in topics if x["label"]]

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "MLB Stats API",
        "topics": topics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[info] {len(topics)}球団ぶんを書き出しました -> {p}\n")
    for t in topics[:6]:
        print(f"  {t['label']:16s} {t['hook']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
