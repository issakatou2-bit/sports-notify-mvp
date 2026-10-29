"""実APIもキーも使わない。run_checksの一時置場引数にも対応。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import gemini_av_check as av

BASE = (Path(sys.argv[1]) if __name__ == '__main__' and len(sys.argv) > 1 and not sys.argv[1].startswith('-')
        else Path(__file__).resolve().parents[1]/'build'/'gemini-tests')
BASE.mkdir(parents=True, exist_ok=True)


def timeline():
    return dict(version=1, lines=[dict(line_id=1, start=0, end=2, text='今日は晴れです。', subtitle='今日は晴れです。')],
                cuts=[dict(cut_id=1, start=0, end=2, screen='自作の文字画面')])


def response():
    return dict(lines=[dict(line_id=1, heard='今日は晴れです。', subtitle_seen='今日は晴れです。',
                           checks={k: 'ok' for k in av.CHECKS}, start_delta_seconds=0,
                           end_delta_seconds=0, findings=[])],
                cuts=[dict(cut_id=1, status='ok', reason='全文が画面内で読めた')])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=BASE, prefix='case-'))
        self.video, self.script, self.prov = [self.root/n for n in ('movie.mp4', 'script.json', 'provenance.json')]
        self.video.write_bytes(b'fake-video')
        av.write_json(self.script, timeline())
        (self.root/'voice.wav').write_bytes(b'fake-voice')
        (self.root/'screen.png').write_bytes(b'fake-screen')
        av.write_json(self.root/'manifest.json', dict(segments=[dict(speaker=2, text='今日は晴れです。', file='voice.wav')]))
        self.provenance = dict(version=1, video_sha256=av.sha256(self.video), script_sha256=av.sha256(self.script),
            review=dict(evidence='自作文字画面の全画面と生成コードを確認', official_art=False,
                        personal_information=False, secrets=False, poster_names=False, unreleased_private_material=False),
            assets=[dict(kind='voicevox', path='voice.wav', sha256=av.sha256(self.root/'voice.wav'),
                         self_created=True, evidence='VOICEVOX自作', engine='voicevox', speaker=2),
                    dict(kind='rendered_screen', path='screen.png', sha256=av.sha256(self.root/'screen.png'),
                         self_created=True, evidence='Pillowで自作')],
            audio_manifests=[dict(path='manifest.json', sha256=av.sha256(self.root/'manifest.json'))])
        av.write_json(self.prov, self.provenance)
        self.asr = dict(status='checked', lines=[])

    def save_prov(self):
        av.write_json(self.prov, self.provenance)

    def validate(self):
        return av.validate_sources(self.video, self.script, self.prov)

    def test_allowed_sources(self):
        self.validate()

    def test_forbidden_directories_are_never_opened(self):
        for directory in ('Desktop/個人情報', 'Desktop/SD', 'Tools/Qwen-Image/outputs', 'Tools/ui-refs', '.secrets'):
            with self.subTest(directory=directory), patch.object(av, 'read_json') as reader:
                with self.assertRaises(av.CheckError):
                    av.validate_sources('C:/Users/issak/'+directory+'/movie.mp4', self.script, self.prov)
                reader.assert_not_called()

    def test_asset_file_type_must_match_kind(self):
        self.provenance['assets'][0]['path'] = 'manifest.json'
        self.save_prov()
        with self.assertRaises(av.CheckError): self.validate()

    def test_bad_video_hash(self):
        self.video.write_bytes(b'changed')
        with self.assertRaises(av.CheckError): self.validate()

    def test_changed_script(self):
        self.script.write_text('{}')
        with self.assertRaises(av.CheckError): self.validate()

    def test_unknown_or_official_assets(self):
        for kind in ('official_art', 'downloaded_bgm', 'unknown'):
            with self.subTest(kind=kind):
                self.provenance['assets'][0]['kind'] = kind
                self.save_prov()
                with self.assertRaises(av.CheckError): self.validate()

    def test_no_review(self):
        self.provenance['review'].pop('poster_names')
        self.save_prov()
        with self.assertRaises(av.CheckError): self.validate()

    def test_voisona_manifest(self):
        for metadata in (dict(voice_engine='voisona'), dict(voice_host='ui'), dict(voice_name='ui_ja_JP'),
                         dict(voice_resolution=dict(host='ui')), dict(solo_host='ui')):
            with self.subTest(metadata=metadata):
                av.write_json(self.root/'manifest.json', dict(segments=[dict(speaker=2, **metadata)]))
                self.provenance['audio_manifests'][0]['sha256'] = av.sha256(self.root/'manifest.json')
                self.save_prov()
                with self.assertRaises(av.CheckError): self.validate()

    def test_voisona_receipt(self):
        av.write_json(self.video.with_name(self.video.name+'.voice.json'), dict(voice_resolution=dict(host='ui')))
        with self.assertRaises(av.CheckError): self.validate()

    def test_manifest_must_cover_all_actual_sources(self):
        av.write_json(self.root/'manifest.json', dict(segments=[dict(speaker=3, text='今日は晴れです。', file='voice.wav')]))
        self.provenance['audio_manifests'][0]['sha256'] = av.sha256(self.root/'manifest.json')
        self.save_prov()
        with self.assertRaises(av.CheckError): self.validate()

    def test_unknown_voice_engine(self):
        av.write_json(self.root/'manifest.json', dict(segments=[dict(speaker=2, file='voice.wav', voice_engine='unknown')]))
        self.provenance['audio_manifests'][0]['sha256'] = av.sha256(self.root/'manifest.json')
        self.save_prov()
        with self.assertRaises(av.CheckError): self.validate()

    def test_ci_never_calls_real_services(self):
        with patch.dict(os.environ, dict(CI='true')), patch.object(av, 'media_probe', return_value=2), patch.object(av.subprocess, 'run'), patch.object(av, 'run_asr') as asr, patch.object(av.Gemini, 'analyze') as gemini:
            code = av.main(['--video', str(self.video), '--script', str(self.script), '--provenance', str(self.prov), '--out', str(self.root/'out')])
        self.assertEqual(code, 1)
        asr.assert_not_called(); gemini.assert_not_called()

    def test_output_reuse_is_rejected(self):
        out = self.root/'out'; out.mkdir(); (out/'result.json').write_text('old')
        code = av.main(['--video', str(self.video), '--script', str(self.script), '--provenance', str(self.prov), '--out', str(out)])
        self.assertEqual(code, 1)
        self.assertEqual((out/'result.json').read_text(), 'old')

    def test_rejection_before_asr_or_cli_or_probe(self):
        self.provenance['assets'][0]['engine'] = 'voisona'
        self.save_prov()
        with patch.object(av, 'run_asr') as asr, patch.object(av.Gemini, 'analyze') as gemini, patch.object(av, 'media_probe') as probe:
            code = av.main(['--video', str(self.video), '--script', str(self.script), '--provenance', str(self.prov), '--out', str(self.root/'out')])
        self.assertEqual(code, 1)
        asr.assert_not_called(); gemini.assert_not_called(); probe.assert_not_called()

    def test_timeline_coverage(self):
        av.validate_timeline(timeline(), 2)
        for key in ('lines', 'cuts'):
            value = timeline(); value[key][0]['end'] = 1
            with self.assertRaises(av.CheckError): av.validate_timeline(value, 2)
            value = timeline(); value[key][0]['start'] = .5
            with self.assertRaises(av.CheckError): av.validate_timeline(value, 2)

    def test_bad_timing_and_duplicate_ids(self):
        for value in (float('nan'), float('inf'), True, -1):
            row = timeline(); row['lines'][0]['end'] = value
            with self.assertRaises(av.CheckError): av.validate_timeline(row, 2)
        row = timeline(); row['lines'] *= 2
        with self.assertRaises(av.CheckError): av.validate_timeline(row, 2)

    def test_exact_response(self):
        result = av.reconcile(timeline(), response(), self.asr)
        self.assertEqual(result['status'], 'no_findings')
        self.assertEqual(result['needs_review'], [])

    def test_missing_and_unknown_lines(self):
        for field in ('lines', 'cuts'):
            value = response(); value[field] = []
            result = av.reconcile(timeline(), value, self.asr)
            self.assertEqual(result['status'], 'needs_review')
        value = response(); value['lines'][0]['checks']['breath'] = 'unknown'
        self.assertTrue(av.reconcile(timeline(), value, self.asr)['needs_review'])

    def test_invalid_and_duplicate_response_ids(self):
        for number in (999, True, '1'):
            value = response(); value['lines'][0]['line_id'] = number
            with self.assertRaises(av.CheckError): av.reconcile(timeline(), value, self.asr)
        value = response(); value['lines'] *= 2
        with self.assertRaises(av.CheckError): av.reconcile(timeline(), value, self.asr)

    def test_all_ok_with_mismatched_transcript(self):
        value = response(); value['lines'][0]['heard'] = '明日は雨です。'
        result = av.reconcile(timeline(), value, self.asr)
        self.assertEqual(result['needs_review'][0]['id'], 1)
        self.assertEqual(result['needs_review'][0]['script']['text'], '今日は晴れです。')

    def test_visible_decimal_and_score_separators_must_not_disappear(self):
        for expected, seen in (('防御率0.25', '防御率025'), ('3-2', '32'), ('-2', '2')):
            script = timeline(); script['lines'][0]['subtitle'] = expected
            value = response(); value['lines'][0]['subtitle_seen'] = seen
            self.assertTrue(av.reconcile(script, value, self.asr)['needs_review'])

    def test_visible_fullwidth_and_line_breaks_are_equivalent(self):
        script = timeline(); script['lines'][0]['subtitle'] = '0.25 / 3-2'
        value = response(); value['lines'][0]['subtitle_seen'] = '０．２５／\n３－２'
        self.assertFalse(av.reconcile(script, value, self.asr)['needs_review'])

    def test_seconds_unknown_and_findings(self):
        for delta in (.7, None, float('nan')):
            value = response(); value['lines'][0]['start_delta_seconds'] = delta
            self.assertTrue(av.reconcile(timeline(), value, self.asr)['needs_review'])
        value = response(); value['lines'][0]['findings'] = [dict(category='breath', reason='1.1秒に息')]
        self.assertIn('1.1秒に息', av.reconcile(timeline(), value, self.asr)['needs_review'][0]['reasons'])

    def test_intentional_subtitle_tail_is_not_an_error(self):
        script = timeline(); script['lines'][0]['expected_end_delta_seconds'] = -.7
        value = response(); value['lines'][0]['end_delta_seconds'] = -.7
        self.assertEqual(av.reconcile(script, value, self.asr)['status'], 'no_findings')
        value['lines'][0]['end_delta_seconds'] = -1.2
        self.assertEqual(av.reconcile(script, value, self.asr)['status'], 'needs_review')
        script['lines'][0]['expected_end_delta_seconds'] = float('nan')
        with self.assertRaises(av.CheckError): av.validate_timeline(script, 2)

    def test_planned_silence_needs_no_fabricated_speech_time(self):
        script = timeline(); script['lines'][0]['text'] = ''
        value = response(); value['lines'][0].update(heard='', start_delta_seconds=None, end_delta_seconds=None)
        self.assertEqual(av.reconcile(script, value, self.asr)['status'], 'no_findings')

    def test_asr_missing_is_not_pass(self):
        self.assertEqual(av.reconcile(timeline(), response(), dict(status='unavailable', lines=[]))['status'], 'needs_review')

    def test_asr_comparison(self):
        words = [dict(start=.1, end=1.8, word='今日は晴れです。')]
        same = av.compare_asr(timeline(), [dict(words=words)])
        self.assertFalse(same[0]['needs_review'])
        self.assertTrue(av.compare_asr(timeline(), [dict(words=[])])[0]['needs_review'])
        self.assertEqual(av.edit_distance('abc', 'adc'), 1)

    def test_asr_no_auto_download(self):
        with self.assertRaises(av.CheckError): av.run_asr(self.video, timeline(), self.root, sys.executable, 'not-a-local-model')

    def test_asr_uses_line_id_for_short_repeated_lines(self):
        script = timeline()
        script['lines'].append(dict(line_id=2,start=2,end=4,text='今日は晴れです。',subtitle='今日は晴れです。'))
        rows = [dict(line_id=i, words=[dict(start=.1,end=.8,word='今日は晴れです。')]) for i in (1,2)]
        self.assertFalse(any(r['needs_review'] for r in av.compare_asr(script, rows)))

    def test_config_access_error_is_sanitized_and_not_retried(self):
        runner = lambda *a, **k: subprocess.CompletedProcess(a,2,'','failed to read config file DO_NOT_PRINT: Access is denied.')
        gemini = av.Gemini(['fake'], self.root, runner=runner, sleeper=lambda _: self.fail('should not retry'))
        with self.assertRaisesRegex(av.CheckError, 'config_access_denied') as error:
            gemini.analyze(self.video, timeline())
        self.assertNotIn('DO_NOT_PRINT', str(error.exception))
        self.assertEqual(gemini.events[0]['error_kind'], 'config_access_denied')

    def fake_cli(self, failures=0, error='503 UNAVAILABLE', fenced=False):
        fake = self.root/'fake_gemini.py'
        # 実際の子プロセス。呼出回数と順序をファイルへ残し、キーもネットワークも不要。
        code = '''import json,sys
from pathlib import Path
root=Path(__file__).parent
log=root/'calls.json'
calls=json.loads(log.read_text()) if log.exists() else []
calls.append(sys.argv[1:]); log.write_text(json.dumps(calls))
if len(calls)<=FAILURES:
 print(ERROR,file=sys.stderr); sys.exit(1)
if sys.argv[1]=='files': print('files/fake123')
else:
 prompt=sys.stdin.read()
 assert '聞こえた事実だけ。分からない所は分からないと書く' in prompt
 print(ANSWER)
'''
        code = code.replace('FAILURES', str(failures)).replace('ERROR', repr(error)).replace('ANSWER', repr(('```json\n' if fenced else '')+json.dumps(response(), ensure_ascii=False)+('\n```' if fenced else '')))
        fake.write_text(code, encoding='utf-8')
        return av.Gemini([sys.executable, str(fake)], self.root, sleeper=lambda _: None)

    def test_fake_cli_and_json(self):
        gemini = self.fake_cli(fenced=True)
        self.assertEqual(gemini.analyze(self.video, timeline()), response())

    def test_503_retries_twice_then_success(self):
        gemini = self.fake_cli(failures=2)
        with patch.object(gemini, 'sleeper') as sleeper:
            gemini.analyze(self.video, timeline())
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [30, 60])
        self.assertEqual(len(av.read_json(self.root/'calls.json')), 3)

    def test_503_exhausted(self):
        gemini = self.fake_cli(failures=5)
        with self.assertRaises(av.CheckError): gemini.analyze(self.video, timeline())
        self.assertEqual(len(av.read_json(self.root/'calls.json')), 3)

    def test_auth_or_quota_not_retried(self):
        gemini = self.fake_cli(failures=5, error='429 quota exhausted')
        with self.assertRaises(av.CheckError): gemini.analyze(self.video, timeline())
        self.assertEqual(len(av.read_json(self.root/'calls.json')), 1)

    def test_upload_over_14mb(self):
        with self.video.open('wb') as stream: stream.truncate(av.INLINE_LIMIT+1)
        gemini = self.fake_cli()
        gemini.analyze(self.video, timeline())
        calls = av.read_json(self.root/'calls.json')
        self.assertEqual(calls[0][:2], ['files', 'upload'])
        self.assertIn('--wait', calls[0])
        self.assertEqual(calls[1][2], 'files/fake123')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
