#!/usr/bin/env python3
"""欧州サッカーの得点王・アシスト王争いを、動画1本ぶんの材料にする。

ESPN の statistics は、リーグごとに goalsLeaders / assistsLeaders を
上位50人ぶん返す。順位表（soccer_race）と同じで、毎日出す枠ではない。
**前回から動いた日だけ**1本作る。

動きの決まり（前回の記録があるときだけ。無いときは動きを言わない）:
  ・首位が替わった／首位に並んだ
  ・首位と2位の差が2以上に開いた・1以内に詰まった
  ・日本人選手が上位10人に入った、または上位10人の中で順位を上げた

同じリーグ・同じ部門は7日に1本まで。1日1本まで。日本人の動きを先に。
動きが無い日は picked を空にして返す（呼ぶ側が止まれるように）。

見た目は順位争い（soccer_race）と同じ新しい部品（soccer_readable の順位表・
冒頭の大きな数字・隅の立ち絵）を使う。ここで画面は描かない。画面に渡す
材料（race_view）と、掛け合いの台本（v4_program）だけを作る。
  ずんだもんが問い、めたんが事実と数字で答える。
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
MAX_NAME = 11              # 表の名前欄に入る字数
SHOWN = 4                  # 画面に出す人数（順位表の1ページ）
WINDOW_DAYS = 7
JST = timezone(timedelta(hours=9))
FRAME_LABEL = "欧州サッカー　得点王・アシスト王争い"


def _key(name: str) -> str:
    """名前の突き合わせ用。アクセントと記号を落として小文字に。"""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z]", "", text.lower())


def _read(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# 日本語の名前。**この表に無い選手は画面にも声にも出さない**
# （soccer_national_topics が「相手選手名が未登録」で止まるのと同じ決まり。
# 読みを勝手に作らない）。
#   1. 日本人選手の名簿（notability_engine.JP_PLAYERS_SOCCER）
#   2. 代表の相手選手の表（data/soccer_national_opponent_names.json）
#   3. この枠の表（data/soccer_leaders_names.json）
#   4. 野球・サッカー共通の読みの表（data/player_kana.json）
_NAME_JP = {_key(p.get("name_en")): p.get("name_jp")
            for p in JP_PLAYERS_SOCCER if p.get("name_en")}
_JP_KEYS = set(_NAME_JP)


def _load_names() -> dict:
    data = HERE.parent / "data"
    out = {}
    for en, row in (_read(data / "soccer_national_opponent_names.json")
                    or {}).items():
        if isinstance(row, dict) and row.get("name") and row.get("reading"):
            out[_key(en)] = row["name"]
    for en, row in ((_read(data / "soccer_leaders_names.json") or {})
                    .get("players") or {}).items():
        if isinstance(row, dict) and row.get("name") and row.get("reading"):
            out[_key(en)] = row["name"]
    for en, jp in ((_read(data / "player_kana.json") or {})
                   .get("names") or {}).items():
        if jp and re.fullmatch(r"[ァ-ヶー・]+", jp):
            out.setdefault(_key(en), jp)
    return out


_NAMES = _load_names()


def name_jp(name: str):
    """日本語の名前。表に無ければ None（英字のまま出さない）。"""
    key = _key(name)
    return _NAME_JP.get(key) or _NAMES.get(key) or None


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


# ---- 前回との比べ -------------------------------------------------------

def detect_movements(previous: dict, current: dict, section: str) -> list:
    """前回の記録があるときだけ動きを返す。無いときは空（作り話にしない）。"""
    if not previous or not previous.get("leader") or not current:
        return []
    out = []
    before_leader = previous.get("leader")
    now_leader = current.get("leader")
    top = current.get("top") or []
    if before_leader and now_leader and before_leader != now_leader:
        # 前の首位が今の上位10人にいれば、その人の名前を言える
        beaten = next((r for r in top if r.get("name") == before_leader), {})
        out.append({"kind": "leader_changed",
                    "overtaken_jp": beaten.get("name_jp")})
    else:
        before_second = previous.get("second_value")
        now_second = current.get("second_value")
        if (now_second is not None and current.get("leader_value") is not None
                and now_second == current.get("leader_value")
                and before_second != previous.get("leader_value")):
            out.append({"kind": "tied_lead"})
        before_gap = previous.get("gap")
        now_gap = current.get("gap")
        if before_gap is not None and now_gap is not None:
            if now_gap >= 2 and before_gap < 2:
                out.append({"kind": "gap_opened", "gap": now_gap})
            elif now_gap <= 1 and before_gap > 1:
                out.append({"kind": "gap_closed", "gap": now_gap})

    old_ranks = {x["name"]: x["rank"] for x in previous.get("jp") or []}
    for entry in current.get("jp") or []:
        old = old_ranks.get(entry["name"])
        if old is None:
            out.append({"kind": "jp_entered", "name_jp": entry["name_jp"],
                        "rank": entry["rank"]})
        elif entry["rank"] < old:
            out.append({"kind": "jp_rose", "name_jp": entry["name_jp"],
                        "old": old, "rank": entry["rank"]})
    return out


def movement_say(move: dict, baseline: str) -> str:
    """めたんの言い方。数字は画面の表に出ているので重ねない。"""
    base = ""
    if baseline:
        d = date.fromisoformat(baseline)
        base = "%d月%d日の前回から、" % (d.month, d.day)
    kind = move["kind"]
    if kind == "leader_changed":
        who = move.get("overtaken_jp")
        return base + ("首位が%sから替わったわ。" % who if who
                       else "首位が替わったわ。")
    if kind == "tied_lead":
        return base + "首位に並んだ選手がいるわ。"
    if kind == "gap_opened":
        return base + "首位と2位の差が開いたわ。"
    if kind == "gap_closed":
        return base + "首位と2位の差が詰まったわ。"
    if kind == "jp_entered":
        return "日本人の%sが、上位10人に入ったわ。" % move["name_jp"]
    if kind == "jp_rose":
        return "日本人の%sが、%s位から%s位に上がったわ。" % (
            move["name_jp"], move["old"], move["rank"])
    return ""


# ---- どの部門を出すか ---------------------------------------------------

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


def shown_rows(top: list) -> list:
    """画面に出す4人。上位4人。日本人が上位10人にいて4人の外なら4人目と入れ替える。"""
    rows = list(top[:SHOWN])
    extra = next((e for e in top[SHOWN:] if e.get("jp")), None)
    if extra and not any(r.get("jp") for r in rows):
        rows = rows[:SHOWN - 1] + [extra]
    return rows


def is_ready(snap: dict) -> bool:
    """出す人が全員、日本語の名前を持っているか（表に無い人は出さない）。"""
    rows = shown_rows(snap.get("top") or [])
    # 表の名前欄は40pxで11字まで（入らない名前は短い呼び名を表に足すまで出さない）
    return len(rows) >= 3 and all(
        r.get("name_jp") and len(r["name_jp"]) <= MAX_NAME for r in rows)


def choose(movements: dict, state: dict, today: date, sections: dict = None):
    candidates = []
    for key, moves in movements.items():
        if not moves or not can_publish(state, key, today):
            continue
        league, section = key.split(":", 1)
        if sections is not None and not is_ready(sections[(league, section)]):
            continue
        jp = any(m["kind"].startswith("jp_") for m in moves)
        candidates.append((0 if jp else 1, -len(moves), key, moves))
    candidates.sort()
    return candidates[0] if candidates else None


def league_jp(league: str, code: str) -> str:
    return SOCCER_LEAGUE_NAME_JP.get(code) or code


# ---- 題・説明 -----------------------------------------------------------

def gap_text(gap, unit: str) -> str:
    """「2点差」「1アシスト差」。単位は数字のあと、「差」は最後。"""
    if gap is None:
        return ""
    return "%s%s差" % (gap, unit)


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
        tail = "%sが%s%sで首位、2位と%s" % (
            leader, value, unit, gap_text(gap, unit))
    else:
        tail = "%sが%s%sで首位" % (leader, value, unit)
    return "%s %s争い｜%s" % (comp, section, tail)


# ---- 画面と台本の材料 ---------------------------------------------------

def race_view(story: dict, today: date) -> dict:
    """画面・台本に渡す材料。v4_program はこれだけから台本を作る。"""
    snap = story["snap"]
    section = story["section"]
    top = snap.get("top") or []
    return {
        "date_jst": today.isoformat(),
        "frame_label": FRAME_LABEL,
        "ticker_head": "%s %s争い" % (story["league_jp"],
                                     SECTION_JP[section]),
        "picked": [story["code"]],
        "leaders": {
            "key": story["key"],
            "code": story["code"],
            "section": section,
            "section_jp": SECTION_JP[section],
            "unit": UNIT[section],
            "league_jp": story["league_jp"],
            "baseline_date": story.get("baseline_date"),
            "movements": story["movements"],
            "title": title_of(story),
            "top": top,
            "shown": [r["name"] for r in shown_rows(top)],
        },
    }


def v4_program(data: dict) -> dict:
    """soccer_slots_v4.race_program から呼ぶ。順位争いと同じ package を通す。

    1) ずんだもん（表紙）：誰が何点で首位かを問う。大きな数字の画面。
    2) めたん（順位表）：事実と数字で答える。行は読むのに合わせて出る。
    3) 締め（既存の締め）
    """
    import soccer_slots_v4 as slots
    import short_renewal
    import review_render_v3 as r3

    info = data["leaders"]
    top = info["top"]
    unit = info["unit"]
    league = info["league_jp"]
    label = info["section_jp"] + "争い"
    rows = [r for r in top if r["name"] in info["shown"]]
    leader = top[0]
    second = top[1] if len(top) > 1 else None
    gap = leader["value"] - second["value"] if second else None

    # 表紙：冒頭で「誰が何点で首位か」を言う。リーグ名と部門は画面の題。
    if gap == 0 and second:
        ask = "%sと%sが%s%sで並んで首位なのだ？" % (
            leader["name_jp"], second["name_jp"], leader["value"], unit)
    else:
        ask = "%sが%s%sで首位って、本当なのだ？" % (
            leader["name_jp"], leader["value"], unit)
    hook = short_renewal.hook(leader["name_jp"], leader["value"], unit,
                              context="%s　%s" % (league, label))
    hook["text"] = ask
    hook["display_unit"] = unit + "で首位"
    cover = dict(kind="cover", text=ask, speaker=3,
                 meta=dict(opening_hook=hook, presenter="zundamon"))

    # 順位表：めたんの答え。首位の点数は表紙で言ったので重ねない。
    scope = "ええ、%sの%sよ。" % (league, label)
    for move in info.get("movements") or []:
        scope += movement_say(move, info.get("baseline_date") or "")
    texts = []
    for i, row in enumerate(rows):
        club = row.get("team_jp") or row.get("team")
        who = "%sの%s" % (club, row["name_jp"])
        place = row["rank"]
        before = rows[i - 1] if i else None
        # 語尾が「〜よ。」ばかりにならないよう、行ごとに言い方を変える（11/25 本人の指摘を受けて）。
        if i == 0:
            matches = row.get("matches")
            if isinstance(matches, int) and matches > 0:
                pace = "%g" % round(row["value"] / matches, 2)
                # 首位の数字は表紙で言ったので重ねない（言い直しの禁止）。
                say = "%sは、%s試合に出て、1試合あたり%s%sのペースね。" % (
                    who, matches, pace, unit)
            else:
                say = "首位は%sね。" % who
        elif before and before["rank"] == place:
            say = "同じ%s位で、%sも並んでいるわ。" % (place, who)
        elif is_japanese(row["name"]):
            say = "日本人では、%s位に%sが入っているわ。%s%sよ。" % (
                place, who, row["value"], unit)
        elif i == 1:
            say = "%s位は%sで、%s%s。" % (place, who, row["value"], unit)
            if gap is not None:
                say += "首位と並んでいるのね。" if gap == 0 else "首位との差は%s%sね。" % (gap, unit)
        elif i % 2:
            say = "%s位は%sで、%s%sよ。" % (place, who, row["value"], unit)
        else:
            say = "%s位には、%sが%s%sで続くわ。" % (place, who, row["value"], unit)
        texts.append(say)
    # 時間が足りない時の補充用（画面に出さない5位以下を、読むだけ）
    spare = []
    for row in top[SHOWN:SHOWN + 3]:
        if row["name"] in info["shown"] or not row.get("name_jp"):
            continue
        spare.append("%s位は%sの%sで、%s%sよ。" % (
            row["rank"], row.get("team_jp") or row.get("team"),
            row["name_jp"], row["value"], unit))
    primary = leader["name_jp"]
    table_title = "%s　%s" % (league, label)
    # 前回の日付は、今日より前の時だけ出す（11/25 見本で「前回は11月25日」と当日が出た）。
    if info.get("baseline_date") and info["baseline_date"][:10] < (data.get("date_jst") or "9999")[:10]:
        # 比べの基準の日付を画面に出す（前回の記録があるときだけ）
        d = date.fromisoformat(info["baseline_date"])
        table_title += "　前回は%d月%d日" % (d.month, d.day)
    display = [dict(position=r["rank"], team=r["name_jp"], team_en=r["name"],
                    club=r.get("team_jp") or r.get("team"), player=True,
                    played=r.get("matches"), points=r["value"]) for r in rows]
    table = dict(kind="standings", text=scope + "".join(texts), speaker=2,
                 caption_units=[scope] + texts,
                 meta=dict(title=table_title, rows=display,
                           shown=[[1, TOP_N]], lines=[], focus=None,
                           highlights=[], gap="", primary=primary,
                           player_rows=True,
                           columns=[(96, "順位", 100), (220, "選手", 420),
                                    (710, "試合", 90),
                                    (810 if unit != "点" else 830,
                                     "アシスト" if unit != "点" else "得点",
                                     130 if unit != "点" else 100)],
                           progressive_rows=True, row_texts=texts,
                           leading_text=scope, reserve_texts=spare))
    segs = [cover, table]
    package = slots.package("race", data, segs, [], info["title"], {})
    package["narration"]["opening_check"] = short_renewal.opening_check(hook)
    package["narration"]["short_content_version"] = "1108"
    return package


# ---- まとめ -------------------------------------------------------------

def build(raw_by_code: dict, previous_state: dict = None,
          today: date = None, only: str = "") -> dict:
    """only は部門の鍵（例 eng.1:goals / PL:goals）。動きが無くても、その部門を
    今の順位だけで作る（見本用。前回との比べは言わない）。"""
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

    story_key, moves = "", []
    if only:
        by_code = {code: league for league, code in LEAGUES}
        league, _, section = only.partition(":")
        league = by_code.get(league, league)
        story_key = "%s:%s" % (league, section)
        if (league, section) not in sections:
            raise ValueError("知らない部門です: %s" % only)
        if not is_ready(sections[(league, section)]):
            raise ValueError("日本語の名前が未登録の選手がいます: %s" % only)
        moves = movements.get(story_key, [])
    else:
        chosen = choose(movements, previous_state, today, sections)
        if chosen:
            _, _, story_key, moves = chosen

    story = None
    if story_key:
        league, section = story_key.split(":", 1)
        code = dict(LEAGUES)[league]
        before = (previous_state.get("sections") or {}).get(story_key) or {}
        story = {
            "key": story_key,
            "league": league,
            "code": code,
            "section": section,
            "league_jp": league_jp(league, code),
            "snap": sections[(league, section)],
            "movements": moves,
            # 前回の記録がある時だけ。画面・説明の「いつと比べたか」に出す
            "baseline_date": (before.get("snapshot_date")
                              if before.get("leader") else None),
        }
        story["title"] = title_of(story)

    updated_at = datetime.now(timezone.utc).isoformat()
    race = race_view(story, today) if story else {}
    if story:
        race["source"] = "ESPN / statistics"
        race["retrieved_at"] = updated_at

    return {
        "date_jst": today.isoformat(),
        "updated_at": updated_at,
        "sections": {"%s:%s" % k: v for k, v in sections.items()},
        "movements": movements,
        "picked": [story["key"]] if story else [],
        "story": story,
        "title": story["title"] if story else "",
        "race": race,
    }


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
    parser.add_argument("--state", default="data/soccer_leaders_state.json")
    parser.add_argument("--today", default="")
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--only", default="",
                        help="部門を指定して作る（例 PL:goals）。動きが無くても今の順位だけで作る")
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
    data = build(raw, previous, today, only=args.only)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    if data.get("picked"):
        race = pathlib.Path(args.race_out)
        race.parent.mkdir(parents=True, exist_ok=True)
        race.write_text(json.dumps(data["race"], ensure_ascii=False,
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
    print("[done] %s" % out)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
