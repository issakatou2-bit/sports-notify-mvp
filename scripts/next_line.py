#!/usr/bin/env python3
"""締めの前に入れる「次」の1行を、MLB の日程の材料から作る（下書き。指示書 Opus-23）。

なぜ要るのか:
  10/9 の分析「コレスポの強みと伸ばし方」: 登録には「登録する理由」が要る。
  いまの締めは「毎日お届けしています。チャンネル登録をお願いします」で、
  次に何が見られるのかを言っていない。「明日9時、ホワイトソックスは突破をかけて第5戦」
  のように、**次の試合を約束する1行**を締めの前に置く。

何をするか（日程 schedule?hydrate=probablePitcher,seriesStatus から）:
  team_line(...)  ある球団の次の試合（試合の話題・17:00 成績の回）
  race_line(...)  ポストシーズン全体で、次に決着しうる試合（20:00 情勢の回）
  day_line(...)   次に試合がある日の、試合の数と最初の試合（19:00 予告の回）
  どれも NextLine（say=読み上げ、screen=画面の文）か、言えないときは None を返す。
  None のときは、いまの締めをそのまま使う（1行を足さない）。

決まり（指示書のとおり）:
  - 日付と時刻は日本時間（Asia/Tokyo）。「明日9時」「あさって9時」「10月14日9時」。
  - 時刻が未定（startTimeTBD）なら時刻を言わない。日本時間の日付も決まらないので、
    「現地10月14日」と、材料にある現地の日付で言う。
    ただしダブルヘッダーの第2試合は「第1試合のあと」と言う（第1試合の日付を使う）。
  - 先発が未定（probablePitcher が無い）なら先発を言わない。
  - 決着したシリーズ（seriesStatus.isOver）の試合は言わない。
  - 数字と名前は材料にあるものだけ。球団名は notability_engine.MLB_TEAM_NAME_JP、
    日本人選手の名前は JP_PLAYERS_MLB、外国人の投手の読みは MLB_NAME_READINGS（姓）にあるときだけ
    読み上げる（無いときは読み上げから外し、画面には材料の英字の綴りを出す。
    generate_asset_video._say と同じ考え）。
  - 「王手」「突破をかけて」「負ければ敗退」は seriesStatus の勝ち数から言えるときだけ。
    seriesStatus の試合番号と勝ち負けの数が合わないときは、勝敗の言い方をやめて「第N戦」だけにする。
  - 相手が決まっていない（「CLE/CWS」のような仮の球団）ときは、相手を言わない。
  - 延期（Postponed）・中止（Cancelled）・一時停止（Suspended）の行は、次の試合として数えない。
    延期で、振り替えの日時（rescheduleDate）が材料にあればその日時で言う。
    次の試合が材料に無く、直近の試合が延期のときは「延期、次の日時は未定」と言う。

読み上げ（say）と画面（screen）の違い:
  say    「あさって」「9時5分」のように耳で分かる言い方。括弧・記号・英字を入れない。
         日本人選手の漢字の名前はそのまま（読み仮名への置き換えは、いままでどおり
         音声合成の直前の notability_engine.apply_readings が行う）。
  screen 「10月11日(日)9時」のように日付を必ず書く（動画は3日ほど見られるので、
         「明日」だけでは見た日によってずれる）。テロップ（v3 の ticker）にもそのまま使える。

この作業リポジトリでは collespo/src の写し（10/7 ごろ）を読むだけで、書き換えない。
コレスポ側に取り込むときは scripts/next_line.py に置けば、同じ import で動く。

使い方（APIにつながない確認）:
  python3 collespo/next_line/next_line.py --json collespo/next_line/fixtures/ps_20261009.json \\
      --team 145 --now 2026-10-09T17:00+09:00
"""

import argparse
import json
import os
import pathlib
import sys
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from dataclasses import asdict

try:
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
except Exception:                                   # noqa: BLE001  tzdata が無い環境
    JST = timezone(timedelta(hours=9))

HERE = pathlib.Path(__file__).resolve().parent

# ポストシーズンの回戦（gameType）。ps_series.ROUNDS と同じ呼び方。
ROUND_JP = {"F": "ワイルドカードシリーズ", "D": "地区シリーズ",
            "L": "リーグ優勝決定シリーズ", "W": "ワールドシリーズ"}
POSTSEASON = set(ROUND_JP)

# 次の試合として数えない状態（detailedState の頭）
NOT_PLAYED = ("Postponed", "Cancelled", "Suspended")
WEEKDAY = "月火水木金土日"

# 何日先までを「次」と言うか。これより先は、締めで約束するには遠い。
MAX_DAYS = 7


@dataclass
class NextLine:
    say: str                       # 読み上げ（締めの読み上げの前に足す）
    screen: str                    # 画面の文（テロップ・締めの画面）
    kind: str                      # "team" / "race" / "day" / "postponed"
    game_pk: int = 0
    facts: dict = field(default_factory=dict)   # 何から言ったか（検査・記録用）


# ---------------------------------------------------------------------------
# 名前の表（コレスポの notability_engine から。無ければ空 → 球団名が言えない行は作らない）
# ---------------------------------------------------------------------------

def _engine():
    root=pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    try:
        import notability_engine as ne            # 本番: scripts/ から見て parents[1]
        return ne
    except ImportError:
        # この作業リポジトリ: collespo/src の写し（別の場所なら環境変数 COLLESPO_SRC）
        src = pathlib.Path(os.environ.get("COLLESPO_SRC") or HERE.parent / "src")
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            import notability_engine as ne
            return ne
        except ImportError:
            return None


def default_names() -> dict:
    """{"teams": {id: 日本語名}, "pitchers": {英語名: 画面の名前}, "readings": {姓: 読み}}"""
    ne = _engine()
    if ne is None:
        return {"teams": {}, "pitchers": {}, "readings": {}}
    return {
        "teams": {int(k): v for k, v in ne.MLB_TEAM_NAME_JP.items()},
        "pitchers": {p["name_en"]: p["name_jp"] for p in ne.JP_PLAYERS_MLB if p.get("name_en")},
        "readings": dict(ne.MLB_NAME_READINGS),
    }


# ---------------------------------------------------------------------------
# 日程の読み取り
# ---------------------------------------------------------------------------

def all_games(schedule: dict) -> list:
    """schedule の dates[].games[] を1列に。同じ gamePk が2度載る日（延期→振り替え）は、
    延期の行より振り替えの行を残す。"""
    by = {}
    for d in schedule.get("dates") or []:
        for g in d.get("games") or []:
            pk = g.get("gamePk")
            old = by.get(pk)
            if old is None or (_not_played(old) and not _not_played(g)):
                by[pk] = g
            elif _not_played(old) and _not_played(g):
                by[pk] = max(old, g, key=lambda x: x.get("gameDate") or "")
    return sorted(by.values(), key=_sort_key)


def _sort_key(g):
    return (g.get("officialDate") or (g.get("gameDate") or "")[:10],
            int(g.get("gameNumber") or 1), g.get("gameDate") or "")


def _state(g) -> str:
    return (g.get("status") or {}).get("detailedState") or ""


def _not_played(g) -> bool:
    return _state(g).startswith(NOT_PLAYED)


def _tbd(g) -> bool:
    return bool((g.get("status") or {}).get("startTimeTBD"))


def _upcoming(g) -> bool:
    """まだ始まっていない試合か（Preview）。終わった・試合中・延期は False。"""
    return ((g.get("status") or {}).get("abstractGameState") == "Preview"
            and not _not_played(g))


def _start(g):
    iso = g.get("gameDate")
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _side(g, team_id):
    for side in ("away", "home"):
        if ((g.get("teams") or {}).get(side) or {}).get("team", {}).get("id") == team_id:
            return side
    return None


def _other(side):
    return "home" if side == "away" else "away"


def _plays(g, team_id) -> bool:
    return _side(g, team_id) is not None


def _series_over(g) -> bool:
    return bool((g.get("seriesStatus") or {}).get("isOver")) and g.get("gameType") in POSTSEASON


def _effective_start(g, games):
    """言える開始時刻。時刻未定なら None。ダブルヘッダー第2試合の未定は第1試合を返す（after=True）。"""
    if not _tbd(g):
        return _start(g), False
    if g.get("doubleHeader") in ("Y", "S") and int(g.get("gameNumber") or 1) == 2:
        first = next((x for x in games if x is not g and int(x.get("gameNumber") or 1) == 1
                      and x.get("officialDate") == g.get("officialDate")
                      and {_tid(x, "away"), _tid(x, "home")} == {_tid(g, "away"), _tid(g, "home")}
                      and not _tbd(x)), None)
        if first is not None:
            return _start(first), True
    return None, False


def _tid(g, side):
    return ((g.get("teams") or {}).get(side) or {}).get("team", {}).get("id")


def next_game(schedule: dict, team_id: int, now: datetime):
    """その球団の次の試合と、言えないときの理由。 -> (game | None, reason)"""
    games = all_games(schedule)
    mine = [g for g in games if _plays(g, team_id)]
    if not mine:
        return None, "no_games"
    cand = []
    for g in mine:
        if not _upcoming(g) or _series_over(g):
            continue
        when, after_first = _effective_start(g, mine)
        # ダブルヘッダー第2試合（時刻未定）は、第1試合が始まった後でも、まだ前なら候補
        if when is not None and when <= now and not after_first:
            continue
        # 時刻未定の試合は、現地の日付が今日（日本時間）より前でなければ候補にする
        if when is None and (g.get("officialDate") or "") < (now.astimezone(JST) - timedelta(days=1)).strftime("%Y-%m-%d"):
            continue
        cand.append(g)
    if cand:
        return cand[0], "ok"
    # 次が無い。直近（いまより後、または24時間以内）の行が延期なら、延期として返す
    recent = [g for g in mine if _not_played(g) and _state(g).startswith("Postponed")
              and (_start(g) or now) >= now - timedelta(hours=24)]
    if recent:
        return recent[-1], "postponed"
    return None, "no_next_game"


# ---------------------------------------------------------------------------
# 言い方の部品
# ---------------------------------------------------------------------------

def _team_jp(g, side, names) -> str:
    """日本語の球団名。表に無い（仮の「CLE/CWS」など）ときは空。"""
    t = ((g.get("teams") or {}).get(side) or {}).get("team") or {}
    return names["teams"].get(t.get("id"), "")


def _day_words(when: datetime, now: datetime):
    """(読み上げの日, 画面の日)。日本時間。"""
    w, n = when.astimezone(JST), now.astimezone(JST)
    diff = (w.date() - n.date()).days
    screen = f"{w.month}月{w.day}日({WEEKDAY[w.weekday()]})"
    say = {0: "今日", 1: "明日", 2: "あさって"}.get(diff, f"{w.month}月{w.day}日")
    return say, screen


def _clock(when: datetime) -> str:
    w = when.astimezone(JST)
    return f"{w.hour}時" + (f"{w.minute}分" if w.minute else "")


def when_words(g, games, now, relative=True):
    """(読み上げ, 画面, facts)。relative=False なら読み上げも「10月11日」にする。"""
    when, after_first = _effective_start(g, games)
    dh = g.get("doubleHeader") in ("Y", "S")
    num = int(g.get("gameNumber") or 1)
    if when is None:
        # 日本時間の日付は決まらない。材料の現地の日付で言う
        od = g.get("officialDate") or (g.get("gameDate") or "")[:10]
        m, d = int(od[5:7]), int(od[8:10])
        say = screen = f"現地{m}月{d}日"
        if dh:
            say += f"のダブルヘッダー第{num}試合"
            screen += f"　ダブルヘッダー第{num}試合（時刻未定）"
        else:
            screen += "（時刻未定）"
        return say, screen, {"local_date": od, "time": None}
    day_say, day_screen = _day_words(when, now)
    if not relative:
        w = when.astimezone(JST)
        day_say = f"{w.month}月{w.day}日"
    if after_first:
        say = f"{day_say}のダブルヘッダー第2試合"
        screen = f"{day_screen}　ダブルヘッダー第2試合（第1試合のあと）"
    else:
        say = f"{day_say}{_clock(when)}"
        screen = f"{day_screen}{_clock(when)}"
        if dh:
            say += f"からのダブルヘッダー第{num}試合"
            screen += f"　ダブルヘッダー第{num}試合"
    return say, screen, {"jst": when.astimezone(JST).isoformat(), "after_first": after_first}


def _series_state(g, team_id=None):
    """seriesStatus から (自分の勝ち, 自分の負け, 勝ち抜けに要る勝ち数)。言えなければ None。

    seriesStatus の wins/losses はリードしている側から見た数（同点なら同じ数）。
    どちらがリードしているかは winningTeam で分かる。team_id が無いときは (リード側, 相手) で返す。
    試合番号と勝ち負けの数が合わないとき（材料の食い違い）は None。
    """
    ss = g.get("seriesStatus") or {}
    if g.get("gameType") not in POSTSEASON or not ss or ss.get("isOver"):
        return None
    total = int(ss.get("totalGames") or g.get("gamesInSeries") or 0)
    wins, losses = ss.get("wins"), ss.get("losses")
    num = int(g.get("seriesGameNumber") or ss.get("gameNumber") or 0)
    if not total or wins is None or losses is None or num != wins + losses + 1:
        return None
    need = total // 2 + 1
    if ss.get("isTied") or wins == losses:
        return wins, losses, need
    leader = (ss.get("winningTeam") or {}).get("id")
    if leader is None:
        return None
    if team_id is None or leader == team_id:
        return wins, losses, need
    return losses, wins, need


def _goal(g) -> str:
    return "世界一" if g.get("gameType") == "W" else "突破"


def _stake(g, team_id):
    """その球団から見た、この試合で懸かっているもの。(読み上げの頭, 画面, facts)"""
    st = _series_state(g, team_id)
    if st is None:
        return "", "", {}
    w, l, need = st
    goal = _goal(g)
    facts = {"wins": w, "losses": l, "need": need}
    if w == need - 1 and l == need - 1:
        return f"勝てば{goal}、負ければ敗退の", f"勝てば{goal}・負ければ敗退", facts
    if w == need - 1:
        return f"{goal}をかけて", f"{w}勝{l}敗　勝てば{goal}", facts
    if l == need - 1:
        return "負ければ敗退の", f"{w}勝{l}敗　負ければ敗退", facts
    if w + l == 0:
        return "", "", facts
    return f"{w}勝{l}敗で迎える", f"{w}勝{l}敗", facts


def _pitcher(g, side, names):
    """(読み上げの名前, 画面の名前)。未定なら ("", "")。読みが分からなければ読み上げは空。"""
    p = ((g.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}
    full = (p.get("fullName") or "").strip()
    if not full:
        return "", ""
    jp = names["pitchers"].get(full)
    if jp:
        return jp, jp
    last = full.split()[-1] if full.split() else ""
    kana = names["readings"].get(last, "")
    # 読みの表（姓）にあれば、読み上げも画面もその片仮名。無ければ画面だけ材料の綴り
    return (kana, kana) if kana else ("", full)


# ---------------------------------------------------------------------------
# 1行を作る
# ---------------------------------------------------------------------------

def team_line(schedule: dict, team_id: int, now: datetime, names=None, who: str = "",
              relative: bool = True, max_days: int = MAX_DAYS):
    """ある球団の次の試合を1行に（試合の話題・17:00 成績の回）。

    who: 「村上宗隆」のように選手名を頭に付ける（「村上宗隆のホワイトソックスは」）。
    例: 「次はあさって9時、ホワイトソックスは、勝てば突破、負ければ敗退の地区シリーズ第5戦、相手はガーディアンズ。」
    """
    names = names or default_names()
    games = all_games(schedule)
    g, reason = next_game(schedule, team_id, now)
    if g is None:
        return None
    side = _side(g, team_id)
    team = names["teams"].get(team_id, "")
    if not team:
        return None
    head = f"{who}の{team}" if who else team
    opp = _team_jp(g, _other(side), names)
    if reason == "postponed":
        return _postponed_line(g, side, head, opp, now, names, relative)

    mine = [x for x in games if _plays(x, team_id)]
    say_when, screen_when, wf = when_words(g, mine, now, relative)
    if wf.get("jst") and datetime.fromisoformat(wf["jst"]) - now > timedelta(days=max_days):
        return None
    ps = g.get("gameType") in POSTSEASON
    say_p, screen_p = _pitcher(g, side, names)
    facts = {"game_pk": g.get("gamePk"), "gameDate": g.get("gameDate"), **wf,
             "opponent": opp, "pitcher": screen_p}
    rescheduled = " （延期分）" if g.get("rescheduledFrom") else ""
    if ps:
        rnd = ROUND_JP[g["gameType"]]
        num = int(g.get("seriesGameNumber") or 0)
        stake_say, stake_screen, sf = _stake(g, team_id)
        facts.update(sf, round=rnd, game=num)
        game_words = f"{rnd}第{num}戦" if num else rnd
        say = (f"次は{say_when}、{head}は、{stake_say}{game_words}" if stake_say
               else f"次は{say_when}、{head}は{game_words}")
        say += f"、相手は{opp}" if opp else ""
        screen = f"次の試合　{screen_when}　{game_words}"
        screen += f"　対{opp}" if opp else ""
        screen += f"　{stake_screen}" if stake_screen else ""
    else:
        say = f"次は{say_when}、{head}は{opp}戦" if opp else f"次は{say_when}、{head}の試合"
        screen = f"次の試合　{screen_when}　" + (f"対{opp}" if opp else "") + rescheduled.strip()
    say += "です。"
    if g.get("rescheduledFrom"):
        say += "延期になっていた試合です。"
    if say_p:
        say += f"先発は{say_p}です。"
    screen += f"　先発 {screen_p}" if screen_p else ""
    return NextLine(say=_tidy(say), screen=screen.strip(), kind="team",
                    game_pk=g.get("gamePk") or 0, facts=facts)


def _postponed_line(g, side, head, opp, now, names, relative):
    res = g.get("rescheduleDate")
    if res:
        # 振り替えの日時が材料にある（振り替えの行は日程に無い）。その日時で言う
        when = datetime.fromisoformat(res.replace("Z", "+00:00"))
        if when > now:
            day_say, day_screen = _day_words(when, now)
            if not relative:
                w = when.astimezone(JST)
                day_say = f"{w.month}月{w.day}日"
            say = f"延期になった{opp}戦は、{day_say}{_clock(when)}に行われます。" if opp else \
                f"延期になった{head}の試合は、{day_say}{_clock(when)}に行われます。"
            screen = f"次の試合　{day_screen}{_clock(when)}　" + (f"対{opp}" if opp else "") + "（延期分）"
            return NextLine(say=say, screen=screen, kind="postponed", game_pk=g.get("gamePk") or 0,
                            facts={"rescheduleDate": res})
    say = f"{head}の{opp}戦は延期になり、次の日時はまだ決まっていません。" if opp else \
        f"{head}の試合は延期になり、次の日時はまだ決まっていません。"
    screen = "次の試合　" + (f"対{opp}　" if opp else "") + "延期（日時未定）"
    return NextLine(say=say, screen=screen, kind="postponed", game_pk=g.get("gamePk") or 0,
                    facts={"reason": (g.get("status") or {}).get("reason")})


def _upcoming_ps(schedule, now):
    games = all_games(schedule)
    out = []
    for g in games:
        if g.get("gameType") not in POSTSEASON or not _upcoming(g) or _series_over(g):
            continue
        when, _ = _effective_start(g, games)
        if when is not None and when <= now:
            continue
        out.append(g)
    return out, games


def race_line(schedule: dict, now: datetime, names=None, relative: bool = True,
              max_days: int = MAX_DAYS):
    """ポストシーズン全体で「次」を1行に（20:00 情勢の回）。

    いちばん早い「決着しうる試合」（どちらかが勝ち抜けまであと1勝）を選ぶ。無ければいちばん早い試合。
    例: 「次はあさって9時、ガーディアンズ対ホワイトソックスの地区シリーズ第5戦。勝った方が突破です。」
    """
    names = names or default_names()
    ups, games = _upcoming_ps(schedule, now)
    timed = [g for g in ups if _effective_start(g, games)[0] is not None]
    if not timed:
        return None
    timed.sort(key=lambda g: _effective_start(g, games)[0])
    deciding = [g for g in timed if (lambda s: s and s[2] - 1 in (s[0], s[1]))(_series_state(g))]
    g = (deciding or timed)[0]
    when, _ = _effective_start(g, games)
    if when - now > timedelta(days=max_days):
        return None
    say_when, screen_when, wf = when_words(g, games, now, relative)
    home, away = _team_jp(g, "home", names), _team_jp(g, "away", names)
    rnd = ROUND_JP[g["gameType"]]
    num = int(g.get("seriesGameNumber") or 0)
    game_words = f"{rnd}第{num}戦" if num else rnd
    if home and away:
        card = f"{home}対{away}"
    elif home or away:
        card = home or away
    else:
        return None
    say = f"次は{say_when}、{card}の{game_words}。"
    screen = f"次の試合　{screen_when}　{card}　{game_words}"
    facts = {"game_pk": g.get("gamePk"), **wf, "round": rnd, "game": num}
    st = _series_state(g)
    if st and home and away:
        lead_w, lead_l, need = st
        goal = _goal(g)
        facts.update(wins=lead_w, losses=lead_l, need=need)
        if lead_w == lead_l == need - 1:
            say += f"勝った方が{goal}です。"
            screen += f"　勝った方が{goal}"
        elif lead_w == need - 1:
            leader_id = ((g.get("seriesStatus") or {}).get("winningTeam") or {}).get("id")
            leader = names["teams"].get(leader_id, "")
            if leader:
                other = away if leader == home else home
                say += f"{leader}が{lead_w}勝{lead_l}敗で{goal}に王手、{other}は負ければ敗退です。"
                screen += f"　{leader}が{goal}に王手"
    return NextLine(say=_tidy(say), screen=screen, kind="race", game_pk=g.get("gamePk") or 0,
                    facts=facts)


def day_line(schedule: dict, now: datetime, names=None, label: str = "ポストシーズン",
             game_types=POSTSEASON, relative: bool = True, max_days: int = MAX_DAYS):
    """次に試合がある日（日本時間）の、試合の数と最初の試合（19:00 予告の回）。

    例: 「明日はポストシーズン2試合。最初は9時、ブリュワーズ対ドジャースのリーグ優勝決定シリーズ第1戦です。」
    時刻未定の試合は、日本時間の日付が決まらないので数えない（数えたかを facts に残す）。
    """
    names = names or default_names()
    games = all_games(schedule)
    ups = []
    for g in games:
        if game_types and g.get("gameType") not in game_types:
            continue
        if not _upcoming(g) or _series_over(g):
            continue
        when, _ = _effective_start(g, games)
        if when is None or when <= now:
            continue
        ups.append((when, g))
    if not ups:
        return None
    ups.sort(key=lambda x: x[0])
    first_when, first = ups[0]
    if first_when - now > timedelta(days=max_days):
        return None
    day = first_when.astimezone(JST).date()
    same = [g for w, g in ups if w.astimezone(JST).date() == day]
    day_say, day_screen = _day_words(first_when, now)
    if not relative:
        day_say = f"{day.month}月{day.day}日"
    home, away = _team_jp(first, "home", names), _team_jp(first, "away", names)
    card = f"{home}対{away}" if home and away else (home or away)
    what = ""
    if first.get("gameType") in POSTSEASON:
        num = int(first.get("seriesGameNumber") or 0)
        what = f"{ROUND_JP[first['gameType']]}第{num}戦" if num else ROUND_JP[first["gameType"]]
    if len(same) == 1:
        say = f"{day_say}は{label}1試合。{_clock(first_when)}から"
        screen = f"{day_screen}　{label}1試合　{_clock(first_when)}から"
    else:
        say = f"{day_say}は{label}{len(same)}試合。最初は{_clock(first_when)}"
        screen = f"{day_screen}　{label}{len(same)}試合　最初は{_clock(first_when)}"
    if card:
        say += f"、{card}" + (f"の{what}" if what else "")
        screen += f"　{card}" + (f"　{what}" if what else "")
    say += "です。"
    return NextLine(say=_tidy(say), screen=screen, kind="day", game_pk=first.get("gamePk") or 0,
                    facts={"date": day.isoformat(), "count": len(same),
                           "tbd_skipped": sum(1 for g in games if _upcoming(g) and _tbd(g)
                                              and (not game_types or g.get("gameType") in game_types))})


def _tidy(text: str) -> str:
    return text.replace("、、", "、").replace("。。", "。").replace("は、、", "は、")


# ---------------------------------------------------------------------------
# 締めにつなぐ（いまの締めの文の前に足すだけ）
# ---------------------------------------------------------------------------

def with_outro(outro_text: str, line) -> str:
    """締めの読み上げの前に「次」の1行を足す。line が None なら締めはそのまま。"""
    if line is None or not line.say:
        return outro_text
    return line.say + outro_text


def publication_time(day, clock, now=None):
    """予約の時刻を基準にする。遅延で予約不能なら実際の制作時刻。"""
    now=now or datetime.now(JST)
    if 'T' in str(clock):return datetime.fromisoformat(clock.replace('Z','+00:00')).astimezone(JST)
    hh,mm=map(int,clock.split(':'))
    scheduled=datetime.fromisoformat(day).replace(hour=hh,minute=mm,tzinfo=JST)
    return max(scheduled,now.astimezone(JST))


def choose(schedule, kind, published_at, team_id=None):
    """公開時刻に基づく材料をJSONで保存。19時はPSのrace_lineだけ。"""
    if kind in ('daily','postseason','morning_postseason'):
        line=race_line(schedule,published_at)
    elif team_id is not None:
        line=team_line(schedule,int(team_id),published_at)
    else:return None
    if line is None:return None
    # 日時未定の延期は「次の試合がある」材料にはしない。
    if line.kind=='postponed' and not line.facts.get('rescheduleDate'):return None
    when=line.facts.get('jst') or line.facts.get('rescheduleDate')
    if when and datetime.fromisoformat(when.replace('Z','+00:00'))-published_at>timedelta(days=MAX_DAYS):return None
    game=next((g for g in all_games(schedule) if g.get('gamePk')==line.game_pk),None)
    if game is None:return None
    ids=[_tid(game,s) for s in ('away','home')]
    result=asdict(line)
    result.update(team_ids=[t for t in ids if t in default_names()['teams']],publication_at=published_at.isoformat(),
                  source_url='https://statsapi.mlb.com/api/v1/schedule')
    return result


def acquire(kind, published_at, team_id=None, schedule_path=None):
    """生成時に一度だけ取得。失敗は理由を残し、次情報なしで続ける。"""
    try:
        schedule=(json.loads(pathlib.Path(schedule_path).read_text(encoding='utf-8')) if schedule_path else
                  fetch_schedule((published_at-timedelta(days=1)).date().isoformat(),(published_at+timedelta(days=8)).date().isoformat()))
        return choose(schedule,kind,published_at,team_id)
    except (OSError,ValueError,KeyError) as exc:
        print('[warn] 次の試合の材料を取得できません: '+str(exc),file=sys.stderr)
        return None


def insert(segments, line):
    if not line:return segments
    if any(s['kind']=='next_line' for s in segments):return segments
    index=next((i for i,s in enumerate(segments) if s['kind']=='outro'),len(segments))
    return segments[:index]+[{'kind':'next_line','speaker':2,'min_duration':.5,
                             'text':line['say'],'meta':{'next_line':line,'who':'四国めたん'}}]+segments[index:]


def frame(t, line):
    """共通の締めの前に出す日付つきの札。caption等の共通関数は変更しない。"""
    import review_render_v3 as r3
    import v3_slot_render as common
    spec={'heading':'次の試合','team_id':None,'v3':{'ticker':line['screen'],'ticker_once':True}}
    if r3.LOOK!='v4':
        return common.frame(t,spec,[('',line['screen'])],'次の試合','出典：MLB公式日程')
    import short_v4_cards as cards
    im=cards.canvas(t,'次の試合')
    text=line['screen'].removeprefix('次の試合　')
    # 球団札の送り幅を含めて折る。材料のteam_idsを個々の球団文字に対応させる。
    names=default_names()['teams']; available={names[tid]:tid for tid in line['team_ids']}
    rows=[];current=''
    chunks=re.findall('|'.join(re.escape(n) for n in sorted(available,key=len,reverse=True))+'|.',text)
    for ch in chunks:
        candidate=current+ch
        width=r3.font(46).getlength(candidate)+sum(cards.inline_badge_width(tid,46)+12 for name,tid in available.items() if name in candidate)
        if current and width>cards.R-cards.L-64:rows.append(current);current=ch
        else:current=candidate
    if current:rows.append(current)
    height=100+len(rows)*66;y=max(300,(r3.CONTENT_TOP+r3.CONTENT_BOTTOM-height)//2)
    cards.panel(im,(cards.L,y,cards.R,y+height))
    cards.text(im,cards.L+30,y+24,'次の試合 · 日本時間',30,r3.GOLD,width=cards.R-cards.L-60)
    for i,row in enumerate(rows):cards.text(im,cards.L+30,y+78+i*66,row,46,width=cards.R-cards.L-60)
    im.info['next_line']=line
    return cards.finish(im,t,line['screen'],'出典：MLB公式日程',once=True)


def fetch_schedule(start: str, end: str, game_types: str = "", get=None) -> dict:
    """日程を取る（本番用。検査では使わない）。get を差し替えられる。"""
    params = {"sportId": 1, "startDate": start, "endDate": end,
              "hydrate": "probablePitcher,seriesStatus"}
    if game_types:
        params["gameType"] = game_types
    if get is None:
        import urllib.request
        q = "&".join(f"{k}={v}" for k, v in params.items())
        with urllib.request.urlopen("https://statsapi.mlb.com/api/v1/schedule?" + q, timeout=30) as r:
            return json.load(r)
    return get("/api/v1/schedule", **params)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="日程の材料から「次」の1行を作って表示する")
    ap.add_argument("--json", required=True, help="schedule の JSON")
    ap.add_argument("--now", required=True, help="いつ見せる文か（例 2026-10-09T17:00+09:00）")
    ap.add_argument("--team", type=int, help="球団ID（無ければ情勢と予告の行だけ）")
    ap.add_argument("--who", default="")
    a = ap.parse_args(argv)
    sched = json.loads(pathlib.Path(a.json).read_text(encoding="utf-8"))
    now = datetime.fromisoformat(a.now)
    rows = []
    if a.team:
        rows.append(("試合の話題・成績", team_line(sched, a.team, now, who=a.who)))
    rows.append(("20:00 情勢", race_line(sched, now)))
    rows.append(("19:00 予告", day_line(sched, now)))
    for label, line in rows:
        print(f"[{label}]")
        if line is None:
            print("  （言える次の試合なし。締めはそのまま）")
        else:
            print(f"  読み上げ: {line.say}\n  画面:     {line.screen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
