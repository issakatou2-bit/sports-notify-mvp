"""訂正の材料の直し方（直す前の文が一致しなければ止まる）と、置いてある直し方の形。"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import correct_video as cv

ROOT = Path(__file__).resolve().parents[1]


class Correct(unittest.TestCase):
    def test_edit_needs_the_old_text(self):
        t = {"items": [["決勝点", "誤り"]], "title": "題"}
        cv.apply_edits(t, [{"where": ["items", 0, 1], "from": "誤り", "to": "正しい"}])
        self.assertEqual(t["items"][0][1], "正しい")
        with self.assertRaises(ValueError):
            cv.apply_edits(t, [{"where": ["title"], "from": "別の題", "to": "x"}])

    def test_every_fix_file_has_what_the_workflow_needs(self):
        for path in (ROOT / "data" / "corrections").glob("*.json"):
            fix = json.loads(path.read_text(encoding="utf-8"))
            for key in ("kind", "topic", "old_video", "material", "edits", "reason"):
                self.assertIn(key, fix, path.name)
            for e in fix["edits"]:
                self.assertNotEqual(e["from"], e["to"], path.name)


class Fresh(unittest.TestCase):
    def test_finds_a_finished_later_game_in_the_same_series(self):
        def fetch(url):
            if "gamePk=" in url:
                return {"dates": [{"games": [{"gamePk": 3, "gameType": "D", "officialDate": "2026-10-06",
                                              "gameDate": "2026-10-07T01:30:00Z",
                                              "teams": {"home": {"team": {"id": 135}}, "away": {"team": {"id": 158}}}}]}]}
            return {"dates": [{"games": [
                {"gamePk": 3, "gameDate": "2026-10-07T01:30:00Z", "status": {"abstractGameState": "Final"},
                 "teams": {"home": {"team": {"id": 135}}, "away": {"team": {"id": 158}}}},
                {"gamePk": 4, "gameDate": "2026-10-08T02:00:00Z", "status": {"abstractGameState": "Final"},
                 "teams": {"home": {"team": {"id": 135}}, "away": {"team": {"id": 158}}}},
                {"gamePk": 9, "gameDate": "2026-10-08T05:00:00Z", "status": {"abstractGameState": "Final"},
                 "teams": {"home": {"team": {"id": 135}}, "away": {"team": {"id": 119}}}}]}]}
        self.assertEqual(cv.later_games(3, fetch), [4])


class Superseded(unittest.TestCase):
    def test_game_topic_is_skipped_after_the_next_game_starts(self):
        import next_asset
        from unittest import mock
        with mock.patch("series_check.later_games", return_value=[4]):
            self.assertTrue(next_asset.superseded({"game": True, "game_pk": 3}))
        with mock.patch("series_check.later_games", return_value=[]):
            self.assertFalse(next_asset.superseded({"game": True, "game_pk": 3}))
        with mock.patch("series_check.later_games", side_effect=OSError("down")):
            self.assertTrue(next_asset.superseded({"game": True, "game_pk": 3}))
        self.assertFalse(next_asset.superseded({"key": "legend_141"}))


if __name__ == "__main__":
    unittest.main(argv=[__file__])
