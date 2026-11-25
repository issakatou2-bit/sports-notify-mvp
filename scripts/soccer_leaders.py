#!/usr/bin/env python3
"""欧州サッカーの得点王・アシスト王争いを、動画1本ぶんの材料にする。

ESPN の statistics は、リーグごとに goalsLeaders / assistsLeaders を
上位50人ぶん返す。順位表（soccer_race）と同じで、毎日出す枠ではない。
**前回から動いた日だけ**1本作る。

動きの決まり:
  ・首位が替わった／首位に並んだ
  ・首位と2位の差が2以上に開いた・1以内に詰まった
  ・日本人選手が上位10人に入った、または上位10人の中で順位を上げた

同じリーグ・同じ部門は7日に1本まで。1日1本まで。日本人の動きを先に。
動きが無い日は picked を空にして返す（呼ぶ側が止まれるように）。
"""

import argparse
import copy
import json
import pathlib
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

try:
    from notability_engine import (JP_PLAYERS_SOCCER, SOCCER_LEAGUE_NAME_JP,
                                   club_name_jp)
except ImportError:                                     # pragma: no cover
    JP_PLAYERS_SOCCER, SOCCER_LEAGUE_NAME_JP = [], {}

    def club_name_jp(name):
        return name

API = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
       "{}/statistics")

LEAGUES = [("eng.1", "PL"), ("esp.1", "PD"), ("ger.1", "BL1"),
           ("ita.1", "SA"), ("fra.1", "FL1")]

SECTIONS = {"goals": "goalsLeaders", "assists": "assistsLeaders"}
SECTION_JP = {"goals": "得点王", "assists": "アシスト王"}
UNIT = {"goals": "点", "assists": "アシスト"}

TOP_N = 10
WINDOW_DAYS = 7
JST = timezone(timedelta(hours=9))


def _key(name: str) -> str:
    """名前の突き合わせ用。アクセントと記号を落として小文字に。"""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z]", "", text.lower())


_NAME_JP = {_key(p.get("name_en")): p.get("name_jp")
            for p in JP_PLAYERS_SOCCER if p.get("name_en")}
_JP_KEYS = set(_NAME_JP)


def _load_kana() -> dict:
    path = HERE.parent / "data" / "player_kana.json"
    try:
        names = json.loads(path.read_text(encoding="utf-8")).get("names") or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {_key(en): jp for en, jp in names.items() if jp}


_KANA = _load_kana()


def name_jp(name: str) -> str:
    key = _key(name)
    return _NAME_JP.get(key) or _KANA.get(key) or name


def is_japanese(name: str) -> bool:
    return _key(name) in _JP_KEYS


def _num(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _int_field(display: str, word: str):
    match = re.search(r"%s:\s*(\d+)" % word, display or "")
    return int(match.group(1)) if match else None


def rank(entries: list) -> list:
    """同じ値は同じ順位にする（1, 2, 2, 4）。"""
    ordered = sorted(entries, key=lambda x: -(x.get("value") or 0))
    out, previous, place = [], object(), 0
    for i, entry in enumerate(ordered):
        value = entry.get("value")
        if i == 0 or value != previous:
            place = i + 1
        out.append({**entry, "rank": place})
        previous = value
    return out


def parse_section(raw: dict, section: str) -> list:
    stat = next((s for s in raw.get("stats") or []
                 if s.get("name") == SECTIONS[section]), {})
    entries = []
    for item in stat.get("leaders") or []:
        athlete = item.get("athlete") or {}
        name = athlete.get("displayName") or ""
        if not name:
            continue
        team = athlete.get("team") or {}
        team_name = team.get("displayName") or ""
        display = item.get("displayValue") or ""
        entries.append({
            "name": name,
            "name_jp": name_jp(name),
            "team": team_name,
            "team_jp": club_name_jp(team_name),
            "value": _num(item.get("value")),
            "matches": _int_field(display, "Matches"),
            "jp": is_japanese(name),
        })
    return rank(entries)


def parse_all(raw_by_code: dict) -> dict:
    out = {}
    for code, section in SECTIONS.items():
        for league, _ in LEAGUES:
            raw = raw_by_code.get(league) or {}
            out[(league, code)] = parse_section(raw, code)
    return out


def snapshot(entries: list) -> dict:
    top = entries[:TOP_N]
    leader = top[0] if top else None
    second = top[1] if len(top) > 1 else None
    gap = None
    if leader and second:
        gap = leader.get("value") - second.get("value")
    return {
        "leader": leader.get("name") if leader else None,
        "leader_jp": leader.get("name_jp") if leader else None,
        "leader_value": leader.get("value") if leader else None,
        "second_value": second.get("value") if second else None,
        "gap": gap,
        "top": [{k: e.get(k) for k in
                 ("rank", "name", "name_jp", "team", "team_jp",
                  "value", "matches", "jp")} for e in top],
        "jp": [{"name": e["name"], "name_jp": e["name_jp"],
                "team_jp": e.get("team_jp") or "",
                "rank": e["rank"], "value": e["value"]}
               for e in top if e.get("jp")],
    }


def _row_before(snapshot: dict, name: str) -> dict:
    """前回のその選手の行。名字だけ差し替えた記録でも名前を取り直す。"""
    for row in (snapshot or {}).get("top") or []:
        if row.get("name") == name:
            return row
    return {}


def _value_before(snapshot: dict, name: str):
    """前回、その選手が何点（何アシスト）だったか。いなければ None。"""
    return _row_before(snapshot, name).get("value")


def detect_movements(previous: dict, current: dict, section: str) -> list:
    if not previous or not current:
        return []
    unit = UNIT.get(section, "")
    out = []
    before_leader = previous.get("leader")
    now_leader = current.get("leader")
    if before_leader and now_leader and before_leader != now_leader:
        text = "%sが%s%sで首位に立った" % (
            current.get("leader_jp"), current.get("leader_value"), unit)
        old_value = _value_before(previous, now_leader)
        if (old_value is not None and current.get("leader_value") is not None
                and current["leader_value"] > old_value):
            text += "。前回より%s%s" % (
                current["leader_value"] - old_value, unit)
        overtaken = _row_before(previous, before_leader).get("name_jp")
        if overtaken:
            text += "。%sを抜いた" % overtaken
        out.append({"kind": "leader_changed", "text": text})
    else:
        before_second = previous.get("second_value")
        now_second = current.get("second_value")
        if (now_second is not None and current.get("leader_value") is not None
                and now_second == current.get("leader_value")
                and before_second != previous.get("leader_value")):
            top = current.get("top") or []
            joined = top[1].get("name_jp") if len(top) > 1 else None
            text = ("%sが%s%sで首位に並んだ" % (joined, now_second, unit)
                    if joined else "2位が%s%sで首位に並んだ" % (now_second, unit))
            out.append({"kind": "tied_lead", "text": text})
        before_gap = previous.get("gap")
        now_gap = current.get("gap")
        if before_gap is not None and now_gap is not None:
            if now_gap >= 2 and before_gap < 2:
                out.append({"kind": "gap_opened",
                            "text": "首位と2位の差が%s%sに開いた"
                                    % (now_gap, unit)})
            elif now_gap <= 1 and before_gap > 1:
                out.append({"kind": "gap_closed",
                            "text": "首位と2位の差が%s%sに詰まった"
                                    % (now_gap, unit)})

    old_ranks = {x["name"]: x["rank"] for x in previous.get("jp") or []}
    for entry in current.get("jp") or []:
        old = old_ranks.get(entry["name"])
        if old is None:
            out.append({"kind": "jp_entered",
                        "text": "%sが%s位で上位10人に入った"
                                % (entry["name_jp"], entry["rank"])})
        elif entry["rank"] < old:
            out.append({"kind": "jp_rose",
                        "text": "%sが%s位から%s位に上がった"
                                % (entry["name_jp"], old, entry["rank"])})
    return out


def within_window(last: str, today: date, days: int = WINDOW_DAYS) -> bool:
    try:
        when = date.fromisoformat(str(last)[:10])
    except (TypeError, ValueError):
        return False
    return (today - when).days < days


def can_publish(state: dict, key: str, today: date) -> bool:
    if str(state.get("last_published_date") or "") == today.isoformat():
        return False
    section = (state.get("sections") or {}).get(key) or {}
    return not within_window(section.get("last_published"), today)


def choose(movements: dict, state: dict, today: date):
    candidates = []
    for key, moves in movements.items():
        if not moves or not can_publish(state, key, today):
            continue
        jp = any(m["kind"].startswith("jp_") for m in moves)
        candidates.append((0 if jp else 1, -len(moves), key, moves))
    candidates.sort()
    return candidates[0] if candidates else None


def league_jp(league: str, code: str) -> str:
    return SOCCER_LEAGUE_NAME_JP.get(code) or code


def title_of(story: dict) -> str:
    snap = story["snap"]
    comp = story["league_jp"]
    section = SECTION_JP[story["section"]]
    unit = UNIT[story["section"]]
    leader = snap.get("leader_jp") or ""
    value = snap.get("leader_value")
    gap = snap.get("gap")
    if gap == 0:
        tail = "%sが%s%sで首位、2位と並ぶ" % (leader, value, unit)
    elif gap is not None:
        tail = "%sが%s%s、2位と%s差" % (leader, value, unit, gap)
    else:
        tail = "%sが%s%sで首位" % (leader, value, unit)
    return "%s %s争い｜%s" % (comp, section, tail)


def build_narration(story: dict, today: date) -> dict:
    day = "%d月%d日" % (today.month, today.day)
    snap = story["snap"]
    comp = story["league_jp"]
    section = SECTION_JP[story["section"]]
    unit = UNIT[story["section"]]
    top = snap.get("top") or []
    leader = top[0] if top else {}
    second = top[1] if len(top) > 1 else None

    segments = [{
        "kind": "race_intro",
        "speaker": 3,
        "text": "%s、欧州サッカーの%s争い。今日は順位が動いたのだ？"
                % (day, section),
        "meta": {"date": today.isoformat(), "mode": "soccer_race", "day": day},
    }]

    jp = snap.get("jp") or []
    if jp:
        parts = ["%sの%s、%sが%s%sで%s位"
                 % (comp, section, x["name_jp"], x["value"], unit, x["rank"])
                 for x in jp[:2]]
        parts += [m["text"] for m in story["movements"]
                  if m["kind"].startswith("jp_")][:2]
        segments.append({"kind": "race_japanese", "speaker": 2,
                         "text": "。".join(parts) + "。", "meta": {}})

    say = "%sの%s争い、首位は%s、%s%s。" % (
        comp, section, leader.get("name_jp", ""),
        leader.get("value"), unit)
    if leader.get("matches"):
        say += "%s試合で%s%s。" % (leader["matches"], leader["value"], unit)
    if leader.get("team_jp"):
        say += "%sの選手よ。" % leader["team_jp"]
    if second:
        if snap.get("gap") == 0:
            say += "2位の%sも%s%sで並んでいるわ。" % (
                second["name_jp"], second["value"], unit)
        else:
            say += "2位の%sは%s%sで、差は%s%sよ。" % (
                second["name_jp"], second["value"], unit,
                snap.get("gap"), unit)
        if second.get("matches"):
            say += "%s試合で%s%s。" % (
                second["matches"], second["value"], unit)
        if second.get("team_jp"):
            say += "%sの選手よ。" % second["team_jp"]
    for move in story["movements"][:2]:
        say += move["text"] + "。"
    segments.append({"kind": "race_line", "speaker": 2, "text": say,
                     "meta": {"code": story["code"], "at": 2,
                              "rows": top[:2]}})

    if len(top) > 2:
        third = top[2]
        more = "3位は%s、%s%s。" % (
            third.get("name_jp"), third.get("value"), unit)
        if third.get("matches"):
            more += "%s試合で%s%s。" % (
                third["matches"], third["value"], unit)
        if third.get("team_jp"):
            more += "%sの選手よ。" % third["team_jp"]
        if len(top) > 3:
            fourth = top[3]
            more += "4位は%s、%s%s。" % (
                fourth.get("name_jp"), fourth.get("value"), unit)
        if len(top) >= TOP_N:
            more += "上位10人まで、%s%sから%s%sの間に%s人がひしめいているわ。" % (
                top[-1].get("value"), unit, leader.get("value"), unit,
                len(top))
        if jp:
            more += "日本人では%sが%s位。" % (
                jp[0]["name_jp"], jp[0]["rank"])
        else:
            more += "この部門の上位10人に日本人選手はいないわ。"
        segments.append({"kind": "race_line", "speaker": 2, "text": more,
                         "meta": {"code": story["code"], "at": TOP_N,
                                  "rows": top}})

    segments.append({"kind": "outro", "speaker": 2,
                     "text": "得点王争いは、次の試合でまた動くわ。"
                             "数字が変わったら、また伝えるわ。コレスポ。",
                     "meta": {}})
    return {"segments": segments, "title": title_of(story),
            "date_jst": today.isoformat()}


def race_view(story: dict, today: date) -> dict:
    snap = story["snap"]
    section = story["section"]
    unit = UNIT[section]
    label = SECTION_JP[section]
    comp_jp = story["league_jp"]
    rows = []
    for entry in snap.get("top") or []:
        matches = entry.get("matches")
        rows.append({
            "position": entry.get("rank"),
            "team": entry.get("name_jp") or entry.get("name"),
            "team_en": entry.get("name"),
            "played": matches,
            "points": entry.get("value"),
            "gf": 0,
            "ga": 0,
            "jp": [entry["name_jp"]] if entry.get("jp") else [],
            "unit": unit,
            "sub": ("%d試合" % matches) if matches else "",
        })

    jp_rows = []
    for entry in snap.get("jp") or []:
        jp_rows.append({
            "name": entry["name_jp"],
            "club_jp": entry.get("team_jp") or "",
            "position": entry["rank"],
            "points": entry["value"],
            "diff": entry["rank"],
            "lines": [{"label": label, "diff": entry["rank"],
                       "text": "%s%sで%s位" % (entry["value"], unit,
                                              entry["rank"])}],
            "out": False,
        })

    notes = ["ESPNの今季成績です。試合数は選手ごとに違います",
             "同点の選手は同じ順位で並べています"]
    lines = [{
        "at": 2,
        "label": "首位と2位",
        "heading": "首位争い",
        "inside": rows[:2],
        "outside": rows[2:3],
        "diff": snap.get("gap"),
        "gap_label": "首位と2位の差",
        "gap_unit": unit,
        "notes": notes,
        "moved": {
            "in": [m["text"] for m in story["movements"]],
            "out": [],
        },
        "jp": [x["name"] for x in jp_rows],
    }]
    if rows:
        lines.append({
            "at": TOP_N,
            "label": "上位%d人" % TOP_N,
            "heading": "%s争い" % label,
            "inside": rows,
            "outside": [],
            "diff": None,
            "notes": notes,
            "moved": {},
            "jp": [x["name"] for x in jp_rows],
        })
    comp = {
        "code": story["code"],
        "name_jp": comp_jp,
        "played": max((r.get("played") or 0) for r in rows) if rows else 0,
        "played_note": "各選手の試合数は行に出ています",
        "clubs": len(rows),
        "ready": True,
        "jp": jp_rows,
        "lines": lines,
    }
    return {
        "date_jst": today.isoformat(),
        "frame_label": "%s争い" % label,
        "frame_note": "%sの%s上位" % (comp_jp, unit),
        "jp_heading": "日本人選手の順位",
        "competitions": [comp],
        "picked": [story["code"]],
    }


def build(raw_by_code: dict, previous_state: dict = None,
          today: date = None) -> dict:
    today = today or datetime.now(JST).date()
    previous_state = previous_state or {}
    parsed = parse_all(raw_by_code)
    sections = {(league, section): snapshot(entries)
                for (league, section), entries in parsed.items()}

    movements = {}
    for (league, section), now in sections.items():
        key = "%s:%s" % (league, section)
        before = (previous_state.get("sections") or {}).get(key) or {}
        moves = detect_movements(before, now, section)
        if moves:
            movements[key] = moves

    chosen = choose(movements, previous_state, today)
    story = None
    if chosen:
        _, _, key, moves = chosen
        league, section = key.split(":", 1)
        code = dict(LEAGUES)[league]
        story = {
            "key": key,
            "league": league,
            "code": code,
            "section": section,
            "league_jp": league_jp(league, code),
            "snap": sections[(league, section)],
            "movements": moves,
        }
        story["title"] = title_of(story)

    updated_at = datetime.now(timezone.utc).isoformat()
    race = race_view(story, today) if story else {}
    if story:
        # 共通の検査（sanity.py）が、原稿の数字を同じ材料で照合できるように。
        race["source"] = "ESPN / statistics"
        race["retrieved_at"] = updated_at
    narration = (build_narration(story, today) if story
                 else {"segments": [], "title": "",
                       "date_jst": today.isoformat()})
    if story:
        try:
            import soccer_sanity_material
            narration["soccer_material"] = soccer_sanity_material.compact(race)
        except Exception:                               # noqa: BLE001
            pass

    data = {
        "date_jst": today.isoformat(),
        "updated_at": updated_at,
        "sections": {"%s:%s" % k: v for k, v in sections.items()},
        "movements": movements,
        "picked": [story["key"]] if story else [],
        "story": story,
        "title": story["title"] if story else "",
        "narration": narration,
        "race": race,
    }
    return data


def load_state(path: str = "data/soccer_leaders_state.json") -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def next_state(previous: dict, data: dict, today: date,
               published_key: str = "") -> dict:
    state = copy.deepcopy(previous or {})
    state["version"] = 1
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    sections = state.setdefault("sections", {})
    for key, snap in (data.get("sections") or {}).items():
        section = sections.setdefault(key, {})
        section.update(snap)
        section["snapshot_date"] = today.isoformat()
    if published_key:
        sections.setdefault(published_key, {})["last_published"] = \
            today.isoformat()
        state["last_published_date"] = today.isoformat()
    return state


def fetch(league: str) -> dict:
    request = urllib.request.Request(
        API.format(league),
        headers={"User-Agent": "collespo-leaders/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all() -> dict:
    out = {}
    for league, _ in LEAGUES:
        try:
            out[league] = fetch(league)
        except Exception as exc:                        # noqa: BLE001
            print("[warn] %s を取れません: %s" % (league, exc),
                  file=sys.stderr)
    return out


def load_fixtures(folder: str) -> dict:
    root = pathlib.Path(folder)
    return {league: json.loads((root / ("%s.json" % league))
                               .read_text(encoding="utf-8"))
            for league, _ in LEAGUES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", default="",
                        help="保存した実応答のフォルダ（試験・見本用）")
    parser.add_argument("--out", default="data/soccer_leaders.json")
    parser.add_argument("--race-out", default="data/soccer_leaders_race.json")
    parser.add_argument("--narration-out",
                        default="build/leaders_narration.json")
    parser.add_argument("--state", default="data/soccer_leaders_state.json")
    parser.add_argument("--today", default="")
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--mark-published", default="",
                        help="公開した部門の鍵（例 PL:goals）")
    parser.add_argument("--github-output", default="",
                        help="GitHub Actions の GITHUB_OUTPUT に結果を書く")
    args = parser.parse_args()

    today = (date.fromisoformat(args.today) if args.today
             else datetime.now(JST).date())

    if args.mark_published:
        state = load_state(args.state)
        state = next_state(state, {"sections": {}}, today,
                           published_key=args.mark_published)
        save_state(args.state, state)
        print("[done] 公開を記録しました: %s" % args.mark_published)
        return 0

    raw = load_fixtures(args.fixtures) if args.fixtures else fetch_all()
    if not raw:
        print("[info] 材料を取れませんでした")
        return 0

    previous = load_state(args.state)
    data = build(raw, previous, today)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    if data.get("picked"):
        race = pathlib.Path(args.race_out)
        race.parent.mkdir(parents=True, exist_ok=True)
        race.write_text(json.dumps(data["race"], ensure_ascii=False,
                                   indent=2), encoding="utf-8")
        narration = pathlib.Path(args.narration_out)
        narration.parent.mkdir(parents=True, exist_ok=True)
        narration.write_text(json.dumps(data["narration"], ensure_ascii=False,
                                        indent=2), encoding="utf-8")
    if not args.no_state:
        save_state(args.state, next_state(previous, data, today))

    if args.github_output:
        picked = data.get("picked") or []
        key = picked[0] if picked else ""
        code = (data.get("story") or {}).get("code", "")
        lines = [
            "count=%d" % (1 if picked else 0),
            "key=%s" % key,
            "code=%s" % code,
            "title=%s" % (data.get("title") or ""),
        ]
        with pathlib.Path(args.github_output).open(
                "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    if not data.get("picked"):
        print("[info] 動きがありません。今日は作りません。")
        return 0
    print(data["title"])
    for segment in data["narration"]["segments"]:
        print("[%s] %s" % (segment.get("speaker", ""), segment["text"]))
    print("[done] %s" % out)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
