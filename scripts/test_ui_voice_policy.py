"""時間・係の鮮度・原稿からの再作成・公開停止をネットなしで検査する。"""
import argparse
import copy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import host_split as hs
import host_split_report as report
import ui_voice_policy as p
import ui_voice_queue as q
import ui_voice_stock as stock

AT = datetime(2026, 10, 27, 12, tzinfo=p.JST)
SCRIPT = dict(segments=[dict(kind='intro', speaker=2, text='成績だよ。', meta={})])


class Queue:
    def __init__(self):
        self.state, self.files = {}, {}

    def read(self):
        return '', copy.deepcopy(self.state), dict(self.files)

    def update(self, change):
        return change(self.state, self.files)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.queue = Queue()
        self.clock = patch.object(q, 'now', return_value=AT)
        self.clock.start()
        self.env = patch.dict(os.environ, COLLESPO_HOST_SPLIT='half', COLLESPO_UI_VOICE_STOCK='',
                              COLLESPO_UI_VOICE_WAIT_MINUTES='15', COLLESPO_SOLO_HOST='metan')
        self.env.start()
        self.remote = patch.object(q, 'GitQueue', return_value=self.queue)
        self.remote.start()
        p.heartbeat(self.queue)

    def tearDown(self):
        self.remote.stop(); self.env.stop(); self.clock.stop()

    def test_time_boundaries_and_wait_headroom(self):
        for hour, minute, allowed in [(0,0,False),(8,39,False),(8,40,True),(18,59,True),
                                     (19,0,False),(19,15,False),(20,39,False),(20,40,False),
                                     (20,55,False),(22,0,False),(23,59,False)]:
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(p.window_reason(AT.replace(hour=hour, minute=minute),15) is None,allowed)

    def test_failure_defaults_for_each_family(self):
        for kind in hs.KINDS+tuple(p.FRESH_ASSETS):
            with self.subTest(kind=kind):
                self.assertEqual(p.failure_action(dict(host_assignment=dict(kind=kind))),'rebuild_metan')
        for kind in ('asset:season_player','asset:season_team','asset:legend','asset:v3'):
            with self.subTest(kind=kind):
                self.assertEqual(p.failure_action(dict(host_assignment=dict(kind=kind))),'defer_next_day')

    def test_health_fresh_stale_missing_future_and_failed(self):
        for delta, status, expected in [(0,'ready',None),(420,'ready',None),(421,'ready','ui_worker_stale'),
                                         (-1,'ready','ui_worker_stale'),(0,'failed','ui_worker_unavailable')]:
            self.queue.files[p.HEALTH_FILE]=q.encoded(dict(version=1,status=status,checked_at=(AT-timedelta(seconds=delta)).isoformat()))
            self.assertEqual(p.health_reason(self.queue.files),expected)
        self.assertEqual(p.health_reason({}),'ui_worker_missing')

    def source(self,kind='morning'):
        day=next(f'2026-10-{d}' for d in range(12,19) if hs.plan(kind,f'2026-10-{d}')['planned_host']=='ui')
        return hs.prepare(SCRIPT,kind,day)

    def test_unavailable_is_planned_metan_before_tone_and_excluded(self):
        self.queue.files.clear()
        source=self.source()
        self.assertEqual(source['host_delivery']['planned_host'],'metan')
        self.assertFalse(source['host_delivery']['comparison_eligible'])
        self.assertEqual(source['segments'],SCRIPT['segments'])
        rec=dict(source,planned_host='metan',actual_host='metan',kind='morning',published=AT.date())
        group=report.aggregate([rec],[],AT.date())['morning']
        self.assertEqual(group['excluded'],1)
        self.assertEqual(group['hosts']['metan']['matched'],0)

    def test_saved_plan_never_reassigned_when_worker_stops(self):
        source=self.source()
        self.queue.files.clear()
        self.assertEqual(hs.prepare(source)['host_delivery'],source['host_delivery'])
        self.assertEqual(os.environ['COLLESPO_SOLO_HOST'],'ui')

    def test_asset_failure_blocks_synthesis_render_and_publication(self):
        source=self.source('asset:season_team')
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
            folder=Path(folder)
            with self.assertRaises(p.VoiceUnavailable):
                p.failure(source,folder/'n.json',folder,'ui_delivery_timeout')
            held=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(held['host_delivery']['action'],'defer_next_day')
            with self.assertRaises(p.VoiceUnavailable):
                q.configure(argparse.Namespace(audio_dir=folder,out=folder/'render'))
            video=folder/'v.mp4';video.write_bytes(b'old-video')
            with self.assertRaises(p.VoiceUnavailable):hs.bind_video(video,folder)

    def test_realtime_failure_rebuilds_original_script_and_excludes_attempt(self):
        source=self.source()
        source['segments'][0]['text']='成績です。'
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
            result=p.failure(source,Path(folder)/'n.json',folder,'ui_delivery_timeout')
            self.assertEqual(result['segments'],SCRIPT['segments'])
            self.assertEqual(result['host_delivery']['planned_host'],'metan')
            self.assertFalse(result['host_delivery']['comparison_eligible'])
            self.assertEqual(result['host_delivery']['previous_attempt']['status'],'held')

    def test_publishing_ui_plan_with_metan_voice_is_rejected(self):
        source=self.source()
        source['voice_resolution']=dict(host='metan',audio_available=True)
        with self.assertRaises(p.VoiceUnavailable):p.assert_publishable(source)

    def test_stock_can_be_used_at_night_without_new_request(self):
        context=dict(topic='fixed',material_key='same')
        self.queue.state['a']=dict(stock=True,status='ready')
        with patch.dict(os.environ,COLLESPO_UI_VOICE_STOCK='on'),patch.object(stock,'asset_context',return_value=context), \
             patch.object(stock,'fresh',return_value=True):
            decision=p.decide(SCRIPT,self.queue,AT.replace(hour=22))
        self.assertEqual((decision['planned_host'],decision['mode']),('ui','stock'))

    def test_failed_stock_at_night_never_enqueues(self):
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder, \
             patch.object(stock.parts_crypto,'key',return_value=b'fixed'),patch.object(stock,'asset_context',return_value=None), \
             patch.object(q,'now',return_value=AT.replace(hour=22)),patch.object(q,'enqueue') as enqueue:
            with self.assertRaises(p.VoiceUnavailable):stock.fulfill(copy.deepcopy(SCRIPT),Path(folder)/'n.json',folder,self.queue)
            enqueue.assert_not_called()

    def test_heartbeat_is_allowed_preserved_and_small(self):
        blob=self.queue.files[p.HEALTH_FILE]
        q.validate_file(p.HEALTH_FILE,blob)
        self.assertIn(p.HEALTH_FILE,q.compact({},self.queue.files))
        with self.assertRaises(q.QueueError):q.validate_file(p.HEALTH_FILE,q.encoded(dict(version=1,status='bad',checked_at=AT.isoformat())))

    def test_early_order_is_idempotent_and_does_not_start_voicevox(self):
        import synthesize_narration as sn
        source=self.source('asset:v3')
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
            folder=Path(folder);path=folder/'n.json';path.write_bytes(q.encoded(source))
            with patch.object(sn,'engine_available',side_effect=AssertionError('先行注文ではVOICEVOXを起動しない')):
                sn.main(['--narration',str(path),'--out-dir',str(folder/'audio'),'--queue-only'])
                sn.main(['--narration',str(path),'--out-dir',str(folder/'audio'),'--queue-only'])
            self.assertEqual(len(self.queue.state),1)
            order=next(iter(self.queue.state.values()))
            self.assertEqual(order['status'],'pending')
            self.assertEqual(order['narration']['segments'][0]['text'],'成績です。')

    def test_weekly_report_runs_without_voice_packages(self):
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
            target=Path(folder)/'weekly.md'
            result=subprocess.run([sys.executable,'-S',str(q.ROOT/'scripts/weekly_report.py'),
                                   '--data',str(q.ROOT/'scripts/fixtures/weekly-report/data'),
                                   '--out',str(target)],capture_output=True,text=True,encoding='utf8')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('めたんと雨衣の半々比較',target.read_text(encoding='utf8'))

    def test_worker_stops_new_synthesis_at_live_boundary(self):
        import base64
        import ui_voice_worker as worker
        from test_ui_voice_queue import portraits,tone
        clock=[AT.replace(hour=19,minute=14)]
        script=copy.deepcopy(SCRIPT);script['segments']*=2
        order=q.make_order(script,'boundary',at=clock[0])
        q.enqueue(self.queue,order)
        calls=[]
        def synth(text,path):
            calls.append(text);tone(text,path);clock[0]+=timedelta(minutes=2)
        def transcode(source,destination):destination.write_bytes(b'fixed-flac')
        with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder,patch.object(q,'now',side_effect=lambda:clock[0]), \
             patch.dict(os.environ,COLLESPO_UI_PARTS_KEY=base64.b64encode(bytes(range(32))).decode()), \
             patch.object(worker,'transcode',side_effect=transcode):
            worker.process(self.queue,folder,synth,portraits())
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads(self.queue.files[p.HEALTH_FILE])['status'],'blocked')


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
