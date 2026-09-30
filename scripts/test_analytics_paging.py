"""Offline checks for full ledger coverage and preserving earlier snapshots."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import fetch_analytics as analytics


def vid(i):
    return f'v{i:010d}'


def page(start, count):
    return {'columnHeaders': [{'name': 'video'}, {'name': 'views'}],
            'rows': [[vid(i), 1] for i in range(start, start + count)]}


class CoverageTests(unittest.TestCase):
    def read(self, pages, known=()):
        api = MagicMock()
        api.reports.return_value.query.return_value.execute.side_effect = pages
        rows = analytics.video_rows(api, date(2026, 8, 23), date(2026, 9, 20), known)
        return rows, api.reports.return_value.query.call_args_list

    def test_includes_low_view_videos_beyond_top_200(self):
        known = [vid(i) for i in range(305)]
        rows, calls = self.read([page(0, 200), page(200, 100), page(300, 5)], known)
        self.assertEqual(len(rows), 305)
        self.assertEqual(rows[-1], {'video': vid(304), 'views': 1})
        self.assertNotIn('filters', calls[0].kwargs)
        self.assertEqual(calls[1].kwargs['filters'], 'video==' + ','.join(known[200:300]))
        self.assertEqual(calls[2].kwargs['filters'], 'video==' + ','.join(known[300:]))
        self.assertTrue(all(c.kwargs['sort'] == '-views' for c in calls))
        self.assertTrue(all(c.kwargs['startDate'] == '2026-08-23' for c in calls))

    def test_missing_activity_is_not_filled_with_zero(self):
        rows, calls = self.read([page(0, 1), {}], [vid(0), vid(1)])
        self.assertEqual(rows, [{'video': vid(0), 'views': 1}])
        self.assertEqual(len(calls), 2)

    def test_empty_and_short_reports_without_ledger_stop(self):
        for count in (0, 1, 199):
            rows, calls = self.read([page(0, count)])
            self.assertEqual((len(rows), len(calls)), (count, 1))

    def test_duplicate_or_unrequested_rows_fail(self):
        for unexpected in (page(0, 1), page(3, 1)):
            with self.assertRaises(ValueError):
                self.read([page(0, 1), unexpected], [vid(0), vid(1)])

    def test_bad_columns_do_not_make_incomplete_records(self):
        for bad in ({'rows': [['x', 1]]},
                    {'columnHeaders': [{'name': 'video'}], 'rows': [['x', 1]]}):
            with self.assertRaises(ValueError):
                self.read([bad])

    def test_both_ledgers_are_deduplicated_and_invalid_ids_ignored(self):
        daily = {'daily': {'today': {'video_id': vid(1)}, 'bad': {'video_id': '../bad'}}}
        assets = {'assets': {'topic': {'video_id': vid(2)}, 'same': {'video_id': vid(1)}}}
        with patch.object(analytics, 'load', side_effect=[daily, assets]):
            self.assertEqual(analytics.known_video_ids(), [vid(1), vid(2)])

    def test_later_batch_failure_preserves_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'analytics.json'
            original = json.dumps({'days': {'earlier': {'videos': []}}})
            target.write_text(original, encoding='utf-8')
            api = MagicMock()
            api.reports.return_value.query.return_value.execute.side_effect = [
                page(0, 200), RuntimeError('supplement unavailable')]
            with patch.object(analytics, 'client', return_value=api), \
                 patch.object(analytics, 'known_video_ids', return_value=[vid(201)]), \
                 patch.object(analytics, '_report') as report, \
                 patch.object(sys, 'argv', ['fetch_analytics', '--out', str(target)]):
                analytics.main()
            report.assert_called_once()
            self.assertEqual(target.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
