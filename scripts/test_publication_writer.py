"""架空の回を使うP1試験。公開APIへの通信なし。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ledger_adapter import FILES, observation
from ledger_compare import compare, health_table
import publication_writer as writer


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        for name in FILES:
            self.save(name, {})

    def save(self, name, value):
        path = self.root / 'data' / (name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def obs(self, key='2026-10-27', **raw):
        return observation('daily', key, dict(video_id='video-a', **raw),
                           'published_videos/daily/' + key)

    def rows(self):
        return [json.loads(p.read_text(encoding='utf-8'))
                for p in (self.root / 'data/publications').glob('*/*.json')]

    def test_upload_writers_keep_legacy_shape_and_write_dates(self):
        import upload_youtube
        video = self.root / 'data/published_videos.json'
        asset = self.root / 'data/published_assets.json'
        with patch.dict(os.environ, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2'):
            upload_youtube.record_video('soccer_results', '2026-10-26', 'result', '架空の題',
                                        path=str(video), publish_at='2026-10-27T02:00:00Z')
            upload_youtube.record_published('fixture/topic', 'asset', 'public', path=str(asset))
        old = json.loads(video.read_text(encoding='utf-8'))['soccer_results']['2026-10-26']
        self.assertEqual(set(old), {'video_id', 'url', 'title', 'published_at', 'publish_at'})
        docs = self.rows()
        self.assertEqual(len(docs), 2)
        ev = next(d for d in docs if d['domain'] == 'soccer')['history'][0]
        self.assertEqual((ev['material_day'], ev['edition_day'], ev['event_day']),
                         ('2026-10-26', '2026-10-27', None))
        self.assertEqual(ev['run_at'], old['published_at'])
        self.assertEqual((ev['state'], ev['run_id'], ev['attempt']), ('scheduled', '123', '2'))
        self.assertEqual(compare(self.root)['issues'], [])

    def test_separate_editions_and_same_edition_concurrent(self):
        # 同じ回32回と、異なる回32回を並行に書く。1回1ファイル、欠落・履歴重複なし。
        observations = [self.obs()] * 32 + [self.obs(f'fixture-{i}') for i in range(32)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda obs: writer.write(obs, self.root), observations))
        self.assertEqual(len(self.rows()), 33)
        self.assertTrue(all(len(d['history']) == 1 for d in self.rows()))
        self.assertEqual(list((self.root / 'data/publications').rglob('*.lock')), [])

    def test_rerun_timestamp_attempt_changes_do_not_duplicate_history(self):
        first = self.obs(published_at='2026-10-27T00:00:00Z')
        writer.write(first, self.root)
        again = self.obs(published_at='2026-10-27T01:00:00Z')
        with patch.dict(os.environ, GITHUB_RUN_ID='another', GITHUB_RUN_ATTEMPT='3'):
            writer.write(again, self.root)
        self.assertEqual(len(self.rows()[0]['history']), 1)
        confirmed = self.obs(published_at='2026-10-27T00:00:00Z')
        confirmed['state'] = 'public_confirmed'
        writer.write(confirmed, self.root)
        writer.write(again, self.root)
        self.assertEqual(len(self.rows()[0]['history']), 2)
        self.assertEqual(self.rows()[0]['history'][-1]['state'], 'public_confirmed')

    def test_same_publication_git_merge_keeps_both_append_only_histories(self):
        from merge_json_conflict import merge_three_way
        first, _ = writer.append(None, self.obs())
        left_obs = self.obs()
        left_obs['state'] = 'held'
        right_obs = self.obs()
        right_obs['state'] = 'scheduled'
        left, _ = writer.append(first, left_obs)
        right, _ = writer.append(first, right_obs)
        merged = merge_three_way(first, left, right, 'data/publications/mlb/fixture.json')
        self.assertEqual(merged['history'][:1], first['history'])
        self.assertEqual([e['state'] for e in merged['history']], ['uploaded', 'held', 'scheduled'])
        self.assertEqual(merge_three_way(first, left, left, 'data/publications/mlb/f.json'), left)
        broken = deepcopy(left)
        broken['history'][0]['state'] = 'held'
        with self.assertRaises(ValueError):
            merge_three_way(first, broken, right, 'data/publications/mlb/f.json')

    def test_history_preserves_replacement_and_repeated_real_transitions(self):
        writer.write(self.obs(), self.root)
        previous = deepcopy(self.rows()[0]['history'])
        for state in ('held', 'public_confirmed', 'held'):
            obs = self.obs()
            obs['state'] = state
            writer.write(obs, self.root)
        obs = self.obs()
        obs['video_id'] = 'replacement'
        writer.write(obs, self.root)
        history = self.rows()[0]['history']
        self.assertEqual(len(history), 5)
        self.assertEqual(history[:1], previous)
        self.assertEqual(history[-1]['video_id'], 'replacement')

    def test_unsafe_names_cannot_escape_or_collide(self):
        for key in ('../../evil', '..\\evil', 'x:y', 'x_y', 'CON', '日本語' * 100):
            path = writer.write(self.obs(key), self.root)
            self.assertTrue(path.resolve().is_relative_to(self.root / 'data/publications/mlb'))
            self.assertLess(len(path.name), 125)
        self.assertEqual(len(self.rows()), 6)

    def test_write_failure_keeps_legacy_and_has_recovery_without_error_text(self):
        import upload_youtube
        with patch.object(writer, 'write', side_effect=OSError('SECRET-should-not-be-printed')), \
             patch('sys.stderr', new_callable=io.StringIO) as log:
            upload_youtube.record_video('daily', '2026-10-27', 'published', 'fixture',
                                        path=str(self.root / 'data/published_videos.json'))
        self.assertEqual(json.loads((self.root / 'data/published_videos.json').read_text())['daily']['2026-10-27']['video_id'], 'published')
        recovered, = (self.root / 'data/publication_recovery').glob('*.json')
        value = json.loads(recovered.read_text(encoding='utf-8'))
        self.assertEqual(value['observation']['video_id'], 'published')
        self.assertNotIn('SECRET', recovered.read_text(encoding='utf-8') + log.getvalue())
        self.assertIn('要回収', str(compare(self.root)['issues']))

    def test_broken_new_document_is_not_overwritten(self):
        path = writer.write(self.obs(), self.root)
        path.write_text('{broken', encoding='utf-8')
        writer.mirror_documents({'published_videos': {'daily': {'2026-10-27': {'video_id': 'b'}}}}, root=self.root)
        self.assertEqual(path.read_text(encoding='utf-8'), '{broken')
        self.assertEqual(len(list((self.root / 'data/publication_recovery').glob('*.json'))), 1)

    def test_hold_and_release_and_correction_original_keep_same_publication(self):
        import video_visibility
        docs = {'daily': {'2026-10-27': {'video_id': 'video-a', 'privacy': 'public'}}}
        path = self.save('published_videos', docs)
        writer.mirror_file(path)
        for privacy in ('private', 'public'):
            saved = dict(privacyStatus=privacy)
            video_visibility.record_status(path, 'video-a', saved)
            writer.mirror_visibility('video-a', saved, root=self.root)
            self.assertEqual(compare(self.root)['issues'], [])
        fix = dict(topic='fixture', old_video='old-video')
        writer.mirror_correction(fix, 'replacement', root=self.root)
        writer.mirror_visibility('old-video', dict(privacyStatus='private'), root=self.root)
        row = next(d for d in self.rows() if d['domain'] == 'asset')
        self.assertEqual(row['history'][-1]['video_id'], 'old-video')
        self.assertEqual(row['history'][-1]['state'], 'held')

    def test_sns_states_and_unknown_dates(self):
        self.save('published_videos', {'daily': {'2026-10-27': {'video_id': 'video-a'}}})
        sky = self.save('bluesky_delivery', {'editions': {'daily:2026-10-27': {
            'video_id': 'video-a', 'state': 'linked', 'uri': 'at://fixture'}}})
        writer.mirror_file(sky)
        tik = self.save('custom-tiktok-file', {'daily': {'2026-10-27': {
            'status': 'PUBLISH_COMPLETE', 'publicly_available': False, 'public_post_ids': []}}})
        writer.mirror_file(tik, ledger_name='published_tiktok')
        events = {d['history'][-1]['service']: d['history'][-1] for d in self.rows()}
        self.assertEqual(events['bluesky']['state'], 'distributed')
        self.assertEqual(events['tiktok']['state'], 'uploaded')
        self.assertIsNone(events['tiktok']['edition_day'])
        self.assertIsNone(events['tiktok']['material_day'])
        pending = dict(publish_id='accepted', status=None, outcome='pending')
        writer.mirror_documents({'published_tiktok': {'daily': {'2026-10-28': pending}}}, root=self.root)
        row = next(d for d in self.rows() if d['key_parts'].get('legacy_key') == '2026-10-28')
        self.assertEqual(row['history'][-1]['state'], 'upload_pending')

    def test_compare_both_missing_video_state_and_no_red_health(self):
        self.save('published_videos', {'daily': {'2026-10-27': {'video_id': 'video-a'}}})
        self.assertEqual(compare(self.root)['issues'][0]['issue'], '旧のみ')
        writer.write(self.obs(), self.root)
        self.assertEqual(compare(self.root)['matched'], 1)
        bad = self.obs()
        bad.update(video_id='wrong', state='held')
        writer.write(bad, self.root)
        writer.write(self.obs('new-only'), self.root)
        issues = compare(self.root)['issues']
        self.assertEqual({x['issue'] for x in issues}, {'食違い', '新のみ'})
        self.assertIn('video_id', issues[0]['detail'])
        self.assertIn('状態', issues[0]['detail'])
        self.assertIn('警告のみ', '\n'.join(health_table(self.root)))

    def test_buffer_remote_history_retries_and_failure_does_not_block_old_save(self):
        import buffer_daily
        remote = {}
        def github(path, method='GET', body=None):
            key = path.removeprefix('/contents/').split('?')[0]
            if method == 'GET':
                if key not in remote:
                    raise HTTPError('fixture', 404, 'missing', {}, None)
                return dict(content=remote[key], sha='sha')
            remote[key] = body['content']
            return {'content': {'sha': 'sha'}}
        ledger = buffer_daily.Ledger.__new__(buffer_daily.Ledger)
        ledger.data = {'deliveries': {}}
        ledger.save = lambda: None
        key = '2026-10-27:daily:twitter'
        raw = dict(state='reserved', youtube_id='video-a', reserved_at='2026-10-27T00:00:00Z')
        with patch.object(buffer_daily, 'github', side_effect=github):
            ledger.set(key, raw)
            ledger.set(key, dict(raw, reserved_at='later'))
            ledger.set(key, dict(raw, state='sent', post_id='post'))
        value, = remote.values()
        doc = json.loads(base64.b64decode(value))
        self.assertEqual([e['state'] for e in doc['history']], ['upload_pending', 'distributed'])
        with patch.object(buffer_daily, 'github', side_effect=RuntimeError('SECRET')), \
             patch.object(writer, 'recover') as recovery:
            ledger.set(key, raw)
        self.assertEqual(ledger.data['deliveries'][key], raw)
        recovery.assert_called_once()

    def test_health_main_warns_without_changing_exit_status(self):
        import healthcheck
        mocks = dict(check_videos=([], 0, 0, set()), published_ids=set(),
                     check_data=([], 0), check_content=([], 0), check_assets=('', 0),
                     check_history=('', 0), check_playlists=('', 0), check_analytics=('', 0),
                     check_credit=('', 0))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name, result in mocks.items():
                stack.enter_context(patch.object(healthcheck, name, return_value=result))
            stack.enter_context(patch('sys.argv', ['healthcheck', '--date', '2026-10-27']))
            stack.enter_context(patch.dict(os.environ, GITHUB_STEP_SUMMARY=''))
            stack.enter_context(patch('ledger_compare.health_table', return_value=['警告：新旧食違い']))
            output = stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
            self.assertEqual(healthcheck.main(), 0)
        self.assertIn('警告：新旧食違い', output.getvalue())

    def test_upload_pending_lost_response_remains_used_no_second_insert(self):
        import soccer_publications as soccer
        import soccer_now
        raw = dict(kind='soccer_now', status='pending', at='2026-10-27T00:00:00Z')
        path = self.save('soccer_flash_receipts', {'game-1': raw})
        with patch.object(soccer, 'ROOT', self.root):
            soccer.mirror_receipt('game-1', raw)
            soccer.mirror_receipt('game-1', dict(raw, at='later'))
            ledger = soccer.load()
        self.assertEqual(self.rows()[0]['history'][0]['state'], 'upload_pending')
        self.assertEqual(len(self.rows()[0]['history']), 1)
        data = dict(games=[dict(id='game-1')])
        self.assertFalse(soccer.eligible(data, ledger))
        with patch.dict(os.environ, COLLESPO_SOCCER_NOW='on', SOCCER_NOW_PUBLISH='true'), \
             patch.object(soccer_now.results, 'validate_data'), \
             patch.object(soccer_now.results, 'utc', return_value=soccer_now.datetime.now(soccer_now.timezone.utc)), \
             patch.object(soccer, 'load', return_value=ledger), \
             patch.object(soccer_now.subprocess, 'run') as request:
            data['games'][0]['finished_utc'] = 'fixture'
            soccer_now.publish(data, self.root, ledger)
        request.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['game-1']['status'], 'pending')


if __name__ == '__main__':
    unittest.main(argv=[__file__])
