"""話している試合を大きく見せる画面。off は今までと同じ。"""
import os
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
    def test_foreign_spelling_is_not_read_aloud(self):
        game = dict(home_team_name='Beşiktaş JK', away_team_name='Crystal Palace FC')
        self.assertEqual(selected.spoken_club(game, 'home'), 'ベシクタシュ')
        self.assertRegex(selected.spoken_club(game, 'away'), '[ァ-ヶ]')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
