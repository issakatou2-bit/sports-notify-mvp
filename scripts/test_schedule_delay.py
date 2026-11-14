"""収録された遅延時刻と期限境界を再現する。通信・公開・実績書換えなし。"""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import buffer_daily as buffer
import healthcheck as health
import missing_kinds as missing
import publication_clock as clock
import soccer_national as national
import soccer_national_publish as publish
import test_soccer_national as fixtures


def instant(value):
    return datetime.fromisoformat(value)


class Watchdog(unittest.TestCase):
    def test_delayed_check_and_recovery_see_same_previous_evening(self):
        for value, day in [('2026-10-23T01:38:01+09:00', '2026-10-22'),
                           ('2026-11-03T06:23:47+09:00', '2026-11-02')]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                now = instant(value)
                self.assertEqual(clock.target_day(now), day)
                path = Path(directory)/'records.json'
                path.write_text('{}', encoding='utf8')
                # 手元の試合記録に左右されないよう、試合のあった日として固定する。
                with patch.object(health, 'load', return_value={}), \
                        patch.object(health, '_mlb_games', return_value=1), \
                        patch.object(health, 'EXPECTED_DAILY', [('morning_press', '報道', '18:00', '0000-00-00')]), \
                        patch.object(health, 'OPTIONAL_DAILY', []), \
                        patch.object(missing.post_common, 'DAILY_LINEUP', [('morning_press', '報道', '', '18:00')]):
                    lines, count, skipped, seen = health.check_videos(day, only_past=True, now=now)
                    self.assertEqual(count, 1)
                    self.assertIn('出ていない', lines[0])
                    self.assertEqual(missing.missing(path=str(path), now=now), [('morning_press', '報道', '18:00')])
                    path.write_text(json.dumps({'morning_press': {day: {'video_id': 'already_sent'}}}), encoding='utf8')
                    self.assertEqual(missing.missing(day, str(path), now=now), [])

    def test_noon_boundary_and_publication_grace(self):
        self.assertEqual(clock.target_day(instant('2026-11-03T11:59:59+09:00')), '2026-11-02')
        self.assertEqual(clock.target_day(instant('2026-11-03T12:00:00+09:00')), '2026-11-03')
        self.assertFalse(clock.publication_due('2026-11-03', '18:00', instant('2026-11-03T18:44:59+09:00')))
        self.assertTrue(clock.publication_due('2026-11-03', '18:00', instant('2026-11-03T18:45:00+09:00')))

    def test_recovery_cli_accepts_pinned_date(self):
        with patch.object(sys, 'argv', ['missing', '--date', '2026-11-02']), \
                patch.object(missing, 'missing', return_value=[]) as query, patch('sys.stderr', new=io.StringIO()):
            self.assertEqual(missing.main(), 0)
        query.assert_called_once_with(day='2026-11-02')

    def test_workflow_pins_date_before_check_and_reuses_it(self):
        import yaml
        document = yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/watchdog.yml').read_text(encoding='utf8'))
        steps = document['jobs']['check']['steps']
        resolve = next(i for i, step in enumerate(steps) if step.get('id') == 'edition')
        check = next(i for i, step in enumerate(steps) if step.get('id') == 'check')
        self.assertLess(resolve, check)
        commands = [step.get('run', '') for step in steps]
        for script in ['healthcheck.py', 'missing_kinds.py']:
            command = next(line for line in commands if script in line)
            self.assertIn('--date "${{ steps.edition.outputs.day }}"', command)


class Social(unittest.TestCase):
    def test_delayed_press_is_due_but_sent_ledger_still_excludes_it(self):
        for value, day in [('2026-11-03T05:30:37+09:00', '2026-11-02'),
                           ('2026-11-04T03:03:59+09:00', '2026-11-03')]:
            with self.subTest(value=value):
                now = instant(value)
                record = dict(video_id='abcdefghijk', published_at=day+'T06:30:00+00:00', publish_at=day+'T09:00:00+00:00')
                run = dict(id=42, head_branch='main', path='.github/workflows/morning_recap.yml',
                           conclusion='success', event='schedule', repository={'full_name': buffer.REPO},
                           created_at=day+'T06:00:00+00:00', updated_at=day+'T07:00:00+00:00')
                records = {'morning_press': {day: record}}
                self.assertEqual(buffer.select_record(run, records, now, 'morning_press', late_edition=True), (day, record))
                with self.assertRaises(ValueError):
                    buffer.select_record(run, records, now, 'morning_press')
                ledger = SimpleNamespace(data={'deliveries': {}})
                with patch.object(buffer, 'datetime') as frozen, \
                        patch.object(buffer.Path, 'read_text', return_value=json.dumps(records)), \
                        patch.object(buffer, 'Ledger', return_value=ledger), \
                        patch.object(buffer, 'SOURCES', {'morning_press': buffer.SOURCES['morning_press']}), \
                        patch.object(buffer, 'day_runs', return_value=[run]) as queries:
                    frozen.now.return_value = now
                    frozen.fromisoformat.side_effect = instant
                    self.assertEqual(buffer.due(['twitter'], late_edition=True), [('morning_press', 42)])
                    queries.reset_mock()
                    ledger.data['deliveries'][day+':morning_press:twitter'] = {'state': 'sent'}
                    self.assertEqual(buffer.due(['twitter'], late_edition=True), [])
                    queries.assert_not_called()

    def test_daily_excluded_and_noon_closes_previous_edition(self):
        before = instant('2026-11-03T11:59:59+09:00')
        self.assertIn('2026-11-02', buffer.eligible_editions(before, 'morning_press', True))
        self.assertEqual(buffer.eligible_editions(before, 'daily', True), ['2026-11-03'])
        self.assertEqual(buffer.eligible_editions(instant('2026-11-03T12:00:00+09:00'), 'morning_press', True), ['2026-11-03'])


class NationalWindows(unittest.TestCase):
    def choose(self, kickoff, at, ledger=None):
        game = national.match(fixtures.event(date=kickoff))
        summary = {'header': {'competitions': [{'status': {'type': {'completed': True}}}]}}
        with patch.object(national, 'result', return_value={'mode': 'result'}), \
                patch.object(national, 'preview', return_value={'mode': 'preview'}):
            return national.choose([game], {'627': {}, '205': {}}, {}, instant(at), ledger or {}, lambda ident: summary)

    def test_morning_result_until_noon(self):
        kickoff = '2026-11-17T13:10:00+00:00'
        for at in ['2026-11-18T10:00:00+09:00', '2026-11-18T11:59:59+09:00']:
            with self.subTest(at=at):
                self.assertEqual(self.choose(kickoff, at)['mode'], 'result')
        self.assertIsNone(self.choose(kickoff, '2026-11-18T12:00:00+09:00'))

    def test_evening_result_fallback_until_noon_and_no_duplicate(self):
        kickoff = '2026-11-14T10:15:00+00:00'
        # 0時〜7時も待たずに出す（11/14 本人「定時の回と違うので普通に投稿していい」）。
        early = self.choose(kickoff, '2026-11-15T06:59:59+09:00')
        self.assertEqual((early['mode'], early['publish_at']), ('result', '2026-11-15T07:20:00+09:00'))
        for at in ['2026-11-15T07:00:00+09:00', '2026-11-15T11:16:38+09:00', '2026-11-15T11:59:59+09:00']:
            with self.subTest(at=at):
                self.assertEqual(self.choose(kickoff, at)['mode'], 'result')
        self.assertIsNone(self.choose(kickoff, '2026-11-15T12:00:00+09:00'))
        ledger = {'soccer_national': {'2026-11-14': {'national_mode': 'result', 'national_event_id': 'test'}}}
        self.assertIsNone(self.choose(kickoff, '2026-11-15T11:16:38+09:00', ledger))

    def test_preview_accepts_delayed_evening_until_22(self):
        kickoff = '2026-11-14T10:15:00+00:00'
        data = self.choose(kickoff, '2026-11-13T21:34:13+09:00')
        self.assertEqual(data['mode'], 'preview')
        self.assertEqual(data['publish_at'], '2026-11-13T21:55:00+09:00')
        self.assertEqual(self.choose(kickoff, '2026-11-13T21:59:59+09:00')['mode'], 'preview')
        self.assertIsNone(self.choose(kickoff, '2026-11-13T22:00:00+09:00'))


class NationalReservation(unittest.TestCase):
    def setUp(self):
        self.switch = patch.dict(os.environ, {'COLLESPO_SOCCER_NATIONAL': 'on'})
        self.switch.start()
        self.addCleanup(self.switch.stop)
        self.data = {'mode': 'result', 'publish_at': '2026-11-14T22:00:00+09:00'}

    def test_workflow_uses_national_upload_and_keeps_sanity_contract(self):
        import sanity_workflows
        root = Path(__file__).resolve().parents[1]
        source = (root/'.github/workflows/soccer_national.yml').read_text(encoding='utf8')
        self.assertIn('scripts/soccer_national_publish.py --upload', source)
        self.assertTrue(sanity_workflows.PUBLISHER.search('scripts/soccer_national_publish.py --upload'))
        self.assertFalse(sanity_workflows.errors(root))

    def test_late_same_day_refreshes_and_early_keeps_original(self):
        self.assertEqual(publish.validate(self.data, instant('2026-11-14T22:23:45+09:00')),
                         instant('2026-11-14T22:25:45+09:00'))
        self.assertEqual(publish.validate(self.data, instant('2026-11-14T21:00:00+09:00')),
                         instant(self.data['publish_at']))
        self.assertEqual(self.data['publish_at'], '2026-11-14T22:00:00+09:00')

    def test_result_crosses_midnight_and_preview_kickoff_remains_blocked(self):
        # 結果は定時の回ではないので、0時を越えても予約する（11/14 本人）。試合から36時間を過ぎたら止める。
        for at, expected in [('2026-11-15T00:00:00+09:00', '2026-11-15T00:02:00+09:00'),
                             ('2026-11-14T23:58:00+09:00', '2026-11-15T00:00:00+09:00')]:
            with self.subTest(at=at):
                self.assertEqual(publish.validate(self.data, instant(at)), instant(expected))
        old = dict(self.data, game={'start_utc': '2026-11-14T10:15:00+00:00'})
        with self.assertRaises(ValueError):
            publish.validate(old, instant('2026-11-16T08:00:00+09:00'))
        preview = dict(self.data, mode='preview', game={'start_utc': '2026-11-14T22:02:00+09:00'})
        with self.assertRaises(ValueError):
            publish.validate(preview, instant('2026-11-14T22:00:00+09:00'))

    def test_upload_recomputes_at_resolver_and_restores_common_uploader(self):
        import upload_youtube as uploader
        argv, resolver = sys.argv, uploader.resolve_publish_at
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'material.json'
            raw = json.dumps(self.data)
            path.write_text(raw, encoding='utf8')
            def fake_upload():
                # 共通入口の元予約一致検査を保ち、長い制作後の解決時刻を確認する。
                self.assertEqual(sys.argv[-2:], ['--publish-at', '22:00'])
                actual = uploader.resolve_publish_at('22:00')
                self.assertEqual(instant(actual), instant('2026-11-14T22:42:30+09:00'))
                return 0
            with patch.object(publish, 'datetime') as frozen, patch.object(uploader, 'main', side_effect=fake_upload):
                frozen.now.side_effect = [instant('2026-11-14T22:20:00+09:00'), instant('2026-11-14T22:40:30+09:00')]
                self.assertEqual(publish.main(['--upload', '--kind', 'soccer_national', '--games', str(path)]), 0)
            self.assertEqual(path.read_text(encoding='utf8'), raw)
        self.assertIs(sys.argv, argv)
        self.assertIs(uploader.resolve_publish_at, resolver)

    def test_upload_restores_resolver_when_day_changes_before_send(self):
        import upload_youtube as uploader
        resolver = uploader.resolve_publish_at
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'material.json'
            path.write_text(json.dumps(self.data), encoding='utf8')
            with patch.object(publish, 'datetime') as frozen, \
                    patch.object(uploader, 'main', side_effect=lambda: uploader.resolve_publish_at('22:00')):
                frozen.now.side_effect = [instant('2026-11-14T23:50:00+09:00'), instant('2026-11-15T00:01:00+09:00')]
                # 送る直前に日付が変わっても、結果は取り直した時刻で出す。共通の予約処理は元に戻す。
                self.assertEqual(instant(publish.upload(['--kind', 'soccer_national', '--games', str(path)])),
                                 instant('2026-11-15T00:03:00+09:00'))
            with patch.object(publish, 'datetime') as frozen,                     patch.object(uploader, 'main', side_effect=lambda: uploader.resolve_publish_at('21:00')):
                frozen.now.side_effect = [instant('2026-11-14T23:50:00+09:00')]
                with self.assertRaises(ValueError):
                    publish.upload(['--kind', 'soccer_national', '--games', str(path)])
        self.assertIs(uploader.resolve_publish_at, resolver)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
