"""ローカルの空のGitを使い、競合・再試行・失敗時の回収を実際の保存経路で検査。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import data_save_recovery
import merge_json_conflict as merge

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DataCommitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.upstream = self.root / 'upstream'
        self.local = self.root / 'local'
        self.env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid',
                        GIT_EDITOR='true')
        self.git(self.root, 'init', '--bare', '-q', str(self.remote))
        for repo in (self.upstream, self.local):
            repo.mkdir()
            self.git(repo, 'init', '-q', '-b', 'main')
            self.git(repo, 'remote', 'add', 'origin', str(self.remote))
        (self.upstream / 'scripts').mkdir()
        for name in ('commit_data.sh', 'merge_json_conflict.py', 'data_save_recovery.py'):
            shutil.copyfile(ROOT / 'scripts' / name, self.upstream / 'scripts' / name)
        (self.upstream / 'scripts/unused.txt').write_text('before')
        # 再試行間の待ち時間だけを省略。Git・JSON・shellの処理は本物を使う。
        (self.upstream / 'test-bin').mkdir()
        (self.upstream / 'test-bin/sleep').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        (self.upstream / 'test-bin/sleep').chmod(0o755)
        self.write(self.upstream, 'published_assets', {'assets': {'old': {'video_id': 'old-video'}}})
        self.write(self.upstream, 'published_videos', {'asset': {'old': {'video_id': 'old-video'}}})
        self.write(self.upstream, 'token_usage', {'days': {'2026-10-16': {'calls': 10, 'in': 100}}})
        self.write(self.upstream, 'ps_game_topics', {'topics': [{'key': 'old', 'items': ['before']}]})
        self.commit(self.upstream, 'initial')
        self.git(self.upstream, 'push', '-qu', 'origin', 'main')
        self.git(self.local, 'fetch', '-q', 'origin', 'main')
        self.git(self.local, 'checkout', '-q', '-B', 'main', 'origin/main')
        self.git(self.local, 'branch', '--set-upstream-to=origin/main')

    def git(self, folder, *args, check=True):
        return subprocess.run(['git', '-c', 'safe.directory=*', *args], cwd=folder, env=self.env,
                              capture_output=True, encoding='utf-8', errors='replace', check=check)

    def write(self, repo, name, data):
        path = repo / 'data' / (name + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def commit(self, repo, message):
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', message)

    def add_run(self, repo, key, video, calls):
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            value = json.loads((repo / 'data' / (name + '.json')).read_text())
            value[kind][key] = {'video_id': video, 'privacy': 'public'}
            self.write(repo, name, value)
        self.write(repo, 'token_usage', {'days': {'2026-10-16': {'calls': calls, 'in': calls * 10}}})
        self.write(repo, 'ps_game_topics', {'topics': [{'key': 'old', 'items': [key]}, {'key': key}]})

    def save(self, paths='data/*.json'):
        result = subprocess.run(['bash', '-c', 'export PATH="$PWD/test-bin:$PATH"; bash scripts/commit_data.sh test ' + paths],
                                cwd=self.local, env=self.env, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=90)
        return result

    def remote_json(self, name):
        return json.loads(self.git(self.remote, 'show', 'main:data/' + name + '.json').stdout)

    def test_publications_auto_saved_with_old_path_and_snapshot(self):
        import publication_writer as writer
        from ledger_adapter import observation
        self.add_run(self.local, 'game', 'new-video', 13)
        obs = observation('daily', '2026-10-27', {'video_id': 'new-video'},
                          'published_videos/daily/2026-10-27')
        path = writer.write(obs, self.local)
        # 別の回を先に保存する競合。両方の1回1ファイルがremoteまで残る。
        other = observation('daily', '2026-10-26', {'video_id': 'other-video'},
                            'published_videos/daily/2026-10-26')
        other_path = writer.write(other, self.upstream)
        self.commit(self.upstream, 'another publication')
        self.git(self.upstream, 'push', '-q')
        writer.recover(obs, OSError('fixture'), self.local)
        result = self.save('data/published_videos.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for target, repo in ((path, self.local), (other_path, self.upstream)):
            name = target.relative_to(repo).as_posix()
            doc = json.loads(self.git(self.remote, 'show', 'main:' + name).stdout)
            self.assertEqual(len(doc['history']), 1)
        recovery, = (self.local / 'data/publication_recovery').glob('*.json')
        self.assertEqual(self.git(self.remote, 'cat-file', '-e',
                                 'main:' + recovery.relative_to(self.local).as_posix()).returncode, 0)
        snapshots = list((self.local / 'build/data-save-recovery').glob('*/data/publications/*/*.json'))
        self.assertEqual(len(snapshots), 1)

    def test_competing_runs_keep_both_records_and_usage_in_real_push(self):
        self.add_run(self.upstream, 'longform', 'other-video', 12)
        self.commit(self.upstream, 'other run')
        self.git(self.upstream, 'push', '-q')
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 13)
        # 保存対象でない生成物があっても台帳を失わない。
        (self.local / 'scripts/unused.txt').write_text('local output')
        result = self.save()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('押しました (1回目)', result.stdout)
        self.assertNotIn('failed to push some refs', result.stdout)
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            self.assertEqual(set(self.remote_json(name)[kind]), {'old', 'longform', 'game'})
        self.assertEqual(self.remote_json('token_usage')['days']['2026-10-16'], {'calls': 15, 'in': 150})
        self.assertEqual({row['key'] for row in self.remote_json('ps_game_topics')['topics']}, {'old', 'longform', 'game'})
        self.assertEqual((self.local / 'scripts/unused.txt').read_text(), 'local output')

    def test_unselected_usage_conflict_does_not_block_record_push(self):
        # run 39104770308: 公開台帳のrebase解決後、対象外の使用量復元で競合。
        self.add_run(self.upstream, 'other', 'other-video', 12)
        self.commit(self.upstream, 'competing publication and usage')
        self.git(self.upstream, 'push', '-q')
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 13)
        result = self.save('data/published_assets.json data/published_videos.json data/ps_game_topics.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            self.assertEqual(set(self.remote_json(name)[kind]), {'old', 'other', 'game'})
        self.assertEqual(self.remote_json('token_usage')['days']['2026-10-16']['calls'], 12)
        restored = json.loads((self.local / 'data/token_usage.json').read_text())
        self.assertEqual(restored['days']['2026-10-16']['calls'], 15)
        self.assertEqual(self.git(self.local, 'diff', '--name-only', '--diff-filter=U').stdout, '')
        self.assertEqual(self.git(self.local, 'stash', 'list').stdout, '')

    def test_non_json_restore_conflict_keeps_records_and_failure_reason(self):
        (self.upstream / 'scripts/unused.txt').write_text('remote output')
        self.commit(self.upstream, 'other run changes non record file only')
        self.git(self.upstream, 'push', '-q')
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 13)
        (self.local / 'scripts/unused.txt').write_text('local output')
        result = self.save()
        self.assertNotEqual(result.returncode, 0)
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            self.assertIn('game', self.remote_json(name)[kind])
        marker, = (self.local / 'build/data-save-recovery').glob('*/FAILED')
        reason = marker.read_text(encoding='utf-8')
        self.assertIn('記録は保存済み', reason)
        self.assertIn('records: saved', reason)
        self.assertIn('scripts/unused.txt', reason)
        self.assertIn('local output', (marker.parent / 'pending.patch').read_text())
        self.assertNotIn('公開済みだが記録が保存できなかった', result.stdout)

    def test_only_topic_and_kana_remote_changes_keep_public_records(self):
        for name in ('season_topics', 'player_kana'):
            self.write(self.upstream, name, {'old': 'before'})
        self.commit(self.upstream, 'seed topic and kana')
        self.git(self.upstream, 'push', '-q')
        self.git(self.local, 'pull', '--ff-only', '-q')
        for name in ('season_topics', 'player_kana', 'ps_game_topics'):
            self.write(self.upstream, name, {'remote': 'other run'})
            self.write(self.local, name, {'local': 'this run'})
        self.commit(self.upstream, 'other run changes non record JSON only')
        self.git(self.upstream, 'push', '-q')
        # add_run はPS一覧も更新するので、台帳だけ追加。
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            self.write(self.local, name, {kind: {'old': {'video_id': 'old-video'},
                                               'game': {'video_id': 'GhJYUObTp3I'}}})
        result = self.save()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
            self.assertEqual(set(self.remote_json(name)[kind]), {'old', 'game'})
        for name in ('season_topics', 'player_kana', 'ps_game_topics'):
            self.assertEqual(self.remote_json(name), {'remote': 'other run', 'local': 'this run'})

    def test_second_race_retries_without_double_counting_usage(self):
        race = self.root / 'race.py'
        race.write_text('''import json, pathlib, subprocess
repo = pathlib.Path(__file__).parent / 'upstream'
counter = pathlib.Path(__file__).with_suffix('.count')
n = int(counter.read_text()) if counter.exists() else 0
if n < 2:
    counter.write_text(str(n + 1))
    for name, kind in [('published_assets', 'assets'), ('published_videos', 'asset')]:
        path = repo / 'data' / (name + '.json')
        data = json.loads(path.read_text())
        data[kind]['race' + str(n)] = {'video_id': 'race-video' + str(n)}
        path.write_text(json.dumps(data))
    (repo / 'data/token_usage.json').write_text(json.dumps({'days': {'2026-10-16': {'calls': 11 + n, 'in': 110 + 10*n}}}))
    for args in [('add', '.'), ('commit', '-qm', 'race'), ('push', '-q')]:
        subprocess.run(['git', *args], cwd=repo, check=True)
''', encoding='utf-8')
        hook = self.local / '.git/hooks/pre-push'
        hook.write_text(f'#!/bin/sh\n"{pathlib.Path(sys.executable).as_posix()}" "{race.as_posix()}"\n', encoding='utf-8')
        hook.chmod(0o755)
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 13)
        result = self.save()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('押しました (3回目)', result.stdout)
        self.assertEqual(set(self.remote_json('published_assets')['assets']), {'old', 'race0', 'race1', 'game'})
        self.assertEqual(self.remote_json('token_usage')['days']['2026-10-16'], {'calls': 15, 'in': 150})

    def test_failed_prefetch_stops_before_sending_and_keeps_recovery(self):
        self.add_run(self.local, 'game', 'unsent-preview', 13)
        self.git(self.local, 'remote', 'set-url', 'origin', str(self.root/'unavailable.git'))
        result=self.save()
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('押しました',result.stdout)
        marker,=(self.local/'build/data-save-recovery').glob('*/FAILED')
        self.assertIn('送信前の取得・取り込みに失敗',marker.read_text(encoding='utf8'))
        self.assertNotIn('game',self.remote_json('published_assets')['assets'])

    def test_push_exhaustion_fails_and_keeps_recovery_with_video_id(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        hook.chmod(0o755)
        self.add_run(self.local, 'game', '-WWdo4q-JcE', 13)
        result = self.save()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('公開済みだが記録が保存できなかった：-WWdo4q-JcE', result.stdout)
        self.assertIn('5回試しても', result.stdout)
        saved = list((self.local / 'build/data-save-recovery').glob('*/FAILED'))
        self.assertEqual(len(saved), 1)
        reason = saved[0].read_text(encoding='utf-8')
        self.assertIn('5回試してもpushできませんでした', reason)
        self.assertIn('pre-receive hook declined', reason)
        self.assertIn('-WWdo4q-JcE', reason)
        value = json.loads((saved[0].parent / 'data/published_assets.json').read_text())
        self.assertEqual(value['assets']['game']['video_id'], '-WWdo4q-JcE')
        self.assertNotIn('game', self.remote_json('published_assets')['assets'])

    def test_identical_usage_edits_still_sum_without_git_conflict(self):
        self.write(self.upstream, 'token_usage', {'days': {'2026-10-16': {'calls': 11, 'in': 110}}})
        self.commit(self.upstream, 'one call in other run')
        self.git(self.upstream, 'push', '-q')
        self.write(self.local, 'token_usage', {'days': {'2026-10-16': {'calls': 11, 'in': 110}}})
        # Gitが自分のcommitを同一変更として落としても、別々の呼出しを計上する。
        result = self.save()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.remote_json('token_usage')['days']['2026-10-16'], {'calls': 12, 'in': 120})

    def test_commit_failure_is_not_reported_as_success(self):
        hook = self.local / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        hook.chmod(0o755)
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 11)
        result = self.save()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('公開済みだが記録が保存できなかった：GhJYUObTp3I', result.stdout)
        marker, = (self.local / 'build/data-save-recovery').glob('*/FAILED')
        self.assertIn('保存対象のgit commitに失敗', marker.read_text(encoding='utf-8'))

    def test_conflicting_video_id_cannot_overwrite_public_record(self):
        self.add_run(self.upstream, 'game', 'other-video', 12)
        self.commit(self.upstream, 'other video for same key')
        self.git(self.upstream, 'push', '-q')
        self.add_run(self.local, 'game', 'GhJYUObTp3I', 13)
        result = self.save()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_json('published_assets')['assets']['game']['video_id'], 'other-video')
        self.assertIn('公開済みだが記録が保存できなかった：GhJYUObTp3I', result.stdout)


class MergePolicyTest(unittest.TestCase):
    def test_equal_usage_deltas_are_both_counted(self):
        self.assertEqual(merge.merge_three_way({'calls': 10}, {'calls': 12}, {'calls': 12}, 'data/token_usage.json'), {'calls': 14})

    def test_unchanged_local_does_not_undo_remote_edit(self):
        self.assertEqual(merge.merge_three_way({'a': 1}, {'a': 2}, {'a': 1}, 'data/test.json'), {'a': 2})

    def test_record_deletions_keep_existing_publication(self):
        self.assertEqual(merge.merge_three_way({'a': 1}, {'a': 1}, {}, 'data/published_videos.json'), {'a': 1})

    def test_caption_events_keep_both_appends_once(self):
        self.assertEqual(merge.merge_three_way({'events': [1]}, {'events': [1, 2]}, {'events': [1, 3]}, 'data/en_caption_state.json'), {'events': [1, 2, 3]})

    def test_record_ids_recurse_without_discarding_other_fields(self):
        self.assertEqual(data_save_recovery.video_ids({'a': [{'video_id': 'one'}], 'b': {'video_id': 'two'}}), {'one', 'two'})

    def test_all_data_save_jobs_preserve_failure_artifacts(self):
        import yaml
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            for job in yaml.safe_load(path.read_text(encoding='utf-8')).get('jobs', {}).values():
                saves = [s for s in job.get('steps', []) if 'scripts/commit_data.sh' in s.get('run', '')]
                if saves:
                    with self.subTest(workflow=path.name):
                        self.assertFalse(any(s.get('continue-on-error') for s in saves))
                        recovery = [s for s in job['steps'] if s.get('with', {}).get('path', '').startswith('build/data-save-recovery/')]
                        self.assertEqual(len(recovery), 1)
                        self.assertIn('always()', recovery[0]['if'])
        text = (ROOT / '.github/workflows/ps_game_now.yml').read_text(encoding='utf-8')
        self.assertTrue(all(line.endswith(' || exit 1') for line in text.splitlines() if 'bash scripts/commit_data.sh' in line))


if __name__ == '__main__':
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    print('ALL OK' if result.wasSuccessful() else 'FAILED')
    raise SystemExit(0 if result.wasSuccessful() else 1)
