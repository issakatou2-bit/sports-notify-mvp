"""見本で公開・保存・通知が動かず、既存入力と定時が保たれること。"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_only

ROOT = Path(__file__).resolve().parents[1]
UNSAFE = ('upload_youtube.py', '--upload', 'post_bluesky.py', 'post_threads.py', 'post_tiktok.py',
          'commit_data.sh', 'git commit', 'git push', 'asset_sns.py', '--record ',
          'playlists.py', 'localize_videos.py', 'verify_published.py', 'soccer_preview_history.py',
          'player_publications.py --sync', 'soccer_publications.py --sync',
          'soccer_national_publish.py', 'captions.py --language', 'send_onesignal.py')
GUARD = "(github.event_name != 'workflow_dispatch' || inputs.sample_only != true)"
MIXED = {('morning_recap', 'Build and upload both shorts'), ('asset_video', 'Build and upload topics'),
         ('season_review', 'Build and upload'), ('offseason_news', 'Check, render and publish through existing asset pipeline'),
         ('ps_game_now', 'Watch and publish')}


def workflow(name):
    return yaml.load((ROOT/'.github/workflows'/f'{name}.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)


class SampleOnlyTests(unittest.TestCase):
    def test_old_dispatch_inputs_and_triggers_are_unchanged(self):
        baseline = json.loads((ROOT/'scripts/fixtures/short-common/workflow_baseline.json').read_text(encoding='utf-8'))
        for name, original in baseline.items():
            with self.subTest(workflow=name):
                current = workflow(name)['on']
                sample = current['workflow_dispatch']['inputs'].pop('sample_only')
                self.assertEqual(sample['type'], 'boolean')
                self.assertEqual(sample['default'], 'false')
                # nullのdispatchと、空のinputsは同じ既存入力なしとして比較。
                if not original.get('workflow_dispatch'):
                    self.assertFalse(current['workflow_dispatch']['inputs'])
                    current['workflow_dispatch'] = original.get('workflow_dispatch')
                self.assertEqual(current, original)

    def test_every_external_step_is_guarded(self):
        baseline = json.loads((ROOT/'scripts/fixtures/short-common/workflow_baseline.json').read_text(encoding='utf-8'))
        seen_mixed = set()
        for name in baseline:
            data = workflow(name)
            samples = []
            for job in data['jobs'].values():
                for step in job.get('steps', []):
                    run = step.get('run', '')
                    step_name = step.get('name', '')
                    if step.get('uses', '').startswith('actions/upload-artifact') and step.get('with', {}).get('name', '').startswith('sample-'):
                        samples.append(step)
                    if not (any(token in run for token in UNSAFE) or step.get('uses', '').startswith(('actions/deploy-pages','actions/upload-pages-artifact'))):
                        continue
                    if (name, step_name) in MIXED:
                        seen_mixed.add((name, step_name))
                        self.assertIn('if [ "$COLLESPO_SAMPLE_ONLY" = true ]; then', run, (name, step_name))
                        boundary = run.index('if [ "$COLLESPO_SAMPLE_ONLY" = true ]; then')
                        external = min(run.index(token) for token in UNSAFE if token in run)
                        self.assertLess(boundary, external, (name, step_name))
                        self.assertRegex(run[boundary:external], r'continue|exit 0')
                    else:
                        self.assertIn(GUARD, step.get('if', ''), (name, step_name, run))
            self.assertTrue(samples, name)
            self.assertTrue(any('.mp4' in s['with']['path'] for s in samples), name)
        self.assertEqual(seen_mixed, MIXED)

    def test_samples_are_saved_in_the_rendering_job(self):
        baseline = json.loads((ROOT/'scripts/fixtures/short-common/workflow_baseline.json').read_text(encoding='utf-8'))
        for name in baseline:
            for job in workflow(name)['jobs'].values():
                steps = job.get('steps', [])
                samples = [s for s in steps if s.get('uses', '').startswith('actions/upload-artifact')
                           and s.get('with', {}).get('name', '').startswith('sample-')
                           and '.mp4' in s.get('with', {}).get('path', '')]
                if not samples:
                    continue
                with self.subTest(workflow=name):
                    self.assertTrue(any(s.get('uses', '').startswith('actions/checkout') for s in steps))
                    self.assertTrue(any('--require-video' in s.get('run', '') for s in steps))
        steps = workflow('morning_recap')['jobs']['morning']['steps']
        marker = next(s for s in steps if s.get('with', {}).get('name') == 'sample-state-morning')
        self.assertIn('always()', marker['if'])
        self.assertNotIn('hashFiles', marker['if'])
        self.assertIn('inputs.sample_only != true', workflow('daily_notify')['jobs']['deploy']['if'])

    def test_local_marker_needs_no_api_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'sample.json'
            env = dict(os.environ, COLLESPO_SAMPLE_ONLY='true')
            env.pop('GH_TOKEN', None)
            result = subprocess.run([sys.executable, str(ROOT/'scripts/sample_only.py'),
                '--mark', str(path)], env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['sample_only'])

    def test_native_watchers_use_existing_nonpublishing_sample_branch(self):
        for name in ('soccer_now', 'soccer_goal_short'):
            steps = [s for j in workflow(name)['jobs'].values() for s in j.get('steps', [])]
            render = next(s['run'] for s in steps if f'{name}.py --sample' in s.get('run', ''))
            self.assertIn('if [ "$COLLESPO_SAMPLE_ONLY" = true ]; then', render)
            self.assertLess(render.index('--sample'), render.index('else'))
        with patch.dict(os.environ, COLLESPO_SAMPLE_ONLY='true'):
            with self.assertRaisesRegex(ValueError, 'sample_only'):
                sample_only.assert_publish_allowed()
            import soccer_now
            with self.assertRaisesRegex(ValueError, 'sample_only'):
                soccer_now.publish({}, Path('unused'), {})
        with patch.dict(os.environ, COLLESPO_SAMPLE_ONLY='false'):
            sample_only.assert_publish_allowed()

    def test_followers_skip_and_propagate_sample_sources(self):
        self.assertTrue(sample_only.source_is_sample([dict(name='sample-soccer_results')]))
        self.assertTrue(sample_only.source_is_sample([dict(name='sample-inherited-build')]))
        self.assertFalse(sample_only.source_is_sample([dict(name='soccer-results')]))
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            data = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
            if 'workflow_run' not in data.get('on', {}):
                continue
            for job_name, job in data['jobs'].items():
                steps = job.get('steps', [])
                if not steps:
                    continue
                with self.subTest(workflow=path.stem, job=job_name):
                    self.assertTrue(any(s.get('id') == 'sample_source' for s in steps))
                    self.assertTrue(any(s.get('with', {}).get('name', '').startswith('sample-inherited') for s in steps))
                    for step in steps:
                        if any(token in step.get('run', '') for token in UNSAFE):
                            self.assertIn("steps.sample_source.outputs.allowed == 'true'", step.get('if', ''))

    @unittest.skipUnless(shutil.which('bash'), 'Bashが必要')
    def test_real_shell_boundaries_skip_upload_but_keep_render(self):
        for name, step_name in MIXED:
            step = next(s for j in workflow(name)['jobs'].values() for s in j['steps'] if s.get('name') == step_name)
            # 実際のYAMLの停止条件を、そのままBashへ渡す。外部処理はprintfの検知器。
            match = re.search(r'if \[ "\$COLLESPO_SAMPLE_ONLY" = true \]; then[^\n]*(?:\n[^\n]*){0,4}?\bfi', step['run'])
            self.assertIsNotNone(match, name)
            boundary = match[0]
            for flag in ('true', 'false'):
                script = 'for t in one two; do mode=test; printf "render\\n"; '+boundary+'; printf "external\\n"; done'
                result = subprocess.run(['bash', '-c', script], env=dict(os.environ, COLLESPO_SAMPLE_ONLY=flag),
                    capture_output=True, text=True, encoding='utf-8', check=True)
                self.assertIn('render', result.stdout)
                self.assertEqual('external' in result.stdout, flag == 'false', (name, flag))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
