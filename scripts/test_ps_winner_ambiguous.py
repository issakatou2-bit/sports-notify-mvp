"""勝者不明の終了試合が他の試合の情勢を止めない。外部通信なし。"""
import contextlib
import copy
import io
import sys
import unittest

import ps_program as p
from test_ps_program import fixture


class WinnerTests(unittest.TestCase):
    def test_ambiguous_final_is_excluded_and_program_continues(self):
        for flags in ((None, None), (False, False), (True, True), (1, False), ('true', False)):
            with self.subTest(flags=flags):
                snap, ev, now = fixture(30)
                games = ev['schedule']['dates'][0]['games']
                good, bad = games[0], games[1]
                for game in (good, bad):
                    game['status']['abstractGameState'] = 'Final'
                good['teams']['home']['isWinner'] = True
                for side, flag in zip(('home', 'away'), flags):
                    bad['teams'][side]['isWinner'] = flag
                original = copy.deepcopy(ev)
                log = io.StringIO()
                with contextlib.redirect_stderr(log):
                    _, accepted = p.validate_source(snap, ev, now)
                    program = p.prepare(snap, ev, 'situation', now)
                self.assertNotIn(bad, accepted)
                self.assertIn(good, accepted)
                self.assertIsNotNone(program)
                row = next(r for r in program['series'] if r['key'] == 'F:117-145')
                self.assertEqual(row['played'], 1)
                self.assertEqual(sum(t['wins'] for t in row['teams']), 1)
                self.assertIn('game_pk=1002', log.getvalue())
                self.assertIn('理由=', log.getvalue())
                self.assertEqual(ev, original)

    def test_normal_games_and_nonfinal_unchanged(self):
        snap, ev, now = fixture(30)
        good = ev['schedule']['dates'][0]['games'][0]
        good['status']['abstractGameState'] = 'Final'
        good['teams']['away']['isWinner'] = True
        good['teams']['home']['isWinner'] = False
        _, games = p.validate_source(snap, ev, now)
        self.assertEqual(games, ev['schedule']['dates'][0]['games'])
        rows = p.series.build(games)
        row = next(r for r in rows if r['key'] == 'F:117-145')
        self.assertEqual(row['played'], 1)
        self.assertEqual(next(t['wins'] for t in row['teams'] if t['id'] == 145), 1)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
