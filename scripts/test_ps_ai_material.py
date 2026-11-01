"""PSはRSの終盤フォームを渡さない。RS/サッカーは既存の入力を保つ。"""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
import notability_engine as ne


GAME={'league':'MLB','matchup':'ドジャース vs パドレス','home_team_id':'119','away_team_id':'135',
      'home_team_name':'ドジャース','away_team_name':'パドレス',
      'reasons':[{'text':'地区シリーズ第1戦。シリーズは0勝0敗。'}]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.standings={'119':ne.Standing('119',1,0,3,wins=99,losses=63,last_ten='7-3',clinched=True),
                        '135':ne.Standing('135',2,9,-2,wins=90,losses=72,last_ten='4-6',clinched=True)}

    def test_each_postseason_round_omits_rs_form(self):
        before=copy.deepcopy(self.standings)
        for kind in ('F','D','L','W'):
            prompt=ne._build_ai_prompt(dict(GAME,game_type=kind),self.standings)
            self.assertNotIn('3連勝中',prompt)
            self.assertNotIn('2連敗中',prompt)
            self.assertNotIn('7-3',prompt)
            self.assertNotIn('4-6',prompt)
            self.assertIn('レギュラーシーズン最終成績 99勝63敗',prompt)
            self.assertIn('シリーズは0勝0敗',prompt)
            context=prompt.split('【チームの状況】')[1].split('【')[0]
            self.assertNotIn('進出を決めている',context)
        self.assertEqual(self.standings,before)

    def test_regular_and_missing_type_keep_existing_input(self):
        for g in (GAME,dict(GAME,game_type='R')):
            prompt=ne._build_ai_prompt(g,self.standings)
            self.assertIn('3連勝中',prompt)
            self.assertIn('直近10試合は7-3',prompt)
            self.assertIn('2連敗中',prompt)

    def test_soccer_uses_soccer_table_even_if_type_is_d(self):
        g=dict(GAME,league='プレミアリーグ',game_type='D')
        self.standings['119'].played=8
        self.standings['135'].played=8
        prompt=ne._build_ai_prompt(g,self.standings)
        self.assertIn('8試合消化',prompt)
        self.assertNotIn('レギュラーシーズン最終成績',prompt)

    def test_missing_table_does_not_invent_current_form(self):
        prompt=ne._build_ai_prompt(dict(GAME,game_type='D'),{})
        self.assertIn('順位表データなし',prompt)
        self.assertNotIn('3連勝中',prompt)


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
