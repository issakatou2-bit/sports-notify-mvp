#!/usr/bin/env python3
"""ワールドシリーズを盛り上げる「データの視点」の材料。

なぜ要るのか:
  シリーズまで試合が無い日にも、公式データから球団史と日程を紹介する。
  対戦カードと開始日時は、その年の公式日程から決める。

何を言うか（全部 MLB 公式の試合結果・球団情報・順位表から。予想はしない）:
  1. 球団史（key: ws_title_history）
     両球団の創設年（APIの firstYearOfPlay）、過去のワールドシリーズ出場年と
     相手・勝敗・何勝何敗、前回出場から何年ぶりか、優勝経験の有無。
     「初優勝」は両方に優勝経験が無いときだけ。片方でも経験があれば言い方を変える。
     さらに、いまワールドシリーズ優勝が無い球団の数と名前。
  2. 日程と本拠地（key: ws_schedule）
     第1戦の本拠地、2-3-2の並び、各戦の日本時間の日付・曜日・時刻、先に4勝で優勝。
     本拠地の理由は、レギュラーシーズンの勝率で裏付けられるときだけ書く。
  3. 今季PSの両球団それぞれの本塁打・打点・打率・奪三振・防御率の上位。
     打率は既定20打席以上、防御率は既定5回以上。各上位3人と境界の同順位。
     確定試合のboxscoreを合算し、率も打数・安打・自責点・アウト数から計算する。
  4. 今季PSで継続中の連続試合安打・本塁打、今季レギュラーシーズンの直接対決、
     既存の日本人選手名簿と公式の出場者・登録選手を照合したPS成績。

過去の優勝は、1903年から昨季までのポストシーズン日程（gameType W）の最終結果から
求める。移転・改名した球団も、APIが返す今の球団idで数える。build/ にキャッシュする。
ワールドシリーズの日程が無い季節は、空の topics を書いて正常終了する。

出力: data/ws_topics.json（generated_topics.py の SOURCES 経由で資産動画になる）
使い方:
  python scripts/ws_topics.py --out data/ws_topics.json
"""

import argparse
import json
import pathlib
import sys
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import ps_odds  # noqa: E402  （球団名の日本語表記を同じ仕組みで使う）

API = "https://statsapi.mlb.com/api/v1"
OUT = "data/ws_topics.json"
FIRST_WS = 1903
DEFAULT_CACHE = ROOT / "build" / "ws_history_cache.json"
JST = timezone(timedelta(hours=9))
WEEKDAYS = "月火水木金土日"
PS_TYPES = "F,D,L,W"
MIN_PA = 20
MIN_OUTS = 15  # 5回。投球回の小数部分は十進数ではなくアウト数。


def _get(path: str, **params) -> dict:
    return ps_odds._get(path, **params)


def team_jp(tid: int, name_en: str = "") -> str:
    """球団の日本語名。ps_odds と同じ辞書・昔の名前の扱いを使う。"""
    import notability_engine as ne
    name = ne.MLB_TEAM_NAME_JP.get(str(tid)) or ps_odds.team_jp(tid, name_en)
    if not name or name.isascii():
        raise ValueError(f"日本語球団名が未登録: {tid}")
    return name


def venue_jp(name_en: str) -> str:
    """球場の日本語名。notability_engine の登録を使う。無ければ空。"""
    import notability_engine as ne
    row = ne.MLB_VENUE_NOTES.get(name_en or "")
    if not row:
        for key, value in ne.MLB_VENUE_NOTES.items():
            if key and key in (name_en or ""):
                row = value
                break
    return row[0] if row else ""


# ---------------------------------------------------------------- API

def games_of(schedule: dict) -> list:
    return [g for day in (schedule or {}).get("dates") or []
            for g in day.get("games") or []]


def ws_games(season: int, get=_get) -> list:
    """その年のポストシーズン日程のうち、ワールドシリーズ（gameType W）の試合。"""
    return games_of(get("/schedule", sportId=1, gameType="W", season=season))


def team_info(tid: int, season: int, get=_get) -> dict:
    rows = get(f"/teams/{tid}", season=season).get("teams") or []
    return rows[0] if rows else {}


def all_teams(season: int, get=_get) -> list:
    return get("/teams", sportId=1, season=season).get("teams") or []


def regular_records(season: int, get=_get) -> dict:
    """{球団id: {wins, losses, pct}}。レギュラーシーズンの順位表から。"""
    d = get("/standings", leagueId="103,104", season=season,
            standingsTypes="regularSeason")
    out = {}
    for block in d.get("records") or []:
        for row in block.get("teamRecords") or []:
            tid = (row.get("team") or {}).get("id")
            if tid is None:
                continue
            wins, losses = int(row.get("wins") or 0), int(row.get("losses") or 0)
            pct = row.get("winningPercentage")
            if not pct or pct.startswith("-"):
                pct = _pct_text(wins, losses)
            out[int(tid)] = {"wins": wins, "losses": losses, "pct": pct}
    return out


# ---------------------------------------------------------------- 過去のWS

def _sort_games(games: list) -> list:
    return sorted(games, key=lambda g: (g.get("seriesGameNumber") or 0,
                                        g.get("gameDate") or "",
                                        g.get("gamePk") or 0))


def parse_series(season: int, games: list) -> dict:
    """1年のワールドシリーズの結果。延期の行・同じ試合の再開の行は1回だけ数える。"""
    unique = {}
    for g in _sort_games(games):
        pk = g.get("gamePk", len(unique))
        # 延期・中断行より、同じ試合の確定した結果を優先する。
        old = unique.get(pk)
        if old is None or (g.get("status") or {}).get("abstractGameState") == "Final":
            unique[pk] = g
    rows = _sort_games(list(unique.values()))
    ids = []
    for g in rows:
        for side in ("away", "home"):
            tid = g["teams"][side]["team"]["id"]
            if tid not in ids:
                ids.append(tid)
    result = {"season": season, "teams": ids[:2], "wins": {}, "losses": {},
              "champion": None, "games": len(rows), "complete": True}
    if len(ids) < 2:
        result["complete"] = not rows
        return result
    a, b = ids[0], ids[1]
    wins = {a: 0, b: 0}
    losses = {a: 0, b: 0}
    for g in rows:
        if (g.get("status") or {}).get("abstractGameState") != "Final":
            continue
        away, home = g["teams"]["away"], g["teams"]["home"]
        aw, hw = bool(away.get("isWinner")), bool(home.get("isWinner"))
        if aw == hw:                      # 引き分け・延期（勝者なし）
            continue
        winner = away["team"]["id"] if aw else home["team"]["id"]
        loser = home["team"]["id"] if aw else away["team"]["id"]
        if winner not in wins or loser not in wins:
            continue
        wins[winner] += 1
        losses[loser] += 1
    result["wins"] = wins
    result["losses"] = losses
    pending = any((g.get("status") or {}).get("abstractGameState") != "Final"
                  and (g.get("status") or {}).get("detailedState") not in
                  ("Cancelled", "Canceled") for g in rows)
    result["complete"] = not pending and max(wins.values()) >= 4 and wins[a] != wins[b]
    if result["complete"]:
        if wins[a] > wins[b]:
            result["champion"] = a
        elif wins[b] > wins[a]:
            result["champion"] = b
    return result


def _norm_result(row: dict) -> dict:
    """JSONのキャッシュから読んだ結果のキーを数値に戻す。"""
    return {
        "season": int(row.get("season") or 0),
        "teams": [int(x) for x in row.get("teams") or []],
        "wins": {int(k): int(v) for k, v in (row.get("wins") or {}).items()},
        "losses": {int(k): int(v) for k, v in (row.get("losses") or {}).items()},
        "champion": int(row["champion"]) if row.get("champion") else None,
        "games": int(row.get("games") or 0),
        "complete": bool(row.get("complete")),
    }


def _read_cache(path) -> dict:
    if not path:
        return {}
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if d.get("version") != 2:
        return {}
    return {int(k): _norm_result(v) for k, v in (d.get("seasons") or {}).items()}


def _write_cache(path, seasons: dict) -> None:
    if not path:
        return
    path = pathlib.Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"version": 2, "seasons": {str(k): v for k, v in seasons.items()}},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"[warn] 過去のWSのキャッシュを書けません({e})", file=sys.stderr)


def load_history(last_season: int, get=_get, cache_path=DEFAULT_CACHE,
                 first: int = FIRST_WS) -> list:
    """1903年〜last_season のワールドシリーズ結果。取れた年は build/ に残す。"""
    cached = _read_cache(cache_path)
    out, changed = [], False
    for season in range(first, last_season + 1):
        row = cached.get(season)
        if not row or not row.get("complete"):
            try:
                row = parse_series(season, ws_games(season, get))
            except Exception as e:                              # noqa: BLE001
                print(f"[warn] {season}年のワールドシリーズを取れません({e})",
                      file=sys.stderr)
                row = {"season": season, "teams": [], "wins": {}, "losses": {},
                       "champion": None, "games": 0, "complete": False}
            else:
                changed = True
            cached[season] = row
        out.append(row)
    if changed:
        _write_cache(cache_path, cached)
    return out


def appearances(history: list, tid: int) -> list:
    """その球団のワールドシリーズ出場（古い順）。"""
    out = []
    for row in history:
        teams = row.get("teams") or []
        if tid not in teams or len(teams) < 2 or not row.get("games"):
            continue
        opp = next(t for t in teams if t != tid)
        out.append({"season": int(row["season"]), "opponent": opp,
                    "wins": int((row.get("wins") or {}).get(tid, 0)),
                    "losses": int((row.get("losses") or {}).get(tid, 0)),
                    "won": row.get("champion") == tid})
    out.sort(key=lambda r: r["season"])
    return out


def title_state(apps: list) -> dict:
    won = [a for a in apps if a["won"]]
    return {"has_title": bool(won), "titles": len(won),
            "last_title": won[-1]["season"] if won else None}


def _pct_text(wins: int, losses: int) -> str:
    total = wins + losses
    return f"{wins / total:.3f}".lstrip("0") if total else ".000"


def title_chance(state: dict, season: int, other_has_title: bool) -> str:
    """その球団の優勝の言い方。「初優勝」は両方に経験が無いときだけ使う。"""
    if state["has_title"]:
        years = season - state["last_title"]
        return "連覇" if years == 1 else f"{years}年ぶり優勝"
    return "初の世界一" if other_has_title else "初優勝"


def no_title_split(history: list, teams: list, exclude=()) -> tuple:
    """(WS優勝が無い球団すべて, 今回の2球団を除いた残り)。teams は [(id, 名前)]。"""
    champions = {row.get("champion") for row in history if row.get("champion")}
    no_title = [(tid, name) for tid, name in teams if tid not in champions]
    others = [(tid, name) for tid, name in no_title if tid not in exclude]
    return no_title, others


def _names_text(rows: list) -> str:
    return "、".join(name for _, name in rows) or "なし"


def _apps_text(apps: list, names: dict) -> str:
    if not apps:
        return "出場なし"
    parts = []
    for a in apps:
        opp = names.get(a["opponent"]) or team_jp(a["opponent"])
        text = f"{a['season']}年　{opp}に{a['wins']}勝{a['losses']}敗"
        if a["won"]:
            text += "（優勝）"
        parts.append(text)
    return "／".join(parts)


def _gap_text(apps: list, season: int) -> str:
    if not apps:
        return "初出場"
    return f"{season - apps[-1]['season']}年ぶり{len(apps) + 1}回目"


def title_history_topic(season: int, pair: tuple, history: list, names: dict,
                        first_years: dict, all_team_rows: list = (),
                        home_id: int = None) -> dict:
    """「どっちが勝っても初優勝」型の話題。優勝経験があれば言い方を変える。"""
    a, b = pair
    apps = {tid: appearances(history, tid) for tid in pair}
    states = {tid: title_state(apps[tid]) for tid in pair}
    gaps = {tid: _gap_text(apps[tid], season) for tid in pair}
    titles = {tid: states[tid]["titles"] for tid in pair}
    lasts = {tid: (apps[tid][-1]["season"] if apps[tid] else None) for tid in pair}

    both_new = not states[a]["has_title"] and not states[b]["has_title"]
    if both_new:
        hook = "どっちが勝っても初優勝"
        ending = "どちらが勝っても初優勝です。"
        chance = {a: "初優勝", b: "初優勝"}
    else:
        chance = {tid: title_chance(states[tid], season,
                                    states[b if tid == a else a]["has_title"])
                  for tid in pair}
        hook = "、".join(f"{names[tid]}は{chance[tid]}" for tid in pair)
        ending = "、".join(f"{names[tid]}は{chance[tid]}を目指します"
                          for tid in pair) + "。"

    items = []
    for tid in pair:
        total = len(apps[tid]) + 1          # 今回を含む
        items.append((f"{names[tid]}の球団史",
                      f"ワールドシリーズ出場{total}回"
                      f"（今回を含む）　優勝{titles[tid]}回"))
        items.append((f"{names[tid]}の過去のWS", _apps_text(apps[tid], names)))
    items.append(("前回のWSから",
                  f"{names[a]}は{gaps[a]}、{names[b]}は{gaps[b]}"))
    items.append(("優勝経験", f"{names[a]} {titles[a]}回、{names[b]} {titles[b]}回"))

    no_title, others = no_title_split(history, list(all_team_rows), exclude=pair)
    if all_team_rows:
        items.append(("WS優勝が無い球団",
                      f"{season - 1}年終了時点　今季の{len(all_team_rows)}球団中{len(no_title)}球団"
                      f"（{_names_text(no_title)}）"))
        items.append(("今回の2球団を除く",
                      f"残り{len(others)}球団（{_names_text(others)}）"))

    intro = (f"ワールドシリーズは{names[a]}と{names[b]}。"
             f"{names[a]}は{gaps[a]}、{names[b]}は{gaps[b]}。{ending}")

    big = str(len(no_title)) if no_title else str(max(len(apps[tid]) + 1
                                                       for tid in pair))
    unit = "球団" if no_title else "回"
    sub = "WS優勝が無い球団" if no_title else "ワールドシリーズ出場"
    chips = [{"label": f"{names[tid]}　WS出場",
              "score": f"{len(apps[tid]) + 1}回"} for tid in pair]
    if others:
        chips.append({"label": "今回の2球団を除く", "score": f"{len(others)}球団"})
    ticker = "前回のWS　" + "　".join(
        f"{names[tid]}{lasts[tid]}年" if lasts[tid] else f"{names[tid]}初出場"
        for tid in pair)
    import notability_engine as ne
    color_id = home_id if home_id in pair else a
    return {
        "key": "ws_title_history",
        "label": "ワールドシリーズ　球団の歩み",
        "hook": hook,
        "heading": f"{names[a]} 対 {names[b]}　ワールドシリーズ",
        "intro": intro,
        "intro_as_is": True,
        "style": "v3",
        "v3": {"who": f"{names[a]} 対 {names[b]}", "big": big, "unit": unit,
               "sub": sub, "tag": hook, "chips": chips[:4], "ticker": ticker},
        "team_id": color_id,
        "abbr": ne.MLB_TEAM_ABBR.get(str(color_id), ""),
        "title": f"【MLB】{hook}｜{names[a]}対{names[b]} #Shorts",
        "items": items,
        "japanese": [],
        "story": True,
        "ws": True,
        "ps_ended": False,
        "season": season,
    }


# ---------------------------------------------------------------- 日程

def jst_label(iso: str, tbd: bool = False) -> str:
    """APIの gameDate（UTC）を、日本時間の「10月24日（土）9時」に。未定は「未定」。"""
    if not iso or tbd:
        return "未定"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return "未定"
    text = f"{t.month}月{t.day}日（{WEEKDAYS[t.weekday()]}）{t.hour}時"
    return text + (f"{t.minute}分" if t.minute else "")


def group_dates(games) -> str:
    """続く試合の日本時間を1つに。「10月24日（土）・25日（日）9時」「10月27日（火）〜29日（木）9時」。"""
    times = []
    for g in games:
        tbd = bool((g.get("status") or {}).get("startTimeTBD"))
        iso = g.get("gameDate")
        try:
            t = None if tbd or not iso else datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST)
        except ValueError:
            t = None
        times.append(t)
    if not times or all(t is None for t in times):
        return "未定"
    if any(t is None for t in times):
        return "・".join("未定" if t is None else f"{t.month}月{t.day}日（{WEEKDAYS[t.weekday()]}）"
                        for t in times)
    def day(t, prev):
        head = f"{t.day}日" if prev is not None and prev.month == t.month else f"{t.month}月{t.day}日"
        return f"{head}（{WEEKDAYS[t.weekday()]}）"
    hours = {(t.hour, t.minute) for t in times}
    if len(times) >= 3:
        text = day(times[0], None) + "〜" + day(times[-1], times[0])
    else:
        text = "・".join(day(t, times[i - 1] if i else None) for i, t in enumerate(times))
    if len(hours) == 1:
        h, m = hours.pop()
        return text + f"{h}時" + (f"{m}分" if m else "")
    return text


def home_order(games: list) -> list:
    """[(試合番号, 本拠地の球団id)]。APIのホーム側をそのまま使う。"""
    return [((g.get("seriesGameNumber") or i + 1),
             g["teams"]["home"]["team"]["id"])
            for i, g in enumerate(_sort_games(games))]


def _game_numbers(nums: list) -> str:
    if len(nums) >= 3 and nums == list(range(nums[0], nums[0] + len(nums))):
        return f"{nums[0]}〜{nums[-1]}"
    return "・".join(str(n) for n in nums)


def pattern_text(order: list, names: dict) -> str:
    """本拠地の並び。2-3-2 のときはその言葉も入れる。"""
    ids = [tid for _, tid in order]
    if (len(ids) == 7 and ids[:2] == [ids[0], ids[0]]
            and ids[2:5] == [ids[2], ids[2], ids[2]]
            and ids[5:] == [ids[0], ids[0]] and ids[0] != ids[2]):
        return (f"2-3-2　第1・2・6・7戦が{names.get(ids[0], '')}、"
                f"第3〜5戦が{names.get(ids[2], '')}")
    groups = []
    for number, tid in order:
        if groups and groups[-1][1] == tid:
            groups[-1][0].append(number)
        else:
            groups.append([[number], tid])
    return "　".join(f"第{_game_numbers(nums)}戦が{names.get(tid, '')}"
                     for nums, tid in groups)


def _home_reason(home: int, away: int, records: dict, names: dict):
    """本拠地の理由。レギュラーシーズンの勝率で言えるときだけ。"""
    h, a = records.get(home), records.get(away)
    if not h or not a:
        return None
    try:
        hp = float(str(h["pct"]).replace(".", "0.", 1)
                   if str(h["pct"]).startswith(".") else h["pct"])
        ap = float(str(a["pct"]).replace(".", "0.", 1)
                   if str(a["pct"]).startswith(".") else a["pct"])
    except (TypeError, ValueError):
        return None
    if hp <= ap:
        return None
    return (f"今季のレギュラーシーズンは{names[home]}{h['wins']}勝{h['losses']}敗"
            f"（勝率{h['pct']}）、{names[away]}{a['wins']}勝{a['losses']}敗"
            f"（勝率{a['pct']}）。勝率が上の{names[home]}が本拠地。")


def schedule_topic(season: int, games: list, names: dict,
                   records: dict = None) -> dict:
    """「日程と本拠地」型の話題。2-3-2 と日本時間、先に4勝を書く。"""
    games = _sort_games(games)
    first = games[0]
    home = first["teams"]["home"]["team"]["id"]
    away = first["teams"]["away"]["team"]["id"]
    order = home_order(games)
    first_label = jst_label(first.get("gameDate"),
                            bool((first.get("status") or {}).get("startTimeTBD")))
    # 同じ本拠地が続く試合はまとめて1行に（10/21 全7試合を1つずつ読むと85秒で長かった）。
    groups = []
    for (number, tid), g in zip(order, games):
        if groups and groups[-1][1] == tid:
            groups[-1][0].append((number, g))
        else:
            groups.append([[(number, g)], tid])
    items = []
    for members, tid in groups:
        nums = [n for n, _ in members]
        label = group_dates([g for _, g in members])
        maybe = [n for n in nums if n >= 5]
        note = ("（必要な場合）" if maybe == nums else
                f"（第{_game_numbers(maybe)}戦は必要な場合）" if maybe else "")
        items.append((f"第{_game_numbers(nums)}戦",
                      f"{label}　{names.get(tid, '')}の本拠地{note}"))
    items.append(("優勝まで", "先に4勝した球団がワールドシリーズ優勝　最大7試合"))
    if records:
        reason = _home_reason(home, away, records, names)
        if reason:
            items.append(("本拠地の理由", reason))
    start = f"日本時間{first_label}" if first_label != "未定" else "日時未定"
    intro = (f"ワールドシリーズは{names[away]}と{names[home]}。2-3-2の並びで、"
             f"第1戦は{start}、{names[home]}の本拠地で始まります。"
             f"先に4勝した球団が優勝です。")
    chips = []
    for (number, tid), g in zip(order[:4], games[:4]):
        label = jst_label(g.get("gameDate"),
                          bool((g.get("status") or {}).get("startTimeTBD")))
        chips.append({"label": f"第{number}戦　{names.get(tid, '')}",
                      "score": label.split("（")[0] if label != "未定" else "未定"})
    import notability_engine as ne
    return {
        "key": "ws_schedule",
        "label": "ワールドシリーズの日程",
        "hook": f"第1戦は{names[home]}の本拠地",
        "heading": f"{names[away]} 対 {names[home]}　日程",
        "intro": intro,
        "intro_as_is": True,
        "style": "v3",
        "v3": {"who": f"{names[home]}の本拠地で開幕", "big": "4", "unit": "勝",
               "sub": "先に4勝で優勝", "tag": "ワールドシリーズ 2-3-2",
               "chips": chips[:4],
               "ticker": "第1戦　" + items[0][1]},
        "team_id": home,
        "abbr": ne.MLB_TEAM_ABBR.get(str(home), ""),
        "title": f"【MLB】ワールドシリーズ｜第1戦は{names[home]}の本拠地 #Shorts",
        "items": items,
        "japanese": [],
        "story": True,
        "ws": True,
        "ps_ended": False,
        "season": season,
    }


# ---------------------------------------------------------------- 今季の注目選手・記録

def final_games(rows: list, types: str) -> list:
    """確定試合だけを日付順に。同じgamePkの再開・重複行は1試合。"""
    unique = {g["gamePk"]: g for g in rows
              if g.get("gamePk") and g.get("gameType") in types.split(",")
              and (g.get("status") or {}).get("abstractGameState") == "Final"}
    return sorted(unique.values(), key=lambda g: (g.get("officialDate") or
                                                 g.get("gameDate") or "",
                                                 g.get("gameDate") or "", g["gamePk"]))


def innings_outs(value: str) -> int:
    whole, dot, part = str(value).partition(".")
    if not whole.isdigit() or (dot and part not in ("0", "1", "2")):
        raise ValueError("投球回の表記が不正")
    return int(whole) * 3 + (int(part) if dot else 0)


def innings_text(outs: int) -> str:
    return str(outs // 3) + (f"回{outs % 3}/3" if outs % 3 else "回")


def rate_text(num: int, den: int, places: int) -> str:
    if not den:
        return "—"
    value = (Decimal(num) / Decimal(den)).quantize(
        Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return format(value, f".{places}f").removeprefix("0") if places == 3 else format(value, f".{places}f")


def player_name(name: str) -> str:
    import notability_engine as ne
    jp = next((p["name_jp"] for p in ne.JP_PLAYERS_MLB if p["name_en"] == name), None)
    return jp or ne.MLB_NAME_READINGS.get(name) or ne.MLB_NAME_READINGS.get(name.rsplit(" ", 1)[-1]) or name


def postseason_players(season: int, pair: tuple, get=_get) -> tuple:
    """両球団の今季PS全確定試合のboxscoreを合算。欠測は例外にして部分順位を防ぐ。"""
    games = []
    for tid in pair:
        games.extend(games_of(get("/schedule", sportId=1, teamId=tid,
                                  gameType=PS_TYPES, season=season)))
    games = final_games(games, PS_TYPES)
    players, counts = {}, {tid: 0 for tid in pair}
    for g in games:
        box = get(f"/game/{g['gamePk']}/boxscore")
        for side in ("away", "home"):
            tid = g["teams"][side]["team"]["id"]
            if tid not in pair:
                continue
            team = box["teams"][side]
            if team["team"]["id"] != tid:
                raise ValueError("boxscoreの球団が不一致")
            counts[tid] += 1
            for p in team["players"].values():
                person, stats = p["person"], p.get("stats") or {}
                key = (tid, person["id"])
                row = players.setdefault(key, dict(team=tid, id=person["id"],
                    name=person["fullName"], pa=0, ab=0, hits=0, hr=0, rbi=0,
                    outs=0, er=0, so=0, pitching_games=0, batting=[]))
                bat, pitch = stats.get("batting") or {}, stats.get("pitching") or {}
                if bat and int(bat["plateAppearances"]) > 0:
                    for dest, src in (("pa", "plateAppearances"), ("ab", "atBats"),
                                      ("hits", "hits"), ("hr", "homeRuns"), ("rbi", "rbi")):
                        row[dest] += int(bat[src])
                    row["batting"].append(dict(hits=int(bat["hits"]), hr=int(bat["homeRuns"]),
                        ab=int(bat["atBats"]), sf=int(bat.get("sacFlies") or 0)))
                if pitch:
                    row["outs"] += innings_outs(pitch["inningsPitched"])
                    row["er"] += int(pitch["earnedRuns"])
                    row["so"] += int(pitch["strikeOuts"])
                    row["pitching_games"] += 1
    return list(players.values()), counts


def current_streak(batting: list, field: str) -> int:
    """今季PSの出場試合を末尾から数える。安打は四球・犠打だけの試合で途切れない。"""
    count = 0
    for row in reversed(batting):
        if row[field] > 0:
            count += 1
        elif field == "hits" and row["ab"] == 0 and row["sf"] == 0:
            continue
        else:
            break
    return count


def watch_topic(key: str, heading: str, season: int, pair: tuple, names: dict,
                items: list, scope: str) -> dict:
    return dict(key="ws_" + key, hook=heading, heading=heading, intro=scope,
                items=items, title=f"【MLB】{heading} #Shorts", label=heading,
                intro_as_is=True, japanese=[], story=True, ws=True, ps_ended=False,
                season=season, team_id=pair[1],
                source="MLB Stats API", scope=scope)


def player_topics(season: int, pair: tuple, names: dict, players: list, counts: dict,
                  min_pa: int = MIN_PA, min_outs: int = MIN_OUTS, top: int = 3) -> list:
    """各球団の上位。境界の同順位を含め、率の比較には丸め前の分数を使う。"""
    scope = (f"{season}年ポストシーズンの確定試合。" +
             "、".join(f"{names[t]}{counts[t]}試合" for t in pair) + "が対象です。")
    topics = []
    metrics = [
        ("ps_home_runs", "本塁打", lambda p: p["hr"], lambda p: p["pa"] > 0,
         lambda p: f"{p['hr']}本塁打", False, ""),
        ("ps_rbi", "打点", lambda p: p["rbi"], lambda p: p["pa"] > 0,
         lambda p: f"{p['rbi']}打点", False, ""),
        ("ps_average", "打率", lambda p: Fraction(p["hits"], p["ab"]),
         lambda p: p["pa"] >= min_pa and p["ab"] > 0,
         lambda p: f"打率{rate_text(p['hits'], p['ab'], 3)}（{p['pa']}打席・{p['ab']}打数{p['hits']}安打）",
         False, f"対象は{min_pa}打席以上です。"),
        ("ps_strikeouts", "奪三振", lambda p: p["so"], lambda p: p["pitching_games"] > 0,
         lambda p: f"{p['so']}奪三振", False, ""),
        ("ps_era", "防御率", lambda p: Fraction(p["er"] * 27, p["outs"]),
         lambda p: p["outs"] >= min_outs and p["outs"] > 0,
         lambda p: f"防御率{rate_text(p['er'] * 27, p['outs'], 2)}（{innings_text(p['outs'])}・自責点{p['er']}）",
         True, f"対象は{innings_text(min_outs)}以上です。"),
    ]
    for key, label, score, eligible, display, ascending, rule in metrics:
        items = []
        for tid in pair:
            rows = sorted((p for p in players if p["team"] == tid and eligible(p)),
                          key=lambda p: (score(p) if ascending else -score(p), p["id"]))
            cutoff = score(rows[min(top, len(rows)) - 1]) if rows else None
            selected = [p for i, p in enumerate(rows)
                        if i < top or score(p) == cutoff]
            items.extend((f"{names[tid]}　{player_name(p['name'])}", display(p)) for p in selected)
            if not selected:
                items.append((names[tid], "対象選手なし"))
        topics.append(watch_topic(key, f"WS両球団の今季PS{label}上位", season,
                                  pair, names, items, scope + rule))
    for field, label in (("hits", "安打"), ("hr", "本塁打")):
        rows = [(p, current_streak(p["batting"], field)) for p in players]
        rows = sorted(((p, n) for p, n in rows if n >= 2), key=lambda x: (-x[1], x[0]["id"]))
        if rows:
            topics.append(watch_topic(f"ps_{field}_streak", f"今季PSで継続中の連続試合{label}",
                season, pair, names,
                [(f"{names[p['team']]}　{player_name(p['name'])}", f"{n}試合連続{label}") for p, n in rows],
                scope + "選手自身の出場試合が対象です。" +
                ("安打は四球・死球・犠打のみの試合を挟んでも継続し、その試合は数えません。" if field == "hits" else "")))
    return topics


def head_to_head_topic(season: int, pair: tuple, names: dict, get=_get) -> dict:
    a, b = pair
    rows = final_games(games_of(get("/schedule", sportId=1, teamId=a,
                                    opponentId=b, gameType="R", season=season)), "R")
    wins = {a: 0, b: 0}
    ties = 0
    for g in rows:
        teams = g["teams"]
        if {teams[s]["team"]["id"] for s in ("away", "home")} != set(pair):
            raise ValueError("対戦カードが不一致")
        aw, hw = (teams[s].get("score") for s in ("away", "home"))
        if aw is None or hw is None:
            raise ValueError("確定スコアが欠測")
        if aw == hw:
            ties += 1
        else:
            wins[teams["away" if aw > hw else "home"]["team"]["id"]] += 1
    items = [(names[t], f"{wins[t]}勝{wins[b if t == a else a]}敗") for t in pair]
    if ties:
        items.append(("引き分け", f"{ties}試合"))
    return watch_topic("season_matchup", "WS両球団の今季の直接対決", season, pair, names,
                       items, f"{season}年レギュラーシーズンの直接対決{len(rows)}試合の確定結果です。")


def japanese_topic(season: int, pair: tuple, names: dict, players: list, get=_get):
    import notability_engine as ne
    registry = {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}
    # PS出場者と、現時点の登録選手（PS未出場を含む）を合わせる。
    people = {(p["team"], p["id"]): p["name"] for p in players if p["name"] in registry}
    for tid in pair:
        for entry in get(f"/teams/{tid}/roster", rosterType="active", season=season)["roster"]:
            p = entry["person"]
            if p["fullName"] in registry:
                people[(tid, p["id"])] = p["fullName"]
    by_id = {(p["team"], p["id"]): p for p in players}
    items = []
    for key, name in sorted(people.items()):
        p = by_id.get(key)
        lines = []
        if p and p["pa"]:
            lines.append(f"{p['pa']}打席・{p['ab']}打数{p['hits']}安打・打率{rate_text(p['hits'], p['ab'], 3)}・{p['hr']}本塁打・{p['rbi']}打点")
        if p and p["pitching_games"]:
            lines.append(f"{p['pitching_games']}登板・{innings_text(p['outs'])}・{p['so']}奪三振・自責点{p['er']}・防御率{rate_text(p['er'] * 27, p['outs'], 2)}")
        items.append((f"{names[key[0]]}　{registry[name]}", "／".join(lines) or "今季PSの打席・登板なし"))
    if items:
        return watch_topic("japanese_players", "WS両球団の日本人選手の今季PS成績", season,
                           pair, names, items, f"{season}年PS確定試合の成績です。日本人選手は既存名簿と公式の出場者・登録選手を照合しています。")
    return None


# ---------------------------------------------------------------- 組み立て

def build_topics(season: int, get=_get, cache_path=DEFAULT_CACHE,
                 min_pa: int = MIN_PA, min_outs: int = MIN_OUTS, top: int = 3) -> list:
    """その年のワールドシリーズの材料。日程が無ければ []。"""
    try:
        games = ws_games(season, get)
    except Exception as e:                                      # noqa: BLE001
        print(f"[warn] ワールドシリーズの日程を取れません({e})", file=sys.stderr)
        return []
    if not games:
        return []
    first = _sort_games(games)[0]
    pair = tuple(((first.get("teams") or {}).get(side) or {})
                 .get("team", {}).get("id") for side in ("away", "home"))
    if not all(pair) or pair[0] == pair[1]:
        return []
    names = {tid: team_jp(tid) for tid in pair}

    team_rows = []
    try:
        team_rows = [(int(t["id"]), team_jp(int(t["id"]), t.get("name", "")))
                     for t in all_teams(season, get)]
    except Exception as e:                                      # noqa: BLE001
        print(f"[warn] 球団の一覧を取れません({e})", file=sys.stderr)

    first_years = {}
    for tid in pair:
        try:
            info = team_info(tid, season, get)
            first_years[tid] = int(info.get("firstYearOfPlay") or 0)
        except Exception as e:                                  # noqa: BLE001
            print(f"[warn] {names[tid]}の球団情報を取れません({e})", file=sys.stderr)
            first_years[tid] = 0

    records = {}
    try:
        records = regular_records(season, get)
    except Exception as e:                                      # noqa: BLE001
        print(f"[warn] レギュラーシーズンの順位表を取れません({e})",
              file=sys.stderr)

    history = load_history(season - 1, get=get, cache_path=cache_path)
    topics = []
    if (history and all(row.get("complete") for row in history)
            and all(first_years.values()) and team_rows):
        topics.append(title_history_topic(
            season, pair, history, names, first_years, team_rows,
            home_id=first["teams"]["home"]["team"]["id"]))
    else:
        print("[warn] 過去のワールドシリーズが揃わないため、球団史の話題は作りません",
              file=sys.stderr)
    topics.append(schedule_topic(season, games, names, records))
    try:
        players, counts = postseason_players(season, pair, get)
        if all(counts.values()):
            topics.extend(player_topics(season, pair, names, players, counts, min_pa, min_outs, top))
            try:
                japanese = japanese_topic(season, pair, names, players, get)
                if japanese:
                    topics.append(japanese)
            except Exception:  # 部分的な名簿で「日本人なし」と結論しない
                print("[warn] 日本人選手の登録情報が欠測。該当話題を省略", file=sys.stderr)
    except Exception:
        print("[warn] 今季PSの成績が欠測。選手順位・連続記録を省略", file=sys.stderr)
    try:
        topics.append(head_to_head_topic(season, pair, names, get))
    except Exception:
        print("[warn] 今季の直接対決が欠測。該当話題を省略", file=sys.stderr)
    return topics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--min-pa", type=int, default=MIN_PA)
    ap.add_argument("--min-ip", default="5.0", help="防御率対象の最少投球回。例: 5.1")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    min_outs = innings_outs(args.min_ip)
    if args.min_pa < 1 or min_outs < 1 or args.top < 1:
        ap.error("打席・投球回・順位数は正数が必要です")
    now = datetime.now(timezone.utc)
    season = args.season or now.year
    topics = build_topics(season, cache_path=args.cache or None,
                          min_pa=args.min_pa, min_outs=min_outs, top=args.top)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": now.isoformat(),
         "source": "MLB Stats API（球団情報・試合結果・順位表・今季PSのboxscore・登録選手）",
         "topics": topics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print("  " + t["title"])
        for a, b in t["items"]:
            print(f"     {a} | {b}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
