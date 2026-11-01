"""話している試合を大きく見せる画面。off は今までと同じ。"""
import os
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT))
import soccer_look
import soccer_readable as readable
import soccer_selected_preview as selected


class FocusTests(unittest.TestCase):
    def test_spoken_japanese_goal_remains_on_the_later_page(self):
        from test_soccer_story_lines import match
        import soccer_results_render as render
        import review_render_v3 as r3
        game=match(['home','away','away','away','home'],['5','38','51','66','83'])
        game['league']='FL1'
        game['goals'][2].update(scorer='町野修斗',japanese_goal=True)
        r3.set_program_clock(None);r3.set_caption('51分に町野修斗が得点。',10,30,speaker=2);r3.set_program_clock(7)
        screen=readable.Screen(render.resolve_clubs(dict(games=[game])),7)
        screen.focus_goals(game,game['goals'][3:],dict(source='ESPN'))
        self.assertEqual({g['minute'] for g in screen.im.info['soccer_goals']},{'51','66','83'})
        self.assertIn('町野修斗',[r['text'] for r in screen.im.info['v3_layout']])
        self.assertEqual(readable.check_frame(screen.im,screen.clubs),[])
        r3.set_caption('',0);r3.set_program_clock(None)

    def test_lillestrom_keeps_its_own_name_and_badge(self):
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        data=json.loads((ROOT/'scripts/fixtures/soccer-daily/20261022.json').read_text(encoding='utf8'))
        for game in data['games']:game.setdefault('season_players',[])
        with mock.patch.dict(os.environ, dict(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SOCCER_TITLE_V2='on')), mock.patch.object(r3,'LOOK','v4'):
            plan=selected.program(data)
            seg=next(s for s in plan['narration']['segments'] if s['meta'].get('home')=='Lillestrøm SK')
            r3.set_caption(seg['text'],20,55,speaker=2);r3.set_program_clock(1.4)
            im=slots.frame(1.4,seg,plan)
            self.assertEqual(plan['clubs']['Lillestrøm SK']['team_en'],'Lillestrøm SK')
            self.assertIn('リールストロム',im.info['semantic_items'])
            self.assertEqual(slots.check_frame(im,plan),[])
            r3.set_program_clock(None)

    def test_long_preview_names_do_not_overlap_kickoff(self):
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        data=json.loads((ROOT/'scripts/fixtures/soccer-daily/20261025.json').read_text(encoding='utf8'))
        for game in data['games']:
            game.setdefault('season_players',[])
        with mock.patch.dict(os.environ, dict(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SOCCER_TITLE_V2='on')), mock.patch.object(r3,'LOOK','v4'):
            plan=selected.program(data)
            for seg in plan['narration']['segments']:
                if seg['kind']=='outro':continue
                r3.set_caption(seg['text'],20,55,speaker=2)
                r3.set_program_clock(1.4)
                im=slots.frame(1.4,seg,plan)
                self.assertEqual(slots.check_frame(im,plan),[])
                self.assertFalse(any(row.get('club_id') and row['role']=='text' and len(row['text'])<3
                                     for row in im.info['v3_layout']))
                self.assertFalse(any(row['role']=='supplement' and 260<=row['box'][1]<390 and len(row['text'])<3
                                     for row in im.info['v3_layout']))
            r3.set_program_clock(None)

    def test_added_time_goal_fits_minute_column(self):
        import copy
        import soccer_results_render as render
        data=json.loads((ROOT/'scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf8'))
        game=copy.deepcopy(data['games'][0])
        goal=copy.deepcopy(game['goals'][0]);goal['minute']='90+5'
        screen=readable.Screen(render.resolve_clubs(data),3)
        screen.focus_goals(dict(game,goals=[goal]),[goal],dict(source='ESPN'))
        self.assertEqual(readable.check_frame(screen.im,screen.clubs),[])

    def test_english_scorer_wraps_at_words(self):
        import copy
        import soccer_results_render as render
        data=json.loads((ROOT/'scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf8'))
        game=copy.deepcopy(data['games'][0]);goal=copy.deepcopy(game['goals'][0])
        goal.update(scorer="Mouhamed N'Diaye",japanese_goal=False)
        screen=readable.Screen(render.resolve_clubs(data),3)
        screen.focus_goals(dict(game,goals=[goal]),[goal],dict(source='ESPN'))
        texts=[row['text'] for row in screen.im.info['v3_layout']]
        self.assertIn('Mouhamed',texts)
        self.assertIn("N'Diaye",texts)
        self.assertNotIn('e',texts)

    def test_focus_is_off_unless_on_and_needs_v6(self):
        for value, want in (('on', True), ('off', False), ('', False), ('true', False)):
            with mock.patch.dict(os.environ, dict(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_FOCUS=value)):
                self.assertEqual(soccer_look.focus(), want)
        with mock.patch.dict(os.environ, dict(COLLESPO_SOCCER_LOOK='v4', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_FOCUS='on')):
            self.assertFalse(soccer_look.focus())

    def test_short_words_never_repeat_club_names(self):
        screen = readable.Screen.__new__(readable.Screen)
        rows = screen.focus_lines(dict(interest=dict(reasons=[
            dict(kind='rank', text='5位リバプール対2位アーセナル、順位差3の直接対決'),
            dict(kind='points', text='勝点差0', gap=0.0),
            dict(kind='cl', text='CL圏の境目 4位A対5位B'),
        ])))
        self.assertEqual(rows, ['順位差3の直接対決', '勝点で並ぶ', 'CL圏の境目'])

    def test_running_score_needs_the_final_score(self):
        screen = readable.Screen.__new__(readable.Screen)
        goals = [dict(minute='5', side='home', scorer='A'), dict(minute='45+2', side='away', scorer='B'),
                 dict(minute='45+2', side='home', scorer='C')]
        game = dict(goals=goals, score=dict(home=2, away=1))
        self.assertEqual(screen.running_scores(game)[('45+2', 'home', 'C')], '2-1')
        self.assertEqual(screen.running_scores(dict(goals=goals, score=dict(home=3, away=1))), {})

    def test_same_minute_same_scorer_shows_no_running_score(self):
        screen = readable.Screen.__new__(readable.Screen)
        goals = [dict(minute='5', side='home', scorer='A'), dict(minute='5', side='home', scorer='A')]
        self.assertEqual(screen.running_scores(dict(goals=goals, score=dict(home=2, away=0))), {})


class SpokenClubTests(unittest.TestCase):
    def test_focus_uses_same_club_name_as_caption(self):
        game = dict(home_team_name='Lillestrøm SK')
        with mock.patch.dict(os.environ, dict(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_FOCUS='on')):
            self.assertEqual(selected.spoken_club(game, 'home'), 'リールストロム')

    def test_foreign_spelling_is_not_read_aloud(self):
        game = dict(home_team_name='Beşiktaş JK', away_team_name='Crystal Palace FC')
        self.assertEqual(selected.spoken_club(game, 'home'), 'ベシクタシュ')
        self.assertRegex(selected.spoken_club(game, 'away'), '[ァ-ヶ]')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
