"""Fixed season-boundary cases and source-to-screen regressions."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

import ps_editorial as policy
import generate_ps_preview as preview
from check_rendered_claims import check_ps_preview

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)


def fixtures():
    snapshot = {'date': '2026-09-28', 'phase': 'regular', 'teams': {}}
    games = []
    for i in range(4):
        lid = 103 if i < 2 else 104
        a, h, b = 100 + 3 * i, 101 + 3 * i, 102 + 3 * i
        for tid in (a, h, b):
            snapshot['teams'][str(tid)] = {'name': f'球団{tid}', 'clinched': True}

        def team(tid):
            return {'id': tid, 'name': f'球団{tid}', 'abbreviation': f'T{tid}', 'league': {'id': lid}}

        game = {'gamePk': 1000 + i, 'gameType': 'F', 'seriesGameNumber': 1,
                'officialDate': '2026-09-29', 'gameDate': '2026-09-30T00:00:00Z',
                'status': {'abstractGameState': 'Preview', 'startTimeTBD': False},
                'teams': {'away': {'team': team(a)}, 'home': {'team': team(h)}}}
        bye = {'gamePk': 2000 + i, 'gameType': 'D', 'seriesGameNumber': 1,
               'officialDate': '2026-10-03', 'gameDate': '2026-10-03T07:33:00Z',
               'status': {'abstractGameState': 'Preview', 'startTimeTBD': True},
               'teams': {'away': {'team': {'id': 9999, 'name': f'T{a}/T{h}'}}, 'home': {'team': team(b)}}}
        games += [game, bye]
    return snapshot, {'dates': [{'games': games}]}


class SeasonBoundary(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.schedule = fixtures()

    def context(self, now=NOW):
        return policy.editorial(self.snapshot, self.schedule, now, 'https://statsapi.mlb.com/example')

    def test_confirmed_before_opening_uses_preview_not_race(self):
        c = self.context()
        self.assertEqual(c['stage'], 'bracket_preview')
        self.assertEqual(len(c['matchups']), 4)
        text = preview.metadata(c)['snippet']
        self.assertIn('組み合わせ確定', text['title'])
        self.assertNotIn('進出争い', str(text))
        self.assertNotIn('きょう動いた', str(text))
        self.assertNotIn('今日動いた', str(text))
        self.assertEqual(policy.apply(self.snapshot, c)['changes'], [])

    def test_qualification_does_not_prove_bracket(self):
        self.schedule['dates'][0]['games'][0]['teams']['away']['team']['name'] = 'AL 6 Winner'
        c = self.context()
        self.assertEqual(c['stage'], 'bracket_pending')
        self.assertEqual(c['matchups'], [])
        self.assertIn('確認中', preview.metadata(c)['snippet']['title'])

    def test_underfilled_field_remains_race(self):
        self.schedule = {'dates': []}
        self.snapshot['teams'].pop('100')
        self.assertEqual(self.context()['stage'], 'race')

    def test_midnight_utc_does_not_use_official_date_as_jst(self):
        c = self.context()
        self.assertEqual(c['matchups'][0]['first_game']['label'], '9/30 09:00')

    def test_tbd_placeholder_timestamp_is_never_published(self):
        c = self.context()
        self.assertEqual(c['matchups'][0]['ds_first']['label'], '10/4 時刻未定')
        self.assertIsNone(c['matchups'][0]['ds_first']['start_utc'])
        self.assertNotIn('16:33', preview.metadata(c)['snippet']['description'])

    def test_first_game_live_changes_editorial_subject(self):
        self.schedule['dates'][0]['games'][0]['status']['abstractGameState'] = 'Live'
        self.assertEqual(self.context()['stage'], 'series')

    def test_opening_instant_changes_editorial_subject(self):
        context = policy.editorial(dict(self.snapshot, date='2026-09-30'), self.schedule,
                                   datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc), 'source')
        self.assertEqual(context['stage'], 'series')

    def test_stale_snapshot_does_not_fall_back_to_old_race(self):
        self.snapshot['date'] = '2026-09-27'
        with self.assertRaisesRegex(ValueError, '当日'):
            self.context()

    def test_disagreement_between_qualifiers_and_fixtures_blocks(self):
        self.snapshot['teams']['100']['clinched'] = False
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.context()

    def test_wrong_league_blocks(self):
        self.schedule['dates'][0]['games'][0]['teams']['away']['team']['league']['id'] = 104
        with self.assertRaisesRegex(ValueError, 'リーグ'):
            self.context()

    def test_ambiguous_winner_path_blocks(self):
        bye = deepcopy(self.schedule['dates'][0]['games'][1])
        self.schedule['dates'][0]['games'][3] = bye
        with self.assertRaises(ValueError):
            self.context()

    def test_valid_real_drawn_text_matches_proof(self):
        data = policy.apply(self.snapshot, self.context())
        errors, output, limits = check_ps_preview(data, '2026-09-28')
        self.assertEqual(errors, [])
        self.assertEqual(len(output), 5)
        self.assertIn('対象外', limits[0])

    def test_tampered_path_fails_even_if_draws_consistently(self):
        data = policy.apply(self.snapshot, self.context())
        data['editorial']['matchups'][0]['bye']['name'] = '別の球団'
        errors, _, _ = check_ps_preview(data, '2026-09-28')
        self.assertTrue(any('保存した公式日程' in e for e in errors))

    def test_conditional_game_not_announced_as_guaranteed(self):
        text = ''.join(s['text'] for s in preview.cards(self.context()))
        self.assertIn('第3戦は必要な場合のみ', text)

    def test_new_preview_requires_review_but_existing_formats_keep_running(self):
        for stage in ('bracket_preview', 'bracket_pending'):
            snapshot = {'editorial': {'stage': stage}}
            for value in ('', 'false', '1', None):
                self.assertTrue(policy.preview_review_required(snapshot, value))
            self.assertFalse(policy.preview_review_required(snapshot, 'true'))
        for stage in ('race', 'series', 'offseason'):
            self.assertFalse(policy.preview_review_required({'editorial': {'stage': stage}}))
        self.assertFalse(policy.preview_review_required({}))

    def test_retrieval_time_alone_is_not_a_new_edition(self):
        context = self.context()
        later = dict(context, date_jst='2026-09-29', retrieved_at='2026-09-29T01:00:00+00:00')
        self.assertEqual(policy.edition_key(context), policy.edition_key(later))
        later = deepcopy(context)
        later['matchups'][0]['first_game']['time_jst'] = '10:00'
        self.assertNotEqual(policy.edition_key(context), policy.edition_key(later))


if __name__ == '__main__':
    unittest.main(argv=['test_ps_editorial'])
