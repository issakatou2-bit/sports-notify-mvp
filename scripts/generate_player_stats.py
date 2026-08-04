"""
MLB Stats APIから選手の今季成績を取得し、ベストナイン編成用のJSONを出力する。

なぜ毎日取り直すのか:
  MLB Stats APIの season 成績は、試合が終わるたびに更新される。
  毎日19時(JST)の生成タイミングで取り直せば、「昨日までの最新成績」で
  編成できる状態が自動的に保たれる。

出力:
  public/player_stats.json
    {
      "updated_at": "...",
      "season": "2026",
      "batters": {"C": [...], "1B": [...], ...},
      "pitchers": [...]
    }

注意:
  MLB Stats APIには公式ドキュメントが無く、レスポンス構造が予告なく
  変わりうる。取得できなかった項目は握りつぶさずログに出し、
  ページ側は「データが無ければ何も出さない」作りにしてある。

使い方:
  python3 scripts/generate_player_stats.py --out public/player_stats.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# 守備位置の略号 -> 表示名。ベストナインの枠に対応する。
POSITION_SLOTS = {
    "C": "捕手",
    "1B": "一塁手",
    "2B": "二塁手",
    "3B": "三塁手",
    "SS": "遊撃手",
    "LF": "左翼手",
    "CF": "中堅手",
    "RF": "右翼手",
    "DH": "指名打者",
}

# 1ポジションあたり、選択肢として持たせる人数
PLAYERS_PER_SLOT = 12
PITCHER_COUNT = 15

# 規定打席に満たない選手が上位に来ないよう、最低打席数を設ける
MIN_PLATE_APPEARANCES = 150
MIN_INNINGS_PITCHED = 50.0


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_hitting(season: str) -> list:
    """打者の今季成績を取得する。OPS順の上位から必要数を確保する。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/stats",
            params={
                "stats": "season",
                "group": "hitting",
                "season": season,
                "sportId": 1,
                "limit": 400,
                "sortStat": "onBasePlusSlugging",
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 打者成績の取得に失敗しました: {e}", file=sys.stderr)
        return []

    out = []
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            player = split.get("player") or {}
            stat = split.get("stat") or {}
            team = split.get("team") or {}
            pos = (split.get("position") or player.get("primaryPosition") or {}).get(
                "abbreviation"
            )
            pa = stat.get("plateAppearances")
            if pa is None or int(pa) < MIN_PLATE_APPEARANCES:
                continue
            out.append(
                {
                    "id": str(player.get("id", "")),
                    "name": player.get("fullName", ""),
                    "team": team.get("abbreviation") or team.get("name", ""),
                    "pos": pos,
                    "ops": stat.get("ops"),
                    "avg": stat.get("avg"),
                    "hr": stat.get("homeRuns"),
                    "rbi": stat.get("rbi"),
                    "pa": pa,
                }
            )
    return out


def fetch_pitching(season: str) -> list:
    """投手の今季成績を取得する。防御率の良い順。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/stats",
            params={
                "stats": "season",
                "group": "pitching",
                "season": season,
                "sportId": 1,
                "limit": 200,
                "sortStat": "earnedRunAverage",
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 投手成績の取得に失敗しました: {e}", file=sys.stderr)
        return []

    out = []
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            player = split.get("player") or {}
            stat = split.get("stat") or {}
            team = split.get("team") or {}
            ip = _safe_float(stat.get("inningsPitched"), 0.0)
            if ip < MIN_INNINGS_PITCHED:
                continue
            out.append(
                {
                    "id": str(player.get("id", "")),
                    "name": player.get("fullName", ""),
                    "team": team.get("abbreviation") or team.get("name", ""),
                    "pos": "P",
                    "era": stat.get("era"),
                    "wins": stat.get("wins"),
                    "losses": stat.get("losses"),
                    "so": stat.get("strikeOuts"),
                    "ip": stat.get("inningsPitched"),
                }
            )
    out.sort(key=lambda p: _safe_float(p.get("era"), 99.0))
    return out[:PITCHER_COUNT]


def group_batters(batters: list) -> dict:
    """打者をポジション別に振り分け、各枠をOPS順の上位で埋める"""
    grouped = {slot: [] for slot in POSITION_SLOTS}
    ordered = sorted(batters, key=lambda p: -_safe_float(p.get("ops"), 0.0))
    for p in ordered:
        pos = p.get("pos")
        if pos in grouped and len(grouped[pos]) < PLAYERS_PER_SLOT:
            grouped[pos].append(p)
    # DHは専任が少なく枠が埋まらないことが多いため、
    # OPS上位の打者で補完する(実際の運用上、指名打者は他ポジションの
    # 選手が務めることが多く、ユーザーの感覚とも合う)
    if len(grouped["DH"]) < PLAYERS_PER_SLOT:
        used = {p["id"] for p in grouped["DH"]}
        for p in ordered:
            if len(grouped["DH"]) >= PLAYERS_PER_SLOT:
                break
            if p["id"] not in used and p.get("pos") != "P":
                grouped["DH"].append(p)
                used.add(p["id"])
    return grouped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="public/player_stats.json")
    parser.add_argument("--season", default=None)
    args = parser.parse_args()

    season = args.season or str(datetime.now(timezone.utc).year)

    batters = fetch_hitting(season)
    pitchers = fetch_pitching(season)

    if not batters and not pitchers:
        print("[warn] 選手成績を1件も取得できませんでした。JSONは出力しません。")
        return

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "batters": group_batters(batters),
        "pitchers": pitchers,
        "position_names": POSITION_SLOTS,
    }

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    total = sum(len(v) for v in data["batters"].values()) + len(pitchers)
    print(f"[info] 選手成績を出力しました({total}名) -> {out_path}")


if __name__ == "__main__":
    main()
