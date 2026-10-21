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
    first = {tid: int(first_years.get(tid) or 0) for tid in pair}
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
        "ws": True,
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
    items = []
    for (number, tid), g in zip(order, games):
        tbd = bool((g.get("status") or {}).get("startTimeTBD"))
        label = jst_label(g.get("gameDate"), tbd)
        items.append((f"第{number}戦", f"{label}　{names.get(tid, '')}の本拠地"))
    items.append(("本拠地の並び", pattern_text(order, names)))
    items.append(("優勝まで", "先に4勝した球団がワールドシリーズ優勝　最大7試合"))
    items.append(("第5戦以降", "どちらも4勝に届いていない場合だけ開催"))
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
        "ws": True,
        "season": season,
    }


# ---------------------------------------------------------------- 組み立て

def build_topics(season: int, get=_get, cache_path=DEFAULT_CACHE) -> list:
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
    return topics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    season = args.season or now.year
    topics = build_topics(season, cache_path=args.cache or None)
    pathlib.Path(args.out).write_text(json.dumps(
        {"updated_at": now.isoformat(),
         "source": "MLB Stats API（球団情報・過去のワールドシリーズの試合結果・順位表）",
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
