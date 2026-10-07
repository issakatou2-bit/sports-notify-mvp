"""表紙と本文の意味を照合。日々変わるデータ・外部APIには依存しない。"""
import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ps_v3_cover as c


def game():
    return {"key": "fixture_game", "game": True, "style": "v2", "label": "地区シリーズ第2戦",
            "items": [["試合の結果", "ホワイトソックス 4対3 ガーディアンズ　敵地で勝利　シリーズはホワイトソックスの2勝0敗"],
                      ["決勝点", "6回表　チェイス・マイドロスのタイムリー"]], "japanese": []}


class Cover(unittest.TestCase):
    def test_score_and_series_are_separate(self):
        t = c.apply(game())
        self.assertEqual(t["v3"]["big"], "4-3")
        self.assertEqual(t["v3"]["chips"][0]["score"], "2-0")
        self.assertEqual(c.check(t), [])

    def test_no_story_changes(self):
        before = game()
        after = c.apply(copy.deepcopy(before))
        self.assertEqual(before["items"], after["items"])
        self.assertEqual(before["label"], after["label"])

    def test_unknown_score_rejected(self):
        t = c.apply(game())
        t["v3"]["big"] = "9-8"
        self.assertTrue(c.check(t))

    def test_ratio_pair_rejected_even_if_numbers_exist(self):
        t = {"items": [["集計", "70チーム中63チーム。7回。1995〜2025年"]]}
        self.assertTrue(c.check(t, {"big": "7", "unit": "/70"}))

    def test_fallback_on_mismatch(self):
        with patch.object(c, "game_v3", return_value={"big": "99"}):
            self.assertEqual(c.apply(game())["style"], "v2")

    def test_reapply_invalidated_v3_resets_style(self):
        t = c.apply(game())
        t["items"] = []
        self.assertEqual(c.apply(t)["style"], "v2")
        self.assertNotIn("v3", t)

    def test_next_game_only_matching_unfinished_series(self):
        row = {"round": "D", "played": 2, "over": False,
               "teams": [{"name": "ホワイトソックス"}, {"name": "ガーディアンズ"}],
               "next": {"game": 3, "day": "10月8日"}}
        t = c.apply(game(), [row])
        self.assertEqual(t["next_game_jp"]["game"], 3)
        for field, value in (("played", 1), ("over", True), ("round", "L")):
            bad = dict(row, **{field: value})
            self.assertNotIn("next_game_jp", c.apply(game(), [bad]))

    def test_odds_ratio_from_material(self):
        t = {"odds": True, "style": "v2", "label": "地区シリーズの2勝0敗",
             "hook": "ホワイトソックスが地区シリーズ2勝0敗",
             "items": [["2勝0敗から勝ち上がったチーム", "70チーム中63チーム（1995〜2025年の地区シリーズ）"]]}
        t = c.apply(t)
        self.assertEqual(t["v3"]["big"], "63")
        self.assertEqual(t["v3"]["unit"], "/70")
        self.assertEqual(c.check(t), [])


if __name__ == "__main__":
    unittest.main()
