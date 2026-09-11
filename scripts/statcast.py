#!/usr/bin/env python3
"""本塁打の飛距離と打球速度を、MLB公式の計測から読む。

なぜ要るのか:
  実測でいちばん強い枠は成績ランキング（8/14〜9/11の37本で
  平均410再生・視聴率100.1%・登録8人）。他の枠の2〜4倍ある。
  **そこに足せる具体的な数字を探していた。**

  「村上宗隆 3打数1安打 1本塁打 1打点」は、起きたことは分かるが
  どんな1本だったかは分からない。MLBは全球場にトラッキングを
  入れていて、**打球速度・角度・飛距離を1球ずつ公開している。**

    https://baseballsavant.mlb.com/statcast_search/csv?...

  9/11に叩いて確認した。9/8〜9/9の本塁打83本ぶんが返り、
  日本人選手は2本含まれていた。

    村上宗隆   飛距離 116m  打球速度 177km/h
    岡本和真   飛距離 118m  打球速度 171km/h

  キーも登録も要らない。1日ぶんで40KB程度のCSVを1回取るだけ。

単位について:
  返ってくるのはフィートとマイル。**日本の視聴者にはメートルと
  km/hで出す。**換算はここだけで行う（画面と読み上げで別々に
  計算すると、片方だけ古い数字が残る）。

使い方:
  python3 scripts/statcast.py --date 2026-09-09
  python3 scripts/statcast.py --date 2026-09-09 --out data/statcast.json
"""

import argparse
import csv
import io
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BASE = "https://baseballsavant.mlb.com/statcast_search/csv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; collespo/1.0)"}

FT_TO_M = 0.3048
MPH_TO_KMH = 1.609344


def fetch_home_runs(day: str, timeout: int = 45) -> list:
    """その日の本塁打の打球データ。取れなければ空。

    本塁打だけに絞る（`hfAB=home\\.\\.run|`）。全打球を取ると
    1日で数MBになり、使う場面が無い。
    """
    params = {
        "all": "true",
        "player_type": "batter",
        "game_date_gt": day,
        "game_date_lt": day,
        "hfAB": "home\\.\\.run|",
        "type": "details",
    }
    try:
        r = requests.get(BASE, params=params, headers=UA, timeout=timeout)
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] 打球データを取れません: {e}", file=sys.stderr)
        return []
    return rows


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _key(name: str) -> str:
    """突き合わせ用の姓。

    Statcast は "Murakami, Munetaka" の形で返す。名簿は
    "Munetaka Murakami"。**姓で突き合わせる。**
    """
    n = (name or "").strip()
    if "," in n:
        return n.split(",")[0].strip().lower()
    return n.split()[-1].lower() if n else ""


def build(rows: list) -> dict:
    """選手ごとの本塁打。{姓: [{...}, ...]}

    1試合に2本打った日は2件返す。**平均にしない。**
    「2本目が130m」は、平均を取ると消えてしまう。
    """
    out = {}
    for r in rows:
        dist = _num(r.get("hit_distance_sc"))
        speed = _num(r.get("launch_speed"))
        if dist is None and speed is None:
            continue
        out.setdefault(_key(r.get("player_name", "")), []).append({
            "name_raw": r.get("player_name", ""),
            "distance_m": round(dist * FT_TO_M) if dist is not None else None,
            "distance_ft": round(dist) if dist is not None else None,
            "speed_kmh": round(speed * MPH_TO_KMH) if speed is not None
            else None,
            "speed_mph": round(speed, 1) if speed is not None else None,
            "angle": _num(r.get("launch_angle")),
            # 何を打ったか。同じ本塁打でも、160km/hの直球を打ったのと
            # 変化球を拾ったのでは中身が違う。
            "pitch": r.get("pitch_type") or "",
            "pitch_kmh": (round(_num(r.get("release_speed")) * MPH_TO_KMH)
                          if _num(r.get("release_speed")) is not None
                          else None),
        })
    return out


def for_player(data: dict, name_en: str) -> list:
    """その選手の本塁打。名簿の英語名（"Munetaka Murakami"）で引く。"""
    return (data.get("home_runs") or {}).get(_key(name_en), [])


def phrase(shots: list) -> str:
    """画面と読み上げに出す言い方。

    **1か所で作る。**画面と読み上げで別々に組み立てると食い違う
    （成績の回で一度起きている）。

    1本なら「飛距離116m・打球速度177km/h」。
    2本以上なら遠いほうを出して「2本目は130m」とは言わない
    （どちらが何本目かは打順で決まり、こちらでは分からない）。
    """
    if not shots:
        return ""
    best = max(shots, key=lambda s: s.get("distance_m") or 0)
    bits = []
    if best.get("distance_m"):
        bits.append("飛距離%dm" % best["distance_m"])
    if best.get("speed_kmh"):
        bits.append("打球速度%dkm/h" % best["speed_kmh"])
    if not bits:
        return ""
    head = "最も遠い1本は" if len(shots) > 1 else ""
    return head + "・".join(bits)


def load(path: str = "data/statcast.json") -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def summary(data: dict) -> str:
    hr = data.get("home_runs") or {}
    lines = ["## 本塁打の計測（MLB公式のトラッキング）", "",
             "%s の本塁打 %d本" % (data.get("date", "?"),
                                sum(len(v) for v in hr.values()))]
    jp = data.get("japanese") or {}
    if jp:
        lines.append("")
        lines.append("### 日本人選手")
        for name, shots in jp.items():
            lines.append("- **%s** %s" % (name, phrase(shots)))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="米国日付 YYYY-MM-DD")
    ap.add_argument("--out", default="data/statcast.json")
    args = ap.parse_args()

    rows = fetch_home_runs(args.date)
    print(f"[info] {args.date} の本塁打: {len(rows)}本")
    hr = build(rows)

    # 日本人選手ぶんは名前つきで取り出しておく。読む側が
    # 姓の突き合わせを繰り返さずに済む。
    jp = {}
    try:
        from notability_engine import JP_PLAYERS_MLB
        for p in JP_PLAYERS_MLB:
            shots = hr.get(_key(p.get("name_en", "")))
            if shots:
                jp[p["name_jp"]] = shots
    except ImportError:
        pass

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": args.date,
        "home_runs": hr,
        "japanese": jp,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print()
    print(summary(data))
    print(f"\n[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
