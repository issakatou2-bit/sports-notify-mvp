#!/usr/bin/env python3
"""ポストシーズンの試合ごとの話題（その日に終わった試合で「何が起きたか」）。

なぜ要るのか:
  10/4、本人「今日の試合それぞれトピックをショート化したい。ハイライトに
  付いたコメントとか、記事とか、活用できるもの取捨選択しつつ。特にCWSが
  敵地でCLEに勝った、しかも村上の先制2ラン決勝HRで」。
  ps_story.py はシリーズが決着してからの総括で、1戦ごとの見どころは
  拾えない。PSは1試合ごとに話題が立つので、試合単位でも出す。

何を言うか（事実は MLB 公式の試合経過・成績表・計測から。盛らない）:
  - 試合の結果とシリーズの勝敗（敵地か本拠地か）
  - 決勝点の場面（何回に、誰の、どんな打撃で）。先制点と同じなら「先制で決勝」
    本塁打なら計測（飛距離・打球の速さ）も
  - 本塁打の一覧（球団ごと。カタカナにできない名前は数だけ）
  - 完封なら継投の人数、勝ち投手・セーブ
  - 日本人選手のその試合の成績（両方の球団、出場した選手だけ）
  - 声: ハイライトのコメント（local_voices.json）と番記者の投稿
    （ps_quotes.json）から、その試合の後のものを1つずつ。出典つき。
    英字が読み上げに残るものは使わない。

日本人選手が出た試合を先に並べる。

出力: data/ps_game_topics.json（generated_topics 経由で、PSの話題と同じ
描画・題・説明。シーズンまとめの枠で先に出す）

画面: 新デザイン「電光掲示板」（review_render_v3、style="v3"）。表紙の材料（v3）は
ps_v3_cover.game_v3 が、この話題の項目・題から作る（材料に無い数字・言葉は足さない）。
次の試合は data/postseason.json から（つじつまが合うときだけ）。作れなければ v2 のまま。
"""

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_story  # noqa: E402
import mlb_headlines  # noqa: E402
import ps_v3_cover  # noqa: E402

API = "https://statsapi.mlb.com/api"
OUT = "data/ps_game_topics.json"
PS_TYPES = ("F", "D", "L", "W")
ROUND_SHORT = ps_story.ROUND_SHORT
# 試合が終わってからこの時間までのものを出す（翌日の夕方の枠に間に合う長さ）。
FRESH_HOURS = 30


def _get(path: str, **params) -> dict:
    import requests
    r = requests.get(API + path, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def finished_games(now: datetime) -> list:
    """直近に終わったPSの試合（schedule の行）。"""
    start = (now - timedelta(hours=FRESH_HOURS + 12)).date().isoformat()
    end = now.date().isoformat()
    d = _get("/v1/schedule", sportId=1, startDate=start, endDate=end,
             gameType=",".join(PS_TYPES), hydrate="team,seriesStatus")
    out = []
    for day in d.get("dates") or []:
        for g in day.get("games") or []:
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            if g.get("gameType") not in PS_TYPES:
                continue
            out.append(g)
    return out


# ------------------------------------------------------------- 試合の中身

EVENT_JP = {
    "Single": "タイムリー", "Double": "タイムリー二塁打", "Triple": "タイムリー三塁打",
    "Sac Fly": "犠牲フライ", "Sac Bunt": "犠牲バント", "Walk": "押し出し四球",
    "Hit By Pitch": "押し出し死球", "Field Error": "失策", "Groundout": "内野ゴロ",
    "Forceout": "内野ゴロ", "Fielders Choice": "野選", "Fielders Choice Out": "野選",
    "Grounded Into DP": "併殺打", "Wild Pitch": "暴投", "Passed Ball": "捕逸",
}


def hr_name(rbi: int) -> str:
    return {1: "ソロ本塁打", 2: "2点本塁打", 3: "3点本塁打", 4: "満塁本塁打"}.get(rbi, "本塁打")


def measure(play: dict) -> dict:
    for e in play.get("playEvents") or []:
        h = e.get("hitData")
        if h and (h.get("launchSpeed") or h.get("totalDistance")):
            return h
    return {}


def measure_text(h: dict) -> str:
    """飛距離はメートル、打球の速さは時速キロ。読み上げで崩れない書き方。"""
    parts = []
    if h.get("totalDistance"):
        parts.append(f"飛距離{round(float(h['totalDistance']) * 0.3048)}メートル")
    if h.get("launchSpeed"):
        parts.append(f"打球の速さ時速{round(float(h['launchSpeed']) * 1.609344)}キロ")
    return "、".join(parts)


def scoring(feed: dict) -> list:
    """得点の場面を順に。[(play, 攻撃側 'away'/'home', 得点後の両軍の点)]"""
    plays = feed["liveData"]["plays"]
    out = []
    for i in plays.get("scoringPlays") or []:
        p = plays["allPlays"][i]
        side = "away" if p["about"].get("halfInning") == "top" else "home"
        out.append((p, side, (p["result"]["awayScore"], p["result"]["homeScore"])))
    return out


def decisive(feed: dict, win_side: str, lose_runs: int):
    """決勝点（勝った側が、相手の最終得点を初めて上回った場面）と、それが先制点か。"""
    first = None
    for p, side, score in scoring(feed):
        if first is None:
            first = p
        mine = score[0] if win_side == "away" else score[1]
        if side == win_side and mine > lose_runs:
            return p, p is first
    return None, False


def inning_text(p: dict) -> str:
    a = p["about"]
    return f"{a['inning']}回{'表' if a.get('halfInning') == 'top' else '裏'}"


def play_text(p: dict, who: str) -> str:
    r = p["result"]
    if r.get("event") == "Home Run":
        return f"{who}の{hr_name(r.get('rbi') or 1)}"
    # 打席の打者は守備側の失策・暴投・捕逸の主体ではない。
    if r.get("event") == "Field Error":
        return f"{who}の打球で相手の失策"
    if r.get("event") in ("Wild Pitch", "Passed Ball"):
        return f"相手の{EVENT_JP[r['event']]}で得点"
    what = EVENT_JP.get(r.get("event"))
    return f"{who}の{what}" if what else f"{who}の打席で得点"


def pitcher_line(st: dict, compact: bool = False) -> str:
    """「4回と3分の1　2失点」。compact は「4回と3分の1を2失点」（数字が続かない形）。"""
    ip = st.get("inningsPitched") or "0.0"
    whole, _, part = ip.partition(".")
    frac = {"1": "と3分の1", "2": "と3分の2"}.get(part, "")
    inn = f"{frac[1:]}回" if whole == "0" and frac else f"{whole}回{frac}"
    runs = st.get("runs") or 0
    lost = f"{runs}失点" if runs else "無失点"
    return f"{inn}{'を' if compact else '　'}{lost}"


def player_lines(box_team: dict, jp: dict) -> list:
    """その球団の日本人選手で、出場した選手の1行。"""
    out = []
    for p in (box_team.get("players") or {}).values():
        name = p["person"]["fullName"]
        if name not in jp:
            continue
        b = p.get("stats", {}).get("batting") or {}
        pi = p.get("stats", {}).get("pitching") or {}
        if pi.get("inningsPitched"):
            line = pitcher_line(pi) + f"　{pi.get('strikeOuts') or 0}奪三振"
        elif b.get("plateAppearances") or b.get("atBats"):
            line = f"{b.get('atBats') or 0}打数{b.get('hits') or 0}安打"
            if b.get("homeRuns"):
                line += f"　{b['homeRuns']}本塁打"
            if b.get("rbi"):
                line += f"　{b['rbi']}打点"
            if b.get("baseOnBalls"):
                line += f"　{b['baseOnBalls']}四球"
        else:
            continue
        out.append({"name": jp[name], "line": line, "en": name})
    return out


# ------------------------------------------------------------------- 声

def team_words(feed: dict) -> dict:
    """訳文に残る英字の球団名・都市名を日本語の球団名へ。"""
    import notability_engine as ne
    out = {}
    for side in ("away", "home"):
        t = feed["gameData"]["teams"][side]
        jp = ne.MLB_TEAM_NAME_JP.get(str(t["id"]), "")
        if not jp:
            continue
        for w in (t.get("name"), t.get("teamName"), t.get("clubName"),
                  t.get("franchiseName"), t.get("locationName"), t.get("shortName")):
            if w:
                out[w] = jp
    # 愛称の最後の1語（White Sox → Sox、Blue Jays → Jays）。試合の2球団で重ならないときだけ。
    # 10/6、「Sox fan」をホワイトソックスと読めず、人名の検索で別の球団に化けた。
    lasts = {}
    for side in ("away", "home"):
        t = feed["gameData"]["teams"][side]
        jp = ne.MLB_TEAM_NAME_JP.get(str(t["id"]), "")
        name = t.get("teamName") or ""
        if jp and " " in name:
            last = name.split()[-1]
            lasts[last] = None if last in lasts else jp
    for last, jp in lasts.items():
        if jp and last not in out:
            out[last] = jp
    return out


def localize(text: str, words: dict, table: dict, jp: dict) -> str:
    for w in sorted(words, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", words[w], text)
    # 見出しの訳に付いた番号（「1. 執拗なレイズが…」）は落とす
    text = re.sub(r"^\s*\d+\.\s*", "", text or "")
    return ps_story.speakable(text, table, jp)


def pick_voice(voices: dict, feed: dict, after: str, words: dict,
               table: dict, jp: dict, jp_names: list):
    """その試合のハイライトに付いたコメントから1つ。日本人選手の名前があるものを先に。"""
    teams = [feed["gameData"]["teams"][s].get("teamName", "").upper() for s in ("away", "home")]
    rows = []
    for v in (voices.get("jp_praise") or []) + (voices.get("voices") or []):
        m = (v.get("matchup") or "").upper()
        if not all(t and t in m for t in teams):
            continue
        if (v.get("at") or "") < after:
            continue
        rows.append(v)
    rows.sort(key=lambda v: (-(any(n in (v.get("jp_players") or []) for n in jp_names)),
                             -(v.get("likes") or 0)))
    seen = set()
    for v in rows:
        if v.get("url", "") + (v.get("title") or "") in seen:
            continue
        seen.add(v.get("url", "") + (v.get("title") or ""))
        said = localize(v.get("ja") or "", words, table, jp)
        if said and len(said) <= 70:
            return {"said": said, "text": v.get("title") or "", "url": v.get("url") or "",
                    "likes": v.get("likes"), "at": v.get("at")}
    return None


def pick_reporter(quotes: list, team_jp: str, after: str, words: dict,
                  table: dict, jp: dict, jp_names: list):
    """その球団の番記者の、試合が始まった後の投稿から1つ。"""
    rows = [x for x in quotes if x.get("team") == team_jp and x.get("jp")
            and (x.get("at") or "") >= after]
    rows.sort(key=lambda x: (-(any(n in (x.get("jp") or "") for n in jp_names)),
                             -(("“" in (x.get("text") or "")) or ('"' in (x.get("text") or ""))),
                             -(x.get("likes") or 0)))
    for x in rows:
        said = localize(x["jp"], words, table, jp)
        if said and len(said) <= 80:
            return {"said": said, "author": x.get("author"), "outlet": x.get("outlet"),
                    "text": x.get("text"), "url": ps_story._bsky_url(x), "at": x.get("at")}
    return None


def quoted(s: str) -> str:
    return s if s.startswith("「") else f"「{s}」"


# ---------------------------------------------------------------- 話題

def pick_headline(headlines, game, feed, words, table, jp):
    """年・ラウンド・第何戦・勝者が一致する公式総括だけ。一般記事や予告は除外。"""
    live = feed.get("liveData") or {}
    teams = (feed.get("gameData") or {}).get("teams") or {}
    score = (live.get("linescore") or {}).get("teams") or {}
    if any(score.get(s, {}).get("runs") is None for s in ("away", "home")):
        return None
    away, home = [score[s]["runs"] for s in ("away", "home")]
    if away == home:
        return None
    winner = teams.get("away" if away > home else "home") or {}
    slug = re.sub(r"[^a-z]+", "-", (winner.get("teamName") or "").lower()).strip("-")
    league = (winner.get("league") or {}).get("id")
    if league not in (103, 104):
        return None
    prefix = "al" if league == 103 else "nl"
    rnd = {"F": prefix + "wc", "D": prefix + "ds", "L": prefix + "cs", "W": "world-series"}.get(game.get("gameType"))
    start = mlb_headlines.utc(game.get("gameDate"))
    end = finished_at(feed)
    num = (game.get("seriesStatus") or {}).get("gameNumber") or game.get("seriesGameNumber")
    if not start or not end or not rnd or not slug or not num:
        return None
    season = str(game.get("season") or start.year)
    expected = (slug, rnd, str(num), season)
    for h in headlines:
        at = mlb_headlines.utc(h.get("at"))
        if h.get("source") != "MLB.com" or mlb_headlines.recap_identity(h.get("url")) != expected:
            continue
        if not at or not end <= at <= end + timedelta(hours=FRESH_HOURS):
            continue
        # 収集時に加え、修正前に保存された訳にも同じ意味検査を適用する。
        from local_reporters import guard_translation
        said = localize(guard_translation(h.get("title") or "", h.get("jp") or ""), words, table, jp)
        if said and len(said) <= 80:
            return {"said": said, "text": h.get("title") or "", "url": h["url"], "at": at.isoformat()}
    return None


def finished_at(feed):
    times = [mlb_headlines.utc(p.get("about", {}).get("endTime"))
             for p in (feed.get("liveData") or {}).get("plays", {}).get("allPlays", [])]
    return max((t for t in times if t), default=None)


def inning_score(feed: dict) -> dict | None:
    """公式linescoreをそのまま材料へ。欠落・合計不一致を0で埋めない。"""
    import notability_engine as ne
    ls = (feed.get('liveData') or {}).get('linescore') or {}
    innings = ls.get('innings') or []
    if not innings or [i.get('num') for i in innings] != list(range(1, len(innings)+1)):
        return None
    out = {'innings': [], 'source': 'MLB Stats API / liveData.linescore'}
    for i in innings:
        row = {'num': i['num']}
        for side in ('away', 'home'):
            value = (i.get(side) or {}).get('runs')
            # ホームが勝って9回裏を打たない場合だけ欠落を許す。
            if value is None and not (side == 'home' and i is innings[-1]):
                return None
            if value is not None and (type(value) is not int or value < 0):
                return None
            row[side] = value
        out['innings'].append(row)
    teams = (feed.get('gameData') or {}).get('teams') or {}
    for side in ('away', 'home'):
        total = (ls.get('teams') or {}).get(side, {}).get('runs')
        if type(total) is not int or total != sum(i[side] or 0 for i in out['innings']):
            return None
        tid = (teams.get(side) or {}).get('id')
        name = ne.MLB_TEAM_NAME_JP.get(str(tid))
        if not name:
            return None
        out[side] = {'id': tid, 'name': name, 'abbr': ne.MLB_TEAM_ABBR.get(str(tid), ''), 'total': total}
    if out['innings'][-1]['home'] is None and out['home']['total'] <= out['away']['total']:
        return None
    return out


def story(game: dict, feed: dict, table: dict, jp: dict, voices: dict, quotes: list, headlines=()) -> dict:
    import notability_engine as ne
    ls = feed["liveData"]["linescore"]["teams"]
    runs = {s: ls[s].get("runs") or 0 for s in ("away", "home")}
    if runs["away"] == runs["home"]:
        return {}
    win_side = "away" if runs["away"] > runs["home"] else "home"
    lose_side = "home" if win_side == "away" else "away"
    teams = feed["gameData"]["teams"]
    name = {s: ne.MLB_TEAM_NAME_JP.get(str(teams[s]["id"]), "") for s in ("away", "home")}
    if not all(name.values()):
        return {}
    win, lose = name[win_side], name[lose_side]
    W, L = runs[win_side], runs[lose_side]
    rnd = ROUND_SHORT.get(game.get("gameType"), "ポストシーズン")
    ser = game.get("seriesStatus") or {}
    num = ser.get("gameNumber") or game.get("seriesGameNumber") or 1
    where = "敵地で" if win_side == "away" else "本拠地で"
    box = feed["liveData"]["boxscore"]["teams"]

    # シリーズの勝敗（勝った側から）
    wins = losses = None
    lead = (ser.get("winningTeam") or {}).get("id")
    if ser.get("wins") is not None and lead:
        if lead == teams[win_side]["id"]:
            wins, losses = ser["wins"], ser["losses"]
        else:
            wins, losses = ser["losses"], ser["wins"]
    elif ser.get("isTied") and ser.get("wins") is not None:
        wins = losses = ser["wins"]
    series_txt = (f"シリーズは{win}の{wins}勝{losses}敗" if wins is not None else "")
    if wins is not None and series_txt and ser.get("isOver"):
        series_txt = f"{win}が{wins}勝{losses}敗で{rnd}突破"

    items = [("試合の結果", f"{win} {W}対{L} {lose}　{where}勝利"
                          + (f"　{series_txt}" if series_txt else ""))]

    japanese = []
    for s in (win_side, lose_side):
        for j in player_lines(box[s], jp):
            j["line"] += f"（{name[s]}）"
            japanese.append(j)
    jp_names = [j["name"] for j in japanese]

    def who_of(person: dict) -> str:
        return ps_story.kana_of(person.get("fullName", ""), table, jp)

    # 決勝点
    hero = None
    decisive_card = None
    dp, first = decisive(feed, win_side, L)
    if dp:
        who = who_of(dp["matchup"]["batter"])
        if who:
            body = f"{inning_text(dp)}　{play_text(dp, who)}"
            if dp["result"].get("event") == "Home Run":
                m = measure_text(measure(dp))
                if m:
                    body += f"（{m}）"
            # 決勝点になるプレーでも、失策や四球などを「決勝打」にしない。
            is_hit = dp["result"].get("event") in ("Single", "Double", "Triple", "Home Run")
            items.append(("先制で決勝の一打" if first and is_hit else "決勝点", body))
            event = dp['result'].get('event')
            description = dp['result'].get('description', '').lower()
            if event == 'Field Error':
                subject = '相手の送球失策' if 'throwing error' in description else '相手の失策'
                action = '決勝点'
            elif event in ('Wild Pitch', 'Passed Ball'):
                subject, action = ('相手の暴投' if event == 'Wild Pitch' else '相手の捕逸'), '決勝点'
            else:
                subject = who
                action = hr_name(dp['result'].get('rbi') or 1) if event == 'Home Run' else EVENT_JP.get(event, event)
            decisive_card = {'inning': inning_text(dp), 'subject': subject, 'action': action,
                             'detail': measure_text(measure(dp)) if event == 'Home Run' else '',
                             'event': event}
            if is_hit:
                hero = (who, dp, first)

    # 本塁打（球団ごと）
    hrs = {"away": [], "home": []}
    for p, side, _ in scoring(feed):
        if p["result"].get("event") == "Home Run":
            hrs[side].append(who_of(p["matchup"]["batter"]))
    total = sum(len(v) for v in hrs.values())
    if total >= 2 or (total == 1 and not (hero and hero[1]["result"].get("event") == "Home Run")):
        parts = []
        for s in (win_side, lose_side):
            if not hrs[s]:
                continue
            names = [n.split("・")[-1] for n in hrs[s]]
            txt = f"{name[s]}{len(hrs[s])}本"
            if all(names):
                txt += "（" + "、".join(names) + "）"
            parts.append(txt)
        items.append(("本塁打", "　".join(parts)))

    # 先発（両球団。カタカナにできない投手の側は出さない）
    starters = []
    for s in (win_side, lose_side):
        ids = box[s].get("pitchers") or []
        if not ids:
            continue
        pl = (box[s].get("players") or {}).get(f"ID{ids[0]}", {})
        st = pl.get("stats", {}).get("pitching") or {}
        who = who_of(pl.get("person") or {})
        if who and st.get("inningsPitched"):
            starters.append(f"{name[s]} {who.split('・')[-1]} {pitcher_line(st, True)}")
    if starters:
        items.append(("先発", "　".join(starters)))
    # 投手（完封なら継投の人数）
    dec = feed["liveData"].get("decisions") or {}
    used = box[win_side].get("pitchers") or []
    if L == 0 and len(used) >= 2:
        items.append(("投手", f"{win}は{len(used)}人の継投で完封"))
    pitch = []
    for role, key in (("勝ち", "winner"), ("セーブ", "save")):
        person = dec.get(key) or {}
        # 先発が勝ち投手なら、先発の行で言っている。
        if key == "winner" and person.get("id") in (box[win_side].get("pitchers") or [None])[:1]:
            continue
        who = who_of(person) if person else ""
        if who:
            st = (box[win_side].get("players") or {}).get(f"ID{person.get('id')}", {}) \
                .get("stats", {}).get("pitching") or {}
            pitch.append(f"{role} {who}" + (f"（{pitcher_line(st, True)}）"
                                             if role == "勝ち" and st.get("inningsPitched") else ""))
    if pitch:
        label = "・".join(("勝ち投手" if x.startswith("勝ち") else "セーブ") for x in pitch)
        body = pitch[0].split(" ", 1)[1] if len(pitch) == 1 else "　".join(pitch)
        items.append((label, body))

    # 声（試合が始まった後のもの）
    start = (game.get("gameDate") or "")[:19]
    words = team_words(feed)
    source = voice = None
    v = pick_voice(voices, feed, start, words, table, jp, jp_names)
    if v:
        items.append(("ハイライトのコメント欄から", quoted(v["said"])))
        voice = v
    jp_side = next((s for s in (win_side, lose_side)
                    if player_lines(box[s], jp)), win_side)
    q = pick_reporter(quotes, name[jp_side], start, words, table, jp, jp_names)
    if q:
        items.append((f"{name[jp_side]}の番記者の投稿から", quoted(q["said"])))
        source = q

    headline = pick_headline(headlines, game, feed, words, table, jp)
    if headline:
        items.append(("MLB.comの見出しから", quoted(headline["said"])))

    # 題: 日本人選手の決勝打なら名前から。日本人選手が出ていれば末尾に名前。
    if ser.get("isOver") and wins is not None:
        result = f"{rnd}突破"
    elif (wins, losses) == (1, 0):
        result = f"{rnd}先勝"
    elif wins is not None:
        result = f"{rnd}{wins}勝{losses}敗に"
    else:
        result = "勝利"
    if hero and hero[0] in jp_names:
        what = ("先制" if hero[2] else "決勝") + (
            {1: "ソロ", 2: "2ラン", 3: "3ラン", 4: "満塁弾"}.get(hero[1]["result"].get("rbi"), "本塁打")
            if hero[1]["result"].get("event") == "Home Run" else "打")
        head = f"{hero[0]}の{what}で{win}が{where}{result}"
        tail = f"{lose}に{W}対{L}"
    else:
        head = f"{win}が{lose}に{W}対{L}で{result}"
        tail = (f"{hero[0].split('・')[-1]}の" + ("先制" if hero[2] else "決勝")
                + ("本塁打" if hero[1]["result"].get("event") == "Home Run" else "打")) if hero else ""
        names = [n for n in jp_names[:2]]
        if names:
            tail = (tail + "　" if tail else "") + "・".join(names)
    if hero and hero[0] in jp_names:
        intro = f"{rnd}第{num}戦、{hero[0]}の{what}で、{win}が{where}{lose}に{W}対{L}で勝ちました。"
    else:
        intro = f"{rnd}第{num}戦、{win}が{where}{lose}に{W}対{L}で勝ちました。"
    title = f"【MLB】{head}" + (f"｜{tail}" if tail else "") + " #Shorts"

    key = f"season_game_{game['gamePk']}"
    return {
        "key": key,
        "label": f"{rnd}第{num}戦",
        "hook": head,
        "heading": f"{name['away']} 対 {name['home']}　{rnd}第{num}戦",
        "intro": intro,
        "intro_as_is": True,
        "style": "v2",
        "team_id": teams[win_side]["id"],
        "abbr": ne.MLB_TEAM_ABBR.get(str(teams[win_side]["id"]), ""),
        "title": title,
        "items": items,
        "japanese": [{"name": j["name"], "line": j["line"]} for j in japanese],
        "japanese_lead": "この試合の日本人選手は、",
        "ps_ended": True,
        "story": True,
        "game": True,
        "source": source,
        "voice": voice,
        "headline": headline,
        "game_pk": game["gamePk"],
        "game_v4": {"score": inning_score(feed), "decisive": decisive_card},
        "game_date": game.get("gameDate"),
        "jp_first": bool(japanese),
        "next_team_id": next((teams[s]['id'] for s in (win_side,lose_side)
                              if any(p.get('person',{}).get('fullName') in jp
                                     for p in box[s].get('players',{}).values())),teams[win_side]['id']),
    }


def build(games: list, feeds: dict, voices: dict, quotes: list, headlines=(), now=None,
          series_rows=()) -> list:
    import notability_engine as ne
    jp = {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB}
    try:
        table = json.loads(pathlib.Path("data/player_kana.json")
                           .read_text(encoding="utf-8")).get("names") or {}
    except (OSError, json.JSONDecodeError):
        table = {}
    out = []
    for g in games:
        feed = feeds.get(g["gamePk"])
        if not feed:
            continue
        if now is not None:
            end = finished_at(feed)
            if end is None or not timedelta(0) <= now - end <= timedelta(hours=FRESH_HOURS):
                print(f"[warn] {g.get('gamePk')} 終了時刻が未確認・未来・30時間より前のため見送り", file=sys.stderr)
                continue
        try:
            t = story(g, feed, table, jp, voices, quotes, headlines)
        except Exception as e:                              # noqa: BLE001
            print(f"[warn] {g.get('gamePk')} を作れません({e})", file=sys.stderr)
            continue
        if t:
            # 試合が終わった時刻。昼の見張り（ps_game_now.py）が、終わってから
            # 何分たったかで出す時を決める。
            end = finished_at(feed)
            t["finished_at"] = end.isoformat() if end else None
            # 新デザインの表紙（v3）。作れない・材料と合わないときは v2 のまま
            out.append(ps_v3_cover.apply(t, series_rows))
    # 日本人選手が出た試合を先に、その中では早く終わった試合から。
    out.sort(key=lambda t: (not t["jp_first"], t.get("game_date") or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", default="data/local_voices.json")
    ap.add_argument("--quotes", default="data/ps_quotes.json")
    ap.add_argument("--headlines", default="data/local_reporters.json")
    ap.add_argument("--postseason", default="data/postseason.json")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        games = finished_games(now)
    except Exception as e:                                  # noqa: BLE001
        # continue-on-errorでも選択処理は進む。古いJSONを残すと前日の材料が選ばれる。
        write_topics(args.out, now, [], "error", "schedule fetch failed")
        print(f"[error] PSの日程を取れません({e})", file=sys.stderr)
        return 1
    feeds = {}
    failed = False
    for g in games:
        try:
            feeds[g["gamePk"]] = _get(f"/v1.1/game/{g['gamePk']}/feed/live")
            end = finished_at(feeds[g["gamePk"]])
            if end is None or end > now:
                failed = True
        except Exception as e:                              # noqa: BLE001
            failed = True
            print(f"[warn] {g['gamePk']} の試合経過を取れません({e})", file=sys.stderr)
    try:
        voices = json.loads(pathlib.Path(args.voices).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        voices = {}
    try:
        quotes = json.loads(pathlib.Path(args.quotes).read_text(encoding="utf-8")).get("posts") or []
    except (OSError, json.JSONDecodeError):
        quotes = []
    try:
        headlines = json.loads(pathlib.Path(args.headlines).read_text(encoding="utf-8")).get("headlines") or []
    except (OSError, json.JSONDecodeError):
        headlines = []
    headlines = [h for h in headlines if mlb_headlines.utc(h.get("at"))
                 and mlb_headlines.utc(h.get("at")) <= now]
    try:
        series_rows = json.loads(pathlib.Path(args.postseason).read_text(encoding="utf-8")).get("series") or []
    except (OSError, json.JSONDecodeError):
        series_rows = []
    topics = build(games, feeds, voices, quotes, headlines, now=now, series_rows=series_rows)
    write_topics(args.out, now, topics, "partial" if failed else "ok")
    print(f"[info] {len(topics)}件 -> {args.out}")
    for t in topics:
        print("  " + t["title"])
        for a, b in t["items"]:
            print(f"     {a} | {b}")
        for j in t["japanese"]:
            print(f"     日本人選手 | {j['name']} {j['line']}")
    return 1 if failed else 0


def write_topics(path, now, topics, status, error=None):
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    d = {"updated_at": now.isoformat(), "status": status,
         "source": "MLB Stats API（試合経過・成績表・計測）・ハイライトのコメント・番記者の投稿・MLB.com見出し",
         "topics": topics}
    if error:
        d["error"] = error
    target.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
