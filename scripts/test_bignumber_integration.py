import copy
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import generate_morning_short as g
import bignumber_render as bn


class Integration(unittest.TestCase):
    def test_default_and_other_slots_unchanged(self):
        narration = {"segments": [{"text": "テスト", "speaker": 3, "meta": {"who": g.ZUNDA}}]}
        with patch.dict(os.environ, {"COLLESPO_PLAYERS_DESIGN": ""}):
            original = copy.deepcopy(narration)
            self.assertEqual(g.bignumber_scenes({}, narration, "players"), [])
            self.assertEqual(narration, original)
        with patch.dict(os.environ, {"COLLESPO_PLAYERS_DESIGN": "bignumber"}):
            self.assertEqual(g.bignumber_scenes({}, narration, "press"), [])
            self.assertEqual(narration, original)

    def test_metan_only_after_successful_validation(self):
        narration = {"segments": [{"text": "テスト", "meta": {}}]}
        with patch.dict(os.environ, {"COLLESPO_PLAYERS_DESIGN": "bignumber"}), \
             patch.object(bn, "scenes_from_morning", return_value=[{"say": "テスト"}]), \
             patch.object(bn, "check_scenes", return_value=[]):
            scenes = g.bignumber_scenes({}, narration, "players")
        self.assertEqual(narration["segments"][0]["speaker"], 2)
        self.assertEqual(scenes[0]["who"], "metan")

    def test_invalid_material_keeps_old_voice(self):
        narration = {"segments": [{"text": "元の声", "speaker": 3}]}
        with patch.dict(os.environ, {"COLLESPO_PLAYERS_DESIGN": "bignumber"}), \
             patch.object(bn, "scenes_from_morning", return_value=[{}]), \
             patch.object(bn, "check_scenes", return_value=["本文不一致"]):
            self.assertEqual(g.bignumber_scenes({}, narration, "players"), [])
        self.assertEqual(narration["segments"][0]["speaker"], 3)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
