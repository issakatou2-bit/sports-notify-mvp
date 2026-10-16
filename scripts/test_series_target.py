"""同じ日付の前戦と対象試合、ホーム入れ替わりを公式固定例で確認。"""
import copy
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notability_engine as ne  # noqa: E402
FIX=json.loads((Path(__file__).parent/'fixtures/site-series-20261015.json').read_text(encoding='utf-8'))
class TargetSeries(unittest.TestCase):
    def get(self, data, target='849810'):
        response=Mock();response.json.return_value=data
        with patch.object(ne.requests,'get',return_value=response):
            return ne.fetch_series_context('119','158','2026-10-15',target_game_id=target)
    def test_cross_midnight_uses_target_id_not_previous_date(self):
        out=self.get(FIX)
        self.assertEqual(out['series_game_number'],4)
        self.assertEqual(out['games_in_series'],7)
        self.assertEqual((out['home_wins_in_stretch'],out['away_wins_in_stretch']),(0,3))
    def test_missing_target_does_not_reuse_previous_game_number(self):
        data=copy.deepcopy(FIX);data['dates'][0]['games']=[g for g in data['dates'][0]['games'] if g['gamePk']!=849810]
        self.assertIsNone(self.get(data))
    def test_target_result_and_later_finals_not_counted_as_prior(self):
        data=copy.deepcopy(FIX)
        for g in data['dates'][0]['games']:
            if g['gameDate']>='2026-10-16T00:00:00Z':
                g['status']['abstractGameCode']='F'
                g['teams']['home']['score']=10;g['teams']['away']['score']=0
        out=self.get(data)
        self.assertEqual((out['home_wins_in_stretch'],out['away_wins_in_stretch']),(0,3))
if __name__=='__main__':unittest.main(argv=[__file__])
