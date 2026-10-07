#!/usr/bin/env python3
"""日本人投手の圧巻の投球の話題（ps_spotlight.py）。APIは使わず、固定の記録で確かめる。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ps_spotlight as sp  # noqa: E402


def pitch(kind, call, mph=95.0):
    return {"isPitch": True, "details": {"type": {"description": kind}, "call": {"description": call}},
            "pitchData": {"startSpeed": mph}}


FEED = {"liveData": {"linescore": {"teams": {"away": {"runs": 3}, "home": {"runs": 1}}},
        "plays": {"allPlays": [
            {"matchup": {"pitcher": {"id": 1}}, "result": {"eventType": "strikeout"},
             "playEvents": [pitch("Four-Seam Fastball", "Called Strike", 97.9),
                            pitch("Splitter", "Swinging Strike"), pitch("Splitter", "Swinging Strike")]},
            {"matchup": {"pitcher": {"id": 1}}, "result": {"eventType": "field_out"},
             "playEvents": [pitch("Curveball", "Ball"), pitch("Four-Seam Fastball", "In play, out(s)")]},
            {"matchup": {"pitcher": {"id": 2}}, "result": {"eventType": "strikeout"},
             "playEvents": [pitch("Slider", "Swinging Strike", 99.0)]}]}}}
LINE = {"inningsPitched": "7.0", "hits": 4, "runs": 1, "earnedRuns": 1, "strikeOuts": 10,
        "baseOnBalls": 1, "numberOfPitches": 98, "note": "(W, 1-0)"}
BOX = {"teams": {"away": {"team": {"id": 119, "name": "Los Angeles Dodgers"},
                          "players": {"ID1": {"person": {"id": 1, "fullName": "Yoshinobu Yamamoto"},
                                              "stats": {"pitching": LINE}}}},
                 "home": {"team": {"id": 144, "name": "Atlanta Braves"}, "players": {}}}}
GAME = {"gamePk": 849819, "gameType": "D", "seriesGameNumber": 3, "gameDate": "2026-10-06T22:00:00Z"}


class Spotlight(unittest.TestCase):
    def test_counts_only_this_pitcher(self):
        s = sp.pitch_stats(FEED, 1)
        self.assertEqual(sum(s["types"].values()), 5)
        self.assertEqual((s["whiff"], s["csw"]), (2, 3))
        self.assertEqual(s["ks"]["Splitter"], 1)
        self.assertAlmostEqual(s["top_mph"], 97.9)

    def test_notable(self):
        self.assertTrue(sp.notable(LINE))
        self.assertTrue(sp.notable({"inningsPitched": "4.0", "earnedRuns": 3, "strikeOuts": 9}))
        self.assertFalse(sp.notable({"inningsPitched": "5.2", "earnedRuns": 0, "strikeOuts": 6}))

    def test_story(self):
        t = sp.story(GAME, BOX, FEED, 1, "山本由伸",
                     {"gameDate": "2026-10-07T22:00:00Z", "seriesGameNumber": 4})
        self.assertEqual(t["title"], "【MLB】山本由伸が7回1失点10奪三振｜最速157.6キロ・空振り2 #Shorts")
        items = dict(t["items"])
        self.assertEqual(items["この試合の投球"], "7回　4安打　1失点　10奪三振　1四球（98球）")
        self.assertEqual(items["試合"], "ドジャース 3対1 ブレーブス　地区シリーズ第3戦　山本由伸が勝ち投手")
        self.assertEqual(items["次の試合"], "日本時間10月8日7時　地区シリーズ第4戦")
        self.assertEqual(t["style"], "v3")
        self.assertTrue(t["spotlight"])

    def test_unknown_pitch_type_skips(self):
        feed = {"liveData": {**FEED["liveData"], "plays": {"allPlays": [
            {"matchup": {"pitcher": {"id": 1}}, "result": {}, "playEvents": [pitch("Eephus", "Ball")]}]}}}
        self.assertEqual(sp.story(GAME, BOX, feed, 1, "山本由伸"), {})


if __name__ == "__main__":
    unittest.main(argv=["test_ps_spotlight"])
