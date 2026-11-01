#!/usr/bin/env python3
"""連勝・敵地での勝ちの話題（ps_momentum.py）。APIは使わず、固定の試合結果で確かめる。"""
import pathlib
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import next_asset  # noqa: E402
import ps_momentum as pm  # noqa: E402

CWS, HOU, CLE = 145, 117, 114
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def game(pk, date, away, home, score=None, game_type="D", n=None):
    a, h = (score or (None, None))
    g = {"gamePk": pk, "gameDate": date, "gameType": game_type,
         "status": {"abstractGameState": "Final" if score else "Preview"},
         "teams": {"away": {"team": {"id": away, "name": f"T{away}"}, "score": a,
                            "isWinner": bool(score) and a > h},
                   "home": {"team": {"id": home, "name": f"T{home}"}, "score": h,
                            "isWinner": bool(score) and h > a}}}
    if n:
        g["seriesGameNumber"] = n
    return g


GAMES = [game(1, "2026-09-29T18:00:00Z", CWS, HOU, (6, 3), "F"),
         game(2, "2026-09-30T18:00:00Z", CWS, HOU, (7, 3), "F"),
         game(3, "2026-10-04T17:00:00Z", CWS, CLE, (3, 0)),
         game(4, "2026-10-05T21:00:00Z", CWS, CLE, (4, 3)),
         game(5, "2026-10-07T20:00:00Z", CLE, CWS, None, n=3)]
TEAM = {"id": CWS, "name": "ホワイトソックス", "players": ["村上宗隆"]}
SERIES = {"key": "D:114-145", "round_jp": "地区シリーズ", "need": 3,
          "teams": [{"id": CWS, "wins": 2}, {"id": CLE, "wins": 0}]}
RECORDS = [(2025, 60, 102), (2024, 41, 121), (2023, 61, 101), (2022, 81, 81)]


def box(tid, ab, h, hr, rbi):
    side = {"team": {"id": tid}, "players": {"ID1": {"person": {"fullName": "Munetaka Murakami"},
            "stats": {"batting": {"plateAppearances": ab + 1, "atBats": ab, "hits": h,
                                  "homeRuns": hr, "rbi": rbi}}}}}
    return {"teams": {"away": side, "home": {"team": {"id": 0}, "players": {}}}}


class Parts(unittest.TestCase):
    def test_streak_counts_road_wins(self):
        s = pm.streak(GAMES, CWS)
        self.assertEqual((s["streak"], s["road"], s["wins"], s["losses"]), (4, 4, 4, 0))

    def test_streak_stops_at_a_loss(self):
        lost = [game(9, "2026-09-28T18:00:00Z", HOU, CWS, (5, 1), "F")] + GAMES
        lost[1] = game(1, "2026-09-29T18:00:00Z", CWS, HOU, (2, 3), "F")
        s = pm.streak(lost, CWS)
        self.assertEqual((s["streak"], s["wins"], s["losses"]), (3, 3, 2))

    def test_history_only_when_there_is_something_to_say(self):
        self.assertEqual(pm.history_line(RECORDS), "2023年から3年続けて100敗以上（2024年は41勝121敗）")
        self.assertEqual(pm.history_line([(2025, 70, 92), (2024, 75, 87), (2023, 70, 92)]),
                         "2023年から3年続けて負け越し")
        self.assertIsNone(pm.history_line([(2025, 90, 72), (2024, 60, 102)]))


class Story(unittest.TestCase):
    def make(self, now=NOW, team=TEAM):
        boxes = [box(CWS, 4, 1, 0, 0), box(CWS, 4, 1, 1, 2), box(CWS, 4, 1, 0, 1), box(CWS, 4, 1, 0, 1)]
        return pm.story(team, SERIES, GAMES, boxes, {}, RECORDS, now, {}, [], {},
                        {"Munetaka Murakami": "村上宗隆"}, "84勝78敗")

    def test_cws_four_road_wins(self):
        t = self.make()
        self.assertEqual(t["title"], "【MLB】村上宗隆のホワイトソックスがポストシーズン4連勝｜4試合すべて敵地 #Shorts")
        items = dict(t["items"])
        self.assertEqual(items["4試合のスコア"], "6対3・7対3・3対0・4対3　得点20・失点9")
        self.assertEqual(items["ここまでの歩み"],
                         "2023年から3年続けて100敗以上（2024年は41勝121敗）　今季は84勝78敗")
        self.assertEqual(items["村上宗隆のポストシーズン"], "4試合で16打数4安打　1本塁打　4打点")
        self.assertEqual(items["次の試合"], "日本時間10月8日5時　本拠地で地区シリーズ第3戦　勝てば突破")
        self.assertTrue(t["momentum"])
        self.assertEqual(t["key"], "season_momentum_D_114_145_145")

    def test_not_after_the_next_game_starts(self):
        self.assertEqual(self.make(now=datetime(2026, 10, 7, 20, 1, tzinfo=timezone.utc)), {})

    def test_only_teams_with_japanese_players(self):
        self.assertEqual(self.make(team={**TEAM, "players": []}), {})

    def test_picker_skips_after_the_next_game_starts(self):
        spec = {"next_game": "2026-10-07T20:00:00Z"}
        self.assertFalse(next_asset.started(spec, NOW))
        self.assertTrue(next_asset.started(spec, datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)))
        self.assertFalse(next_asset.started({}))


class HomeClinch(unittest.TestCase):
    """10/6 MLB.com「本拠地での突破は120年ぶり？」。公式の試合結果で、本拠地で決めた最後のシリーズを遡る。"""
    def test_clinch_is_the_last_game_of_a_won_series(self):
        ws = {"dates": [{"games": [
            {**game(1, "1906-10-13T19:00:00Z", CWS, 112, (8, 6), "W"), "seriesDescription": "World Series"},
            {**game(2, "1906-10-14T19:00:00Z", 112, CWS, (3, 8), "W"), "seriesDescription": "World Series"}]}]}
        self.assertEqual(pm.clinches(ws, CWS), [("1906-10-14", "World Series", True)])
        self.assertEqual(pm.clinches(ws, 112), [])                        # 負けた側は無し

    def test_unfinished_series_is_not_a_clinch(self):
        self.assertEqual(pm.clinches({"dates": [{"games": GAMES[2:]}]}, CWS), [])

    def test_search_goes_back_until_a_home_clinch(self):
        road = {"dates": [{"games": [{**g, "seriesDescription": "Wild Card"} for g in GAMES[:2]]}]}
        home = {"dates": [{"games": [
            {**game(1, "1906-10-14T19:00:00Z", 112, CWS, (3, 8), "W"), "seriesDescription": "World Series"}]}]}
        calls = []

        def get(path, **p):
            calls.append(p["season"])
            return home if p["season"] == 1906 else road if p["season"] == 2026 else {}
        self.assertEqual(pm.last_home_clinch(CWS, 2026, get), (1906, "World Series"))
        self.assertEqual(calls[0], 2026)

    def test_line_only_when_long_ago(self):
        self.assertEqual(pm.home_clinch_line((1906, "World Series"), 2026),
                         "本拠地でのシリーズ突破は、1906年のワールドシリーズ優勝以来120年ぶり")
        self.assertIsNone(pm.home_clinch_line((2015, "AL Division Series"), 2026))
        self.assertIsNone(pm.home_clinch_line(None, 2026))

    def test_title_uses_it(self):
        boxes = []
        t = pm.story(TEAM, SERIES, GAMES, boxes, {}, RECORDS, NOW, {}, [], {}, {}, "84勝78敗",
                     (1906, "World Series"))
        self.assertEqual(t["title"],
                         "【MLB】村上宗隆のホワイトソックスがポストシーズン4連勝｜勝てば本拠地で120年ぶりの突破 #Shorts")
        self.assertEqual(dict(t["items"])["勝てば"], "本拠地でのシリーズ突破は、1906年のワールドシリーズ優勝以来120年ぶり")


if __name__ == "__main__":
    unittest.main(argv=["test_ps_momentum"])
