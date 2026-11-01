"""偽の記録・素材だけで送信境界と実時刻の保持を確認する。"""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import av_check_inputs as link
import gemini_av_check as av

BASE = (Path(sys.argv[1]) if __name__ == '__main__' and len(sys.argv) > 1
        else Path(__file__).resolve().parents[1]/'build'/'av-input-tests')
BASE.mkdir(parents=True, exist_ok=True)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=BASE))
        self.video = self.root/'video.mp4'
        self.video.write_bytes(b'fake video')
        self.voice_path, self.record_path = self.root/'voice.json', self.root/'record.json'
        (self.root/'voice.wav').write_bytes(b'fake voice')
        (self.root/'screen.png').write_bytes(b'fake screen')
        (self.root/'drawing.py').write_text('# fake drawing', encoding='utf-8')
        self.voice = dict(version=1, segments=[dict(line_id=1, text='前半。後半。', file='voice.wav',
            voice_engine='voicevox', speaker=2, duration=999, sha256=av.sha256(self.root/'voice.wav'))])
        av.write_json(self.voice_path, self.voice)
        self.record = dict(version=1, fps=30, frame_count=60, video_sha256=av.sha256(self.video),
            voice_manifest_sha256=av.sha256(self.voice_path),
            lines=[dict(line_id=1, source_line_ids=[1], text='前半。後半。', subtitle='前半。後半。',
                        start_frame=0, end_frame=60, start=0, end=2)],
            cuts=[dict(cut_id=1, screen='自作の色札', start_frame=0, end_frame=60, start=0, end=2)],
            subtitles=[dict(source_line_ids=[1], subtitle='前半。', start_frame=0, end_frame=21, start=0, end=.7),
                       dict(source_line_ids=[1], subtitle='後半。', start_frame=21, end_frame=60, start=.7, end=2)])
        av.write_json(self.record_path, self.record)
        self.review = dict(video_sha256=av.sha256(self.video), render_timeline_sha256=av.sha256(self.record_path),
            all_assets_accounted_for=True, reviewed_cut_ids=[1, 2],
            drawing_code=[dict(path='drawing.py', sha256=av.sha256(self.root/'drawing.py'), evidence='描画コードを読んだ')],
            review=dict(evidence='コードと全画面を確認した偽の試験材料', official_art=False,
                personal_information=False, secrets=False, poster_names=False, unreleased_private_material=False),
            assets=[dict(kind='rendered_screen', classification='self_created', self_created=True,
                path='screen.png', sha256=av.sha256(self.root/'screen.png'), evidence='コード自作の色札')])
        self.review_path = self.root/'review.json'
        av.write_json(self.review_path, self.review)

    def convert(self):
        return link.timeline(self.record, self.voice, av.sha256(self.video), av.sha256(self.voice_path), 2)

    def run_link(self, review=True):
        av.write_json(self.voice_path, self.voice)
        self.record['voice_manifest_sha256'] = av.sha256(self.voice_path)
        av.write_json(self.record_path, self.record)
        self.review['render_timeline_sha256'] = av.sha256(self.record_path)
        av.write_json(self.review_path, self.review)
        args = ['--video', str(self.video), '--render-timeline', str(self.record_path),
                '--voice-manifest', str(self.voice_path), '--out', str(self.root/'out')]
        if review:
            args += ['--review', str(self.review_path)]
        with patch.object(av, 'media_probe', return_value=2):
            return link.main(args)

    def test_real_frames_and_subtitle_pages_not_audio_duration(self):
        script = self.convert()
        self.assertEqual([c['start'] for c in script['cuts']], [0, .7])
        self.assertEqual(script['lines'][0]['end'], 2)
        self.assertEqual(script['lines'][0]['source_line_ids'], [1])
        self.assertEqual(len(script['lines'][0]['subtitle_pages']), 2)

    def test_gaps_overlaps_and_missing_tail(self):
        original = copy.deepcopy(self.record)
        for kind in ('lines', 'cuts', 'subtitles'):
            for edge in ('gap', 'overlap', 'tail'):
                with self.subTest(kind=kind, edge=edge):
                    self.record = copy.deepcopy(original)
                    row = self.record[kind][-1]
                    if edge == 'tail': row['end_frame'] -= 1; row['end'] -= 1/30
                    elif edge == 'gap': row['start_frame'] += 1; row['start'] += 1/30
                    else: row['start_frame'] -= 1; row['start'] -= 1/30
                    with self.assertRaises(av.CheckError): self.convert()

    def test_seconds_must_match_frames(self):
        self.record['lines'][0]['end'] = 1.9
        with self.assertRaises(av.CheckError): self.convert()

    def test_fingerprint_mismatch(self):
        for field in ('video_sha256', 'voice_manifest_sha256'):
            with self.subTest(field=field):
                old = self.record[field]; self.record[field] = 'bad'
                with self.assertRaises(av.CheckError): self.convert()
                self.record[field] = old

    def test_audio_text_mismatch(self):
        self.record['lines'][0]['text'] = '違う台詞'
        with self.assertRaises(av.CheckError): self.convert()

    def test_unrendered_voice_line_is_not_silently_dropped(self):
        self.voice['segments'].append(dict(self.voice['segments'][0], line_id=2))
        with self.assertRaises(av.CheckError): self.convert()

    def test_missing_subtitle_and_frame_metadata_refused(self):
        del self.record['subtitles']
        with self.assertRaises(av.CheckError): self.convert()

    def test_unavailable_audio_cannot_get_provenance(self):
        self.voice['segments'][0]['file'] = 'missing.wav'
        self.assertEqual(self.run_link(), 1)
        self.assertFalse((self.root/'out/provenance.json').exists())

    def test_asset_directory_cannot_be_relabelled_self_created(self):
        self.review['assets'][0]['path'] = 'assets/portraits/screen.png'
        self.assertEqual(self.run_link(), 1)

    def test_incomplete_inventory_refused(self):
        self.review['all_assets_accounted_for'] = False
        self.assertEqual(self.run_link(), 1)

    def test_reused_output_refused(self):
        self.assertEqual(self.run_link(), 0)
        self.assertEqual(self.run_link(), 1)

    def test_no_review_leaves_only_timeline(self):
        self.assertEqual(self.run_link(review=False), 1)
        self.assertTrue((self.root/'out/timeline.json').is_file())
        self.assertFalse((self.root/'out/provenance.json').exists())

    def test_planned_ui_refused_before_opening_voice(self):
        self.voice['segments'][0]['planned_host'] = 'ui'
        with patch.object(link, 'provenance', wraps=link.provenance) as gate:
            self.assertEqual(self.run_link(), 1)
            gate.assert_called_once()
        self.assertFalse((self.root/'out/provenance.json').exists())

    def test_official_and_unknown_review_refused(self):
        self.review['assets'][0]['classification'] = 'official'
        self.assertEqual(self.run_link(), 1)
        self.assertFalse((self.root/'out/provenance.json').exists())

    def test_poster_name_refused(self):
        self.review['review']['poster_names'] = True
        self.assertEqual(self.run_link(), 1)
        self.assertFalse((self.root/'out/provenance.json').exists())

    def test_code_hash_refused(self):
        self.review['drawing_code'][0]['sha256'] = 'bad'
        self.assertEqual(self.run_link(), 1)

    def test_all_subtitle_cuts_must_be_reviewed(self):
        self.review['reviewed_cut_ids'] = [1]
        self.assertEqual(self.run_link(), 1)

    def test_success_and_dry_run_never_calls_asr_or_gemini(self):
        self.assertEqual(self.run_link(), 0)
        args = ['--video', str(self.video), '--script', str(self.root/'out/timeline.json'),
                '--provenance', str(self.root/'out/provenance.json'), '--out', str(self.root/'check'), '--dry-run']
        with patch.object(av, 'media_probe', return_value=2), patch.object(av.subprocess, 'run') as decode, \
                patch.object(av, 'run_asr') as asr, patch.object(av, 'Gemini') as gemini:
            self.assertEqual(av.main(args), 0)
            asr.assert_not_called(); gemini.assert_not_called()
            self.assertEqual(decode.call_count, 1)
            self.assertIn('-xerror', decode.call_args.args[0])
        self.assertEqual(av.read_json(self.root/'check/result.json')['status'], 'preflight_only')

    def test_bad_provenance_dry_run_stops_before_decode(self):
        self.assertEqual(self.run_link(), 0)
        self.video.write_bytes(b'changed')
        with patch.object(av.subprocess, 'run') as runner, patch.object(av, 'run_asr') as asr, \
                patch.object(av, 'Gemini') as gemini:
            self.assertEqual(av.main(['--video', str(self.video), '--script', str(self.root/'out/timeline.json'),
                '--provenance', str(self.root/'out/provenance.json'), '--out', str(self.root/'check'), '--dry-run']), 1)
            runner.assert_not_called(); asr.assert_not_called(); gemini.assert_not_called()

    def test_missing_provenance_has_clear_reason_before_any_subprocess(self):
        self.assertEqual(self.run_link(review=False), 1)
        with patch.object(av.subprocess, 'run') as runner:
            self.assertEqual(av.main(['--video', str(self.video), '--script', str(self.root/'out/timeline.json'),
                '--provenance', str(self.root/'out/provenance.json'), '--out', str(self.root/'check'), '--dry-run']), 1)
            runner.assert_not_called()
        self.assertIn('出所JSONがありません', av.read_json(self.root/'check/result.json')['reason'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
