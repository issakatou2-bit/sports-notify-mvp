"""注目理由あり/なし、日本人優先、欠測/別期間/誤検出と画面・音声の一致。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
os.environ.update(COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_DUO='off')
import soccer_match_interest as interest
import soccer_slots_v4 as slots
import soccer_v5_cards as cards
import name_reading_guard as readings
import review_render_v3 as r3


class Interest(unittest.TestCase):
    def setUp(self):
        self.cases=json.loads((ROOT/'scripts/fixtures/soccer-interest/cases.json').read_text(encoding='utf8'))['games']
        self.addCleanup(r3.set_caption,'',0,0);self.addCleanup(r3.set_program_clock,None)

    def test_reasons_when_present_none_when_missing(self):
        picked=interest.decide(self.cases[0])
        self.assertEqual([r['text'] for r in picked['reasons']],['順位差2の直接対決','勝点差1'])
        self.assertEqual(interest.decide(self.cases[1]),dict(reasons=[],player=None))

    def test_japanese_eligible_player_prioritized_only_one(self):
        game=self.cases[2];player=interest.decide(game)['player']
        self.assertEqual(player['name'],'鎌田大地');self.assertEqual(player['assists'],3)
        game=copy.deepcopy(game);game['season_players'][0]['assists']=2
        self.assertEqual(interest.decide(game)['player']['name'],'ハーランド')
        readings.validate_query('期待選手はハーランドです。',{'accent_phrases':[{'moras':[{'text':'ハーランドデス'}]}]})

    def test_stale_future_last_game_stats_and_injury_not_expectation(self):
        for update in ({'as_of':'2026-09-24T10:00:00Z'},{'as_of':'2026-10-13T10:00:00Z'},
                       {'scope':'game'},{'out':True},{'goals':None,'assists':None},{'goals':-1},
                       {'goals':True},{'goals':3.2},{'minutes':0},{'club':'不明FC'},{'name':'未登録太郎'}):
            game=copy.deepcopy(self.cases[2]);game['season_players']=game['season_players'][:1]
            game['season_players'][0].update(update)
            self.assertIsNone(interest.decide(game)['player'],update)

    def test_title_cl_relegation_require_supplied_line_and_points(self):
        game=copy.deepcopy(self.cases[1]);game.update(home_standing=dict(rank=1,points=13),away_standing=dict(rank=2,points=12))
        self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'title')
        game.update(home_standing=dict(rank=4,points=12),away_standing=dict(rank=5,points=11))
        self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'rank')
        game['cl_line']=4;self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'cl')
        game.update(home_standing=dict(rank=16,points=3),away_standing=dict(rank=17,points=2),relegation_line=17)
        self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'relegation')
        game.pop('relegation_line');game.pop('cl_line')
        self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'rank')

    def test_derby_table_exact_pair_not_same_city_guess(self):
        game=copy.deepcopy(self.cases[1]);game.update(home_team_name='Manchester City FC',away_team_name='Manchester United FC')
        self.assertEqual(interest.decide(game)['reasons'][0]['kind'],'derby')
        game.update(home_team_name='Fulham FC',away_team_name='Crystal Palace FC')
        self.assertFalse(interest.decide(game)['reasons'])

    def test_form_only_five_valid_results(self):
        game=copy.deepcopy(self.cases[1]);game['home_standing']={'last_five':['L','D','W','W','W']}
        self.assertEqual(interest.decide(game)['reasons'][0]['text'],'ホーム側 3連勝')
        for form in (['W']*4,['W']*6,['W','W','?',None,'W']):
            game['home_standing']['last_five']=form;self.assertFalse(interest.decide(game)['reasons'])

    def test_previous_season_pair_and_orientation(self):
        game=copy.deepcopy(self.cases[1]);game['season']=2026
        game['previous_season_h2h']=dict(season=2025,home_team_name=game['away_team_name'],away_team_name=game['home_team_name'],score=dict(home=2,away=1))
        self.assertIn('今回のホーム側が1対2',interest.decide(game)['reasons'][0]['text'])
        game['previous_season_h2h']['season']=2026;self.assertFalse(interest.decide(game)['reasons'])
        game['previous_season_h2h'].update(season=2025,away_team_name='ユベントス')
        self.assertFalse(interest.decide(game)['reasons'])

    def test_nullable_or_invalid_rank_and_points_do_not_make_facts(self):
        game=copy.deepcopy(self.cases[1])
        for value in (None,'不明',{'rank':False,'points':True},{'rank':-1,'points':float('nan')}):
            game.update(home_standing=value,away_standing=value)
            self.assertFalse(interest.decide(game)['reasons'])

    def test_actual_pipeline_same_fact_on_screen_and_spoken(self):
        data=dict(generated_at='2026-10-11T09:00:00Z',games=[self.cases[2]])
        plan=slots.program('preview',data);seg=plan['narration']['segments'][1]
        self.assertIn('鎌田大地',seg['text']);self.assertIn('3アシスト',seg['text'])
        self.assertEqual(seg['meta']['interest']['player']['assists'],3)
        for t in (0,.35,1.5,3,18):
            r3.set_program_clock(0);r3.set_caption(seg['text'],20,100,speaker=2);r3.set_program_clock(t)
            im=slots.frame(t,seg,plan);self.assertFalse(slots.check_frame(im,plan))
            self.assertTrue(any('3アシスト' in row['text'] for row in im.info['v3_layout']))
        readings.validate_dialogue(plan['narration'])

    def test_actual_saved_fpl_source_and_cold_data_are_distinguished(self):
        import preview_soccer_v5
        data=preview_soccer_v5.saved_preview_material();plan=slots.program('preview',data)
        stars=[s for s in plan['narration']['segments'] if s['meta'].get('expectation_name')]
        self.assertEqual(len(stars),1)
        self.assertEqual(stars[0]['meta']['expectation_name'],'鎌田大地')
        self.assertIn('FPL',stars[0]['meta']['source'])
        self.assertIn('今季FPL集計',stars[0]['text'])
        no_reasons=[s for s in plan['narration']['segments'] if s['kind']=='preview' and not s['meta']['interest']['reasons']]
        self.assertTrue(no_reasons)

    def test_default_b_and_explicit_a(self):
        from PIL import Image
        club=cards.original.load_clubs()['Liverpool FC']
        with patch.dict(os.environ):
            os.environ.pop('COLLESPO_SOCCER_BADGE',None)
            im=Image.new('RGB',(200,60));cards.scarf(im,(5,5,195,45),club)
            self.assertEqual(im.info['v5_contrasts'][0]['variant'],'B')
        with patch.dict(os.environ,COLLESPO_SOCCER_BADGE='A'):
            im=Image.new('RGB',(200,60));cards.scarf(im,(5,5,195,45),club)
            self.assertEqual(im.info['v5_contrasts'][0]['variant'],'A')

    def test_same_clubs_different_day_bind_to_their_own_game(self):
        first=copy.deepcopy(self.cases[2]);second=copy.deepcopy(first)
        second.update(game_id='next-day',start_time_utc='2026-10-13T14:00:00Z')
        for p in second['season_players']:p['as_of']='2026-10-12T10:00:00Z'
        second['season_players'][0]['assists']=4
        plan=slots.program('preview',dict(generated_at='2026-10-11T09:00:00Z',games=[first,second]))
        segments=[s for s in plan['narration']['segments'] if s['kind']=='preview']
        self.assertEqual([s['meta']['interest']['player']['assists'] for s in segments],[3,4])
        self.assertEqual([s['meta']['game_id'] for s in segments],[first['game_id'],'next-day'])
        duplicate=copy.deepcopy(first);duplicate['game_id']='duplicate'
        plan=slots.program('preview',dict(generated_at='2026-10-11T09:00:00Z',games=[first,duplicate]))
        self.assertTrue(all('interest' not in s['meta'] for s in plan['narration']['segments'] if s['kind']=='preview'))


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
