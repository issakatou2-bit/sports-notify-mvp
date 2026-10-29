"""10/15の尺超過と10/14の無変更を、保存材料と作り物のWAVで再現する。"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

import soccer_selected_preview as selected
import soccer_slots_v4 as slots
import soccer_preview_history as history
import synthesize_narration as sn

FIX = Path(__file__).parent / 'fixtures' / 'soccer-length'


def wav(path, seconds):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(1000)
        out.writeframes(b'\0\0' * round(seconds * 1000))


def material(day, folder):
    fixture = json.loads((FIX / (day + '.json')).read_text(encoding='utf-8'))
    plan = selected.program(fixture['data'])
    # 点検用の入力材料は追加されるが、台詞・札・話者・表示時間の契約は同一。
    evidence = {'soccer_material', 'sanity_materials', 'sanity_date_jst'}
    actual = {k: v for k, v in plan['narration'].items() if k not in evidence}
    expected = {k: v for k, v in fixture['narration'].items() if k not in evidence}
    if actual != expected:
        raise AssertionError('保存原稿の組み立てが変わりました')
    audio = []
    for i, (seg, seconds) in enumerate(zip(plan['narration']['segments'], fixture['audio_seconds'])):
        path = folder / f'seg_{i:03d}.wav'; wav(path, seconds)
        audio.append(dict(copy.deepcopy(seg), file=str(path), duration=seconds, index=i))
    return plan, audio


class SoccerLength(unittest.TestCase):
    def snapshot(self, plan):
        record = dict(video_id='test-video', preview_binding=history.binding(plan['data'], plan['narration']))
        day = plan['data']['generated_at'][:10]
        return history.snapshot(plan['data'], plan['narration'], {'daily_soccer': {day: record}})

    def test_oct15_58587_fits_including_motion_tail_and_rounding(self):
        for moving in (False, True):
            with self.subTest(motion=moving), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory); plan, audio = material('2026-10-15', folder)
                original = copy.deepcopy(plan)
                base = {row['file']: (row['text'], row['duration']) for row in audio}
                changed = []
                def synth(text, speaker, path):
                    old_text, seconds = base[str(path.with_name(path.name.replace('_short', '')))]
                    wav(path, seconds * len(text) / len(old_text)); changed.append(text)
                    return True
                with patch.object(slots.motion, 'enabled', return_value=moving), \
                     patch.object(sn, 'synth_one', side_effect=synth), \
                     patch.object(sn, 'audio_duration', side_effect=lambda p: wave_seconds(p)), \
                     patch('sys.stdout', new_callable=io.StringIO) as log:
                    self.assertAlmostEqual(sum(slots.durations(plan['narration']['segments'], audio, False)), 58.587)
                    slots.fit_preview(plan, audio)
                    seconds = sum(slots.video_times(plan['narration']['segments'], audio))
                    self.assertLessEqual(seconds, 55)
                    self.assertTrue(changed); self.assertIn('[shorten]', log.getvalue())
                    self.assertEqual(len(audio), len(plan['narration']['segments']))
                    self.assertEqual(len([s for s in plan['narration']['segments'] if s['kind'] == 'preview']), 4)
                    # 最初の変更は最後の試合の補足。時刻と対戦は全件保持。
                    self.assertTrue(changed[0].startswith(original['narration']['segments'][-2]['text'].split('。')[0]))
                    for before, after in zip(original['narration']['segments'], plan['narration']['segments']):
                        self.assertEqual(before['meta'], after['meta'])
                        self.assertTrue(after['text'].startswith(before['text'].split('。')[0]))
                    self.assertEqual(len(self.snapshot(plan)['games']), 4)
                print(f'10/15 synthetic 58.587 -> {seconds:.3f}s (motion={moving})')

    def test_oct14_51_seconds_untouched(self):
        for moving in (False, True):
            with self.subTest(motion=moving), tempfile.TemporaryDirectory() as directory:
                plan, audio = material('2026-10-14', Path(directory))
                before = copy.deepcopy((plan, audio))
                with patch.object(slots.motion, 'enabled', return_value=moving), patch.object(sn, 'synth_one') as synth:
                    slots.fit_preview(plan, audio)
                    self.assertEqual((plan, audio), before); synth.assert_not_called()
                    self.assertLessEqual(sum(slots.video_times(plan['narration']['segments'], audio)), 55)
                    self.assertAlmostEqual(sum(slots.durations(plan['narration']['segments'], audio)), 51)

    def test_drop_fourth_then_third_and_keep_first_two(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, audio = material('2026-10-15', Path(directory))
            for seg, row in zip(plan['narration']['segments'], audio):
                if seg['kind'] == 'preview':
                    seg['text'] = seg['text'].split('。')[0] + '。'
                    seg['meta']['interest']['player'] = None
                    row.update(text=seg['text'], duration=22); wav(Path(row['file']), 22)
                    row['meta'] = copy.deepcopy(seg['meta'])
            ids = [s['meta']['game_id'] for s in plan['narration']['segments'] if s['kind'] == 'preview']
            with patch.object(slots.motion, 'enabled', return_value=False), patch('sys.stdout', new_callable=io.StringIO) as log:
                slots.fit_preview(plan, audio)
                self.assertLessEqual(sum(slots.video_times(plan['narration']['segments'], audio)), 55)
                self.assertEqual([s['meta']['game_id'] for s in plan['narration']['segments'] if s['kind'] == 'preview'], ids[:2])
                self.assertLess(log.getvalue().index('4試合目'), log.getvalue().index('3試合目'))
                self.assertEqual([g['game_id'] for g in self.snapshot(plan)['games']], ids[:2])
                # 短縮の記録なし・順序の入れ替えは引き続き拒否する。
                adjustment = plan['narration'].pop('preview_length_adjustment')
                with self.assertRaisesRegex(ValueError, '選定順'):
                    self.snapshot(plan)
                plan['narration']['preview_length_adjustment'] = adjustment
                adjustment['kept_ids'].reverse()
                with self.assertRaisesRegex(ValueError, '選定順'):
                    self.snapshot(plan)

    def test_extreme_length_still_keeps_one_match_under_55(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, audio = material('2026-10-15', Path(directory))
            for row in audio:
                row['duration'] = 60; wav(Path(row['file']), 60)
            def synth(text, speaker, path):
                wav(path, 60 if text != '注目の一戦です。' else 3)
                return True
            with patch.object(slots.motion, 'enabled', return_value=True), \
                 patch.object(sn, 'synth_one', side_effect=synth), \
                 patch.object(sn, 'audio_duration', side_effect=wave_seconds), \
                 patch('sys.stdout', new_callable=io.StringIO):
                slots.fit_preview(plan, audio)
                self.assertLessEqual(sum(slots.video_times(plan['narration']['segments'], audio)), 55)
                self.assertEqual(len([s for s in plan['narration']['segments'] if s['kind'] == 'preview']), 1)
                self.assertEqual(len(self.snapshot(plan)['games']), 1)

    def test_compat_passes_fitted_plan_and_saves_matching_audio_and_script(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); audio_dir = folder / 'audio'; audio_dir.mkdir()
            plan, audio = material('2026-10-15', audio_dir)
            data = folder / 'games.json'; data.write_text(json.dumps(plan['data']), encoding='utf-8')
            narration = folder / 'soccer_narration.json'
            narration.write_text(json.dumps(plan['narration']), encoding='utf-8')
            manifest = audio_dir / 'manifest.json'
            manifest.write_text(json.dumps(dict(segments=audio)), encoding='utf-8')
            def synth(text, speaker, path):
                wav(path, 5); return True
            def render(fitted, voices, out):
                self.assertLessEqual(sum(slots.video_times(fitted['narration']['segments'], voices)), 55)
                for seg, row in zip(fitted['narration']['segments'], voices):
                    self.assertEqual(seg['text'], row['text'])
                return dict(seconds=54)
            with patch.object(slots, 'program', return_value=plan), \
                 patch.object(slots.motion, 'enabled', return_value=True), \
                 patch.object(sn, 'synth_one', side_effect=synth), \
                 patch.object(sn, 'audio_duration', side_effect=wave_seconds), \
                 patch.object(slots, 'render_video', side_effect=render) as draw:
                slots.run_compat('preview', data, audio_dir=audio_dir, out=folder / 'video')
            draw.assert_called_once()
            saved = json.loads(narration.read_text(encoding='utf-8'))
            rows = json.loads(manifest.read_text(encoding='utf-8'))['segments']
            self.assertEqual(saved, plan['narration'])
            self.assertEqual([s['text'] for s in saved['segments']], [r['text'] for r in rows])


def wave_seconds(path):
    with wave.open(str(path), 'rb') as source:
        return source.getnframes() / source.getframerate()


if __name__ == '__main__':
    unittest.main(argv=[__file__])
