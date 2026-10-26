"""得点・アシスト限定、月曜予約、既定オフ、投稿前後の記録を保存材料で検査。"""
import copy
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import soccer_goal_short as goal
import soccer_jp_week as week
import soccer_now as now
import soccer_week_publish as release

ROOT = Path(__file__).resolve().parents[1]
CLOCK = datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)  # 月曜7:30 JST


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK.astimezone(tz) if tz else CLOCK.replace(tzinfo=None)


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        self.summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        self.clock = now.results.utc('2026-09-20T17:15:00Z')

    def items(self, **kwargs):
        return goal.build(self.boards, self.summaries, self.clock, **kwargs)[0]

    def test_saved_goal_one_match_one_video(self):
        data = self.items()
        self.assertEqual([d['games'][0]['id'] for d in data], ['401876452'])
        self.assertEqual(len(data[0]['games']), 1)
        self.assertEqual(data[0]['players'][0]['goals'], 1)

    def test_assist_only_unknown_and_zero(self):
        data = self.items()[0]
        for goals, assists, expected in ((0, 1, 1), (None, 1, 1), (0, 0, 0), (None, None, 0)):
            with self.subTest(goals=goals, assists=assists):
                d = copy.deepcopy(data)
                d['games'][0]['players'][0].update(goals=goals, assists=assists)
                with patch.object(now, 'build', return_value=([d, d], [])):
                    self.assertEqual(len(self.items()), expected)

    def test_three_hour_freshness_and_pending(self):
        item = self.items()[0]
        end = now.results.utc(item['games'][0]['finished_utc'])
        for offset, expected in ((-1, False), (180*60, True), (180*60+1, False)):
            with self.subTest(offset=offset):
                items, _ = goal.build(self.boards, self.summaries, end+now.timedelta(seconds=offset))
                self.assertEqual(bool(items), expected)
        for status in ('pending', 'uploaded'):
            self.assertEqual(self.items(receipts={'401876452': {'status': status}}), [])

    def test_no_end_time_or_unfinished(self):
        for boards in self.boards.values():
            for event in boards.get('events', []):
                event['competitions'][0]['status']['type']['completed'] = False
        self.assertEqual(self.items(), [])

    def test_same_initial_different_full_given_name(self):
        row = dict(athlete=dict(fullName='Kodai Sano', lastName='Sano'))
        self.assertIsNone(now.results.resolve_player([row], 'Kaishu Sano'))
        self.assertEqual(now.results.resolve_player([row], 'Kodai Sano'), row)

    def test_off_makes_no_fetch_or_render(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', ['goal', '--plan']), \
                patch.object(goal, 'live_material') as fetch, patch.object(goal, 'save') as save, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            goal.main()
        fetch.assert_not_called()
        save.assert_not_called()
        self.assertEqual(output.getvalue().strip(), 'go=0')

    def test_plan_never_publishes(self):
        with patch.dict(os.environ, {'COLLESPO_SOCCER_GOAL_SHORT': 'on'}, clear=True), \
                patch.object(sys, 'argv', ['goal', '--plan']), patch.object(goal, 'datetime') as clock, \
                patch.object(goal, 'live_material', return_value=(self.boards, self.summaries)), \
                patch.object(now, 'publish') as publish, patch('sys.stdout', new_callable=io.StringIO) as output:
            clock.now.return_value = self.clock
            goal.main()
        publish.assert_not_called()
        self.assertEqual(output.getvalue().strip().splitlines()[-1], 'go=1')

    def test_sample_cannot_enter_live_path_even_when_on(self):
        with patch.dict(os.environ, {'COLLESPO_SOCCER_GOAL_SHORT': 'on'}), \
                patch.object(sys, 'argv', ['goal', '--sample']), \
                patch.object(goal, 'live_material') as fetch, patch.object(now, 'publish') as publish, \
                patch.object(goal, 'save', return_value='sample.mp4') as save, patch('sys.stdout', new_callable=io.StringIO):
            goal.main()
        fetch.assert_not_called()
        publish.assert_not_called()
        self.assertTrue(save.call_args.args[0]['sample_fictional'])

    def test_registered_cups_use_single_day_fetch_and_final_rosters(self):
        import soccer_extra_fixtures as fixtures
        import soccer_selection as selection
        event = copy.deepcopy(next(e for b in self.boards.values() for e in b['events'] if str(e['id']) == '401876452'))
        # 現所属リーグがPLでもカップ戦を照合する。UTC日付をまたぐ8時間。
        clock = now.results.utc('2026-09-21T00:15:00Z')
        event['date'] = '2026-09-20T18:00:00Z'
        competition = dict(code='CL', espn='uefa.champions')
        with patch.object(selection, 'competitions', return_value=[competition]), \
                patch.object(fixtures, 'fetch_board', return_value={'events': [event]}) as fetch, \
                patch.object(now.results, 'fetch_json', return_value={'fixture': True}) as summary:
            boards, summaries = goal.live_material(clock, {})
            self.assertEqual(list(boards), ['CL_20260921'])
            self.assertIn('401876452', summaries)
            fetch.assert_called_once_with(competition, date(2026, 9, 20), days=2)
            self.assertIn('/uefa.champions/summary?', summary.call_args.args[0])
            summary.reset_mock()
            goal.live_material(clock, {'401876452': {'status': 'pending'}})
            summary.assert_not_called()

    def test_render_uses_morning_script_audio_fit_and_renderer(self):
        directory = ROOT/'build/codex/tmp'/('soccer-save-test-'+uuid4().hex)
        with patch.object(goal.subprocess, 'run') as run:
            goal.save(self.items()[0], directory)
        scripts = [Path(c.args[0][1]).name for c in run.call_args_list]
        self.assertEqual(scripts, ['soccer_results_render.py', 'synthesize_narration.py', 'soccer_result_story.py', 'soccer_results_render.py'])
        self.assertTrue(all(c.args[0][0] == sys.executable and c.kwargs['check'] for c in run.call_args_list))
        self.assertIn('--goal-short', run.call_args_list[0].args[0])
        self.assertIn('--goal-short', run.call_args_list[-1].args[0])

    def test_existing_v5_goal_intro_and_actual_completion_ticker(self):
        import soccer_results_render as render
        data = self.items()[0]
        with patch.dict(os.environ, {'COLLESPO_SOCCER_LOOK': 'v5', 'COLLESPO_HOST_SPLIT': ''}):
            narr = render.production_narration(data, goal_short=True)
        self.assertEqual(narr['segments'][0]['kind'], 'intro')
        self.assertIn('上田綺世', narr['segments'][0]['text'])
        self.assertIn('ゴール', narr['segments'][0]['text'])
        self.assertEqual(render.program_spec(data)['ticker'], data['result_ticker'])
        self.assertNotIn('昨夜', json.dumps(narr, ensure_ascii=False))

    def test_publication_gates_and_failed_checkpoint(self):
        data = self.items()[0]
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, '公開変数'):
                now.publish(data, 'unused', {}, goal_short=True)
        with patch.dict(os.environ, {'COLLESPO_SOCCER_GOAL_SHORT': 'on'}, clear=True), \
                patch.object(now, 'datetime') as clock:
            clock.now.return_value = self.clock
            with self.assertRaisesRegex(ValueError, '試作'):
                now.publish(dict(data, sample_fictional=True), 'unused', {}, goal_short=True)
            import host_split
            with patch.object(host_split, 'publication', return_value=None), patch('soccer_publications.load', return_value={}), \
                    patch.object(now.subprocess, 'run') as sanity_run, \
                    patch.object(now, 'checkpoint_receipt', side_effect=ValueError('checkpoint failure')) as checkpoint, \
                    patch.object(Path, 'write_text'):
                ledger = {}
                with self.assertRaisesRegex(ValueError, 'checkpoint failure'):
                    now.publish(data, 'unused', ledger, goal_short=True)
                self.assertEqual(ledger['401876452']['status'], 'pending')
                self.assertEqual(checkpoint.call_args.args[0].name, 'soccer_flash_receipts.json')
                sanity_run.assert_called_once()
                self.assertTrue(sanity_run.call_args.kwargs['check'])

    def test_checkpoint_reads_back_same_remote_receipt(self):
        path = now.ROOT/'data/soccer_goal_short_receipts.json'
        for remote, valid in (({'event': {'status': 'pending'}}, True), ({}, False)):
            with patch.object(now.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(remote))) as run:
                if valid:
                    now.checkpoint_receipt(path, 'event', {'status': 'pending'})
                else:
                    with self.assertRaisesRegex(ValueError, '本番台帳'):
                        now.checkpoint_receipt(path, 'event', {'status': 'pending'})
                self.assertEqual(len(run.call_args_list), 3)


class WeekTests(unittest.TestCase):
    def data(self, **kwargs):
        return dict(date='2026-10-26', key='2026-10-26', rows=[{'name': 'fixture'}], **kwargs)

    def test_monday_independent_of_evening_slot_and_matches(self):
        self.assertTrue(week.due(self.data(today_matches=10), {}, {'daily_soccer': {'2026-10-26': {}}}, scheduled=True)[0])
        self.assertFalse(week.due(dict(self.data(), date='2026-10-27'), {}, {}, scheduled=True)[0])

    def test_week_key_done_pending_and_existing_publication(self):
        for state, record in (({'done': ['2026-10-26']}, {}), ({'pending': {'2026-10-26': {}}}, {}),
                              ({}, {'soccer_week': {'2026-10-26': {'video_id': 'id'}}})):
            self.assertFalse(week.due(self.data(), state, record, scheduled=True)[0])
        self.assertFalse(week.due(dict(self.data(), rows=[]), {}, {}, scheduled=True)[0])
        self.assertFalse(week.due(dict(self.data(), key='2026-10-25'), {}, {}, scheduled=True)[0])

    def test_weekend_jst_boundaries_and_unfinished(self):
        matches = [dict(utcDate=stamp, status=status) for stamp, status in (
            ('2026-10-22T14:59:59Z', 'FINISHED'), ('2026-10-22T15:00:00Z', 'FINISHED'),
            ('2026-10-25T21:00:00Z', 'FINISHED'), ('2026-10-26T15:00:00Z', 'FINISHED'),
            ('2026-10-25T20:00:00Z', 'IN_PLAY'))]
        selected = week.weekend_matches({'PL': matches}, date(2026, 10, 26))['PL']
        self.assertEqual(selected, matches[1:3])

    def test_full_given_name_even_for_one_candidate(self):
        elements = [dict(id=1, second_name='Sano', web_name='Sano', first_name='Kodai')]
        self.assertIsNone(week.resolve(elements, 'Kaishu Sano'))
        self.assertIsNone(week.resolve(elements, 'Ko Sano'))
        self.assertEqual(week.resolve(elements, 'Kodai Sano'), 1)

    def test_reservation_same_monday_nine_jst(self):
        self.assertEqual(release.reservation(self.data(), CLOCK), '2026-10-26T00:00:00Z')
        for stamp in ('2026-10-26T00:00:00Z', '2026-10-26T01:00:00Z'):
            self.assertIsNone(release.reservation(self.data(), now.results.utc(stamp)))
        with self.assertRaises(ValueError):
            release.reservation(self.data(), now.results.utc('2026-10-24T23:00:00Z'))

    def test_release_requires_on(self):
        argv = ['week', '--week', 'unused.json', '--video-date', '2026-10-26', '--publish-at', '09:00']
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', argv):
            with self.assertRaisesRegex(ValueError, '公開変数'):
                release.main()

    def test_release_pending_and_confirmed_record(self):
        for confirmed in (False, True):
            directory = ROOT/'build/codex/tmp'/('soccer-week-test-'+uuid4().hex)
            (directory/'data').mkdir(parents=True)
            material = directory/'data/soccer_jp_week.json'
            material.write_text(json.dumps(self.data()), encoding='utf8')
            at = '2026-10-26T00:00:00Z'
            def upload():
                self.assertNotIn('--week', sys.argv)
                self.assertEqual(fake.resolve_publish_at('09:00'), at)
                if confirmed:
                    (directory/'data/published_videos.json').write_text(json.dumps({'soccer_week': {'2026-10-26': dict(video_id='id', publish_at=at)}}), encoding='utf8')
            fake = SimpleNamespace(main=upload, resolve_publish_at=None)
            argv = ['week', '--week', str(material), '--video-date', '2026-10-26', '--publish-at', '09:00', '--kind', 'soccer_week']
            with self.subTest(confirmed=confirmed), patch.dict(os.environ, {'COLLESPO_SOCCER_WEEK': 'on'}), \
                    patch.dict(sys.modules, {'upload_youtube': fake}), patch.object(sys, 'argv', argv), \
                    patch.object(release, 'datetime', FrozenClock), patch.object(release, 'ROOT', directory), \
                    patch.object(now, 'checkpoint_receipt') as checkpoint:
                if confirmed:
                    release.main()
                    self.assertEqual(checkpoint.call_count, 2)
                else:
                    with self.assertRaisesRegex(ValueError, 'pending継続'):
                        release.main()
                state = week._load(directory/'data/soccer_week_state.json')
                self.assertEqual('2026-10-26' in state.get('done', []), confirmed)
                self.assertEqual('2026-10-26' in state['pending'], not confirmed)


class WorkflowTests(unittest.TestCase):
    def test_opt_in_schedule_and_existing_look(self):
        import yaml
        for name, variable, cron in (('soccer_goal_short', 'COLLESPO_SOCCER_GOAL_SHORT', '17,47 * * * *'),
                                     ('soccer_week', 'COLLESPO_SOCCER_WEEK', '15 22 * * 0')):
            data = yaml.safe_load((ROOT/f'.github/workflows/{name}.yml').read_text(encoding='utf8'))
            trigger = data.get('on', data.get(True))
            self.assertEqual(trigger['schedule'][0]['cron'], cron)
            self.assertNotIn('workflow_run', trigger)
            self.assertIn(variable, data['jobs']['build']['if'])
            env = dict(data.get('env', {}), **data['jobs']['build'].get('env', {}))
            self.assertIn("'off'", env[variable])
            self.assertIn("'v5'", env['COLLESPO_SOCCER_LOOK'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
