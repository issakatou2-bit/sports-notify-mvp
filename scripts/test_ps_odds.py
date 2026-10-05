#!/usr/bin/env python3
"""2勝0敗・0勝2敗の話題（ps_odds.py）。APIは使わず、固定の試合結果で確かめる。"""
import pathlib
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ps_odds as po  # noqa: E402

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)


def game(pk, date, away, home, winner, state="Final"):
    return {"gamePk": pk, "gameDate": date, "status": {"abstractGameState": state},
            "teams": {"away": {"team": {"id": away, "name": f"T{away}"}, "isWinner": winner == away},
                      "home": {"team": {"id": home, "name": f"T{home}"}, "isWinner": winner == home}}}


def schedule(*games):
    return {"dates": [{"games": list(games)}]}


class History(unittest.TestCase):
    def test_postponed_rows_are_not_counted(self):
        # 2016年のように、延期の行（勝者なし）と本番の行が同じ gamePk で並ぶ
        postponed = game(3, "2016-10-08", 1, 2, None, state="Final")
        postponed["teams"]["away"]["isWinner"] = postponed["teams"]["home"]["isWinner"] = None
        rows = po.season_series(schedule(game(1, "2016-10-06", 1, 2, 2), game(2, "2016-10-07", 1, 2, 2),
                                         postponed, game(3, "2016-10-09", 1, 2, 2)))
        self.assertEqual(len(rows), 1)
        self.assertEqual([w for _, w, _ in rows[0]["games"]], [2, 2, 2])

    def test_summary_counts_comebacks_and_away_losses(self):
        sweep = {"season": 2010, "teams": (1, 2), "names": {1: "A", 2: "B"},
                 "games": [("1", 2, 2), ("2", 2, 2), ("3", 2, 1)]}           # 2勝0敗のまま3連勝
        back = {"season": 2017, "teams": (114, 147), "names": {147: "New York Yankees", 114: "Cleveland Indians"},
                "games": [("1", 114, 114), ("2", 114, 114), ("3", 147, 147), ("4", 147, 147), ("5", 147, 114)]}
        split = {"season": 2012, "teams": (5, 6), "names": {5: "C", 6: "D"},
                 "games": [("1", 5, 6), ("2", 6, 5), ("3", 6, 6)]}           # 1勝1敗は数えない
        s = po.summarize([sweep, back, split])
        self.assertEqual((s["up"], s["held"], s["back"], s["away2"], s["away2_back"]), (2, 1, 1, 2, 1))
        self.assertEqual(s["backs"][0]["team"], "ヤンキース")
        self.assertEqual(s["backs"][0]["over"], "インディアンス")     # 当時の名前


SUMMARY = {"up": 70, "held": 63, "back": 7, "away2": 45, "away2_back": 4,
           "backs": [{"season": 2017, "team": "ヤンキース", "over": "インディアンス", "lost_away": True},
                     {"season": 2015, "team": "ブルージェイズ", "over": "レンジャーズ", "lost_away": False},
                     {"season": 2012, "team": "ジャイアンツ", "over": "レッズ", "lost_away": False}]}

ROW = {"key": "D:135-158", "round": "D", "round_jp": "地区シリーズ", "played": 2, "over": False,
       "teams": [{"id": 158, "name": "ブリュワーズ", "wins": 2, "players": []},
                 {"id": 135, "name": "パドレス", "wins": 0, "players": ["松井裕樹"]}]}
NOW_GAMES = [game(11, "2026-10-04T20:00:00Z", 135, 158, 158),
             game(12, "2026-10-05T00:00:00Z", 135, 158, 158),
             {**game(13, "2026-10-07T01:30:00Z", 158, 135, None, state="Preview"), "seriesGameNumber": 3}]


class Story(unittest.TestCase):
    def test_trailing_japanese_team(self):
        t = po.story(ROW, SUMMARY, NOW_GAMES, NOW, 1995, 2025)
        self.assertEqual(t["title"],
                         "【MLB】松井裕樹のパドレスが地区シリーズ0勝2敗｜ここから勝ち上がったのは70チーム中7 #Shorts")
        items = dict(t["items"])
        self.assertEqual(items["いまのシリーズ"],
                         "ブリュワーズ 2勝0敗 パドレス　第3戦は日本時間10月7日10時30分　パドレスの本拠地")
        self.assertEqual(items["0勝2敗から勝ち上がったチーム"], "70チーム中7チーム（1995〜2025年の地区シリーズ）")
        self.assertEqual(items["敵地で2連敗してから"], "45チーム中4チーム")
        self.assertTrue(t["key"].endswith("_0_2"))

    def test_not_after_the_next_game_starts(self):
        late = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(po.story(ROW, SUMMARY, NOW_GAMES, late, 1995, 2025), {})

    def test_only_japanese_series_and_only_two_nothing(self):
        no_jp = {**ROW, "teams": [{**ROW["teams"][0]}, {**ROW["teams"][1], "players": []}]}
        self.assertEqual(po.story(no_jp, SUMMARY, NOW_GAMES, NOW, 1995, 2025), {})
        one_one = {**ROW, "teams": [{**ROW["teams"][0], "wins": 1}, {**ROW["teams"][1], "wins": 1}]}
        self.assertEqual(po.story(one_one, SUMMARY, NOW_GAMES, NOW, 1995, 2025), {})

    def test_leading_japanese_team(self):
        lead = {**ROW, "key": "D:114-145",
                "teams": [{"id": 145, "name": "ホワイトソックス", "wins": 2, "players": ["村上宗隆"]},
                          {"id": 114, "name": "ガーディアンズ", "wins": 0, "players": []}]}
        games = [game(21, "2026-10-03T17:00:00Z", 145, 114, 145), game(22, "2026-10-05T21:00:00Z", 145, 114, 145),
                 game(23, "2026-10-07T22:00:00Z", 114, 145, None, state="Preview")]
        t = po.story(lead, SUMMARY, games, NOW, 1995, 2025)
        self.assertIn("村上宗隆のホワイトソックスが地区シリーズ2勝0敗", t["title"])
        self.assertEqual(dict(t["items"])["2勝0敗から勝ち上がったチーム"], "70チーム中63チーム（1995〜2025年の地区シリーズ）")
        self.assertTrue(t["key"].endswith("_2_0"))


if __name__ == "__main__":
    unittest.main(argv=["test_ps_odds"])
