#!/usr/bin/env python3
"""PSの話題（ps_story.py）。公式APIは使わず、固定の成績表で確かめる。"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_story as ps  # noqa: E402
import ps_quotes as pq  # noqa: E402
from checks_report import check, section, done  # noqa: E402

ps.season_team = lambda tid: {"runs": 850, "gamesPlayed": 162}
ps.season_hr_leaders = lambda tid, n=2: [("Pete Crow-Armstrong", 45), ("Alex Bregman", 28)]
KANA = {"Pete Crow-Armstrong": "ピート・クロウ＝アームストロング", "Alex Bregman": "アレックス・ブレグマン",
        "Xander Bogaerts": "ザンダー・ボガーツ", "Jed Hoyer": "ジェド・ホイヤー"}
JP = {"Seiya Suzuki": "鈴木誠也"}


def P(ab, h, so=0, hr=0, rbi=0):
    return {"AB": ab, "H": h, "SO": so, "HR": hr, "RBI": rbi, "outs": 0, "ER": 0, "K": 0}


ROW = {"key": "F:112-135", "round": "F", "round_jp": "ワイルドカードシリーズ", "over": True,
       "winner": 135, "teams": [{"id": 135, "name": "パドレス", "wins": 2},
                                {"id": 112, "name": "カブス", "wins": 0}]}
TOT = {112: {"R": 1, "H": 8, "AB": 62, "HR": 0, "SO": 19, "scores": [(0, 8), (1, 4)],
             "players": {"Pete Crow-Armstrong": P(7, 0, 4), "Alex Bregman": P(8, 0, 4),
                         "Seiya Suzuki": P(7, 2)}},
       135: {"R": 12, "H": 21, "AB": 64, "HR": 4, "SO": 13, "scores": [(8, 0), (4, 1)],
             "players": {"Xander Bogaerts": P(8, 4, 0, 1, 2)}}}
QUOTES = [{"team": "カブス", "text": "Jed Hoyer on the Cubs' season: “it feels like we let something slip away”",
           "jp": "Jed Hoyerが今季を振り返る：「チャンスを逃してしまった」", "likes": 22,
           "author": "Meghan Montemurro", "handle": "x.bsky.social", "uri": "at://d/app.bsky.feed.post/1"}]

section("事実から切り口を選ぶ")
t = ps.story(ROW, [1, 2], TOT, dict(KANA), JP, QUOTES)
items = dict(t["items"])
check("題", t["title"].split("｜")[0],
      "【MLB】カブス、打線が沈黙、クロウ＝アームストロング・ブレグマンも不発")
check("得点は今季平均と並べる", items["カブスの得点"], "2試合で計1点　今季は1試合平均5.2点")
check("チーム打率", items["カブスのチーム打率"], "2試合で.129（62打数8安打）　三振19")
check("主力の不振（今季の本塁打つき）", items["ピート・クロウ＝アームストロング"],
      "7打数0安打　4三振（今季45本塁打）")
check("スコアは「対」で読める形", items["シリーズの結果"].endswith("0対8、1対4）"), True)
check("勝った側の主役", items["パドレスの主役"], "ザンダー・ボガーツ　8打数4安打　1本塁打　2打点")
check("日本人選手のシリーズ成績", t["japanese"], [{"name": "鈴木誠也", "line": "7打数2安打（カブス）"}])
check("引用は名前をカタカナにして、二重のかっこにしない",
      items["カブスの番記者の投稿から"], "ジェド・ホイヤーが今季を振り返る：「チャンスを逃してしまった」")
check("出典を持つ", (t["source"]["author"], t["source"]["url"]),
      ("Meghan Montemurro", "https://bsky.app/profile/x.bsky.social/post/1"))

section("言い過ぎない")
calm = {112: dict(TOT[112], R=9, players={"Pete Crow-Armstrong": P(7, 3)}),
        135: dict(TOT[135], players={"Xander Bogaerts": P(8, 2)})}
check("打線が普通で主役もいなければ作らない", ps.story(ROW, [1, 2], calm, dict(KANA), JP, []), {})
check("カタカナにできない名前が残る引用は使わない",
      ps.speakable("Zzyzx Qwerty が語った", {"Zzyzx Qwerty": ""}, {}), "")

section("番記者の投稿を貯める")
from datetime import datetime, timezone  # noqa: E402
now = datetime(2026, 10, 3, tzinfo=timezone.utc)
old = [{"uri": "a", "at": "2026-09-20T00:00:00Z"}, {"uri": "b", "at": "2026-10-02T00:00:00Z"}]
check("10日より古いものは捨て、重複は足さない",
      [x["uri"] for x in pq.merge(old, [{"uri": "b", "at": "2026-10-02T00:00:00Z"},
                                        {"uri": "c", "at": "2026-10-03T00:00:00Z"}], now)],
      ["b", "c"])

sys.exit(done())
