"""国内順位とCL順位の混同・選手でなくクラブへの帰属を確認する。"""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import notability_engine as engine


class RankScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / 'preview.json'
        self.data = {'competitions': [
            {'code': 'BL1', 'season': {'year': 2026}, 'last_season_year': 2025,
             'last_season': [{'team': 'Eintracht Frankfurt', 'position': 8},
                             {'team': '1. FSV Mainz 05', 'position': 10}]},
            {'code': 'CL', 'season': {'year': 2026}, 'last_season_year': 2025,
             'last_season': [{'team': 'Eintracht Frankfurt', 'position': 33}]}]}
        self.save()

    def tearDown(self):
        engine._LAST_SEASON_CACHE = None
        self.directory.cleanup()

    def save(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        engine._LAST_SEASON_CACHE = None

    def ranks(self, league):
        return engine._last_season_ranks(str(self.path), league=league)

    def test_competitions_do_not_overwrite_each_other_or_cached_results(self):
        key = engine.normalize_club('Eintracht Frankfurt')
        self.assertEqual(self.ranks('BL1')[key], 8)
        self.assertEqual(self.ranks('CL')[key], 33)
        self.assertEqual(self.ranks('ブンデスリーガ')[key], 8)
        self.data['competitions'].reverse()
        self.save()
        self.assertEqual(self.ranks('BL1')[key], 8)

    def test_unknown_competition_has_no_fallback_rank(self):
        self.assertEqual(self.ranks('unknown'), {})
        self.assertEqual(self.ranks(None), {})

    def test_unverified_season_and_impossible_domestic_rank_are_omitted(self):
        self.data['competitions'][0]['last_season_year'] = 2024
        self.save()
        self.assertEqual(self.ranks('BL1'), {})
        self.data['competitions'][0]['last_season_year'] = 2025
        for value in (33, 0, -1, True, '8', 8.5):
            self.data['competitions'][0]['last_season'][0]['position'] = value
            self.save()
            self.assertNotIn(engine.normalize_club('Eintracht Frankfurt'), self.ranks('BL1'))

    def test_both_clubs_keep_their_own_rank_and_competition_in_prompt_material(self):
        game = engine.Game('fixture', 'BL1', '1', '2', 'Eintracht Frankfurt', '1. FSV Mainz 05')
        ranks = self.ranks('BL1')
        with patch.object(engine, '_last_season_ranks', return_value=ranks):
            text = engine.rule_soccer_last_season(game)[0].text
        self.assertIn('フランクフルト（昨季ブンデスリーガ8位）', text)
        self.assertIn('マインツ（昨季ブンデスリーガ10位）', text)
        game = copy.deepcopy(game)
        game.league = 'CL'
        ranks = self.ranks('CL')
        ranks[engine.normalize_club('Eintracht Frankfurt')] = 3
        with patch.object(engine, '_last_season_ranks', return_value=ranks):
            text = engine.rule_soccer_last_season(game)[0].text
        self.assertIn('CLリーグフェーズ3位', text)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
