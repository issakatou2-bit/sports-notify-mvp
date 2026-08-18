#!/usr/bin/env python3
"""
その試合の時刻・その球場の天気を引く。

なぜ要るのか:
  天気は見どころに直結する。外野へ風が吹けば打球が伸び、気温が低ければ
  飛距離が落ち、雨なら順延の可能性がある。既に球場の性格(リグレーは
  風向きで変わる、など)には触れているので、その日の実際の数字を
  添えれば、一般論から「今夜どうなのか」に変わる。

  どれも観測値と予報値で、こちらの解釈は入らない。

材料:
  球場の座標  … MLB Stats API の /venues?hydrate=location(57/62球場で取れる)
  天気       … Open-Meteo。鍵不要・無料・営利利用可

  どちらも認証が要らないので、Secretsを増やさずに済む。

何を書き、何を書かないか:
  数字だけを出す。「打者有利な条件」のような判断は書かない。
  風速と風向きを出せば、どう読むかは見る人が決められる。

出力: data/venue_weather.json

使い方:
  python3 scripts/venue_weather.py --games notable_games.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
METEO = "https://api.open-meteo.com/v1/forecast"
JST = timezone(timedelta(hours=9))

# 風向きの呼び名。16方位まで細かくすると読み上げが長くなる。
DIRECTIONS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]

# これを超えたら「強い風」と書き添える。打球への影響が話に値する目安。
STRONG_WIND_KMH = 20


def direction_jp(deg) -> str:
    try:
        d = float(deg)
    except (TypeError, ValueError):
        return ""
    return DIRECTIONS[int((d + 22.5) % 360 // 45)]


def venue_coords() -> dict:
    """
    球場名 -> (緯度, 経度, タイムゾーン)。取れなければ空。

    座標を手で持たない。移転も改称もあるし、こちらが写した瞬間に
    古くなる。公式が持っているものを毎回引く。
    """
    try:
        r = requests.get(f"{MLB_API}/venues",
                         params={"hydrate": "location,timezone", "sportId": 1},
                         timeout=20)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 球場の座標を取れませんでした: {e}", file=sys.stderr)
        return {}
    out = {}
    for v in r.json().get("venues", []):
        loc = v.get("location") or {}
        c = loc.get("defaultCoordinates") or {}
        if not c.get("latitude"):
            continue
        out[v.get("name", "")] = {
            "lat": c["latitude"], "lon": c["longitude"],
            "tz": (v.get("timeZone") or {}).get("id") or "UTC",
        }
    return out


def fetch_weather(lat: float, lon: float, tz: str) -> dict:
    try:
        r = requests.get(METEO, params={
            "latitude": lat, "longitude": lon,
            "hourly": ("temperature_2m,precipitation_probability,"
                       "wind_speed_10m,wind_direction_10m"),
            "forecast_days": 2, "timezone": tz}, timeout=20)
        r.raise_for_status()
        d = r.json()
        hourly = d.get("hourly") or {}
        # 現地時刻に直すのに要る。時刻の並びだけでは分からない。
        hourly["_utc_offset_hours"] = (d.get("utc_offset_seconds") or 0) / 3600
        return hourly
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 天気を取れませんでした: {e}", file=sys.stderr)
        return {}


def kickoff_utc(start_jst: str) -> datetime:
    """
    "08/17 01:15" (JST) を UTC の日時に直す。読めなければ None。

    試合データが持っているのはJSTだけ(画面も通知もJSTで出すので、
    そこに合わせてある)。天気は現地時刻で返ってくるので、
    いったんUTCを経由して突き合わせる。

    年は入っていない。日本時間の「今日」を基準に、
    近い方の年を当てる(年をまたぐ12月末/1月初の数日のため)。
    """
    try:
        md, hm = str(start_jst).split(" ", 1)
        month, day = (int(x) for x in md.split("/"))
        hour, minute = (int(x) for x in hm.split(":")[:2])
    except (ValueError, IndexError, AttributeError):
        return None
    now = datetime.now(JST)
    year = now.year
    # 12月に「01/02」が来たら翌年、1月に「12/30」が来たら前年
    if month == 12 and now.month == 1:
        year -= 1
    elif month == 1 and now.month == 12:
        year += 1
    try:
        return datetime(year, month, day, hour, minute,
                        tzinfo=JST).astimezone(timezone.utc)
    except ValueError:
        return None


def at_kickoff(hourly: dict, start_jst: str, tz_offset_hours: float) -> dict:
    """
    試合開始に最も近い時刻の値。時刻が読めなければ空。

    Open-Meteoは球場の現地時刻で返す。試合開始はJSTで持っているので、
    UTCを経由して現地時刻に直してから探す。
    ずれると別の時間帯の天気を出すことになる。
    """
    times = hourly.get("time") or []
    if not times:
        return {}
    t = kickoff_utc(start_jst)
    if t is None:
        return {}
    local = t + timedelta(hours=tz_offset_hours)
    want = local.strftime("%Y-%m-%dT%H:00")
    idx = None
    for i, s in enumerate(times):
        if s >= want:
            idx = i
            break
    if idx is None:
        idx = len(times) - 1
    return {
        "temp_c": (hourly.get("temperature_2m") or [None] * (idx + 1))[idx],
        "rain_pct": (hourly.get("precipitation_probability")
                     or [None] * (idx + 1))[idx],
        "wind_kmh": (hourly.get("wind_speed_10m") or [None] * (idx + 1))[idx],
        "wind_deg": (hourly.get("wind_direction_10m")
                     or [None] * (idx + 1))[idx],
        "at": times[idx],
    }


def describe(w: dict) -> str:
    """
    読み上げと画面に出す1行。数字だけを並べ、良し悪しは書かない。
    「打者有利」と言った瞬間に、観測値がこちらの見立てになる。
    """
    if not w or w.get("temp_c") is None:
        return ""
    bits = [f"気温{w['temp_c']:.0f}度"]
    wind = w.get("wind_kmh")
    if wind is not None:
        d = direction_jp(w.get("wind_deg"))
        bits.append(f"{d}の風{wind:.0f}キロ" if d else f"風{wind:.0f}キロ")
        if wind >= STRONG_WIND_KMH:
            bits.append("やや強い風")
    rain = w.get("rain_pct")
    if rain:
        bits.append(f"降水確率{rain}%")
    return "　".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="notable_games.json")
    ap.add_argument("--out", default="data/venue_weather.json")
    args = ap.parse_args()

    try:
        games = [g for g in json.loads(pathlib.Path(args.games).read_text(
            encoding="utf-8")).get("games", []) if g.get("is_notable")][:3]
    except (json.JSONDecodeError, OSError) as e:
        print(f"[info] {args.games} を読めないため天気は付けません: {e}")
        return 0
    if not games:
        print("[info] 対象の試合がありません")
        return 0

    coords = venue_coords()
    if not coords:
        return 0

    out = {}
    for g in games:
        name = g.get("venue_name") or ""
        c = coords.get(name)
        if not c:
            print(f"[info] {name or '(球場不明)'} の座標が無いため飛ばします")
            continue
        hourly = fetch_weather(c["lat"], c["lon"], c["tz"])
        # Open-Meteo が返す時刻はこのオフセットの現地時刻
        off = (hourly.get("_utc_offset_hours") or 0)
        w = at_kickoff(hourly, g.get("start_time_jst") or "", off)
        line = describe(w)
        if not line:
            continue
        out[g.get("game_id") or name] = {
            "venue": name, "venue_jp": g.get("venue_jp"),
            "text": line, **w,
        }
        print(f"[info] {g.get('venue_jp') or name}: {line}")

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "venues": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(out)}球場ぶん -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
