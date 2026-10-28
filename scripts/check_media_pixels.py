"""指定commitと現在の同一素材を別プロセスで描き、全画素を比較する（通信なし）。

heavy_wait --minutes 30 の内側で実行する。履歴のコードは一時的な読込だけで採用版を書き換えない。
"""
import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('generate_morning_short', 'generate_asset_video', 'generate_longform', 'longform_render_v3',
           'bignumber_render', 'v3_slot_render', 'soccer_slots_v4', 'soccer_readable', 'synthesize_narration')


class HistoricalModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, ref):
        self.ref = ref

    def find_spec(self, fullname, path=None, target=None):
        if fullname in MODULES:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        source = subprocess.run(['git', 'show', f'{self.ref}:scripts/{name}.py'], cwd=ROOT,
                                capture_output=True, check=True).stdout
        module.__file__ = str(ROOT / 'scripts' / (name + '.py'))
        exec(compile(source, module.__file__, 'exec'), module.__dict__)


def sample(ref):
    if ref != 'current':
        sys.meta_path.insert(0, HistoricalModules(ref))
    sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]
    os.chdir(ROOT)
    # 動作指定・フォントを両プロセスで固定。生成・API・公開は呼ばない。
    os.environ.update(COLLESPO_SOLO_HOST='metan', COLLESPO_HOST_SPLIT='off', COLLESPO_DUO='off',
                      COLLESPO_MOTION='off', COLLESPO_SHORT_LOOK='v4')
    os.environ.pop('COLLESPO_BUBBLE', None)
    import generate_morning_short as g
    import review_render_v3 as r3
    rows = []

    def keep(label, image):
        if image is None:
            rows.append(dict(label=label, size=None, sha256=None))
            return
        raw = image.convert('RGB').tobytes()
        rows.append(dict(label=label, size=list(image.size), sha256=hashlib.sha256(raw).hexdigest()))
        image.close()

    # 既存の全画面検査が持つ固定/保存素材（旧版・長編・資産・サッカー）。
    import test_render
    def capture(label, function, *args, allow_none=False, **kwargs):
        keep('existing/' + label, function(*args, **kwargs))
    test_render.check = capture
    g.set_spoken('字幕はそのままです。3安打でした。')
    test_render.main()

    import generate_longform as lf
    import longform_render_v3 as lr3
    for style in ('legacy', 'v3'):
        segment = dict(kind='talk', speaker=2, text='3安打でした。次の試合の見どころです。' * 12)
        pages = lf.paginate([segment]) if style == 'legacy' else lr3.paginate([segment])
        for page, seg in enumerate(pages):
            for t in (0, 1 / 30, .2, .5, 1.5):
                im = (lf.render_line(min(1, t), seg, topic='固定の話題') if style == 'legacy' else
                      lr3.render_line(t, seg, topic='固定の話題', dur=3))
                keep(f'longform/{style}/{page}/{t}', im)

    import test_daily_v3
    import daily_v3
    for look in ('v3', 'v4'):
        r3.LOOK = look
        data, narration = test_daily_v3.DailyV3().data()
        os.environ['COLLESPO_COMMENTS_DESIGN'] = 'comments'
        design = daily_v3.prepare(data, narration, 'voices')
        for i, seg in enumerate(narration['segments']):
            r3.set_program_clock(0)
            r3.set_caption(seg['text'], 8, 40, speaker=2, hide_caption=seg['kind']=='outro')
            for t in (0, 1 / 30, .3, 1.5, 4.2):
                r3.set_program_clock(t)
                keep(f'daily/{look}/{i}/{t}', daily_v3.frame(t, seg, design, 8))

    r3.LOOK = 'v4'
    import bignumber_render as bn
    import test_bignumber_render
    _, _, narration, scenes = test_bignumber_render.build(ROOT / 'scripts/fixtures/bignumber/morning_recap.json')
    plan = bn.timeline(scenes, [2.0] * len(narration['segments']))
    for i, row in enumerate(plan):
        for delta in (0, 1 / 30, .4):
            r3.set_program_clock(row['t0'] + delta)
            keep(f'bignumber/{i}/{delta}', bn.frame(row['t0'] + delta, plan))

    import generate_asset_video as asset
    topic = 'pixel_fixture'
    spec = dict(style='v3', label='固定の成績', heading='固定の成績', hook='3安打', intro='固定の成績と次の試合を伝えます。',
                items=[('成績', '3安打'), ('次の試合', '見どころ')], v3=dict(big='3', unit='安打', tag='固定'))
    asset.LIST_TOPICS[topic] = spec
    for look in ('v3', 'v4'):
        r3.LOOK = look
        for kind, meta in [('intro', {}), ('list', dict(topic=topic, start=0, count=2)), ('outro', {})]:
            r3.set_program_clock(0)
            r3.set_caption('成績は3安打でした。次の試合です。', 8, 24, speaker=2)
            for t in (0, 1 / 30, .4, 1.5, 4.2):
                r3.set_program_clock(t)
                keep(f'asset/{look}/{kind}/{t}', asset.render_v3(t, kind, meta, spec, topic))

    # 本番の書出しループも最後まで通す。圧縮前の全フレームを捨てずに逐次ハッシュ。
    # 外部通信・投稿・音声生成は呼ばない。既存の合成・結合・圧縮設定は比較対象から分ける。
    from types import SimpleNamespace
    from unittest.mock import patch
    import render_timeline
    import short_content
    import video_common
    import wave
    folder = ROOT / 'build/media-pixels/loop-inputs'
    folder.mkdir(parents=True, exist_ok=True)
    voice = folder / 'fixed.wav'
    with wave.open(str(voice), 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x00\x01' * 6000)
    sinks = []
    class Sink:
        def __init__(self):
            self.sha = hashlib.sha256()
            self.frames = 0
        def write(self, raw):
            self.sha.update(raw)
            self.frames += 1
            return len(raw)
        def close(self):
            pass
    class Process:
        def __init__(self, cmd, **kwargs):
            self.stdin = Sink()
            self.returncode = 0
            Path(cmd[-1]).write_bytes(b'pixel-fixture')
            sinks.append(self.stdin)
        def wait(self):
            return 0
    proxy = SimpleNamespace(**{name: getattr(subprocess, name) for name in dir(subprocess) if not name.startswith('__')})
    proxy.Popen = Process
    def finish_loop(label):
        sink = sinks[-1]
        rows.append(dict(label='loop/' + label, frames=sink.frames, sha256=sink.sha.hexdigest()))
    def document(name, segments):
        path = folder / (name + '.json')
        path.write_text(json.dumps(dict(label='固定', top='固定の話題', segments=segments), ensure_ascii=False), encoding='utf-8')
        audio = folder / (name + '-audio')
        audio.mkdir(exist_ok=True)
        payload = dict(segments=[dict(seg, index=i, file=str(voice), duration=.25) for i, seg in enumerate(segments)])
        (audio / 'manifest.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path, audio
    r3.LOOK = 'v4'
    os.environ.update(COLLESPO_COMMENTS_DESIGN='legacy', COLLESPO_PLAYERS_DESIGN='legacy')
    small = [dict(kind='intro', speaker=2, text='固定の成績です。', meta={}),
             dict(kind='list', speaker=2, text='3安打です。', meta=dict(start=0, count=1)),
             dict(kind='outro', speaker=2, text='コレスポ。', meta={})]
    path, audio = document('morning', small)
    with patch.object(render_timeline.Recorder, 'save'), patch.object(short_content, 'require'), \
         patch.object(g, 'subprocess', proxy), patch.object(g, 'build_narration_track', return_value=None), \
         patch.object(g, 'plan_durations', side_effect=lambda segs: [.7] * len(segs)), \
         patch.object(sys, 'argv', ['render', '--mode', 'local', '--recap', str(ROOT/'scripts/fixtures/bignumber/morning_recap.json'),
                                   '--narration', str(path), '--audio-dir', str(audio), '--out', str(folder/'morning')]):
        g.main()
    finish_loop('morning-legacy')
    path, audio = document('asset', small)
    with patch.object(render_timeline.Recorder, 'save'), patch.object(short_content, 'require'), \
         patch.object(asset, 'subprocess', proxy), patch.object(asset, 'build_narration_track', return_value=None), \
         patch.object(asset, 'plan_durations', side_effect=lambda segs: [.7] * len(segs)), \
         patch.object(sys, 'argv', ['render', '--topic', topic, '--narration', str(path), '--audio-dir', str(audio), '--out', str(folder/'asset')]):
        asset.main()
    finish_loop('asset-v4')
    dialogue = [dict(kind=kind, speaker=speaker, text=text, meta={})
                for kind, speaker, text in [('intro', 2, 'コレスポ'), ('intro', 3, 'コレスポ'),
                                            ('talk', 2, '3安打でした。'), ('talk', 3, '次の試合です。'),
                                            ('outro', 2, 'コレスポ'), ('outro', 3, 'コレスポ')]]
    path, audio = document('longform', dialogue)
    for style in ('legacy', 'v3'):
        os.environ['COLLESPO_LONGFORM_STYLE'] = style
        with patch.object(render_timeline.Recorder, 'save'), patch.object(lf, 'subprocess', proxy), \
             patch.object(video_common, 'build_narration_track', return_value=voice), patch.object(lr3, 'add_sound', return_value=voice), \
             patch.object(video_common, 'mix_wavs', return_value=voice), \
             patch.object(sys, 'argv', ['render', '--dialogue', str(path), '--audio-dir', str(audio), '--out', str(folder/('longform-'+style))]):
            lf.main()
        finish_loop('longform-' + style)

    from preview_soccer_selected import saved_cases
    import soccer_slots_v4 as slots
    os.environ['COLLESPO_SOCCER_LOOK'] = 'v6'
    r3.LOOK = 'v4'
    for case in saved_cases():
        if not case.get('plan'):
            continue
        for i, seg in enumerate(case['narration']['segments']):
            r3.set_program_clock(0)
            r3.set_caption(seg['text'], 12, 40, speaker=2, hide_caption=seg['kind']=='outro')
            for t in (0, 1 / 30, .4, 3, 9):
                r3.set_program_clock(t)
                keep(f'soccer/{case["key"]}/{i}/{t}', slots.frame(t, seg, case['plan']))
    import synthesize_narration as synth
    for speaker in (2, 3):
        query = dict(speedScale=1, prePhonemeLength=.1, postPhonemeLength=.1,
                     pauseLengthScale=1, pitchScale=0, intonationScale=1)
        response = SimpleNamespace(content=voice.read_bytes(), json=lambda: dict(query), raise_for_status=lambda: None)
        destination = folder / f'voice-{speaker}.wav'
        with patch.object(synth.requests, 'post', return_value=response) as post, \
             patch.object(synth.name_reading_guard, 'prepare_query', side_effect=lambda original, value, *args: value), \
             patch.object(synth.name_reading_guard, 'validate_query', return_value={}):
            if not synth.synth_one('3安打でした。', speaker, destination):
                raise AssertionError('固定WAVの合成試験に失敗')
        requests = [dict(url=call.args[0], **call.kwargs) for call in post.call_args_list]
        rows.append(dict(label=f'audio/{speaker}', sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), requests=requests))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='c42da5dc')
    parser.add_argument('--out', default='build/media-pixels/result.json')
    parser.add_argument('--sample')
    args = parser.parse_args()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.sample:
        target.write_text(json.dumps(sample(args.sample), ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    ref = subprocess.run(['git', 'rev-parse', '--verify', args.base + '^{commit}'], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    paths = []
    for name in (ref, 'current'):
        path = target.parent / (('before' if name != 'current' else 'after') + '.json')
        paths.append(path)
        subprocess.run([sys.executable, __file__, '--sample', name, '--out', str(path.resolve())], cwd=ROOT, check=True)
    before, after = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    changed = [dict(before=a, after=b) for a, b in zip(before, after) if a != b]
    result = dict(base_commit=ref, samples_before=len(before), samples_after=len(after),
                  changed=changed, matched=len(before)==len(after) and not changed,
                  comparison='同一フォント・素材・指定時刻のRGB全画素SHA256。動画圧縮前の描画を比較')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
