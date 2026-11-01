import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import soccer_story_lines as flow
import soccer_selected_preview as preview
import soccer_result_story as story

ROOT = Path(__file__).resolve().parents[1]

def match(sides, minutes=None):
    minutes = minutes or [str(i*10+5) for i in range(len(sides))]
    goals = [dict(side=s, minute=m, scorer='unknown'+str(i), own_goal=False,
                  japanese_goal=False, japanese_assists=[]) for i, (s,m) in enumerate(zip(sides, minutes))]
    return dict(home=dict(name_en='Olympique de Marseille',name_jp='マルセイユ'),
                away=dict(name_en='Le Havre AC',name_jp='ル・アーブル'),
                score={s:sides.count(s) for s in ('home','away')}, goals=goals,
                goals_complete=True, league_jp='リーグアン', players=[])


class StoryTests(unittest.TestCase):
    def test_four_goal_lead_and_late_reply(self):
        game = match(['home']*4+['away']*3,['5','33','50','60','76','85','90+2'])
        units = flow.flow_units(game)
        self.assertIn('マルセイユが4点を先行しました。',units)
        self.assertIn('ルアーブルが終盤に3点を返しました。',units)
        self.assertFalse(any('unknown' in u for u in units))

    def test_late_boundary_and_added_time(self):
        for minute, late in [('75',False),('75+3',False),('76',True),('90+4',True)]:
            units = flow.flow_units(match(['home','away'],['5',minute]))
            self.assertEqual('終盤' in ''.join(units),late)

    def test_equalizer_reversal_and_clean_sheet(self):
        self.assertIn('逆転しました',''.join(flow.flow_units(match(['home','away','away']))))
        self.assertIn('同点に追いつきました',''.join(flow.flow_units(match(['home','away']))))
        self.assertIn('無失点で勝ちました',''.join(flow.flow_units(match(['home','home']))))
        self.assertIn('無得点',''.join(flow.flow_units(match([]))))

    def test_incomplete_mismatch_duplicate_and_ambiguous_order(self):
        game = match(['home','away'])
        for altered in [dict(game,goals_complete=False),dict(game,score=dict(home=3,away=1)),
                        match(['home','away'],['5','5'])]:
            self.assertEqual(flow.goal_trace(altered),[])
            self.assertNotRegex(''.join(flow.flow_units(altered)),'先制|同点|逆転|返しました|先行')
        game=match(['home','home'],['5','5']);game['goals'][1]['scorer']=game['goals'][0]['scorer']
        self.assertEqual(flow.goal_trace(game),[])

    def test_japanese_goals_and_assists_always_spoken(self):
        game=match(['home']*4)
        game['goals'][0].update(scorer='上田綺世',japanese_goal=True)
        game['goals'][-1]['japanese_assists']=['南野拓実']
        text=''.join(flow.flow_units(game))
        self.assertIn('上田綺世が得点',text)
        self.assertIn('南野拓実がアシスト',text)

    def test_half_time_added_time_and_final_shortening(self):
        game=match(['home']*4,['45+3','46','65','80'])
        game['id']='test'
        game['goals'][0].update(scorer='上田綺世',japanese_goal=True)
        game['goals'][-1]['japanese_assists']=['南野拓実']
        self.assertIn('後半だけで3点',''.join(flow.flow_units(game)))
        segments=[dict(kind=k,text='',meta=dict(event_id='test')) for k in ('followup','followup-detail')]
        with patch.dict(os.environ,dict(COLLESPO_SOCCER_FOCUS='on',COLLESPO_SOCCER_LOOK='v6')):
            shortened=story.shorten_required(segments,dict(games=[game]),3)
        text=''.join(s['text'] for s in shortened)
        self.assertIn('上田綺世が得点',text)
        self.assertIn('南野拓実がアシスト',text)
        self.assertEqual(shortened[0]['meta']['goals'],game['goals'])

    def test_preview_points_and_no_cl_assumption(self):
        game=dict(home_team_name='Liverpool FC',away_team_name='Arsenal FC',
                  competition_code='PL',home_standing=dict(rank=5,points=15),away_standing=dict(rank=2,points=21),cl_line=4)
        self.assertIn('勝点3に縮まります',flow.preview_conclusion(game))
        for points, phrase in [(21,'勝点で並ぶ2チーム'),(18,'と勝点で並びます'),(20,'を勝点で上回ります')]:
            game['home_standing']['points']=points
            self.assertIn(phrase,flow.preview_conclusion(game))
        for bad in (None,True,float('nan'),'15',-1):
            game['home_standing']['points']=bad
            self.assertEqual(flow.preview_conclusion(game),'')

    def test_points_back_saved_float_values_are_oriented_correctly(self):
        game=dict(home_team_name='Liverpool FC',away_team_name='Arsenal FC',
                  competition_code='PL',home_standing=dict(rank=5,points_back=6.0),away_standing=dict(rank=2,points_back=0.0))
        self.assertIn('リバプールが勝てば、アーセナルとの差は勝点3',flow.preview_conclusion(game))
        game['home_standing']['points_back']=0.0
        self.assertIn('勝点で並ぶ2チーム',flow.preview_conclusion(game))
        game['home_standing'].update(points=20,points_back=6.0)
        game['away_standing']['points']=20
        self.assertEqual(flow.preview_conclusion(game),'')
        game['home_standing'].pop('points');game['away_standing'].pop('points')
        for code in ('CL','EL','FAC','DFB','unknown'):
            game['competition_code']=code
            self.assertEqual(flow.preview_conclusion(game),'')

    def test_caption_names_keep_registered_reading(self):
        import club_display_names as names
        game=match(['home'])
        self.assertEqual(flow.caption_names('ル・アーブルが先制しました。',[game]),'ルアーブルが先制しました。')
        self.assertEqual(names.lookup('ル・アーブル')['reading'],names.lookup('ルアーブル')['reading'])

    def test_on_has_no_filler_and_retains_all_goals(self):
        raw=json.loads((ROOT/'data/soccer_games.json').read_text(encoding='utf8'))
        import soccer_selection
        data=soccer_selection.select(raw,availability={})
        result=json.loads((ROOT/'scripts/fixtures/soccer-results/run-38817456251.json').read_text(encoding='utf8'))
        with patch.dict(os.environ,dict(COLLESPO_SOCCER_FOCUS='on',COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4')),patch('soccer_publications.load',return_value={}):
            plan=preview.program(data)
            self.assertNotRegex(''.join(s['text'] for s in plan['narration']['segments']),'どう表れるか|この両チームの対戦|所属クラブの一戦|活躍が期待|出場する場合')
            narr=story.narration(result)
            for seg in narr['segments']:
                if seg['kind']=='followup-detail':
                    game=next(g for g in result['games'] if g['id']==seg['meta']['event_id'])
                    self.assertCountEqual(seg['meta']['goals'],game['goals'])
            import sanity_sources, sanity_material, sanity_internal
            for doc in (plan['narration'],narr):
                sources=sanity_sources.collect([doc])
                self.assertTrue(sources)
                self.assertFalse(sanity_material.check(doc,sources))
                self.assertFalse(sanity_internal.check([doc]))
            import name_reading_guard
            name_reading_guard.validate_dialogue(plan['narration'])
            name_reading_guard.validate_dialogue(narr)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
