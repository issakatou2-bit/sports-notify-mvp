"""資産動画の実際の予約引数を、アップロードせず公開設定ごとに検査する。"""
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class AssetPrivacy(unittest.TestCase):
    def test_ab_record_without_host_tracking_preserves_site_visibility(self):
        import upload_youtube as upload
        import video_visibility
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'published.json'
            for privacy in ('public', 'private', 'unlisted'):
                with self.subTest(privacy=privacy):
                    upload.record_video('asset', 'season_player_fixture', 'fixture-id', '試験',
                                        path=str(path), privacy=privacy,
                                        experiment={'ab_enabled': False, 'ab_variant': 'A'})
                    row = json.loads(path.read_text(encoding='utf-8'))['asset']['season_player_fixture']
                    self.assertEqual(row['privacy'], privacy)
                    self.assertEqual(video_visibility.is_public(row), privacy == 'public')

    def test_schedule_arguments_follow_requested_privacy(self):
        bash = shutil.which('bash')
        self.assertIsNotNone(bash, '本番の予約引数の検査にはbashが必要')
        for name in ('asset_video', 'season_review'):
            workflow = yaml.safe_load((ROOT / f'.github/workflows/{name}.yml').read_text(encoding='utf-8'))
            body = next(step['run'] for job in workflow['jobs'].values() for step in job['steps']
                        if 'python scripts/upload_youtube.py' in step.get('run', ''))
            self.assertIn('source scripts/asset_publish_args.sh', body)
            binding = re.search(r'asset_publication_args [^\n]*', body)
            upload = re.search(r'(?m)^[ \t]*python scripts/upload_youtube\.py(?:[^\n]*\\\n)*[^\n]*', body)
            self.assertIsNotNone(binding)
            self.assertIsNotNone(upload)
            for privacy in ('public', 'private', 'unlisted', ''):
                with self.subTest(workflow=name, privacy=privacy):
                    # 本番の引数組立と呼出行を使い、pythonだけを表示用関数にする。
                    script = ('source scripts/asset_publish_args.sh\n'
                              'python() { printf "%s\\n" "$@"; }\n' + binding[0] + '\n' + upload[0])
                    result = subprocess.run([bash, '--noprofile', '--norc', '-c', script], cwd=ROOT,
                                            env={'PATH': os.defpath, 'PRIVACY': privacy, 'AT': '18:30',
                                                 't': 'fixture', 'FORCE': '',
                                                 **({'SYSTEMROOT': os.environ['SYSTEMROOT']}
                                                    if 'SYSTEMROOT' in os.environ else {})},
                                            capture_output=True, text=True, check=True)
                    argv = result.stdout.splitlines()
                    self.assertEqual('--publish-at' in argv, privacy in ('public', ''))
                    self.assertEqual(argv[argv.index('--privacy') + 1], privacy or 'public')
                    if '--publish-at' in argv:
                        self.assertEqual(argv[argv.index('--publish-at') + 1], '18:30')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
