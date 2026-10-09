#!/usr/bin/env python3
"""「次」の1行（next_line.py）の検査。通信しない。

材料:
  - fixtures/ps_20261009.json  2026年ポストシーズン 10/3〜10/14 の本物の日程（10/9 に取ったまま）。
  - fixtures/reg_202609.json   2026年9月の、延期・ダブルヘッダー・時刻未定・中止のある2カード（本物）。
  - 「その時点では試合前だった」形は、下の as_of() が作る（いまより後の試合を Preview に戻し、
    点数を消し、ポストシーズンの seriesStatus を、それまでに終わった試合から数え直す）。
    as_of で作った材料の勝ち負けは、本物の日程の結果と同じ（数え直しが合っているかも検査する）。
  - 一部の検査（時刻未定・食い違い・決着後の試合）は、本物の材料の1か所だけを書き換えて使う。
    書き換えた所は、その検査の中に書いてある。

球団名・日本人選手の名前・読みは collespo/src の写し（notability_engine）から。
写しが別の場所にあるときは、環境変数 COLLESPO_SRC にそのフォルダを入れる。

動かし方（リポジトリの一番上で）:
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider collespo/next_line/test_next_line.py
"""
import copy
import json
import pathlib
import re
import socket
import sys
from datetime import datetime

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import next_line as nl  # noqa: E402

FIX = HERE / "fixtures" / "next-line"
PS = json.loads((FIX / "ps_20261009.json").read_text(encoding="utf-8"))
REG = json.loads((FIX / "reg_202609.json").read_text(encoding="utf-8"))
NAMES = nl.default_names()

CWS, CLE, LAD, ATL, TB, NYY, MIL, BAL, TOR = 145, 114, 119, 144, 139, 147, 158, 110, 141


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """検査の途中で通信しようとしたら落とす。"""
    def deny(*a, **k):
        raise AssertionError("検査で通信しようとしました")
    monkeypatch.setattr(socket.socket, "connect", deny)


def t(iso):
    return datetime.fromisoformat(iso)


def as_of(schedule, now):
    """now の時点の日程に戻す。いまより後の「終わった」試合を Preview にし、点数を消す。
    延期・中止の行はそのまま（その時点で分かっていた、として扱う）。
    ポストシーズンの seriesStatus は、now より前に終わった試合から数え直す（winningTeam も）。"""
    s = copy.deepcopy(schedule)
    games = [g for d in s["dates"] for g in d["games"]]
    for g in games:
        st = g["status"]
        if nl._start(g) > now and not st.get("detailedState", "").startswith(nl.NOT_PLAYED):
            g["status"] = {"abstractGameState": "Preview", "detailedState": "Scheduled",
                           "startTimeTBD": st.get("startTimeTBD", False)}
            for side in ("away", "home"):
                g["teams"][side].pop("score", None)
                g["teams"][side].pop("isWinner", None)
    finals = [g for g in games if g["status"]["abstractGameState"] == "Final"
              and not g["status"]["detailedState"].startswith(nl.NOT_PLAYED)]
    for g in games:
        if g["gameType"] not in nl.POSTSEASON or g["status"]["abstractGameState"] != "Preview":
            continue
        pair = {nl._tid(g, "away"), nl._tid(g, "home")}
        wins = {tid: 0 for tid in pair}
        for f in finals:
            if f["gameType"] == g["gameType"] and {nl._tid(f, "away"), nl._tid(f, "home")} == pair:
                for side in ("away", "home"):
                    if f["teams"][side].get("isWinner"):
                        wins[nl._tid(f, side)] += 1
        (a, wa), (b, wb) = sorted(wins.items(), key=lambda x: -x[1])
        ss = dict(g.get("seriesStatus") or {}, wins=wa, losses=wb, isTied=wa == wb,
                  isOver=False, gameNumber=wa + wb + 1)
        ss.pop("winningTeam", None)
        if wa != wb:
            ss["winningTeam"] = {"id": a}
        g["seriesStatus"] = ss
    return s


def numbers(text):
    return [int(x) for x in re.findall(r"\d+", text)]


# ---------------------------------------------------------------------------
# 本物の日程そのまま（10/9 17:00 に見せる文）
# ---------------------------------------------------------------------------

NOW = t("2026-10-09T17:00+09:00")


def test_game5_both_sides_on_the_brink():
    """2勝2敗の第5戦。日本時間 10/11 9時（2026-10-11T00:00Z）。先発は未定なので言わない。"""
    line = nl.team_line(PS, CWS, NOW, NAMES)
    assert line.say == ("次はあさって9時、ホワイトソックスは、勝てば突破、負ければ敗退の"
                        "地区シリーズ第5戦、相手はガーディアンズです。")
    assert line.screen == ("次の試合　10月11日(日)9時　地区シリーズ第5戦　対ガーディアンズ"
                           "　勝てば突破・負ければ敗退")
    assert "先発" not in line.say + line.screen
    assert line.game_pk == 849831
    other = nl.team_line(PS, CLE, NOW, NAMES)
    assert "ガーディアンズは、勝てば突破、負ければ敗退" in other.say
    assert "相手はホワイトソックス" in other.say


def test_who_prefix_for_player_episode():
    line = nl.team_line(PS, CWS, NOW, NAMES, who="村上宗隆")
    assert line.say.startswith("次はあさって9時、村上宗隆のホワイトソックスは、")


def test_decided_series_is_not_mentioned_next_round_game1():
    """ドジャースは地区シリーズを3勝1敗で決めた。次はリーグ優勝決定シリーズ第1戦（10/12 9時）。"""
    line = nl.team_line(PS, LAD, NOW, NAMES)
    assert line.say == "次は10月12日9時、ドジャースはリーグ優勝決定シリーズ第1戦、相手はブリュワーズです。"
    assert "地区シリーズ" not in line.say.replace("リーグ優勝決定シリーズ", "")
    assert "勝" not in line.say.replace("優勝", "")   # 0勝0敗は言わない


def test_unknown_opponent_is_omitted():
    """レイズの相手は「CLE/CWS」（まだ決まっていない）。相手を言わない。"""
    line = nl.team_line(PS, TB, NOW, NAMES)
    assert line.say == "次は10月13日9時、レイズはリーグ優勝決定シリーズ第1戦です。"
    assert "CLE" not in line.say + line.screen and "対" not in line.screen


def test_eliminated_team_has_no_line():
    """ヤンキースは0勝3敗で敗退。日程に次の試合が無いので1行を作らない（締めはそのまま）。"""
    assert nl.team_line(PS, NYY, NOW, NAMES) is None
    assert nl.next_game(PS, NYY, NOW) == (None, "no_next_game")
    assert nl.with_outro("締め。", None) == "締め。"


def test_race_picks_deciding_game():
    line = nl.race_line(PS, NOW, NAMES)
    assert line.say == "次はあさって9時、ガーディアンズ対ホワイトソックスの地区シリーズ第5戦。勝った方が突破です。"
    assert line.screen.endswith("勝った方が突破")


def test_day_line_counts_games_of_that_day():
    line = nl.day_line(PS, NOW, NAMES)
    assert line.say == ("あさってはポストシーズン1試合。9時から、ガーディアンズ対ホワイトソックスの"
                        "地区シリーズ第5戦です。")
    later = nl.day_line(PS, t("2026-10-12T12:00+09:00"), NAMES)
    # 10/13（日本時間）は 6時のドジャース戦（10/12 21:00Z）と 9時のレイズ戦（10/13 00:00Z）
    assert later.facts["count"] == 2
    assert later.say.startswith("明日はポストシーズン2試合。最初は6時、ブリュワーズ対ドジャース")


def test_race_after_division_series():
    line = nl.race_line(PS, t("2026-10-11T12:00+09:00"), NAMES)
    assert line.say == "次は明日9時、ブリュワーズ対ドジャースのリーグ優勝決定シリーズ第1戦。"


# ---------------------------------------------------------------------------
# その時点に戻した日程（as_of）
# ---------------------------------------------------------------------------

def test_as_of_recount_matches_real_series_status():
    """as_of の数え直しが、本物の seriesStatus（試合後の値）と合うか。
    10/7 12:00 の時点の第3戦の「試合前」の状態は、本物の第2戦の「試合後」の状態と同じはず。"""
    old = as_of(PS, t("2026-10-07T12:00+09:00"))
    g3 = next(g for d in old["dates"] for g in d["games"] if g["gamePk"] == 849833)
    real_g2 = next(g for d in PS["dates"] for g in d["games"] if g["gamePk"] == 849834)
    assert (g3["seriesStatus"]["wins"], g3["seriesStatus"]["losses"]) == (
        real_g2["seriesStatus"]["wins"], real_g2["seriesStatus"]["losses"]) == (2, 0)
    assert g3["seriesStatus"]["winningTeam"]["id"] == real_g2["seriesStatus"]["winningTeam"]["id"] == CWS


def test_clinch_chance_and_elimination_game():
    """10/7 12:00。ホワイトソックス2勝0敗で第3戦（日本時間 10/8 5時、本拠地）。"""
    now = t("2026-10-07T12:00+09:00")
    old = as_of(PS, now)
    cws = nl.team_line(old, CWS, now, NAMES)
    assert cws.say.startswith("次は明日5時、ホワイトソックスは、突破をかけて地区シリーズ第3戦、相手はガーディアンズ")
    assert cws.screen.startswith("次の試合　10月8日(木)5時　地区シリーズ第3戦　対ガーディアンズ　2勝0敗　勝てば突破")
    # 先発 Sean Newcomb は読みの表に無い → 読み上げでは言わず、画面に材料の綴り
    assert "先発" not in cws.say and cws.screen.endswith("先発 Sean Newcomb")
    cle = nl.team_line(old, CLE, now, NAMES)
    assert "ガーディアンズは、負ければ敗退の地区シリーズ第3戦" in cle.say
    assert "0勝2敗　負ければ敗退" in cle.screen


def test_pitcher_reading_from_table():
    """ドジャース2勝1敗で第4戦（10/8 7時）。先発 Tyler Glasnow は読みの表に「グラスノー」がある。"""
    now = t("2026-10-07T12:00+09:00")
    line = nl.team_line(as_of(PS, now), LAD, now, NAMES)
    assert line.say == ("次は明日7時、ドジャースは、突破をかけて地区シリーズ第4戦、"
                        "相手はブレーブスです。先発はグラスノーです。")
    assert line.screen.endswith("2勝1敗　勝てば突破　先発 グラスノー")


def test_japanese_pitcher_and_even_series():
    """10/6 12:00。1勝1敗で第3戦（10/7 7時）。先発は山本由伸（日本人選手の名簿にある）。"""
    now = t("2026-10-06T12:00+09:00")
    line = nl.team_line(as_of(PS, now), LAD, now, NAMES)
    assert line.say == ("次は明日7時、ドジャースは、1勝1敗で迎える地区シリーズ第3戦、"
                        "相手はブレーブスです。先発は山本由伸です。")
    assert line.screen.endswith("1勝1敗　先発 山本由伸")
    # 読み仮名への置き換えは、いままでどおり音声合成の直前に（ここでは漢字のまま）
    ne = nl._engine()
    assert "ヤマモト" in ne.apply_readings(line.say)


def test_race_prefers_earliest_deciding_game():
    now = t("2026-10-07T12:00+09:00")
    line = nl.race_line(as_of(PS, now), now, NAMES)
    assert line.say == ("次は明日5時、ホワイトソックス対ガーディアンズの地区シリーズ第3戦。"
                        "ホワイトソックスが2勝0敗で突破に王手、ガーディアンズは負ければ敗退です。")


def test_day_line_on_busy_day():
    now = t("2026-10-07T12:00+09:00")
    line = nl.day_line(as_of(PS, now), now, NAMES)
    # 10/8（日本時間）は 5時・7時・9時・11時の4試合
    assert line.facts["count"] == 4
    assert line.say.startswith("明日はポストシーズン4試合。最初は5時、ホワイトソックス対ガーディアンズ")


# ---------------------------------------------------------------------------
# 材料の1か所だけを書き換えた検査
# ---------------------------------------------------------------------------

def _game(s, pk):
    return next(g for d in s["dates"] for g in d["games"] if g["gamePk"] == pk)


def test_time_tbd_uses_local_date_and_no_time():
    s = copy.deepcopy(PS)
    _game(s, 849831)["status"]["startTimeTBD"] = True          # 書き換え: 第5戦を時刻未定に
    line = nl.team_line(s, CWS, NOW, NAMES)
    assert line.say.startswith("次は現地10月10日、ホワイトソックスは、勝てば突破")
    assert "9時" not in line.say and "時刻未定" in line.screen
    # 予告・情勢の行は、日本時間の日付が決まらない試合を選ばない
    assert nl.race_line(s, NOW, NAMES).game_pk != 849831
    assert nl.day_line(s, NOW, NAMES).game_pk != 849831


def test_series_already_over_is_skipped():
    s = copy.deepcopy(PS)
    g5 = _game(s, 849831)
    g5["seriesStatus"]["isOver"] = True                         # 書き換え: 決着したことにする
    assert nl.team_line(s, CWS, NOW, NAMES) is None
    assert nl.race_line(s, NOW, NAMES).game_pk != 849831


def test_inconsistent_series_status_drops_stakes():
    s = copy.deepcopy(PS)
    _game(s, 849831)["seriesStatus"]["wins"] = 3                # 書き換え: 第5戦の前に3勝（あり得ない）
    line = nl.team_line(s, CWS, NOW, NAMES)
    assert "突破" not in line.say and "敗退" not in line.say
    assert "地区シリーズ第5戦" in line.say


def test_world_series_goal_word():
    s = copy.deepcopy(PS)
    _game(s, 849831)["gameType"] = "W"                          # 書き換え: ワールドシリーズにする
    line = nl.team_line(s, CWS, NOW, NAMES)
    assert "勝てば世界一、負ければ敗退のワールドシリーズ第5戦" in line.say


def test_far_future_is_not_promised():
    assert nl.team_line(PS, LAD, NOW, NAMES, max_days=2) is None


def test_relative_off_says_date():
    line = nl.team_line(PS, CWS, NOW, NAMES, relative=False)
    assert line.say.startswith("次は10月11日9時、")


# ---------------------------------------------------------------------------
# レギュラーシーズン（延期・ダブルヘッダー・時刻未定・中止）
# ---------------------------------------------------------------------------

def test_postponed_then_doubleheader_game1():
    """9/22 の試合が雨で延期 → 9/23 にダブルヘッダー（S）。9/23 8:00（日本時間）に見せる。
    第1試合は振り替え分で、日本時間 9/24 2時35分（2026-09-23T17:35Z）。"""
    now = t("2026-09-23T08:00+09:00")
    line = nl.team_line(as_of(REG, now), BAL, now, NAMES)
    # 先発 Chris Bassitt は読みの表に無いので、読み上げでは言わない（画面に綴り）
    assert line.say == ("次は明日2時35分からのダブルヘッダー第1試合、オリオールズはブルージェイズ戦です。"
                        "延期になっていた試合です。")
    assert line.screen.endswith("先発 Chris Bassitt")
    assert "9月24日(木)2時35分" in line.screen and "延期分" in line.screen


def test_postponed_with_reschedule_date_only():
    """振り替えの行が日程に無く、延期の行の rescheduleDate だけがあるとき。"""
    now = t("2026-09-23T08:00+09:00")
    s = as_of(REG, now)
    s["dates"] = [d for d in s["dates"] if d["date"] == "2026-09-22"]   # 9/23 以降を取らなかった日程
    line = nl.team_line(s, BAL, now, NAMES)
    assert line.kind == "postponed"
    assert line.say == "延期になったブルージェイズ戦は、明日2時35分に行われます。"


def test_postponed_without_new_date():
    now = t("2026-09-23T08:00+09:00")
    s = as_of(REG, now)
    s["dates"] = [d for d in s["dates"] if d["date"] == "2026-09-22"]
    s["dates"][0]["games"][0].pop("rescheduleDate")                    # 書き換え: 振り替え日が未発表
    line = nl.team_line(s, BAL, now, NAMES, who="")
    assert line.say == "オリオールズのブルージェイズ戦は延期になり、次の日時はまだ決まっていません。"
    assert line.screen == "次の試合　対ブルージェイズ　延期（日時未定）"


def test_doubleheader_game2_time_tbd():
    """9/25 のダブルヘッダー（Y）。第2試合は本物の材料で startTimeTBD。
    第1試合が終わったあと（9/26 9:00 日本時間）に見せると「今日のダブルヘッダー第2試合」。"""
    before = t("2026-09-26T00:00+09:00")
    line1 = nl.team_line(as_of(REG, before), NYY, before, NAMES)
    assert line1.say.startswith("次は今日5時5分からのダブルヘッダー第1試合、ヤンキースはオリオールズ戦")
    after = t("2026-09-26T09:00+09:00")
    s = as_of(REG, after)
    g2 = _game(s, 823489)
    g2["status"] = {"abstractGameState": "Preview", "detailedState": "Scheduled",
                    "startTimeTBD": True}                               # 書き換え: 第2試合はまだ前
    line2 = nl.team_line(s, NYY, after, NAMES)
    assert line2.say.startswith("次は今日のダブルヘッダー第2試合、ヤンキースはオリオールズ戦")
    assert "第1試合のあと" in line2.screen and "5時" not in line2.say


def test_cancelled_game_is_not_next():
    """9/27 の試合は中止（Cancelled）。それしか残っていなければ1行を作らない。"""
    now = t("2026-09-27T09:00+09:00")
    assert nl.team_line(as_of(REG, now), NYY, now, NAMES) is None


# ---------------------------------------------------------------------------
# 共通の決まり
# ---------------------------------------------------------------------------

def _all_lines():
    out = []
    for now in ("2026-10-06T12:00+09:00", "2026-10-07T12:00+09:00", "2026-10-09T17:00+09:00",
                "2026-10-11T12:00+09:00"):
        n = t(now)
        s = as_of(PS, n)
        for tid in (CWS, CLE, LAD, ATL, TB, NYY, MIL, 135):
            out.append((s, n, nl.team_line(s, tid, n, NAMES)))
        out.append((s, n, nl.race_line(s, n, NAMES)))
        out.append((s, n, nl.day_line(s, n, NAMES)))
    return [(s, n, x) for s, n, x in out if x is not None]


def test_numbers_come_from_the_data():
    """読み上げ・画面の数字は、日本時間の月・日・時・分、試合番号、勝ち負け、試合数のどれか。"""
    lines = _all_lines()
    assert len(lines) > 20
    for s, n, line in lines:
        g = _game(s, line.game_pk)
        when = nl._effective_start(g, nl.all_games(s))[0].astimezone(nl.JST)
        ok = {when.month, when.day, when.hour, when.minute, int(g.get("seriesGameNumber") or 0)}
        ss = g.get("seriesStatus") or {}
        ok |= {ss.get("wins"), ss.get("losses"), line.facts.get("count")}
        for x in numbers(line.say) + numbers(line.screen):
            assert x in ok, (x, line.say, line.screen)


def test_say_has_no_symbols_or_latin():
    for _, _, line in _all_lines():
        assert not re.search(r"[A-Za-z()（）/　]", line.say), line.say
        assert line.say.endswith("。")


def test_with_outro_puts_line_before_closing():
    line = nl.team_line(PS, CWS, NOW, NAMES)
    closing = "コレスポでは、毎日午後七時に、その日の注目試合を理由つきでお届けしています。"
    assert nl.with_outro(closing, line) == line.say + closing


def test_fetch_schedule_uses_given_getter():
    seen = {}

    def get(path, **params):
        seen.update(params, path=path)
        return {"dates": []}
    assert nl.fetch_schedule("2026-10-09", "2026-10-16", "F,D,L,W", get=get) == {"dates": []}
    assert seen["hydrate"] == "probablePitcher,seriesStatus" and seen["gameType"] == "F,D,L,W"


def test_cli_runs_on_fixture(capsys):
    assert nl.main(["--json", str(FIX / "ps_20261009.json"), "--now", "2026-10-09T17:00+09:00",
                    "--team", str(CWS)]) == 0
    out = capsys.readouterr().out
    assert "勝てば突破、負ければ敗退" in out


def test_publication_clock_not_fetch_clock_and_unknown_pitcher():
    now=t('2026-10-07T12:00:00+09:00')
    at=nl.publication_time('2026-10-07','17:00',now)
    assert at==t('2026-10-07T17:00:00+09:00')
    line=nl.choose(as_of(PS,now),'morning',at,CWS)
    assert '明日5時' in line['say'] and '10月8日' in line['screen']
    assert 'Newcomb' not in line['say'] and 'Newcomb' in line['screen']
    assert line['publication_at']==at.isoformat()
    assert set(line['team_ids'])=={CWS,CLE}
    delayed=t('2026-10-07T21:00:00+09:00')
    assert nl.publication_time('2026-10-07','17:00',delayed)==delayed


def test_intake_seven_days_boundary_and_no_regular_season_19h_line():
    from datetime import timedelta
    now=t('2026-10-07T17:00:00+09:00')
    sched=as_of(PS,now)
    game=nl.next_game(sched,CWS,now)[0]
    only={'dates':[{'games':[copy.deepcopy(game)]}]}
    g=only['dates'][0]['games'][0]
    g['gameDate']=(now+timedelta(days=7)).isoformat();g['officialDate']='2026-10-14'
    assert nl.choose(only,'morning',now,CWS)
    g['gameDate']=(now+timedelta(days=7,seconds=1)).isoformat()
    assert nl.choose(only,'morning',now,CWS) is None
    assert nl.choose(REG,'daily',t('2026-09-01T19:00:00+09:00')) is None


def test_acquire_includes_previous_us_date(monkeypatch):
    seen=[]
    monkeypatch.setattr(nl,'fetch_schedule',lambda start,end: seen.append((start,end)) or {'dates':[]})
    assert nl.acquire('morning',t('2026-10-07T17:00:00+09:00'),CWS) is None
    assert seen==[('2026-10-06','2026-10-15')]


if __name__=='__main__':
    raise SystemExit(pytest.main([__file__,'-q','-p','no:cacheprovider']))
