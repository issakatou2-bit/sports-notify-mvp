"""既定・掛け合いの保持と、素材欠落や古い声を採用しない検査。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import solo_host as host


class SoloHostTest(unittest.TestCase):
    def test_outro_credit_switches_with_portrait(self):
        import review_render_v3 as r3
        for selected, expected in (('metan', 'VOICEVOX:四国めたん'), ('ui', host.UI_CREDIT)):
            with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': selected}), patch.object(r3, 'LOOK', 'v4'), \
                 patch.object(r3, 'presenter'), patch.object(r3, 'source') as source:
                r3.outro(0)
                self.assertIn(expected, source.call_args.args[1])
                self.assertIn('MLB Stats API', source.call_args.args[1])

    def test_credit_follows_solo_voice_and_preserves_default(self):
        source = '保存材料\n音声: VOICEVOX:四国めたん\n出典: MLB公式'
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'metan'}):
            self.assertEqual(host.credit(source, [dict(speaker=2)]), source)
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'ui'}):
            self.assertIn(host.UI_CREDIT, host.credit(source, [dict(speaker=2)]))
            self.assertNotIn('VOICEVOX', host.credit(source, [dict(speaker=2)]))
            self.assertEqual(host.credit(source, [dict(speaker=2), dict(speaker=3)]), source)

    def test_default_and_duo(self):
        solo = [dict(speaker=2, text='成績です。', meta={})]
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': ''}):
            self.assertEqual(host.for_segments(solo), 'metan')
            self.assertEqual(host.presentation('metan', ('metan',)), ('metan', ('metan',)))
            host.validate_audio(solo)
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'ui'}):
            self.assertEqual(host.for_segments(solo), 'ui')
            self.assertEqual(host.presentation('metan', ('metan',)), ('ui', ('ui',)))
            self.assertEqual(host.presentation('metan', ('zundamon', 'metan')), ('metan', ('zundamon', 'metan')))
            self.assertEqual(host.for_segments(solo+[dict(speaker=3)]), 'metan')
            self.assertEqual(host.for_segments([dict(speaker=2, meta={'duo': True})]), 'metan')

    def test_stale_audio_is_rejected_in_both_directions(self):
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'ui'}):
            with self.assertRaisesRegex(ValueError, '保存音声'):
                host.validate_audio([dict(speaker=2)])
            host.validate_audio([dict(speaker=2, voice_host='ui')])
        with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'metan'}):
            with self.assertRaisesRegex(ValueError, '保存音声'):
                host.validate_audio([dict(speaker=2, voice_host='ui')])

    def test_missing_assets_and_auth_fail_explicitly(self):
        with patch.dict(os.environ, {'COLLESPO_UI_PORTRAIT_DIR': ''}):
            with self.assertRaisesRegex(ValueError, '既存立ち絵'):
                host.portrait('base', 500)
        with patch.dict(os.environ, {'VOISONA_API_USERNAME': '', 'VOISONA_API_PASSWORD': ''}):
            with self.assertRaisesRegex(ValueError, '認証'):
                host.synthesize('成績です。', Path('build/test-ui.wav'))

    def test_synthesis_manifest_records_actual_voice(self):
        import json
        import tempfile
        import synthesize_narration as sn
        build = Path(__file__).resolve().parents[1]/'build'
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as folder, \
             patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'ui'}):
            folder = Path(folder)
            (folder/'narration.json').write_text(json.dumps({'segments': [dict(speaker=2, text='成績です。', meta={})]}), encoding='utf8')
            args = ['synthesize_narration', '--narration', str(folder/'narration.json'), '--out-dir', str(folder)]
            with patch.object(sys, 'argv', args), patch.object(host, 'synthesize', return_value=True) as synth, \
                 patch.object(sn, 'audio_duration', return_value=2), patch.object(sn, 'engine_available') as vv:
                sn.main()
                synth.assert_called_once()
                vv.assert_not_called()
            saved = json.loads((folder/'manifest.json').read_text(encoding='utf8'))['segments']
            self.assertEqual(saved[0]['voice_name'], 'ui_ja_JP')
            host.validate_audio(saved)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
