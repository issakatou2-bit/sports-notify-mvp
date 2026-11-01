"""分割しても全試験を一度ずつ実行し、失敗を成功へ変えない。"""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_checks as checks
import yaml


class Execution(unittest.TestCase):
    def test_import_cache_preserves_transitive_cycles_and_refreshes_next_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts/a.py').write_text('import b\nimport requests\nimport os\n', encoding='utf8')
            (root / 'scripts/b.py').write_text('import a\nfrom PIL import Image\nimport helper\nimport notability_engine\n', encoding='utf8')
            helper = root / 'scripts/helper.py'
            helper.write_text('import pytest\n', encoding='utf8')
            (root / 'notability_engine.py').write_text('pass\n', encoding='utf8')
            cache = {}
            with patch.object(checks, 'ROOT', root):
                with patch.object(checks.ast, 'parse', wraps=checks.ast.parse) as parse:
                    self.assertEqual(checks._third_party('a.py', imports=cache), {'requests', 'PIL', 'pytest'})
                    self.assertEqual(checks._third_party('b.py', imports=cache), {'requests', 'PIL', 'pytest'})
                    self.assertEqual(parse.call_count, 3)
                helper.write_text('import bs4\n', encoding='utf8')
                self.assertEqual(checks._third_party('a.py', imports={}), {'requests', 'PIL', 'bs4'})

    def test_parallel_import_checks_keep_all_targets_and_import_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            for name, source in {'a.py': 'import argparse', 'b.py': 'import argparse',
                                 'test_a.py': 'import argparse', 'run_checks.py': 'import argparse',
                                 'helper.py': 'pass'}.items():
                (root / 'scripts' / name).write_text(source, encoding='utf8')
            with patch.object(checks, 'ROOT', root), patch.object(checks, 'IMPORT_WORKERS', 4), \
                    patch.object(checks, 'run', side_effect=lambda cmd: subprocess.CompletedProcess(
                        cmd, 1, stdout='', stderr='ImportError: fixture' if cmd[1].endswith('b.py') else '')) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(checks.check_imports(), 1)
            self.assertCountEqual([Path(call.args[0][1]).name for call in run.call_args_list],
                                  ['a.py', 'b.py'])
            self.assertTrue(all(call.args[0][-1] == '--help' for call in run.call_args_list))

    def test_shards_cover_all_tests_once_with_private_output_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            names = [f'test_case_{i:02}.py' for i in range(11)]
            for name in names:
                (root / 'scripts' / name).touch()
            calls = []

            def fake_run(cmd):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, int(cmd[1].endswith(names[7])),
                                                   stdout='NG fixture failure', stderr='')

            failures = 0
            with patch.object(checks, 'ROOT', root), patch.object(checks, 'run', fake_run), \
                    contextlib.redirect_stdout(io.StringIO()):
                for index in range(4):
                    with patch.object(checks, 'TEST_SHARD', (index, 4)):
                        failures += checks.check_tests(str(root / 'out'))
            self.assertEqual(failures, 1)
            self.assertCountEqual([Path(cmd[1]).name for cmd in calls], names)
            self.assertEqual(len({cmd[2] for cmd in calls}), len(names))
            self.assertTrue(all(Path(cmd[2]).is_dir() for cmd in calls))

    def test_syntax_checks_valid_and_invalid_files_without_subprocess(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'good.py').write_text('x = 1\n', encoding='utf8')
            (root / 'scripts' / 'bad.py').write_text('def broken(\n', encoding='utf8')
            (root / 'notability_engine.py').write_text('pass\n', encoding='utf8')
            with patch.object(checks, 'ROOT', root), patch.object(checks, 'run') as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(checks.check_syntax(), 1)
            run.assert_not_called()

    def test_ci_keeps_full_history_all_shards_and_required_check(self):
        doc = yaml.safe_load((checks.ROOT / '.github/workflows/checks.yml').read_text(encoding='utf8'))
        suite = doc['jobs']['check_suite']
        self.assertFalse(suite['strategy']['fail-fast'])
        entries = suite['strategy']['matrix']['include']
        self.assertEqual([e['shard'] for e in entries if e['section'] == 'tests'], [0, 1, 2, 3])
        self.assertEqual(sum(e['section'] == 'static' for e in entries), 1)
        self.assertEqual(suite['steps'][0]['with']['fetch-depth'], 0)
        self.assertEqual(doc['jobs']['checks']['needs'], 'check_suite')
        self.assertEqual(doc['jobs']['checks']['if'], 'always()')
        self.assertIn('test "$RESULT" = success', doc['jobs']['checks']['steps'][0]['run'])
        self.assertTrue(any('node --test scripts/test_web_*.cjs' in s.get('run', '')
                            for s in suite['steps']))

    def test_invalid_shard_fails_before_any_check(self):
        for value in ['-1/4', '4/4', '0/0', 'one/four', '1/2/3']:
            with self.subTest(value=value), patch.object(sys, 'argv', ['checks', '--test-shard='+value]), \
                    patch.object(checks, 'check_syntax') as syntax, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    checks.main()
                self.assertEqual(error.exception.code, 2)
                syntax.assert_not_called()

    def test_sections_partition_existing_checks_and_default_still_runs_all(self):
        import sanity_workflows

        names = [name for name in vars(checks) if name.startswith('check_')]
        for section in ['all', 'static', 'tests']:
            with self.subTest(section=section), contextlib.ExitStack() as stack:
                called = []
                for name in names:
                    fake = lambda *_, name=name: called.append(name) or 0
                    fake.__name__ = name
                    stack.enter_context(patch.object(checks, name, fake))
                stack.enter_context(patch.object(sanity_workflows, 'errors', return_value=[]))
                argv = ['checks'] if section == 'all' else ['checks', '--section', section]
                stack.enter_context(patch.object(sys, 'argv', argv))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                self.assertEqual(checks.main(), 0)
                expected = (names if section == 'all' else
                            ['check_tests'] if section == 'tests' else
                            [name for name in names if name != 'check_tests'])
                self.assertCountEqual(called, expected)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
