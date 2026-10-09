#!/usr/bin/env python3
"""長編の材料（numbers_material）と台本の検査（longform_editorial）の、10/5に見つかった3点。

- 自責0でも失点1なら、点は入っている（松井 10/4: 1.1回 失点1 自責0）
- 死球も走者（佐々木 10/4: 2回 被安打0 四球2 死球1）
- 指標の上下・1位の選手名は英字のまま台詞に渡さない（Logan Henderson など）
APIは使わない。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numbers_material as nm  # noqa: E402
import longform_editorial as le  # noqa: E402

MATSUI = {"type": "pitcher", "ip": "1.1", "er": 0, "r": 1, "hbp": 0, "hits": 1,
          "so": 0, "bb": 1, "holds": 1}
SASAKI = {"type": "pitcher", "ip": "2.0", "er": 0, "r": 0, "hbp": 1, "hits": 0,
          "so": 1, "bb": 2, "holds": 0}


class PitcherLine(unittest.TestCase):
    def test_unearned_run_is_in_the_line_and_reading(self):
        self.assertIn("失点1", nm._line(MATSUI))
        self.assertEqual(nm._numbers(MATSUI)["失点"], 1)
        self.assertTrue(any("点は入っている" in r for r in nm.readings(MATSUI)))

    def test_no_runs_line_is_unchanged(self):
        self.assertNotIn("失点", nm._line(SASAKI))

    def test_hit_by_pitch_is_a_baserunner(self):
        self.assertIn("死球1", nm._line(SASAKI))
        self.assertTrue(any(r.startswith("死球1") for r in nm.readings(SASAKI)))

    def test_batter_runs_without_hits_are_not_called_scoreless(self):
        # 10/8 長編: 大谷は0安打でも失策で生還して1得点
        ohtani = {"name": "大谷翔平", "type": "batter", "headline": "3打数0安打　1四球　1盗塁", "runs": 1}
        self.assertTrue(any(r.startswith("得点1") and "点に結びつかなかった" in r for r in nm.readings(ohtani)))
        self.assertFalse(any(r.startswith("得点") for r in nm.readings(dict(ohtani, runs=0))))


class NeighbourNames(unittest.TestCase):
    def setUp(self):
        nm._kana.table = {"Logan Henderson": "ローガン・ヘンダーソン", "Nobody Known": ""}

    def tearDown(self):
        del nm._kana.table

    def test_known_name_becomes_katakana(self):
        self.assertEqual(nm._person({"name": "Logan Henderson", "shown": "0.84"}),
                         {"name": "ローガン・ヘンダーソン", "shown": "0.84"})

    def test_japanese_player_uses_japanese_name(self):
        self.assertEqual(nm._kana("Munetaka Murakami"), "村上宗隆")

    def test_unknown_name_is_dropped_but_value_kept(self):
        self.assertEqual(nm._person({"name": "Nobody Known", "shown": "0.80"}),
                         {"name": "", "shown": "0.80"})


class LatinNameInScript(unittest.TestCase):
    def check(self, *lines):
        return le.check({"mode": "numbers", "material": {}, "panels": {},
                         "segments": [{"text": t} for t in lines]})

    def test_english_full_name_is_stopped(self):
        got = self.check("1つ上はLogan Hendersonの0.84よ。")
        self.assertEqual(got, ["1行目: 英字の選手名を台詞にしています（Logan Henderson）"])

    def test_acronyms_and_single_words_pass(self):
        self.assertEqual(self.check("WHIPは0.87、OPSも高いの。", "Savantの評価は上位ね。"), [])


if __name__ == "__main__":
    unittest.main(argv=["test_longform_material"])
