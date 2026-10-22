"""全ソロ種類の声・絵・受領記録。ネットも実声も使わずMP4まで確認。"""
import argparse
import base64
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import host_split as hs
import solo_host
import synthesize_narration as sn
import ui_voice_parts as parts
import ui_voice_queue as q
import ui_voice_stock as stock
import ui_voice_worker as worker
from test_host_split import day_for
import test_ui_voice_queue as fixtures
from test_ui_voice_queue import AT, MemoryQueue, SCRIPT, portraits, stock_sleep, tone


class PortraitFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.QueueTest.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixtures.QueueTest.tearDownClass.__func__(cls)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=q.ROOT/'build')
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, COLLESPO_HOST_SPLIT='half', COLLESPO_SOLO_HOST='metan',
                              COLLESPO_UI_PORTRAIT_DIR='', COLLESPO_UI_VOICE_WAIT_MINUTES='15',
                              COLLESPO_UI_PARTS_KEY=base64.b64encode(bytes(range(32))).decode('ascii'))
        self.env.start()
        self.clock = patch.object(q, 'now', return_value=AT)
        self.clock.start()

    def tearDown(self):
        self.clock.stop(); self.env.stop(); self.temp.cleanup()

    def generate(self, folder, kind, failure=None):
        folder.mkdir(parents=True)
        queue = MemoryQueue()
        source = hs.prepare(copy.deepcopy(SCRIPT), kind, day_for('ui', kind))
        # 複数区間の途中で雨衣が残らないことも検査する。
        source['segments'].append(dict(kind='outro', speaker=2, text='次の試合です。', meta={'who':'四国めたん'}))
        path = folder/'narration.json'; path.write_bytes(q.encoded(source))
        audio = folder/'audio'

        def deliver(seconds):
            worker.process(queue, folder/'cache', tone, portraits())
            ref = next(iter(queue.state.values()))['parts_ref']
            if failure == 'missing':
                del queue.files[ref]
            elif failure == 'corrupt':
                # 末尾が元から'!'でも必ず壊れるよう、1ビット反転する。
                queue.files[ref] = queue.files[ref][:-1]+bytes([queue.files[ref][-1] ^ 1])

        with patch.object(q, 'GitQueue', return_value=queue), \
             patch.object(stock, 'asset_context', return_value=None), \
             stock_sleep(deliver), \
             patch.object(sn, 'engine_available', return_value=True), \
             patch.object(sn, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)) as vv:
            sn.main(['--narration', str(path), '--out-dir', str(audio)])
        manifest = hs.read(audio/'manifest.json')
        actual = 'metan' if failure else 'ui'
        self.assertEqual(manifest['voice_resolution']['host'], actual)
        self.assertEqual(vv.call_count, 2 if failure else 0)
        self.assertTrue(all(s['file'] and s['duration'] > 0 for s in manifest['segments']))
        self.assertTrue(all(s.get('voice_host', 'metan') == actual for s in manifest['segments']))
        if failure:
            self.assertEqual(manifest['voice_resolution']['reason'], 'ui_portrait_unavailable')
        return path, audio, queue

    def test_every_kind_with_and_without_parts_finishes_video(self):
        import characters
        import video_common as vc
        kinds = hs.KINDS+tuple(hs.asset_kind(t) for t in (
            'season_game_1','season_story_1','season_spotlight_1','season_league_1',
            'season_team_1','season_odds_1','season_momentum_1','legend_a','v3_rules_multi'))
        for kind in kinds:
            for missing in (False, True):
                with self.subTest(kind=kind, missing=missing):
                    folder = self.folder/(kind.replace(':','-')+str(missing))
                    _, audio, _ = self.generate(folder, kind, 'missing' if missing else None)
                    out = folder/'video'
                    hs.render_audio(audio, out)
                    manifest = hs.read(audio/'manifest.json')
                    solo_host.validate_audio(manifest['segments'])
                    frame = Image.new('RGB', (1080,1920), 'white')
                    characters.presenter(frame,.1,('metan',))
                    self.assertEqual(frame.info['duo_portraits'][0]['who'], 'metan' if missing else 'ui')
                    frame.resize((108,192)).save(out/'frame.png')
                    track = vc.build_narration_track(manifest['segments'], [.3,.3], out)
                    video = out/'fixture.mp4'
                    subprocess.run([q.ffmpeg(),'-v','error','-y','-loop','1','-i',str(out/'frame.png'),
                                    '-i',str(track),'-t','0.6','-c:v','libx264','-pix_fmt','yuv420p',
                                    '-c:a','aac',str(video)], check=True, capture_output=True)
                    subprocess.run([q.ffmpeg(),'-v','error','-i',str(video),'-f','null','-'], check=True,capture_output=True)
                    hs.bind_video(video,audio)
                    receipt = hs.publication(video)
                    self.assertEqual((receipt['planned_host'],receipt['actual_host']),('ui','metan' if missing else 'ui'))
                    self.assertEqual(bool(receipt['host_fallback_reason']),missing)

    def test_bad_cipher_and_missing_key_use_metan_for_all_segments(self):
        self.generate(self.folder/'corrupt', 'morning', 'corrupt')
        with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=''):
            self.generate(self.folder/'no-key', 'morning', 'missing')

    def test_lost_portraits_after_receiving_voice_regenerate_every_segment(self):
        path, audio, queue = self.generate(self.folder/'lost','daily')
        (audio/'portrait/p000.png').unlink()
        queue.files.clear()
        with patch.object(q,'GitQueue',return_value=queue), \
             patch.object(sn,'engine_available',return_value=True), \
             patch.object(sn,'synth_one',side_effect=lambda text,speaker,out:(tone(text,out) or True)) as vv:
            q.configure(argparse.Namespace(audio_dir=audio,out=self.folder/'recovered'))
        self.assertEqual(vv.call_count,2)
        self.assertEqual(hs.read(path)['voice_resolution']['reason'],'ui_portrait_unavailable')
        solo_host.validate_audio(hs.read(audio/'manifest.json')['segments'])

    def test_ps_validation_before_voice_receives_parts_or_uses_metan_preview(self):
        import ps_program as ps
        import review_render_v3 as r3
        from test_ps_program import fixture
        snapshot,evidence,at = fixture(30)
        with patch.dict(os.environ,COLLESPO_PS_DESIGN='v3'),patch.object(r3,'LOOK','v4'):
            for slot in ('forecast','situation'):
                program = ps.prepare(snapshot,evidence,slot,at,{})
                self.assertIsNotNone(program)
                for available in (True,False):
                    queue = MemoryQueue()
                    if available:
                        parts.publish(queue.files,portraits(),parts.key())
                    os.environ['COLLESPO_SOLO_HOST']='ui'
                    os.environ['COLLESPO_UI_PORTRAIT_DIR']=''
                    with patch.object(q,'GitQueue',return_value=queue):
                        report = ps.check_program(program)
                    self.assertTrue(report['rendered'])
                    self.assertEqual(os.environ['COLLESPO_SOLO_HOST'],'ui')


if __name__ == '__main__':
    unittest.main(argv=[__file__])
