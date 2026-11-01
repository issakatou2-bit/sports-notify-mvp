import sys
import unittest
import asset_policy as policy

class Selection(unittest.TestCase):
    def test_named_official_regular_only(self):
        good=dict(title='大谷翔平の本塁打',source='MLB Stats API',game_type='R',items=[('成績','54本塁打')])
        self.assertTrue(policy.selectable('season_player_1',good,{'大谷翔平'}))
        for changes in ({'title':'大谷翔平の順位表'},{'title':'大谷翔平の所属球団まとめ'},{'title':'ドジャースのまとめ'},{'game_type':'P'},{'source':'海外報道'},{'items':[('球団の結末','ポストシーズン進出')]}):
            self.assertFalse(policy.selectable('season_player_1',{**good,**changes},{'大谷翔平'}))
        for key in ('team_1','season_team_1','venue_1'):
            self.assertFalse(policy.selectable(key,good,{'大谷翔平'}))

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
