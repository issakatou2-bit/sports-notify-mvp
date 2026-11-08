"""ショートの締め・重複表示・実音声の音量と圧縮後の上限。"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import short_common as common
import sound_mix as sound


class ShortCommonTests(unittest.TestCase):
    def test_only_promotion_changes(self):
        body = dict(kind='list', text='本編の事実です。', speaker=3, meta=dict(start=1))
        original = dict(segments=[body, dict(kind='next_program', text='番組案内です。', meta={}),
            dict(kind='outro', text='長い案内です。', speaker=2, meta={})])
        result = common.prepare(original)
        self.assertEqual(result['segments'][0], body)
        self.assertEqual(len(original['segments']), 3)
        self.assertEqual([s['kind'] for s in result['segments']], ['list', 'outro'])
        self.assertEqual(result['segments'][-1]['text'], common.OUTRO_TEXT)

    def test_every_duration_planner_uses_short_outro(self):
        import generate_morning_short as morning
        import generate_asset_video as asset
        import duo
        import generate_verdict_short as verdict
        import soccer_results_render as results
        import soccer_slots_v4 as slots
        import synthesize_narration as synth
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'voice.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(np.zeros(24000*2, dtype='<i2').tobytes())
            segment = common.prepare(dict(segments=[dict(kind='outro', text='旧案内', speaker=2, meta={})]))['segments'][0]
            voice = dict(segment, duration=2.0, file=str(path))
            for planner in (morning.plan_durations, asset.plan_durations, duo.durations, verdict.plan_durations):
                with self.subTest(planner=planner.__module__):
                    self.assertLessEqual(planner([voice])[0], 2.5)
            with patch.object(synth, 'audio_duration', return_value=2.0):
                for planner in (results.durations, slots.durations):
                    with self.subTest(planner=planner.__module__):
                        self.assertLessEqual(planner([segment], [voice])[0], 2.5)
            with patch.object(synth,'audio_duration',return_value=2.45), patch.object(slots.motion,'enabled',return_value=True):
                measured=dict(voice,duration=2.45)
                self.assertLessEqual(slots.video_times([segment],[measured])[0],2.5)
        self.assertEqual(common.duration(dict(kind='outro', duration=2.45), 10), 2.5)
        with self.assertRaisesRegex(ValueError, '2.5秒'):
            common.duration(dict(kind='outro', duration=3), 10)

    def test_duplicate_caption_keeps_extra_explanation(self):
        from PIL import Image
        image = Image.new('RGB', (1080, 1920))
        image.info['v3_layout'] = [dict(role='text', text='大きな引用の', box=[72, 400, 800, 470]),
                                  dict(role='text', text='本文です。', box=[72, 480, 800, 550])]
        self.assertTrue(common.duplicate_caption(image, '「大きな引用の本文です。」'))
        self.assertFalse(common.duplicate_caption(image, 'その理由を補足します。'))
        image.info['short_visible_texts'] = ['防御率1.20です。']
        self.assertFalse(common.duplicate_caption(image, '防御率12.0です。'))
        self.assertEqual(common.prepare({'can_make': False}), {'can_make': False})

    def test_displayed_team_alias_does_not_repeat_quote(self):
        with patch.dict(__import__('os').environ, COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan', COLLESPO_BUBBLE='slant'):
            import short_saved_render
            short_saved_render.setup()
            import review_render_v3 as render
            import short_v4_cards as cards
            quote = 'Dodgersの守備を評価する文です。'
            with patch.object(render, 'LOOK', 'v4'):
                for text, expected in [(quote, False), ('引用の背景を補足します。', True)]:
                    render.set_program_clock(0)
                    render.set_caption(text, 8, 20)
                    render.set_program_clock(1)
                    image = cards.quotes(1, [dict(said=quote, at=0, end=8)], 'ファンの声', '', '', '')
                    self.assertEqual('bubble_style' in image.info, expected)
                render.set_program_clock(None)

    def test_duo_caption_suppresses_only_matching_text(self):
        from PIL import Image
        import review_render_v3 as render
        import duo_presenter
        with patch.object(render, '_PROGRAM_CLOCK', [None]), patch.dict(render._CAPTION,
                dict(text='引用の本文です。', duration=5, start=0, hide_caption=False)):
            image = Image.new('RGB', (1080, 1920))
            image.info['short_visible_texts'] = ['引用の本文です。']
            duo_presenter.caption(image, 1)
            self.assertFalse(image.info.get('v3_layout'))
            image.info['short_visible_texts'] = ['異なる説明です。']
            duo_presenter.caption(image, 1)
            self.assertTrue(image.info.get('v3_layout'))

    def test_real_next_match_card_is_kept(self):
        card = dict(kind='next_line', text='次の試合は明日です。', meta=dict(screen='next-match'))
        result = common.prepare(dict(segments=[card]))
        self.assertEqual(result['segments'][0], card)
        self.assertEqual(result['segments'][-1]['kind'], 'outro')
        for value in [float('nan'), float('inf'), -1]:
            with self.assertRaises(ValueError):
                common.duration(dict(kind='outro', duration=value), 5)

    def test_same_card_speaker_change_has_no_extra_sound(self):
        segments = [dict(kind='list', meta=dict(duo=True, screen=1)),
                    dict(kind='list', meta=dict(duo=True, screen=1)),
                    dict(kind='list', meta=dict(duo=True, screen=2)),
                    dict(kind='outro', meta={})]
        self.assertEqual([c[0] for c in common.transition_cues(segments, [2, 3, 4, 2])], [5, 9])

    def test_longform_copy_and_old_mixer_defaults_remain(self):
        import review_render_v3 as render
        self.assertIn('明日の試合', render.INSEASON_OUTRO_TEXT)
        self.assertGreater(len(render.INSEASON_OUTRO_TEXT), len(common.OUTRO_TEXT))
        self.assertEqual(sound.BGM_DB, -15)
        self.assertEqual(sound.DUCK_DB, -5)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpegが必要')
    def test_measured_music_voice_gap_and_encoded_peak(self):
        # 声の大小と長い無音を含む対照で、既存BGMと切替音を実際に重ねる。
        rate = 24000
        seconds = 6
        t = np.arange(rate*seconds)/rate
        for name, amplitude in [('normal', .18), ('quiet', .025), ('hot', .7), ('spike', .18)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                envelope = (.15+.85*np.sin(2*np.pi*2.3*t)**2) * ((t % 2) < 1.4)
                voice = amplitude*(np.sin(2*np.pi*220*t)+.22*np.sin(2*np.pi*1100*t))*envelope
                if name == 'spike':
                    voice[rate*3] = .99
                with wave.open(str(out/'voice.wav'), 'wb') as output:
                    output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                    output.writeframes((voice*32767).astype('<i2').tobytes())
                sound.mix_short_file(out/'voice.wav', out/'mixed.wav', sound.bgm_path(),
                    cues=[(2, 'transition', 'b', -12), (4, 'transition', 'b', -12)])
                report = json.loads((out/'audio_mix.json').read_text(encoding='utf-8'))
                self.assertTrue(report['pass'])
                self.assertAlmostEqual(report['bgm_below_voice_lu'], 15, delta=1)
                self.assertLessEqual(report['mixed']['true_peak_dbtp'], -1.5)
                subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(out/'mixed.wav'),
                    '-c:a', 'aac', '-b:a', '160k', str(out/'encoded.m4a')], check=True, capture_output=True)
                encoded = sound.verify_short_video(out/'encoded.m4a')
                self.assertLessEqual(encoded['true_peak_dbtp'], -1)
                print('SHORT_AUDIO_MEASUREMENT '+json.dumps(dict(case=name,
                    voice_lufs=report['voice_measured']['lufs'], bgm_lufs=report['bgm_measured']['lufs'],
                    gap_lu=report['bgm_below_voice_lu'], mixed=report['mixed'], encoded=encoded)))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
