"""描画せず、生成器のコマ割当と音声・補助時刻表の境界を照合する。"""
import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import video_common as vc

HERE = Path(__file__).resolve().parent


class FrameTotalTest(unittest.TestCase):
    def assert_boundaries(self, counts, durations, fps):
        self.assertEqual(sum(counts), round(sum(durations) * fps))
        frame0, elapsed = 0, 0.0
        for n, duration in zip(counts, durations):
            self.assertLessEqual(abs(frame0 / fps - elapsed), .5 / fps + 1e-10)
            self.assertGreaterEqual(n, 0)
            frame0 += n
            elapsed += duration

    def test_many_segments_and_rates(self):
        for fps in (24, 30, 60, 29.97):
            for durations in ([1.03] * 20, [1.017] * 200,
                              [.01, 0, .019, .5] * 20, [1.015] * 21, []):
                with self.subTest(fps=fps, segments=len(durations)):
                    self.assert_boundaries(vc.segment_frame_counts(durations, fps), durations, fps)
        self.assertEqual(sum(vc.segment_frame_counts([1.03] * 20, 30)), 618)

    def test_actual_generator_allocation_without_rendering(self):
        # 実際の描画ループの入口だけ実行する。描画や ffmpeg は起動しない。
        expected = {'generate_asset_video.py': 1, 'generate_longform.py': 1,
                    'generate_morning_short.py': 2, 'generate_verdict_short.py': 1,
                    'generate_video.py': 1, 'generate_weekly.py': 1,
                    'generate_ps_preview.py': 1, 'preview_solo_host.py': 1,
                    'preview_motion.py': 1}
        for name, number in expected.items():
            tree = ast.parse((HERE / name).read_text(encoding='utf-8-sig'))
            loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)
                     and {'n'} <= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
                     and {'dur', 'duration'} & {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}]
            with self.subTest(generator=name):
                self.assertEqual(len(loops), number)
            for loop in loops:
                for durations in ([1.03] * 20, [1.017, 2.011, .505] * 20):
                    env = dict(FPS=30, fps=30, a=SimpleNamespace(fps=30), video_common=vc, vc=vc,
                               durations=durations, segs=[{}] * len(durations),
                               segments=[{}] * len(durations),
                               script={'segments': [{}] * len(durations)},
                               narr={'segments': [{}] * len(durations)},
                               narration={'segments': [{}] * len(durations)}, times=durations,
                               pages=[({}, d) for d in durations], counts=[])
                    if name == 'generate_longform.py':
                        allocation = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                                          and any(isinstance(t, ast.Name) and t.id == 'frame_counts'
                                                  for t in n.targets))
                        exec(compile(ast.Module(body=[allocation], type_ignores=[]), name, 'exec'), env)
                    body = ast.parse('counts.append(n)').body
                    isolated = ast.For(target=loop.target, iter=loop.iter, body=body, orelse=[])
                    module = ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[]))
                    exec(compile(module, name, 'exec'), env)
                    with self.subTest(generator=name, line=loop.lineno):
                        self.assertEqual(len(env['counts']), len(durations))
                        self.assert_boundaries(env['counts'], durations, 30)

    def test_longform_pages_and_sound_cues(self):
        import longform_render_v3 as lr3
        durations = [1.03] * 20
        pages = [(dict(kind='talk', panel=str(i), chapter=i), d)
                 for i, d in enumerate(durations)]
        rows = lr3.timeline(pages, {str(i): {} for i in range(20)}, 30)
        self.assert_boundaries([r['frames'] for r in rows], durations, 30)
        frame0 = 0
        for row in rows:
            self.assertEqual(row['start'], frame0 / 30)
            frame0 += row['frames']
        with patch.object(lr3, 'cues', return_value=[(0, 'transition', 'b', 0)]):
            cues = lr3.all_cues(pages, {}, fps=30)
        self.assertEqual([c[0] for c in cues], [round(r['start'], 3) for r in rows])

    def test_lipsync_and_expressions_share_frame_boundaries(self):
        import lipsync
        import fan_events
        durations = [1.03] * 20
        segments = [dict(text='確認です。', speaker=2, duration=1.02)] * 20
        with tempfile.TemporaryDirectory() as td, \
                patch.object(lipsync, 'enabled', return_value=True), \
                patch.object(fan_events, 'enabled', return_value=True), \
                patch.object(fan_events, 'decision', return_value={'reason': '確認'}), \
                patch('motion.enabled', return_value=False):
            lipsync.prepare(segments, durations, td, fps=30)
            fan_events.prepare({}, segments, durations, td, fps=30)
            for track in (lipsync.TRACK, fan_events.TRACK):
                self.assert_boundaries([round((r['end'] - r['start']) * 30) for r in track], durations, 30)
                for i, row in enumerate(track):
                    self.assertAlmostEqual(row['start'], round(sum(durations[:i]) * 30) / 30)
            for a, b in zip(lipsync.TRACK, fan_events.TRACK):
                self.assertEqual((a['start'], a['end']), (b['start'], b['end']))
            lipsync.TRACK.clear()
            fan_events.TRACK.clear()

    def test_hook_receipt_matches_rendered_frames_and_audio(self):
        import hook_ab
        durations = [1.03] * 20
        segments = [dict(kind='talk', text='確認です。', speaker=2,
                         file='voice.wav', duration=1.02) for _ in durations]
        narration = dict(hook_ab={'ab_variant': 'A'}, segments=segments)
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / 'video.mp4'
            video.write_bytes(b'unit test')
            hook_ab.bind_video(video, narration, segments, durations, 30)
            receipt = json.loads(hook_ab.receipt_path(video).read_text(encoding='utf-8'))
        self.assertEqual(receipt['duration_seconds'], 618 / 30)
        for i, row in enumerate(receipt['dialogue_starts']):
            self.assertAlmostEqual(row['start'], sum(durations[:i]), places=6)
            self.assertLessEqual(abs(row['scene_start'] - row['start']), .5 / 30 + 1e-6)

    def test_audio_keeps_small_gaps_and_cumulative_sample_count(self):
        # 以前は各10msの無音が省かれ、20区間で0.2秒早まっていた。
        durations = [1.0301] * 20
        with tempfile.TemporaryDirectory() as td, \
                patch('solo_host.validate_audio'), patch('lipsync.prepare'), \
                patch.object(vc.subprocess, 'run'):
            out = Path(td)
            source = out / 'voice.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setparams((1, 2, 1000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 1020)
            vc.build_narration_track([dict(file=str(source))] * 20, durations, out)
            samples = 0
            parts = (out / 'audio_list.txt').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(parts), 40)
            for i in range(20):
                self.assertLessEqual(abs(samples / 1000 - sum(durations[:i])), .0005 + 1e-10)
                for entry in parts[2*i:2*i+2]:
                    with wave.open(entry[6:-1], 'rb') as wav:
                        samples += wav.getnframes()
            self.assertEqual(samples, round(sum(durations) * 1000))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
