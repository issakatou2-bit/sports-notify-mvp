"""全登録経路の英語付与と翻訳失敗時の継続。API/LLMは全て作り物。"""
import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest import mock

import localize_videos as lv
import localize_weekly as weekly
import upload_youtube as upload
import yaml

ROOT = Path(__file__).resolve().parent.parent


def body():
    return {'snippet': {'title': '日本語の題', 'description': '日本語の説明', 'categoryId': '17'},
            'status': {'privacyStatus': 'public'}}


class UploadLocalization(unittest.TestCase):
    def test_common_uploader_covers_episode_types_and_failure(self):
        kinds = ['daily', 'daily_soccer', 'players', 'player', 'local', 'press',
                 'voices', 'postseason', 'all', 'asset', 'season_review', 'ps_game_now',
                 'weekly', 'weekly_verdict', 'longform', 'longform_v3', 'soccer_daily',
                 'soccer_race', 'soccer_voices', 'soccer_week', 'soccer_results',
                 'player_story', 'japan_reacts', 'ui_voice']
        for kind in kinds:
            for fails in (False, True):
                with self.subTest(kind=kind, translation_fails=fails):
                    original = body()
                    original['snippet']['tags'] = [kind]
                    original['status']['publishAt'] = '2026-10-20T01:00:00Z'
                    saved = copy.deepcopy(original)
                    yt = mock.Mock()
                    yt.videos.return_value.insert.return_value.execute.return_value = {'id': 'fake'}
                    with mock.patch.dict(lv.os.environ, {'ANTHROPIC_API_KEY': 'fake'}), \
                         mock.patch.object(lv, 'anthropic', mock.Mock()), \
                         mock.patch.object(lv, 'translate', return_value=('E' * 140, 'English description'),
                                           side_effect=RuntimeError('unavailable') if fails else None) as translate, \
                         mock.patch.object(upload, 'MediaFileUpload'):
                        self.assertEqual(upload.insert_with_retry(yt, original, 'fake.mp4'), {'id': 'fake'})
                    sent = yt.videos.return_value.insert.call_args.kwargs
                    self.assertEqual(sent['body']['status'], saved['status'])
                    self.assertEqual(sent['body']['snippet']['title'], saved['snippet']['title'])
                    self.assertEqual(sent['body']['snippet']['defaultLanguage'], 'ja')
                    self.assertEqual(original, saved)
                    translate.assert_called_once()
                    if fails:
                        self.assertNotIn('localizations', sent['body'])
                    else:
                        self.assertIn('localizations', sent['part'])
                        self.assertEqual(len(sent['body']['localizations']['en']['title']), 100)
                        self.assertEqual(sent['body']['localizations']['en']['description'], 'English description')

    def test_all_direct_insert_sites_use_shared_translation_and_parts(self):
        found = set()
        for path in (ROOT / 'scripts').glob('*.py'):
            if path.name.startswith('test_'):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            if any(isinstance(n, ast.Call) and ast.unparse(n.func).endswith('.videos().insert')
                   for n in ast.walk(tree)):
                found.add(path.name)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or '.videos().insert(' not in ast.unparse(node.value):
                    continue
                if path.name == 'upload_youtube.py':
                    continue  # 上の試験で登録関数全体を実行。
                # 本番の登録直前の2文をそのまま実行し、外部依存だけ差し替える。
                prep = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                            and isinstance(n.value, ast.Call)
                            and ast.unparse(n.value.func) == 'localize_videos.prepare_upload')
                for fails in (False, True):
                    with self.subTest(path=path.name, fails=fails):
                        yt = mock.Mock()
                        namespace = dict(localize_videos=lv, body=body(), snippet=body()['snippet'],
                                         yt=yt, api_build=mock.Mock(return_value=yt), creds=object(),
                                         path=Path('fake.mp4'), video=Path('fake.mp4'), out=Path('fake'),
                                         Path=Path, MediaFileUpload=mock.Mock())
                        module = ast.Module(body=[prep, node], type_ignores=[])
                        with mock.patch.dict(lv.os.environ, {'ANTHROPIC_API_KEY': 'fake'}), \
                             mock.patch.object(lv, 'anthropic', mock.Mock()), \
                             mock.patch.object(lv, 'translate', return_value=('English', 'Description'),
                                               side_effect=RuntimeError('unavailable') if fails else None):
                            exec(compile(module, str(path), 'exec'), namespace)
                        sent = yt.videos.return_value.insert.call_args.kwargs
                        self.assertEqual('localizations' in sent['body'], not fails)
                        self.assertEqual('localizations' in sent['part'], not fails)
        self.assertEqual(found, {'upload_youtube.py', 'soccer_now.py', 'pilot_upload.py',
                                 'repair_daily_20260912.py', 'repair_ps_labels_20260926.py'})

    def test_empty_translation_or_missing_key_preserves_japanese(self):
        for result in (('', 'English description'), ('English', '')):
            with mock.patch.object(lv, 'translate', return_value=result):
                translated = lv.prepare_upload(body(), ai=object())
                self.assertNotIn('localizations', translated)
        with mock.patch.dict(lv.os.environ, {'ANTHROPIC_API_KEY': ''}), \
             mock.patch.object(lv, 'translate') as translate:
            self.assertNotIn('localizations', lv.prepare_upload(body()))
            translate.assert_not_called()

    def test_existing_languages_and_translation_once_across_retries(self):
        original = body()
        original['localizations'] = {'fr': {'title': 'FR', 'description': 'FR desc'}}
        with mock.patch.object(lv, 'translate', return_value=('English', 'Description')):
            result = lv.prepare_upload(original, ai=object())
        self.assertEqual(result['localizations']['fr'], original['localizations']['fr'])
        with mock.patch.object(lv, 'translate') as translate:
            lv.prepare_upload(result, ai=object())
            translate.assert_not_called()
        class RetryError(Exception):
            resp = type('Response', (), {'status': 503})()
        yt = mock.Mock()
        yt.videos.return_value.insert.return_value.execute.side_effect = [RetryError(), {'id': 'fake'}]
        with mock.patch.dict(lv.os.environ, {'ANTHROPIC_API_KEY': 'fake'}), \
             mock.patch.object(lv, 'anthropic', mock.Mock()), \
             mock.patch.object(lv, 'translate', return_value=('English', 'Description')) as translate, \
             mock.patch.object(upload, 'MediaFileUpload'), mock.patch('time.sleep'), \
             mock.patch('googleapiclient.errors.HttpError', RetryError):
            upload.insert_with_retry(yt, original, 'fake.mp4', waits=(0,))
            translate.assert_called_once()

    def test_workflow_upload_steps_receive_translation_credentials(self):
        matched = 0
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
            for job in (workflow.get('jobs') or {}).values():
                for step in job.get('steps', []):
                    run = step.get('run', '')
                    if not any(name in run for name in ('upload_youtube.py', 'pilot_upload.py upload',
                            'soccer_results_upload.py', 'ps_daily_entry.py --stage upload',
                            'generate_ps_preview.py --upload')):
                        continue
                    matched += 1
                    env = dict(workflow.get('env') or {}, **(job.get('env') or {}))
                    env.update(step.get('env') or {})
                    self.assertIn('ANTHROPIC_API_KEY', env, str(path))
        self.assertGreaterEqual(matched, 15)
        workflow = yaml.load((ROOT / '.github/workflows/localize_weekly.yml').read_text(encoding='utf-8'),
                             Loader=yaml.BaseLoader)
        self.assertEqual(len(workflow['on']['schedule']), 1)
        text = (ROOT / '.github/workflows/localize_weekly.yml').read_text(encoding='utf-8')
        self.assertIn('MODE=--dry-run', text)
        self.assertIn('if [ "$ENABLED" = "on" ]; then MODE=--apply; fi', text)


class WeeklyAudit(unittest.TestCase):
    now = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)

    def video(self, ident, days=1, privacy='public', en=None):
        return {'id': ident, 'snippet': dict(body()['snippet'],
                publishedAt=(self.now - timedelta(days=days)).isoformat()),
                'status': {'privacyStatus': privacy},
                'localizations': {'fr': {'title': 'FR', 'description': 'desc'}, **({'en': en} if en else {})}}

    def client(self, videos):
        yt = mock.Mock()
        def listing(**kwargs):
            result = mock.Mock()
            result.execute.return_value = {'items': [v for v in videos if v['id'] in kwargs['id'].split(',')]}
            return result
        yt.videos.return_value.list.side_effect = listing
        return yt

    def test_dry_run_counts_entire_window_without_ai_or_update(self):
        videos = [self.video('missing'), self.video('partial', en={'title': 'EN'}),
                  self.video('ok', en={'title': 'EN', 'description': 'desc'}),
                  self.video('boundary', days=14), self.video('old', days=15),
                  self.video('private', privacy='private'), self.video('unlisted', privacy='unlisted'),
                  self.video('future', days=-1)]
        yt = self.client(videos)
        with mock.patch.object(lv, 'all_ids', return_value=[v['id'] for v in videos]), \
             mock.patch.object(lv, 'translate') as translate, mock.patch.object(lv, 'save_store') as save:
            report = weekly.audit(yt, self.now, limit=1)
        self.assertEqual((report['checked'], report['missing_title'], report['missing_metadata']), (4, 2, 3))
        self.assertEqual(report['attempted'], 0)
        yt.videos.return_value.update.assert_not_called()
        translate.assert_not_called()
        save.assert_not_called()

    def test_apply_reuses_backfill_with_limit_and_ignores_stale_store(self):
        videos = [self.video('a'), self.video('b'), self.video('c')]
        yt = self.client(videos)
        with mock.patch.object(lv, 'all_ids', return_value=['a', 'b', 'c']), \
             mock.patch.object(lv, 'load_store', return_value={'a': {'title_en': 'stale'}}), \
             mock.patch.object(lv, 'save_store'), \
             mock.patch.object(lv, 'translate', return_value=('E' * 120, 'English description')):
            report = weekly.audit(yt, self.now, limit=2, apply=True, ai=object())
        self.assertEqual((report['missing_title'], report['attempted'], report['updated']), (3, 2, 2))
        self.assertEqual(yt.videos.return_value.update.call_count, 2)
        for call in yt.videos.return_value.update.call_args_list:
            sent = call.kwargs['body']
            self.assertEqual(len(sent['localizations']['en']['title']), 100)
            self.assertEqual(sent['localizations']['fr']['title'], 'FR')
            self.assertEqual(sent['snippet']['title'], '日本語の題')

    def test_failed_translations_do_not_exceed_attempt_limit(self):
        videos = [self.video('a'), self.video('b')]
        yt = self.client(videos)
        with mock.patch.object(lv, 'all_ids', return_value=['a', 'b']), \
             mock.patch.object(lv, 'load_store', return_value={}), mock.patch.object(lv, 'save_store'), \
             mock.patch.object(lv, 'translate', side_effect=RuntimeError('unavailable')) as translate:
            report = weekly.audit(yt, self.now, limit=1, apply=True, ai=object())
        self.assertEqual((report['attempted'], report['updated']), (1, 0))
        translate.assert_called_once()
        yt.videos.return_value.update.assert_not_called()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
