"""非公開試験の予約なし・記録分離と、公開の既定動作を検査。通信しない。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import soccer_results_upload as entry

ROOT = Path(__file__).resolve().parents[1]


class PrivateResults(unittest.TestCase):
    def test_public_unlisted_and_scheduled_private_require_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory)/'sample.mp4'
            video.write_bytes(b'fixture')
            material = Path(directory)/'results.json'
            material.write_text(json.dumps({'date_jst': '2026-10-09'}), encoding='utf-8')
            for privacy, reservation in (('public', None), ('unlisted', None),
                                         ('private', '2099-10-09T00:00:00Z')):
                argv = ['upload', '--kind', 'soccer_results', '--sport', 'soccer',
                        '--video', str(video), '--video-date', '2026-10-09',
                        '--games', str(material), '--privacy', privacy]
                with self.subTest(privacy=privacy), patch.object(sys, 'argv', argv), \
                        patch.dict(os.environ, {'YOUTUBE_CLIENT_ID':'test', 'YOUTUBE_CLIENT_SECRET':'test', 'YOUTUBE_REFRESH_TOKEN':'test'}), \
                        patch.object(entry.upload, 'Credentials'), patch.object(entry.upload, 'build'), \
                        patch.object(entry.upload, 'published_video', return_value={}), \
                        patch.object(entry.upload, 'resolve_publish_at', return_value=reservation), \
                        patch.object(entry.upload, 'build_metadata', return_value={'snippet': {'title':'試験', 'description':''}}), \
                        patch.object(entry.upload, 'insert_with_retry') as send:
                    with self.assertRaisesRegex(ValueError, '合格記録'):
                        entry.upload.main()
                    send.assert_not_called()

    def setUp(self):
        # CIでも作り物の動画URLを実行Summaryへ書かない。
        summary = patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''})
        summary.start()
        self.addCleanup(summary.stop)

    def test_real_uploader_builds_private_status_without_publication_time(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory)/'sample.mp4'
            video.write_bytes(b'fixed test input; no real video upload')
            record = Path(directory)/'private.json'
            material = Path(directory)/'results.json'
            material.write_text(json.dumps({'date_jst': '2026-10-09'}), encoding='utf-8')
            argv = ['upload', '--kind', 'soccer_results', '--sport', 'soccer',
                    '--video', str(video), '--video-date', '2026-10-09',
                    '--games', str(material), '--privacy', 'private']
            with patch.object(entry, 'PRIVATE_RECORD', record), patch.object(sys, 'argv', argv), patch.dict(os.environ, {'YOUTUBE_CLIENT_ID': 'test', 'YOUTUBE_CLIENT_SECRET': 'test', 'YOUTUBE_REFRESH_TOKEN': 'test'}), patch.object(entry.upload, 'Credentials'), patch.object(entry.upload, 'build'), patch.object(entry.upload, 'build_metadata', return_value={'snippet': {'title': '試験', 'description': ''}}), patch.object(entry.upload, 'insert_with_retry', return_value={'id': 'private-status-test'}) as send:
                entry.main()
            status = send.call_args.args[1]['status']
            self.assertEqual(status['privacyStatus'], 'private')
            self.assertNotIn('publishAt', status)
            self.assertEqual(json.loads(record.read_text(encoding='utf-8'))['soccer_results']['2026-10-09']['video_id'], 'private-status-test')

    def test_private_uses_separate_lookup_and_record(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory)/'private.json'
            lookup, writer = entry.upload.published_video, entry.upload.record_video
            def simulated_upload():
                self.assertEqual(entry.upload.published_video('soccer_results', '2026-10-09'), {})
                entry.upload.record_video('soccer_results', '2026-10-09', 'private-test', '試験')
            with patch.object(entry, 'PRIVATE_RECORD', record), patch.object(entry.upload, 'main', side_effect=simulated_upload), patch.object(sys, 'argv', ['upload', '--privacy', 'private', '--video-date', '2026-10-09']):
                entry.main()
            self.assertIs(entry.upload.published_video, lookup)
            self.assertIs(entry.upload.record_video, writer)
            row = json.loads(record.read_text(encoding='utf-8'))['soccer_results']['2026-10-09']
            self.assertEqual(row['video_id'], 'private-test')
            self.assertNotIn('publish_at', row)

    def test_private_rejects_reservation_and_missing_upload(self):
        with patch.object(entry.upload, 'main') as send, patch.object(sys, 'argv', ['upload', '--privacy', 'private', '--video-date', '2026-10-09', '--publish-at', '23:00']):
            with self.assertRaises(SystemExit):
                entry.main()
            send.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            lookup, writer = entry.upload.published_video, entry.upload.record_video
            with patch.object(entry, 'PRIVATE_RECORD', Path(directory)/'missing.json'), patch.object(entry.upload, 'main'), patch.object(sys, 'argv', ['upload', '--privacy', 'private', '--video-date', '2026-10-09']):
                with self.assertRaisesRegex(RuntimeError, 'アップロード記録がありません'):
                    entry.main()
            self.assertIs(entry.upload.published_video, lookup)
            self.assertIs(entry.upload.record_video, writer)

    def test_public_delegates_without_changing_record_functions(self):
        lookup, writer = entry.upload.published_video, entry.upload.record_video
        with patch.object(entry.upload, 'main', return_value='public') as send, patch.object(sys, 'argv', ['upload', '--video-date', '2026-10-09', '--publish-at', '23:00']):
            self.assertEqual(entry.main(), 'public')
            send.assert_called_once_with()
        self.assertIs(entry.upload.published_video, lookup)
        self.assertIs(entry.upload.record_video, writer)

    def test_workflow_gates_private_and_public(self):
        wf = yaml.safe_load((ROOT/'.github/workflows/soccer_results.yml').read_text(encoding='utf-8'))
        inputs = wf.get('on', wf.get(True))['workflow_dispatch']['inputs']
        self.assertEqual(inputs['privacy']['default'], 'public')
        self.assertEqual(inputs['privacy']['options'], ['public', 'private'])
        self.assertFalse(inputs['publish']['default'])
        steps = {s.get('name'): s for s in wf['jobs']['build']['steps']}
        for event, switch, publish, privacy, count, expected in [
                ('workflow_dispatch', '', True, 'private', '1', (True, False, False)),
                ('workflow_dispatch', '', True, 'public', '1', (True, True, True)),
                ('workflow_dispatch', '', False, 'private', '1', (False, False, False)),
                ('schedule', 'true', False, '', '1', (True, True, True)),
                ('schedule', '', False, '', '1', (False, False, False)),
                ('workflow_dispatch', '', True, 'private', '0', (False, False, False))]:
            values = {'github.event_name': event, 'vars.SOCCER_RESULTS_PUBLISH': switch,
                      'inputs.publish': publish, 'inputs.privacy': privacy, 'steps.gate.outputs.count': count}
            for name, want in zip(('Upload to YouTube', 'Require a future reservation', 'Confirm reservation'), expected):
                expr = steps[name]['if']
                for key in sorted(values, key=len, reverse=True):
                    expr = expr.replace(key, repr(values[key]))
                self.assertEqual(eval(expr.replace('&&', ' and ').replace('||', ' or '), {'__builtins__': {}}), want, (event, privacy, name))
        script = steps['Upload to YouTube']['run']
        self.assertIn('if [ "$PRIVACY" != private ]; then args+=(--publish-at "$PUBLISH_AT"); fi', script)
        self.assertIn('scripts/soccer_results_upload.py', script)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
