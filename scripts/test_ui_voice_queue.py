"""固定原稿・合成した単音・作り物の立ち絵だけ。VoiSonaとネットワークは呼ばない。"""
import argparse
import base64
import copy
from datetime import datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

from PIL import Image
import ui_voice_queue as q
import ui_voice_stock as stock
import ui_voice_policy as policy
import ui_voice_worker as worker
import ui_voice_parts as parts_crypto

AT = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
SCRIPT = dict(segments=[dict(kind='intro', text='固定の成績です。', speaker=2, meta={})])


class MemoryQueue:
    def __init__(self):
        self.state, self.files = {}, {}
        self.fail_delivery = False

    def read(self):
        return '', copy.deepcopy(self.state), dict(self.files)

    def update(self, change):
        state, files = copy.deepcopy(self.state), dict(self.files)
        result = change(state, files)
        if self.fail_delivery and any(v['status'] == 'ready' for v in state.values()):
            self.fail_delivery = False
            raise q.QueueError('固定の返送失敗')
        self.state, self.files = state, files
        return result


def tone(text, path):
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<h', round(2000*math.sin(i*2*math.pi*440/24000)))
                                 for i in range(7200)))


def portraits():
    buffer = io.BytesIO()
    Image.new('RGBA', (32, 64), '#446688').save(buffer, 'PNG')
    keys = {'右腕': ('基本', '上げ', '指', '考え'), '左腕': ('基本', '上げ'),
            '眉': ('基本', '上げ', '困り'), '目': ('開', '閉', '笑', '見開'), '口': ('閉', '開', '大', '笑')}
    parts = dict(size=[32, 64], crop=[0, 0, 32, 64], 体='p000.png')
    parts.update({k: dict.fromkeys(values, 'p000.png') for k, values in keys.items()})
    return {'p000.png': buffer.getvalue(), 'parts.json': q.encoded(parts)}


class QueueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # CIでも本物のFLAC往復・MP4 decodeを必ず実行する。VoiSonaは不要。
        (q.ROOT/'build').mkdir(exist_ok=True)
        cls.tools = tempfile.TemporaryDirectory(dir=q.ROOT/'build')
        if not shutil.which('ffmpeg'):
            tool = Path(cls.tools.name)/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
            shutil.copyfile(q.ffmpeg(), tool)
            tool.chmod(0o755)
        cls.tool_env = patch.dict(os.environ, PATH=cls.tools.name+os.pathsep+os.environ.get('PATH', ''))
        cls.tool_env.start()

    @classmethod
    def tearDownClass(cls):
        cls.tool_env.stop()
        cls.tools.cleanup()

    def setUp(self):
        (q.ROOT/'build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=q.ROOT/'build')
        self.folder = Path(self.temp.name)
        self.queue = MemoryQueue()
        self.clock = patch.object(q, 'now', return_value=AT)
        self.clock.start()
        self.env = patch.dict(os.environ, COLLESPO_SOLO_HOST='ui', COLLESPO_UI_VOICE_WAIT_MINUTES='15',
                              COLLESPO_UI_PARTS_KEY=base64.b64encode(bytes(range(32))).decode('ascii'))
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.clock.stop(); self.temp.cleanup()

    def order(self, stock_order=False, at=AT, episode='fixture'):
        order = q.make_order(SCRIPT, episode, stock=stock_order, at=at)
        q.enqueue(self.queue, order)
        return order

    def test_order_receive_video_and_lossless_samples(self):
        """注文の待機中にPCが受注し、実際の描画・音声結合・MP4全尺decodeまで。"""
        import synthesize_narration as sn
        import video_common as vc
        import characters
        narration = self.folder/'narration.json'
        narration.write_bytes(q.encoded(SCRIPT))
        audio = self.folder/'audio'
        calls = []

        def poll(seconds):
            calls.append(seconds)
            worker.process(self.queue, self.folder/'cache', tone, portraits())

        with patch.object(stock, 'asset_context', return_value=None), patch.object(stock.time, 'sleep', side_effect=poll), \
             patch.object(q, 'GitQueue', return_value=self.queue), \
             patch.object(sys, 'argv', ['synthesize', '--narration', str(narration), '--out-dir', str(audio)]), \
             patch.object(sn, 'engine_available') as vv, patch.object(worker, 'apsc_synthesizer') as real:
            sn.main()
            vv.assert_not_called(); real.assert_not_called()
        self.assertEqual(calls, [20])
        manifest = json.loads((audio/'manifest.json').read_text(encoding='utf8'))
        voice_record = json.loads((audio/'voice_manifest.json').read_text(encoding='utf8'))['segments'][0]
        self.assertEqual((voice_record['voice_engine'], voice_record['speaker'], voice_record['source_speaker']),
                         ('voisona', None, 2))
        import voice_manifest
        self.assertEqual(voice_record['sha256'], voice_manifest.sha256(audio/voice_record['file']))
        expected = self.folder/'expected.wav'
        tone('', expected)
        self.assertEqual((audio/'seg_000.wav').read_bytes()[-14400:], expected.read_bytes()[-14400:])
        out = self.folder/'video'
        q.configure(argparse.Namespace(audio_dir=audio, out=out))
        frame = Image.new('RGB', (1080, 1920), 'white')
        import review_render_v3 as r3
        r3.set_caption(SCRIPT['segments'][0]['text'], .3, .4, speaker=2)
        characters.presenter(frame, .1, ('metan',))
        self.assertEqual(frame.info['duo_portraits'][0]['who'], 'ui')
        frame.resize((270, 480)).save(out/'frame.png')
        track = vc.build_narration_track(manifest['segments'], [.4], out)
        video = out/'fixture.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(out/'frame.png'),
                        '-i', str(track), '-t', '0.4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', str(video)], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True, capture_output=True)
        q.configure(argparse.Namespace(video=video))
        self.assertEqual(os.environ['COLLESPO_SOLO_HOST'], 'ui')

    def test_deadline_fallback_is_real_metan_in_audio_portrait_and_credit(self):
        import synthesize_narration as sn
        import solo_host
        import characters
        with patch.dict(os.environ, COLLESPO_UI_VOICE_WAIT_MINUTES='0'):
            path = self.folder/'narration.json'
            path.write_bytes(q.encoded(SCRIPT))
            audio = self.folder/'audio'
            with patch.object(q, 'GitQueue', return_value=self.queue), \
                 patch.object(sn, 'engine_available', return_value=True), \
                 patch.object(sn, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)) as synth, \
                 patch.object(sys, 'argv', ['synthesize', '--narration', str(path), '--out-dir', str(audio)]):
                sn.main()
            self.assertEqual(synth.call_args.args[1], 2)
            saved = json.loads((audio/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(saved['voice_resolution']['host'], 'metan')
            self.assertNotIn('voice_host', saved['segments'][0])
            self.assertEqual(next(iter(self.queue.state.values()))['status'], 'expired')
            out = self.folder/'fallback'
            q.configure(argparse.Namespace(audio_dir=audio, out=out))
            solo_host.validate_audio(saved['segments'])
            self.assertEqual(solo_host.presentation('metan', ('metan',)), ('metan', ('metan',)))
            desc = '音声: VOICEVOX:四国めたん'
            self.assertEqual(solo_host.credit(desc, saved['segments']), desc)
            with patch.object(solo_host, 'portrait', side_effect=AssertionError('雨衣を表示してはいけない')):
                frame = Image.new('RGB', (1080, 1920))
                characters.place_busts(frame, 'metan', '成績です。', .1, 1, ('metan',))
            os.environ['COLLESPO_SOLO_HOST'] = 'ui'
            with patch.object(sys, 'argv', ['ps_program.py', '--upload', '--video', str(out/'fixture.mp4')]):
                q.configure(argparse.Namespace(upload=True, audio_dir=audio))
            self.assertEqual(os.environ['COLLESPO_SOLO_HOST'], 'metan')

    def test_failed_delivery_retries_without_generating_twice_and_no_duplicate_consumer(self):
        order = self.order()
        self.queue.fail_delivery = True
        with patch.object(worker, 'transcode', wraps=worker.transcode), patch(__name__+'.tone', wraps=tone) as synth:
            with self.assertRaises(q.QueueError):
                worker.process(self.queue, self.folder/'cache', synth, portraits())
            worker.process(self.queue, self.folder/'cache', synth, portraits())
            worker.process(self.queue, self.folder/'cache', synth, portraits())
            self.assertEqual(synth.call_count, 1)
        self.assertIsNotNone(stock.take(self.queue, order['id']))
        self.assertIsNone(stock.take(self.queue, order['id']))

    def test_incomplete_local_synthesis_does_not_submit_twice(self):
        order = self.order()
        synth = unittest.mock.Mock(side_effect=RuntimeError('fixed crash'))
        worker.process(self.queue, self.folder/'cache', synth, portraits())
        self.assertEqual(self.queue.state[order['id']]['failure']['stage'], 'synthesize')
        self.assertNotIn('fixed crash', json.dumps(self.queue.state))
        worker.process(self.queue, self.folder/'cache', synth, portraits())
        self.assertEqual(synth.call_count, 1)
        self.assertEqual(self.queue.state[order['id']]['status'], 'discarded')
        other = self.order(episode='next order')
        self.assertEqual(worker.process(self.queue, self.folder/'cache', tone, portraits()), 1)
        self.assertEqual(self.queue.state[other['id']]['status'], 'ready')

    def test_not_running_does_not_load_client_or_read_queue(self):
        with patch.object(worker, 'available', return_value=False), \
             patch.object(worker, 'apsc_synthesizer') as client, patch.object(q, 'GitQueue') as remote, \
             patch.object(sys, 'argv', ['worker']):
            worker.main()
            client.assert_not_called(); remote.assert_called_once()

    def test_apsc_adapter_is_lazy_and_uses_local_fixed_output_without_real_client(self):
        apsc = self.folder/'apsc'
        apsc.mkdir()
        cache = self.folder/'fixed-order'
        cache.mkdir()
        client = unittest.mock.Mock()
        def render(text, options, output):
            self.assertEqual(Path.cwd(), apsc)
            self.assertEqual(options, {})
            self.assertTrue(output.is_relative_to(apsc/'build/ui_voice/collespo-queue/fixed-order'))
            tone(text, output)
            return output
        client.synthesize.side_effect = render
        fake = types.SimpleNamespace(Client=unittest.mock.Mock(return_value=client), ui_say=lambda text: text)
        cwd = Path.cwd()
        with patch.dict(sys.modules, voisona_talk=fake), patch.object(sys, 'path', list(sys.path)):
            synth = worker.apsc_synthesizer(apsc)
            fake.Client.assert_not_called()
            for index in range(2):
                destination = cache/f'seg_{index:03d}.wav'
                synth('固定の成績です。', destination)
                self.assertTrue(destination.is_file())
                self.assertEqual(Path.cwd(), cwd)
            fake.Client.assert_called_once()

    def test_expired_order_and_other_pc_claim_do_not_generate(self):
        order = self.order(at=AT-timedelta(hours=1))
        claimed = self.order(episode='another')
        self.queue.state[claimed['id']].update(status='working', worker='different-pc')
        synth = unittest.mock.Mock()
        worker.process(self.queue, self.folder/'cache', synth, portraits())
        synth.assert_not_called()
        self.assertEqual(self.queue.state[order['id']]['status'], 'pending')

    def test_stock_age_numbers_affiliation_and_current_checks(self):
        order = self.order(True)
        context = dict(topic='team_fixture', material_key='fixed')
        order['context'] = context
        self.assertTrue(stock.fresh(order, SCRIPT, context))
        self.assertFalse(stock.fresh(order, SCRIPT, context, at=AT+timedelta(days=8)))
        self.assertFalse(stock.fresh(order, SCRIPT, dict(context, material_key='new club')))
        updated = copy.deepcopy(SCRIPT)
        updated['segments'][0]['text'] = '4打数2安打です。'
        self.assertFalse(stock.fresh(order, updated, context))
        with patch.object(stock, 'current_checks', return_value=['fixed invalid number']):
            self.assertFalse(stock.fresh(order, SCRIPT, context))

    def test_stock_discards_stale_and_uses_oldest_available(self):
        context = dict(topic='team_fixture', material_key='fixed')
        # voice deadlineは1週間。登録順と作成日時を逆にしてFIFOを検証。
        for name, age in [('new', 0), ('old', 1), ('stale', 2)]:
            order = q.make_order(SCRIPT, name, minutes=7*24*60, stock=True, at=AT-timedelta(days=age))
            order['context'] = dict(context, material_key='old club') if name == 'stale' else context
            q.enqueue(self.queue, order)
        worker.process(self.queue, self.folder/'cache', tone, portraits())
        path = self.folder/'narration.json'
        script = copy.deepcopy(SCRIPT)
        path.write_bytes(q.encoded(script))
        with patch.object(stock, 'asset_context', return_value=context):
            result = stock.fulfill(script, path, self.folder/'audio', self.queue)
        by_name = {r['episode']: r for r in self.queue.state.values()}
        self.assertEqual(result['order'], by_name['old']['id'])
        self.assertEqual(by_name['stale']['status'], 'discarded')
        self.assertEqual(by_name['new']['status'], 'ready')

    def test_missing_stock_orders_early_in_available_window(self):
        script = copy.deepcopy(SCRIPT)
        path = self.folder/'n.json'
        path.write_bytes(q.encoded(script))
        with patch.object(stock, 'asset_context', return_value=dict(topic='team_fixture', material_key='fixed')), \
             patch.object(stock.time, 'sleep', side_effect=lambda seconds: worker.process(self.queue,self.folder/'stock-miss-cache',tone,portraits())):
            result = stock.fulfill(script,path,self.folder/'audio',self.queue)
        self.assertEqual(result['host'],'ui')
        self.assertEqual(len(self.queue.state),1)

    def test_prioritization_discards_stale_before_choosing_a_topic(self):
        for name, age in [('new', 0), ('old', 1), ('stale', 2)]:
            order = q.make_order(SCRIPT, name, minutes=7*24*60, stock=True, at=AT-timedelta(days=age))
            order.update(status='ready', context=dict(topic=name, material_key='old' if name == 'stale' else 'fixed'))
            q.enqueue(self.queue, order)
        def context(narration):
            return narration['context']
        def rebuild(topic):
            return dict(SCRIPT, context=dict(topic=topic, material_key='fixed'))
        with patch.object(q, 'GitQueue', return_value=self.queue), patch.object(stock, 'rebuild', side_effect=rebuild), \
             patch.object(stock, 'asset_context', side_effect=context):
            self.assertEqual(stock.prioritize(['plain', 'new', 'stale', 'old']), ['old', 'new', 'plain', 'stale'])
        self.assertEqual(next(o for o in self.queue.state.values() if o['episode'] == 'stale')['status'], 'discarded')

    def test_nonzero_deadline_really_expires_and_late_worker_cannot_return(self):
        clock = [AT]
        with patch.object(q, 'now', side_effect=lambda: clock[0]), \
             patch.dict(os.environ, COLLESPO_UI_VOICE_WAIT_MINUTES='1'), \
             patch.object(stock.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0]+timedelta(seconds=seconds))):
            with self.assertRaises(policy.VoiceUnavailable):
                stock.fulfill(copy.deepcopy(SCRIPT), self.folder/'n.json', self.folder/'audio', self.queue)
            self.assertEqual(clock[0], AT+timedelta(minutes=1))
            synth = unittest.mock.Mock()
            worker.process(self.queue, self.folder/'cache', synth, portraits())
            synth.assert_not_called()
            self.assertEqual(next(iter(self.queue.state.values()))['status'], 'expired')

    def test_worker_lock_releases_and_cannot_overlap(self):
        with worker.single_worker(self.folder/'lock') as first:
            self.assertTrue(first)
            with worker.single_worker(self.folder/'lock') as second:
                self.assertFalse(second)
        with worker.single_worker(self.folder/'lock') as third:
            self.assertTrue(third)

    def test_broken_return_is_rejected_and_never_adopted_as_ui(self):
        order = self.order()
        worker.process(self.queue, self.folder/'cache', tone, portraits())
        saved, bundle = stock.take(self.queue, order['id'])
        bundle['seg_000.flac'] = b'broken'
        with self.assertRaisesRegex(q.QueueError, '指紋'):
            stock.install(saved, bundle, self.folder/'audio', SCRIPT)

    def test_public_payload_is_encrypted_shared_and_changes_only_with_parts_or_key(self):
        first = self.order()
        images = portraits()
        worker.process(self.queue, self.folder/'cache', tone, images)
        ref = self.queue.state[first['id']]['parts_ref']
        encrypted = self.queue.files[ref]
        second = self.order(episode='second')
        worker.process(self.queue, self.folder/'cache', tone, images)
        self.assertEqual(ref, self.queue.state[second['id']]['parts_ref'])
        self.assertEqual(encrypted, self.queue.files[ref])
        for name, blob in self.queue.files.items():
            q.validate_file(name, blob)
            self.assertFalse(blob.startswith(b'\x89PNG'), name)
            self.assertFalse(name.endswith(('.png', '/parts.json')), name)
            self.assertNotIn(images['p000.png'], blob)
            self.assertNotIn(images['parts.json'], blob)
        self.assertEqual(parts_crypto.decrypt(ref, encrypted), images)
        changed = dict(images)
        changed['parts.json'] = q.encoded(dict(json.loads(images['parts.json']), revision=2))
        third = self.order(episode='changed')
        worker.process(self.queue, self.folder/'cache', tone, changed)
        ref2 = self.queue.state[third['id']]['parts_ref']
        self.assertNotEqual(ref, ref2)
        self.queue.state[first['id']]['status'] = self.queue.state[second['id']]['status'] = 'used'
        compact = q.compact(self.queue.state, self.queue.files)
        self.assertNotIn(ref, compact)
        self.queue.state[third['id']]['status'] = 'used'
        compact = q.compact(self.queue.state, compact)
        self.assertIn(ref2, compact)  # 消費後も最新の一組を次の回に再利用。
        with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=base64.b64encode(b'x'*32).decode('ascii')):
            fourth = self.order(episode='rotated')
            worker.process(self.queue, self.folder/'cache', tone, changed)
            self.assertNotEqual(ref2, self.queue.state[fourth['id']]['parts_ref'])

    def test_wrong_key_tampering_and_plaintext_are_rejected(self):
        order = self.order()
        worker.process(self.queue, self.folder/'cache', tone, portraits())
        ref = self.queue.state[order['id']]['parts_ref']
        blob = self.queue.files[ref]
        with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=base64.b64encode(b'x'*32).decode('ascii')):
            with self.assertRaises(q.QueueError):
                parts_crypto.decrypt(ref, blob)
            saved, bundle = stock.take(self.queue, order['id'])
            with self.assertRaises(q.QueueError):
                stock.install(saved, bundle, self.folder/'wrong', SCRIPT)
            self.assertFalse((self.folder/'wrong/portrait').exists())
        with self.assertRaises(q.QueueError):
            parts_crypto.decrypt(ref, blob[:-1]+bytes([blob[-1] ^ 1]))
        for name, data in [('payload/'+order['id']+'/p000.png', portraits()['p000.png']),
                           ('payload/'+order['id']+'/parts.json', portraits()['parts.json']),
                           (ref, portraits()['p000.png'])]:
            with self.assertRaises(q.QueueError):
                q.validate_file(name, data)

    def test_missing_or_invalid_key_falls_back_before_connecting_or_synthesizing(self):
        path = self.folder/'script.json'
        path.write_bytes(q.encoded(SCRIPT))
        for key in ('', 'invalid', base64.b64encode(b'short').decode('ascii')):
            with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=key), \
                 patch.object(q, 'GitQueue') as remote, patch.object(stock.time, 'sleep') as wait:
                with self.assertRaises(policy.VoiceUnavailable):
                    stock.fulfill(copy.deepcopy(SCRIPT), path, self.folder/'no-key')
                remote.assert_not_called(); wait.assert_not_called()
                with patch(__name__+'.tone') as synth:
                    with self.assertRaises(q.QueueError):
                        worker.process(self.queue, self.folder/'cache', synth, portraits())
                    synth.assert_not_called()
        import synthesize_narration as sn
        audio = self.folder/'missing-key-audio'
        with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=''), patch.object(q, 'GitQueue') as remote, \
             patch.object(sn, 'engine_available', return_value=True), \
             patch.object(sn, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)) as synth, \
             patch.object(sys, 'argv', ['synthesize', '--narration', str(path), '--out-dir', str(audio)]):
            sn.main()
            remote.assert_not_called()
            self.assertEqual(synth.call_args.args[1], 2)
        manifest = json.loads((audio/'manifest.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['voice_resolution']['host'], 'metan')

    def test_launcher_updates_clean_main_before_worker_and_stops_on_failure(self):
        shell = shutil.which('powershell') or shutil.which('pwsh')
        if not shell:
            self.skipTest('PowerShell is not installed')
        scripts = self.folder/'launcher/scripts'
        scripts.mkdir(parents=True)
        source = (q.ROOT/'scripts/run_ui_voice_worker.ps1').read_text(encoding='utf-8-sig')
        # 実運用中の係と排他名を共用すると、起動を省いて試験が不定期に失敗する。
        # 試験ごとの専用名にし、実運用の係には触れない。
        mutex = r"'Local\CollespoUiVoiceWorker'"
        self.assertEqual(source.count(mutex), 1)
        source = source.replace(mutex, rf"'Local\CollespoUiVoiceWorker-Test-{self.folder.name}'")
        # テストでは実ユーザーの変数を絶対に読まない。Git/Pythonも固定の関数。
        source = source.replace("[Environment]::GetEnvironmentVariable('COLLESPO_UI_PARTS_KEY', 'User')", "'fixture-only'")
        source = source.replace("[Environment]::GetEnvironmentVariable('COLLESPO_APSC_ROOT', 'User')", "''")
        source = source.replace("Write-Output 'Worker update failed. Check clean main, origin and Git connection.'",
                                'Write-Output $_.Exception.Message')
        launcher = scripts/'run.ps1'
        launcher.write_text(source, encoding='utf-8-sig')
        fixture = scripts/'fixture.ps1'
        fixture.write_text(r'''
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'calls.txt'
function global:git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$GitArgs)
    Add-Content -LiteralPath $log -Value ($GitArgs -join ' ')
    $global:LASTEXITCODE = 0
    switch ($GitArgs[2]) {
        'branch' { if ($env:COLLESPO_LAUNCHER_TEST_CASE -eq 'branch') { 'other' } else { 'main' } }
        'remote' { if ($env:COLLESPO_LAUNCHER_TEST_CASE -eq 'origin') { 'other' } else { 'https://github.com/issakatou2-bit/sports-notify-mvp.git' } }
        'status' { if ($env:COLLESPO_LAUNCHER_TEST_CASE -eq 'dirty') { ' M scripts/changed.py' } }
        'pull' { Write-Error 'fixture fetch progress'; if ($env:COLLESPO_LAUNCHER_TEST_CASE -eq 'pull') { $global:LASTEXITCODE = 1 } }
        default { throw 'Unexpected Git operation' }
    }
}
function global:FixturePython {
    param([string]$Script)
    Add-Content -LiteralPath $log -Value ('worker '+$Script)
    if ($env:COLLESPO_UI_PARTS_KEY -ne 'fixture-only') { throw 'key' }
    Write-Error 'fixture worker warning'
    $global:LASTEXITCODE = 0
}
& (Join-Path $PSScriptRoot 'run.ps1') -Python FixturePython
exit $LASTEXITCODE
''', encoding='utf-8-sig')
        for case in ('ok', 'branch', 'origin', 'dirty', 'pull'):
            with self.subTest(case=case):
                log = scripts/'calls.txt'
                log.unlink(missing_ok=True)
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File', str(fixture)],
                                        env=dict(os.environ, COLLESPO_LAUNCHER_TEST_CASE=case),
                                        capture_output=True, timeout=30)
                self.assertTrue(log.is_file(), result.stdout+result.stderr)
                calls = log.read_text(encoding='utf8').splitlines()
                if case == 'ok':
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn('pull --ff-only origin main', calls[-2])
                    self.assertTrue(calls[-1].startswith('worker '))
                    self.assertIn('ui_voice_worker.py', calls[-1])
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(any(c.startswith('worker ') for c in calls))
                    if case != 'pull':
                        self.assertFalse(any('pull --ff-only' in c for c in calls))
        self.assertFalse((self.folder/'audio/manifest.json').exists())

    def test_default_never_contacts_queue_and_preserves_synthesis_bytes(self):
        import synthesize_narration as sn
        script = copy.deepcopy(SCRIPT)
        path = self.folder/'narration.json'
        path.write_bytes(q.encoded(script))
        raw = path.read_bytes()
        audio = self.folder/'audio'
        with patch.dict(os.environ, COLLESPO_SOLO_HOST=''), patch.object(q, 'GitQueue', side_effect=AssertionError('既定の外部接続')), \
             patch.object(sn, 'engine_available', return_value=True), \
             patch.object(sn, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)), \
             patch.object(sys, 'argv', ['synthesize', '--narration', str(path), '--out-dir', str(audio)]):
            sn.main()
        self.assertEqual(path.read_bytes(), raw)
        self.assertNotIn('voice_resolution', json.loads((audio/'manifest.json').read_text(encoding='utf8')))
        expected = self.folder/'expected.wav'
        tone('', expected)
        self.assertEqual((audio/'seg_000.wav').read_bytes(), expected.read_bytes())
        current_manifest = (audio/'manifest.json').read_bytes()
        # 基点の本番コードを同じ固定音・同じ出力先で動かし、既定の全バイトを照合。
        source = subprocess.check_output(['git', 'show', '69abfa47:scripts/synthesize_narration.py'], cwd=q.ROOT).decode('utf8')
        previous = types.ModuleType('synthesis_before_queue')
        previous.__file__ = sn.__file__
        exec(compile(source, sn.__file__, 'exec'), previous.__dict__)
        with patch.dict(os.environ, COLLESPO_SOLO_HOST=''), patch.object(previous, 'engine_available', return_value=True), \
             patch.object(previous, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)), \
             patch.object(sys, 'argv', ['synthesize', '--narration', str(path), '--out-dir', str(audio)]):
            previous.main()
        self.assertEqual((audio/'manifest.json').read_bytes(), current_manifest)
        self.assertEqual((audio/'seg_000.wav').read_bytes(), expected.read_bytes())

    def test_social_credit_uses_published_voice_not_current_ui_preference(self):
        import buffer_daily as daily
        import solo_host
        record = dict(title='【MLB】固定の成績 #Shorts', video_id='fixture', description=solo_host.UI_CREDIT)
        self.assertIn(solo_host.UI_CREDIT, daily.caption('instagram', '2026-10-15', record))
        fallback = dict(record, description='音声: VOICEVOX:四国めたん')
        self.assertNotIn('雨衣', daily.caption('instagram', '2026-10-15', fallback))
        with patch.dict(os.environ, COLLESPO_SOLO_HOST=''):
            before = daily.caption('instagram', '2026-10-15', fallback)
        with patch.dict(os.environ, COLLESPO_SOLO_HOST='ui'):
            self.assertEqual(before, daily.caption('instagram', '2026-10-15', fallback))

    def test_git_snapshot_has_one_commit_and_conflict_preserves_both_orders(self):
        remote, a, b = [self.folder/name for name in ('remote.git', 'a', 'b')]
        def git(*args):
            return subprocess.run(['git', *map(str, args)], check=True, capture_output=True).stdout.decode().strip()
        git('init', '--bare', remote)
        for repo in (a, b):
            git('init', repo)
            git('-C', repo, 'remote', 'add', 'origin', remote.as_posix())
        qa, qb = q.GitQueue(a), q.GitQueue(b)
        one = q.make_order(SCRIPT, 'one', at=AT)
        two = q.make_order(SCRIPT, 'two', at=AT)
        original = qa.git
        raced = []
        def race(*args, **kw):
            if args[0] == 'push' and not raced:
                raced.append(True)
                q.enqueue(qb, two)
            return original(*args, **kw)
        with patch.object(qa, 'git', side_effect=race):
            q.enqueue(qa, one)
        _, rows, _ = qa.read()
        self.assertEqual(set(rows), {one['id'], two['id']})
        q.terminal(qa, one['id'], 'expired')
        worker.process(qa, self.folder/'git-cache', tone, portraits())
        _, rows, files = qa.read()
        ref = rows[two['id']]['parts_ref']
        self.assertEqual(parts_crypto.decrypt(ref, files[ref]), portraits())
        self.assertFalse(any(blob.startswith(b'\x89PNG') for blob in files.values()))
        with self.assertRaises(q.QueueError):
            qa.update(lambda state, blobs: blobs.update({'payload/'+two['id']+'/p000.png': portraits()['p000.png']}))
        self.assertIsNotNone(stock.take(qa, two['id']))
        _, _, files = qa.read()
        self.assertEqual(set(files), {'parts/current.json', 'worker-health.json', ref})
        self.assertEqual(git('--git-dir', remote, 'rev-list', '--count', 'ui-voice-queue'), '1')


if __name__ == '__main__':
    # run_checksの追加引数はunittestへ渡さない。
    unittest.main(argv=[__file__])
