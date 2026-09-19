"""Execute the actual workflow shell with a fake publisher: never use credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

BASH = shutil.which('bash')
if os.name == 'nt':
    candidate = Path('C:/Program Files/Git/bin/bash.exe')
    BASH = str(candidate) if candidate.exists() else None


@unittest.skipUnless(BASH, 'bash is needed to exercise the runner shell')
class BatchDelivery(unittest.TestCase):
    def execute(self, mode, fail=''):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/buffer_daily.yml').read_text(encoding='utf-8')
        script = textwrap.dedent(workflow.rsplit('        run: |\n', 1)[1])
        script = script.replace("${{ inputs.kind || 'daily' }}", 'daily')
        script = script.replace('/tmp/due.tsv', '"$TEST_DIR/due.tsv"')
        fake = '''
python() {
  case "$*" in
    *--reconcile*) echo CHECK; [ "$FAIL" != reconcile ]; return ;;
    *--list-due*) [ "$FAIL" != list ] || return 1; printf 'morning\\t123\\nmorning_press\\t123\\n'; return ;;
    *) echo "CALL:$*"; if [[ "$*" == *'--kind morning '* ]] && [ "$FAIL" = first ]; then return 1; fi ;;
  esac
}
'''
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([BASH, '--noprofile', '--norc', '-eo', 'pipefail'],
                                  input=fake + script, text=True, encoding='utf-8',
                                  capture_output=True, env={**os.environ, 'MODE': mode,
                                  'FAIL': fail, 'SOURCE_RUN': '123',
                                  'TEST_DIR': directory.replace('\\', '/')})

    def test_failure_is_reported_after_remaining_kinds_are_attempted(self):
        result = self.execute('publish_due', 'first')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('--kind morning_press --source-run 123 --publish', result.stdout)

    def test_successful_batch_finishes_successfully(self):
        result = self.execute('publish_due')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('CALL:'), 2)

    def test_listing_failure_does_not_appear_as_no_work(self):
        result = self.execute('publish_due', 'list')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('CALL:', result.stdout)

    def test_explicit_reconcile_never_creates_posts(self):
        result = self.execute('reconcile')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CALL:', result.stdout)
        self.assertNotEqual(self.execute('reconcile', 'reconcile').returncode, 0)

    def test_validation_is_not_publication(self):
        result = self.execute('validate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--source-run 123', result.stdout)
        self.assertNotIn('--publish', result.stdout)


if __name__ == '__main__':
    unittest.main()
