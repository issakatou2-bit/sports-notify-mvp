#!/usr/bin/env python3
"""
その日の打点が「どういう場面で入ったか」を、MLB公式APIから判定する。

    python3 scripts/clutch.py --date 2026-08-10

なぜ要るか:
  同じ3ランでも、逆転と大差での1本では試合への効き方が違う。
  ところが成績のエンドポイント(people/{id}/stats)が返すのは1日の合計で、
  何回に何点差で打ったかを持っていない。貢献度がそこを見られず、
  「打点3」を一律に扱っていた。

どう取るか:
  /game/{gamePk}/playByPlay が1プレーごとに、そのプレー後の
  awayScore / homeScore を返す。直前のプレーの値と比べれば
  「打つ前の点差」が分かる。打者IDも入っているので、
  日本人選手の打席だけを拾える。

  外部サイトを見に行く必要はなく、認証も要らない。
  1日あたりのリクエストはその日の試合数(10〜15)。
"""

import argparse
import json
import sys
import time

import requests

API = "https://statsapi.mlb.com/api/v1"

# 状況ごとの加点。貢献度(打者は好打で70〜100)に対する上乗せなので、
# 大きすぎると状況だけで順位が決まってしまう。
# 逆転が最も重く、勝ち越し、同点と続く。
CLUTCH_POINTS = {
    "サヨナラ": 35,
    "逆転": 25,
    "満塁本塁打": 20,
    "勝ち越し": 15,
    "先頭打者本塁打": 15,
    "同点": 12,
}

# 表示の優先順。1日に複数あった場合、いちばん重いものを見出しに使う。
CLUTCH_ORDER = ["サヨナラ", "逆転", "満塁本塁打", "勝ち越し",
                "先頭打者本塁打", "同点"]

# 用語の説明。画面の下に小さく出して、聞き慣れない言葉で止まらないようにする。
CLUTCH_NOTES = {
    "サヨナラ": "サヨナラ＝最終回裏に決着をつける一打",
    "満塁本塁打": "満塁本塁打＝グランドスラム。一度に4点",
    "先頭打者本塁打": "先頭打者本塁打＝試合の初打席での一発",
    "逆転": "逆転＝負けている場面をひっくり返した一打",
    "勝ち越し": "勝ち越し＝同点から抜け出した一打",
    "同点": "同点＝負けている場面を追いついた一打",
}


def classify(before: int, after: int) -> str:
    """
    打撃側から見た点差の変化を、場面の名前に直す。

    before … その打席の前の点差(自チーム - 相手)
    after  … その打席の後の点差
    """
    if before < 0 <= after and after > 0:
        return "逆転"
    if before == 0 and after > 0:
        return "勝ち越し"
    if before < 0 and after == 0:
        return "同点"
    return ""


def game_pks(date: str, timeout: int = 30) -> list:
    r = requests.get(f"{API}/schedule", params={"sportId": 1, "date": date},
                     timeout=timeout)
    r.raise_for_status()
    out = []
    for d in r.json().get("dates", []):
        for g in d.get("games", []):
            if g.get("gamePk"):
                out.append(g["gamePk"])
    return out


def scan_game(pk: int, wanted: set, timeout: int = 30) -> list:
    """1試合を走査して、対象打者の「効いた打席」を返す。"""
    r = requests.get(f"{API}/game/{pk}/playByPlay", timeout=timeout)
    r.raise_for_status()
    plays = r.json().get("allPlays", [])

    out = []
    prev_a = prev_h = 0
    last_index = len(plays) - 1
    for idx, p in enumerate(plays):
        res = p.get("result", {})
        about = p.get("about", {})
        a = res.get("awayScore", prev_a)
        h = res.get("homeScore", prev_h)

        batter = ((p.get("matchup") or {}).get("batter") or {}).get("id")
        rbi = res.get("rbi") or 0
        ev = res.get("eventType")

        if batter and str(batter) in wanted:
            top = about.get("halfInning") == "top"
            before = (prev_a - prev_h) if top else (prev_h - prev_a)
            after = (a - h) if top else (h - a)

            kinds = []
            # 打点が動いていない打席は、場面の判定をしても意味が無い
            if rbi:
                k = classify(before, after)
                if k:
                    kinds.append(k)
                # 試合を終わらせた一打。9回裏以降で、これが最後のプレー。
                if (not top and idx == last_index
                        and about.get("inning", 0) >= 9 and after > 0
                        and before <= 0):
                    kinds.append("サヨナラ")

            if ev == "home_run":
                # 満塁本塁打は打点4で必ず判別できる
                if rbi == 4:
                    kinds.append("満塁本塁打")
                # 試合の最初の打席での一発。以降のイニングの先頭とは別物。
                if idx == 0:
                    kinds.append("先頭打者本塁打")

            for kind in kinds:
                out.append({
                    "player_id": str(batter),
                    "kind": kind,
                    "event": res.get("event"),
                    "event_type": ev,
                    "rbi": rbi,
                    "inning": about.get("inning"),
                })
        prev_a, prev_h = a, h
    return out


def build(date: str, player_ids, sleep: float = 0.2) -> dict:
    """
    player_id -> {"plays": [...], "points": n, "label": "逆転3ラン"}
    """
    wanted = {str(p) for p in player_ids if p}
    if not wanted:
        return {}

    found = []
    pks = game_pks(date)
    print(f"[info] {date} の試合数: {len(pks)}")
    for pk in pks:
        try:
            found += scan_game(pk, wanted)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] gamePk={pk} を読めませんでした: {e}", file=sys.stderr)
        time.sleep(sleep)

    out: dict = {}
    for f in found:
        e = out.setdefault(f["player_id"], {"plays": [], "points": 0})
        e["plays"].append(f)
        e["points"] += CLUTCH_POINTS.get(f["kind"], 0)

    for pid, e in out.items():
        e["label"] = _label(e["plays"])
        e["note"] = _note(e["plays"])
    return out


def _best(plays: list):
    for kind in CLUTCH_ORDER:
        for p in plays:
            if p["kind"] == kind:
                return p
    return None


def _label(plays: list) -> str:
    """見出しにする一言。いちばん重い場面を選ぶ。"""
    best = _best(plays)
    if not best:
        return ""
    kind = best["kind"]
    # 「満塁本塁打3ラン」のような重複を避ける。
    # それ自体が打った内容を表している言葉は、そのまま使う。
    if kind in ("満塁本塁打", "先頭打者本塁打"):
        return kind
    return f"{kind}{_event_jp(best)}"


def _note(plays: list) -> str:
    """見出しに使った言葉の説明。聞き慣れない語で止まらないようにする。"""
    best = _best(plays)
    return CLUTCH_NOTES.get(best["kind"], "") if best else ""


def _event_jp(play: dict) -> str:
    if play.get("event_type") == "home_run":
        rbi = play.get("rbi") or 1
        return {1: "ソロ", 2: "2ラン", 3: "3ラン", 4: "満塁本塁打"}.get(rbi, "本塁打")
    return "打点"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="米国日付 YYYY-MM-DD")
    ap.add_argument("--players", default="",
                    help="MLBの選手IDをカンマ区切りで。省略時は全打者")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    ids = [x.strip() for x in args.players.split(",") if x.strip()]
    if not ids:
        print("[error] --players に選手IDを指定してください")
        return 1

    data = build(args.date, ids)
    for pid, e in data.items():
        print(f"  {pid}: +{e['points']}点  {e['label']}")
        for p in e["plays"]:
            print(f"      {p['inning']}回 {p['kind']} {p['event']} 打点{p['rbi']}")
    if args.out:
        import pathlib
        pathlib.Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
