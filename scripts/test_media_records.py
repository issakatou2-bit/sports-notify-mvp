"""出所の取り違え・欠番・丸め・字幕分割・保存漏れを固定した素材で検査する。"""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import media_records_check
import render_timeline
import voice_manifest
from voice_test_fixture import wav_file

ROOT = Path(__file__).resolve().parents[1]


class MediaRecords(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'build')
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_actual_voice_and_original_rain_voice_plan_are_separate(self):
        path = self.folder / 'seg_004.wav'
        wav_file(path)
        segment = dict(index=4, speaker=2, file=str(path), text='固定の台詞', duration=999)
        plan = dict(host_delivery=dict(planned_host='metan', previous_attempt=dict(planned_host='ui')),
                    voice_resolution=dict(host='metan', reason='ui_rebuilt_after_hold'))
        before = path.read_bytes()
        result = voice_manifest.save(self.folder, [segment], plan)
        row = result['segments'][0]
        self.assertEqual((row['line_id'], row['speaker_key'], row['voice_engine'], row['speaker']),
                         (5, 'metan', 'voicevox', 2))
        self.assertEqual((row['planned_host'], row['planned_engine']), ('ui', 'voisona'))
        self.assertEqual(row['file'], 'seg_004.wav')
        self.assertEqual(row['duration'], .25)
        self.assertEqual(row['sha256'], voice_manifest.sha256(path))
        self.assertEqual(path.read_bytes(), before)

    def test_voisona_never_inherits_voicevox_speaker_and_missing_voice_is_explicit(self):
        path = self.folder / 'seg_000.wav'
        wav_file(path)
        rows = voice_manifest.save(self.folder, [dict(speaker=2, file=str(path), voice_engine='voisona'),
                                                dict(speaker=3, file=None)])['segments']
        self.assertIsNone(rows[0]['speaker'])
        self.assertEqual((rows[0]['source_speaker'], rows[0]['actual_voice_key']), (2, 'ui'))
        self.assertEqual((rows[1]['voice_engine'], rows[1]['sha256'], rows[1]['status']), (None, None, 'unavailable'))
        voice_manifest.record_file(path, '実際の雨衣', 'voisona', 2)
        voice_manifest.save(self.folder, [], dict(host_delivery=dict(planned_host='ui')), status='held')
        held = json.loads((self.folder / 'voice_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((held['status'], held['segments'], held['planned_host']), ('held', [], 'ui'))

    def test_shortened_audio_keeps_the_original_line_and_plan(self):
        source = self.folder / 'seg_003.wav'
        wav_file(source)
        voice_manifest.save(self.folder, [dict(index=3, speaker=2, file=str(source), text='長い文')],
                            dict(host_delivery=dict(planned_host='ui')))
        shortened = self.folder / 'seg_003_short.wav'
        wav_file(shortened, frames=3000)
        voice_manifest.record_file(shortened, '短い文', 'voicevox', 2)
        saved = json.loads((self.folder / 'voice_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved['segments']), 1)
        row = saved['segments'][0]
        self.assertEqual((row['line_id'], row['file'], row['duration']), (4, shortened.name, .125))
        self.assertEqual((row['planned_host'], row['planned_engine'], row['voice_engine']), ('ui', 'voisona', 'voicevox'))

    def test_direct_synthesis_writes_actual_wave_fingerprint(self):
        import synthesize_narration as synth
        from types import SimpleNamespace
        source = self.folder / 'source.wav'
        wav_file(source)
        target = self.folder / 'seg_002.wav'
        response = SimpleNamespace(content=source.read_bytes(), json=lambda: {}, raise_for_status=lambda: None)
        with patch.object(synth.requests, 'post', return_value=response), \
             patch.object(synth.name_reading_guard, 'prepare_query', return_value={}), \
             patch.object(synth.name_reading_guard, 'validate_query', return_value={}):
            self.assertTrue(synth.synth_one('晴れです。', 3, target))
        row = json.loads((self.folder / 'voice_manifest.json').read_text(encoding='utf-8'))['segments'][0]
        self.assertEqual((row['line_id'], row['voice_engine'], row['speaker']), (3, 'voicevox', 3))
        self.assertEqual(row['sha256'], voice_manifest.sha256(target))

    def test_fitted_file_uses_explicit_source_line_instead_of_filename_order(self):
        path = self.folder / 'fit_2_digest.wav'
        wav_file(path)
        voice_manifest.record_file(path, '短い文', 'voicevox', 2,
                                   planned=dict(host_delivery=dict(planned_host='metan')))
        voice_manifest.record_file(path, '短い文', 'voicevox', 2, index=9,
                                   planned=dict(host_delivery=dict(planned_host='ui')))
        saved = json.loads((self.folder / 'voice_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved['segments']), 1)
        self.assertEqual((saved['segments'][0]['line_id'], saved['segments'][0]['planned_host']), (10, 'ui'))

    def test_observed_frames_keep_original_ids_pages_gaps_and_chorus(self):
        sources = [dict(index=3, text='長い台詞', speaker=2), dict(index=7, text='外した台詞'),
                   dict(index=8, text='コレスポ'), dict(index=9, text='コレスポ')]
        recorder = render_timeline.Recorder(30, sources)
        pipe = io.BytesIO()
        image = Image.new('RGB', (4, 4), 'red')
        untouched = image.tobytes()
        recorder.select(sources[0], 0)
        recorder.write(pipe, untouched, image)  # 字幕なしの最初の1コマ
        render_timeline.subtitle(image, '前半')
        recorder.write(pipe, untouched, image)
        recorder.repeat(pipe, untouched)  # キャッシュを再使用
        image.info.clear()
        render_timeline.subtitle(image, '後半')
        render_timeline.scene(image, dict(page=2))
        recorder.write(pipe, untouched, image)
        recorder.select(dict(_source_line_ids=[9, 10], kind='intro'), 2)
        image.info.clear()
        recorder.write(pipe, untouched, image, overlap=True)
        recorder.write(pipe, untouched, image)  # 完成mp4ではこのコマを短縮
        self.assertEqual(image.tobytes(), untouched)
        self.assertEqual(pipe.getvalue(), untouched * 6)
        video = self.folder / 'test.mp4'
        video.write_bytes(b'fixture only')
        probe = dict(streams=[dict(nb_frames='5', avg_frame_rate='30/1')])
        with patch.object(render_timeline.subprocess, 'run', return_value=type('Probe', (), {'stdout': json.dumps(probe)})()):
            result = recorder.save(video, self.folder)
        self.assertEqual((result['frame_count'], result['written_frame_count']), (5, 6))
        self.assertEqual([r['line_id'] for r in result['lines']], [4, 9])
        self.assertEqual(result['lines'][1]['source_line_ids'], [9, 10])
        for rows, identity in ((result['lines'], 'line_id'), (result['cuts'], 'cut_id')):
            self.assertTrue(all(type(row[identity]) is int and row[identity] > 0 for row in rows))
            self.assertEqual(len({row[identity] for row in rows}), len(rows))
            self.assertEqual(rows[0]['start'], 0)
            self.assertEqual(rows[-1]['end'], result['frame_count'] / result['fps'])
        self.assertEqual(result['lines'][0]['subtitle_start'], 1 / 30)
        self.assertEqual(result['lines'][0]['subtitle_end'], 5 / 30)
        self.assertEqual(result['source_lines'][1]['rendered'], False)
        self.assertEqual(result['cuts'][-1]['end_frame'], 5)
        self.assertEqual([r['subtitle'] for r in result['subtitles'] if not r.get('intentional')], ['', '前半', '後半', ''])
        self.assertTrue((video.with_suffix('') / 'voice_manifest.json').is_file())

    def test_real_encoded_frames_and_relative_manifest(self):
        import ui_voice_queue
        from shutil import which
        if not which('ffprobe'):
            self.skipTest('ffprobeが必要です')
        audio = self.folder / 'audio'
        audio.mkdir()
        source = audio / 'seg_000.wav'
        wav_file(source)
        segments = [dict(index=0, file=str(source), speaker=2, text='固定')]
        voice_manifest.save(audio, segments)
        video = self.folder / 'small.mp4'
        process = subprocess.Popen([ui_voice_queue.ffmpeg(), '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                    '-s', '16x16', '-r', '30', '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)],
                                   stdin=subprocess.PIPE)
        recorder = render_timeline.Recorder(30, segments)
        recorder.select(segments[0], 0)
        image = Image.new('RGB', (16, 16), '#223344')
        for _ in range(4):
            recorder.write(process.stdin, image.tobytes(), image)
        process.stdin.close()
        self.assertEqual(process.wait(), 0)
        result = recorder.save(video, audio)
        self.assertEqual(result['frame_count'], 4)
        saved = json.loads((video.with_suffix('') / 'voice_manifest.json').read_text(encoding='utf-8'))
        row = saved['segments'][0]
        actual = video.with_suffix('') / row['file']
        self.assertEqual(actual.resolve(), source.resolve())
        self.assertEqual(row['sha256'], voice_manifest.sha256(actual))

    def test_artifact_missing_one_json_or_other_job_is_detected(self):
        folder = self.folder / '.github/workflows'
        folder.mkdir(parents=True)
        path = folder / 'test.yml'
        text = '''jobs:
  build:
    steps:
      - run: python scripts/generate_asset_video.py
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          path: |
            build/**/voice_manifest.json
            build/**/render_timeline.json
'''
        path.write_text(text, encoding='utf-8')
        self.assertEqual(media_records_check.errors(self.folder), [])
        path.write_text(text.replace('            build/**/voice_manifest.json\n', ''), encoding='utf-8')
        self.assertEqual(len(media_records_check.errors(self.folder)), 1)
        path.write_text(text.replace('if: always()', 'if: success()'), encoding='utf-8')
        self.assertEqual(len(media_records_check.errors(self.folder)), 2)
        self.assertEqual(media_records_check.errors(ROOT), [])

    def test_record_failure_never_stops_video_or_voice(self):
        # 記録は確認用。壊れても動画・音声づくりは成功のまま（警告だけ）。
        recorder = render_timeline.Recorder(30, [dict(index=0, text='台詞')])
        recorder.select(dict(index=0), 0)
        stream = io.BytesIO()
        with patch('builtins.print') as log:
            recorder.repeat(stream, b'xx')  # 描画前のキャッシュ
            recorder.write(stream, b'yy', Image.new('RGB', (2, 2)))
            self.assertIsNone(recorder.save(self.folder / 'none.mp4', self.folder))
        self.assertEqual(stream.getvalue(), b'xxyy')
        self.assertIn('::warning::', str(log.call_args_list))
        fresh = render_timeline.Recorder(30, [dict(index=0, text='台詞')])
        with patch('builtins.print') as log, patch.object(fresh, '_save', side_effect=ValueError('不一致')):
            self.assertIsNone(fresh.save(self.folder / 'none.mp4', self.folder))
        self.assertIn('不一致', str(log.call_args_list))
        broken = self.folder / 'broken'
        broken.mkdir()
        (broken / 'voice_manifest.json').write_text('{壊れた', encoding='utf-8')
        with patch('builtins.print') as log:
            self.assertIsNone(voice_manifest.record_file(broken / 'seg_000.wav', '文', 'voicevox', 2))
            self.assertIsNone(voice_manifest.save(broken, [dict(file=str(broken / 'missing.wav'), speaker=2)], None, status=object()))
        self.assertIn('声の出所の記録', str(log.call_args_list))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
