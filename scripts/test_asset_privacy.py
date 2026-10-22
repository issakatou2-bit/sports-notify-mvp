"""資産動画の実際の予約引数を、アップロードせず公開設定ごとに検査する。"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AssetPrivacy(unittest.TestCase):
    def test_schedule_arguments_follow_requested_privacy(self):
        workflow = (ROOT / '.github/workflows/asset_video.yml').read_text(encoding='utf-8')
        block = re.search(r'^ +PUB=.*\n +if \[.*PRIVACY.*\n', workflow, re.M)
        self.assertIsNotNone(block)
        bash = shutil.which('bash')
        self.assertIsNotNone(bash, '本番の予約引数の検査にはbashが必要')
        for privacy in ('public', 'private', 'unlisted', ''):
            with self.subTest(privacy=privacy):
                # 実際の2行だけを実行。送信処理や鍵を渡さない。
                script = block[0] + '\nprintf "<%s>\\n" "${PUB[@]}"'
                result = subprocess.run([bash, '--noprofile', '--norc', '-c', script],
                                        env={'PATH': os.defpath, 'PRIVACY': privacy,
                                             **({'SYSTEMROOT': os.environ['SYSTEMROOT']}
                                                if 'SYSTEMROOT' in os.environ else {})},
                                        capture_output=True, text=True, check=True)
                expected = '<--publish-at>\n<18:30>\n' if privacy in ('public', '') else '<>\n'
                self.assertEqual(result.stdout, expected)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
