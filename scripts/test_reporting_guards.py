import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import local_reporters as lr
import post_bluesky as bsky


class ReportingGuards(unittest.TestCase):
    def test_rbi_is_not_the_number_of_bases(self):
        for source, wrong, expected in [
            ("Shohei Ohtani's RBI double", '大谷翔平の2点二塁打', '大谷翔平の適時二塁打'),
            ("An RBI triple", '3打点の三塁打', '適時三塁打'),
            ("His two-run double", '2点二塁打', '2点二塁打'),
            ("His 2-RBI double", '2点二塁打', '2点二塁打'),
            ("His RBI double, second hit today", '2安打目の適時二塁打', '2安打目の適時二塁打')]:
            self.assertEqual(lr.guard_translation(source, wrong), expected)

    def test_unspecified_abs_actor_is_not_invented(self):
        source = 'Yunior Marte fans Shohei Ohtani after ABS challenge'
        translated = 'ユニオル・マルテがABS判定に異議を唱えた後、大谷翔平を三振に仕留める'
        self.assertEqual(lr.guard_translation(source, translated),
                         'ABSチャレンジ後、ユニオル・マルテが大谷翔平を三振に仕留める')
        self.assertEqual(lr.guard_translation('Marte challenges the call', translated), translated)

    def test_api_translation_goes_through_guard(self):
        msg = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(text='1. 大谷翔平の2点二塁打')])
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: msg))
        with patch.dict(sys.modules, {'anthropic':SimpleNamespace(Anthropic=lambda **kwargs:client)}), \
             patch.object(lr.token_log, 'allowed', return_value=True), patch.object(lr.token_log, 'record'):
            result = lr.translate([{'text':"Shohei Ohtani's RBI double"}], 'test-only')
        self.assertEqual(result[0]['jp'], '大谷翔平の適時二塁打')

    def test_empty_transport_error_is_visible_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'summary.md'
            err = TimeoutError()
            err.__cause__ = RuntimeError('private-token-must-not-appear')
            output=io.StringIO()
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY':str(dest)}), contextlib.redirect_stderr(output):
                bsky.report_failure(err, '送信')
            text=output.getvalue()+dest.read_text(encoding='utf-8')
            self.assertIn('TimeoutError',text)
            self.assertIn('RuntimeError',text)
            self.assertIn('送達は未確定',text)
            self.assertNotIn('private-token',text)


if __name__ == '__main__':
    unittest.main(argv=['test_reporting_guards'])
