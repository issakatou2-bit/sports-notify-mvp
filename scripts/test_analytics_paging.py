"""Offline checks for full ledger coverage and preserving earlier snapshots."""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import fetch_analytics as analytics
from analytics_snapshots import video_snapshots


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
            previous = {'2026-11-24': {'videos': [{'video': vid(0)}]}}
            target.write_text(json.dumps({'days': previous}), encoding='utf-8')
            api = MagicMock()
            batches = iter([page(0, 200), RuntimeError('supplement unavailable')])

            def query(**params):
                request = MagicMock()
                if params['dimensions'] == 'video':
                    result = next(batches)
                    if isinstance(result, Exception):
                        request.execute.side_effect = result
                    else:
                        request.execute.return_value = result
                elif params['dimensions'] == 'deviceType':
                    request.execute.return_value = report('deviceType,views,estimatedMinutesWatched',
                                                          [['MOBILE', 9, 2.5]])
                else:
                    request.execute.return_value = {}
                return request

            api.reports.return_value.query.side_effect = query
            with patch.object(analytics, 'datetime', wraps=datetime) as clock, \
                 patch.object(analytics, 'client', return_value=api), \
                 patch.object(analytics, 'known_video_ids', return_value=[vid(201)]), \
                 patch.object(analytics, '_report') as log, \
                 patch.object(sys, 'argv', ['fetch_analytics', '--out', str(target)]):
                clock.now.return_value = datetime(2026, 11, 25, tzinfo=analytics.JST)
                analytics.main()
            log.assert_called_once()
            store = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(video_snapshots(store), previous)
            saved = store['days']['2026-11-25']
            self.assertNotIn('videos', saved)
            self.assertEqual(saved['breakdowns']['last_28_days']['device']['status'], 'ok')


def report(columns, rows):
    return {'columnHeaders': [{'name': name} for name in columns.split(',')], 'rows': rows}


class BreakdownTests(unittest.TestCase):
    def test_partial_failure_persists_other_reports_and_video_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'analytics.json'
            end = date(2026, 11, 25)
            prior = {(end - timedelta(days=n)).isoformat(): {'videos': []} for n in range(1, 91)}
            target.write_text(json.dumps({'days': prior}), encoding='utf-8')
            api = MagicMock()
            traffic = 'insightTrafficSourceType'
            responses = {
                'day': report('day,views', [['2026-11-22', 12]]),
                'video': page(0, 1),
                traffic: report(f'estimatedMinutesWatched,{traffic},views',
                                [[8.5, 'SHORTS', 30], [1, 'YT_CHANNEL', 4]]),
                'subscribedStatus': report('subscribedStatus,views,averageViewPercentage',
                                           [['UNSUBSCRIBED', 20, 63.5]]),
                'country': report('country,views,estimatedMinutesWatched', [['JP', 20, 7.2]]),
            }

            def query(**params):
                request = MagicMock()
                dimension = params['dimensions']
                if dimension == 'deviceType':
                    request.execute.side_effect = TimeoutError('private details')
                elif dimension == 'day' and params['metrics'] != analytics.DAILY_METRICS:
                    request.execute.return_value = {}
                else:
                    request.execute.return_value = responses.get(dimension, {})
                return request

            api.reports.return_value.query.side_effect = query
            with patch.object(analytics, 'datetime', wraps=datetime) as clock, \
                 patch.object(analytics, 'client', side_effect=[api, None]), \
                 patch.object(analytics, 'known_video_ids', return_value=[]), \
                 patch.object(sys, 'argv', ['fetch_analytics', '--no-curves', '--out', str(target)]):
                clock.now.return_value = datetime(2026, 11, 25, tzinfo=analytics.JST)
                self.assertEqual(analytics._run(), 0)

            store = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(len(store['days']), 90)
            self.assertNotIn(min(prior), store['days'])
            self.assertEqual(store['days'][max(prior)], prior[max(prior)])
            self.assertEqual(store['daily']['2026-11-22']['views'], 12)
            saved = store['days'][end.isoformat()]
            self.assertEqual(saved['videos'], [{'video': vid(0), 'views': 1, 'title': ''}])
            self.assertEqual(saved['sources'], {})
            breakdowns = saved['breakdowns']
            self.assertEqual(breakdowns['impressions']['status'], 'unavailable')
            self.assertEqual(breakdowns['registration_source']['status'], 'unavailable')
            week, month = (breakdowns[f'last_{n}_days'] for n in (7, 28))
            self.assertEqual(week['range'], ['2026-11-16', '2026-11-22'])
            self.assertEqual(month['range'], ['2026-10-26', '2026-11-22'])
            self.assertEqual(week['traffic_source']['rows'][1],
                             {traffic: 'YT_CHANNEL', 'views': 4, 'estimatedMinutesWatched': 1})
            self.assertEqual(month['traffic_source'], week['traffic_source'])
            self.assertEqual(month['subscribed_status']['rows'][0]['averageViewPercentage'], 63.5)
            self.assertEqual(month['country']['rows'][0]['country'], 'JP')
            self.assertEqual(month['device'], {'status': 'error', 'reason': 'TimeoutError'})
            self.assertEqual(month['demographics'], {'status': 'empty', 'rows': []})

            calls = [call.kwargs for call in api.reports.return_value.query.call_args_list]
            self.assertEqual([(c['startDate'], c['endDate'], c['metrics']) for c in calls
                              if c['dimensions'] == traffic],
                             [(w['range'][0], w['range'][1], 'views,estimatedMinutesWatched')
                              for w in (week, month)])
            country = next(c for c in calls if c['dimensions'] == 'country')
            self.assertEqual((country['sort'], country['maxResults']), ('-views', 10))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
