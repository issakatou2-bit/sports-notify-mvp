"""Reproduce the 9/12 IL error and verify the distribution gate without a network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pathlib
import sys
import unittest
sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parent.parent)]
import mlb_availability as a
import generate_narration as narration

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.game = {'league': 'MLB', 'home_team_id': '119', 'away_team_id': '146',
                     'start_time_jst': '09/13 05:10', 'is_notable': True,
                     'jp_players': ['大谷翔平', '山本由伸'], 'jp_starters': [],
                     'reasons': [{'tag': 'jp_team', 'text': '大谷翔平が所属', 'weight': 2},
                                 {'tag': 'streak', 'text': 'ドジャースは8連勝中', 'weight': 4}],
                     'score': 6, 'log_notes': ['大谷翔平は連続安打中'],
                     'notification_hook': '大谷翔平が復帰なるか', 'ai_summary': '大谷翔平に期待'}
        self.snapshot = {'roster_type': 'active', 'checked_at': NOW.isoformat(),
                         'teams': {'119': {'players': [{'id': '808967', 'name': 'Yoshinobu Yamamoto'}]}}}

    def test_il_not_in_active_roster_blocks_all_preview_routes(self):
        result = a.prepare([self.game], self.snapshot, NOW)[0]
        self.assertEqual(result['jp_players'], ['山本由伸'])
        self.assertNotIn('大谷', str(result))
        self.assertEqual(result['score'], 4)
        self.assertIn('大谷', str(self.game))  # original inputs retained

    def test_missing_stale_future_and_failed_snapshot_fail_closed(self):
        for delta in (-7, 1):
            snap = deepcopy(self.snapshot)
            snap['checked_at'] = (NOW + timedelta(hours=delta)).isoformat()
            self.assertFalse(a.eligible(self.game, '山本由伸', snap, NOW))
        self.assertFalse(a.eligible(self.game, '山本由伸', {}, NOW))
        self.snapshot['teams']['119']['unavailable'] = True
        self.assertFalse(a.eligible(self.game, '山本由伸', self.snapshot, NOW))

    def test_team_association_and_people_active_are_insufficient(self):
        for snap in ({'active': True}, {**self.snapshot, 'roster_type': '40Man'}):
            self.assertFalse(a.eligible(self.game, '大谷翔平', snap, NOW))

    def test_active_starter_survives_but_il_starter_does_not(self):
        self.game['jp_starters'] = [{'name': '大谷翔平'}, {'name': '山本由伸'}]
        self.assertEqual(a.prepare([self.game], self.snapshot, NOW)[0]['jp_starters'], [{'name': '山本由伸'}])

    def test_player_on_another_team_does_not_qualify(self):
        self.snapshot['teams']['112'] = {'players': [{'name': 'Shohei Ohtani'}]}
        self.assertFalse(a.eligible(self.game, '大谷翔平', self.snapshot, NOW))

    def test_current_active_roster_replaces_old_absence_inference(self):
        self.snapshot['teams']['119']['players'].append({'name': 'Shohei Ohtani'})
        self.assertTrue(a.eligible(self.game, '大谷翔平', self.snapshot, NOW))

    def test_the_actual_bad_intro_is_rejected(self):
        bad = {'date_label': '09/13', 'segments': [{'kind': 'intro',
                'text': 'オオタニ・ショウヘイは5日ぶりの出場なるか。',
                'meta': {'hook': {'at': 0, 'sub': '大谷翔平'}}}]}
        with self.assertRaises(ValueError):
            a.check_narration({'games': [self.game]}, bad, self.snapshot, NOW)
        bad['segments'][0]['text'] = 'オオタニ・ショウヘイに期待です。'
        with self.assertRaises(ValueError):
            a.check_narration({'games': [self.game]}, bad, self.snapshot, NOW)

    def test_historical_result_is_not_a_future_participation_claim(self):
        good = {'date_label': '09/13', 'segments': [{'kind': 'recap', 'text': '大谷翔平の過去の成績'}]}
        a.check_narration({'games': [self.game]}, good, self.snapshot, NOW)

    def test_soccer_inputs_are_preserved(self):
        soccer = {**self.game, 'league': 'プレミアリーグ'}
        self.assertEqual(a.prepare([soccer], {}, NOW), [soccer])

    def test_inactive_pitcher_cannot_reenter_through_soccer_branch(self):
        # The old soccer fallback also consumed MLB jp_team reasons.
        self.game['reasons'] = [{'tag':'jp_team','text':'ドジャースには山本由伸が所属','weight':1},
                                {'tag':'streak','text':'ドジャースは8連勝中','weight':4}]
        snap = {**self.snapshot, 'checked_at': datetime.now(timezone.utc).isoformat()}
        hook = narration.pick_hook([self.game], snap)
        self.assertEqual(hook['sub'], 'ドジャース')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
