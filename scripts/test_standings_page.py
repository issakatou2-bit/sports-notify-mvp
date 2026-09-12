"""Protect the meaning of standings, missing data and failed refreshes."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import generate_standings_page as page


def fixture():
    data = {}
    for d, did in enumerate(page.ORDER):
        data[did] = [dict(team={'id': 1000 + 5*d + n, 'name': f'Team-{d}-{n}'},
                         season='2026', divisionRank=str(n), divisionLeader=n == 1,
                         wildCardRank=str(d % 3 * 4 + n - 1) if n > 1 else None,
                         gamesPlayed=146, wins=80, losses=66, winningPercentage='.548',
                         gamesBack='-' if n == 1 else '1.5',
                         wildCardGamesBack='+1.5', lastUpdated='2026-09-10T20:00:00Z')
                     for n in range(1, 6)]
    return data


class StandingsTests(unittest.TestCase):
    def test_wildcard_uses_api_ranks_and_excludes_division_leaders(self):
        data = fixture()
        rows = page.wildcard_rows(data, page.ORDER[:3])
        self.assertEqual(len(rows), 12)
        self.assertEqual([page.rank_number(t['wildCardRank']) for t in rows], list(range(1, 13)))
        self.assertTrue(all(t['divisionRank'] != '1' for t in rows))
        # A tied API leader flag must not leak into the wild-card list.
        data[201][1]['divisionLeader'] = True
        self.assertEqual(len(page.wildcard_rows(data, page.ORDER[:3])), 11)

    def test_missing_is_not_zero_or_a_leader(self):
        row = dict(team={'id': 9999, 'name': '<unsafe>'}, divisionRank='2')
        result = page.table_html([row], 'Example', 2026)
        self.assertIn('&lt;unsafe&gt;', result)
        self.assertNotIn('<unsafe>', result)
        self.assertNotIn('<td>0</td>', result)
        self.assertIn('未取得', result)
        self.assertEqual(page.cell(0), '0')
        self.assertEqual(page.cell('-'), '-')

    def test_wildcard_gap_sign_and_cutoff_are_preserved(self):
        rows = page.wildcard_rows(fixture(), page.ORDER[:3])
        result = page.table_html(rows, 'League', 2026, wildcard=True)
        self.assertIn('+1.5', result)
        self.assertEqual(result.count('class="cutoff"'), 1)
        self.assertNotIn('class="cutoff"', page.table_html(rows, 'League', 2020, wildcard=True))

    def test_remaining_is_a_reference_and_missing_stays_unknown(self):
        self.assertEqual(page.remaining({'gamesPlayed': 146}, 2026), '16')
        self.assertEqual(page.remaining({'gamesPlayed': 162}, 2026), '0')
        for value in (None, True, -1, 163, '146'):
            self.assertEqual(page.remaining({'gamesPlayed': value}, 2026), '未取得')
        self.assertEqual(page.remaining({'gamesPlayed': 60}, 2020), '未取得')

    def test_partial_duplicate_and_wrong_season_rejected(self):
        original = fixture()
        page.validate_data(original, 2026)
        partial = copy.deepcopy(original)
        partial.pop(201)
        duplicate = copy.deepcopy(original)
        duplicate[201][1]['team']['id'] = duplicate[201][0]['team']['id']
        for data, season in ((partial, 2026), (duplicate, 2026), (original, 2025)):
            with self.assertRaises(ValueError):
                page.validate_data(data, season)

    def test_source_dates_are_distinct_from_fetch_date(self):
        data = fixture()
        data[201][0]['lastUpdated'] = '2026-09-11T21:00:00Z'
        data[201][1].pop('lastUpdated')
        text = page.render_page(data, 2026, datetime(2026, 9, 12, 1, tzinfo=timezone.utc))
        self.assertIn('2026/09/12 10:00 日本時間', text)
        self.assertIn('2026/09/11 05:00〜09/12 06:00', text)
        self.assertIn('1球団は更新日時未取得', text)
        self.assertIn('リアルタイム順位ではありません', text)
        self.assertEqual(text.count('<table class="std-table">'), 8)

    def test_failed_fetch_does_not_destroy_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'standings.html'
            target.write_text('previous valid page', encoding='utf-8')
            with patch.object(sys, 'argv', ['standings', '--out', str(target)]), \
                 patch.object(page, 'fetch', side_effect=RuntimeError('unavailable')):
                self.assertEqual(page.main(), 1)
            self.assertEqual(target.read_text(encoding='utf-8'), 'previous valid page')


if __name__ == '__main__':
    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=0).result
    print('ALL OK' if result.wasSuccessful() else 'FAILURES')
    raise SystemExit(0 if result.wasSuccessful() else 1)
