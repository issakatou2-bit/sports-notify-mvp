"""保存した公式材料から見本3本。heavy_wait内限定・投稿機能なし。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'build_reports/jp_assets_20261101'
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
os.environ.update(COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan',
                  COLLESPO_HOST_SPLIT='', COLLESPO_UI_VOICE_STOCK='',
                  COLLESPO_CAPTION_BREAKS='bunsetsu', COLLESPO_MOTION='on', COLLESPO_HOOK_AB='', PYTHONUTF8='1')


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def run(only=None):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=9)))
    if (19, 15) <= (now.hour, now.minute) < (20, 40):
        raise RuntimeError('19:15〜20:40は描画開始禁止')
    import requests
    original_request = requests.sessions.Session.request
    def local_only(session, method, url, **kwargs):
        if urlparse(url).hostname not in ('127.0.0.1', 'localhost'):
            raise RuntimeError('見本制作中の外部通信を禁止: '+urlparse(url).hostname)
        return original_request(session, method, url, **kwargs)
    requests.sessions.Session.request = local_only
    import jp_assets as season_stock
    import generate_asset_video as g
    import review_render_v3 as r3
    import synthesize_narration as synth
    import short_content
    import sanity_material
    import name_reading_guard
    import v3_rules
    OUT.mkdir(parents=True, exist_ok=True)
    document = season_stock.build()
    write(OUT/'topics.json', document)
    desired = [('a_hitting', 'season_compare_2026_660271_673548'),
               ('b_pitching', 'season_compare_2026_808967_684007'),
               ('c_club', 'season_momentum_rs2026_119_823907_823817')]
    if only:
        desired = [(name, key) for name, key in desired if name == only]
    specs = {t['key']:t for t in document['topics']}
    engine, log = None, None
    report = dict(distribution='ローカルのみ・外部送信/投稿なし', samples=[])
    previous_report = __import__('season_stock').read(OUT/'manifest.json') if only else {}
    session = requests.Session()
    session.trust_env = False
    def ready():
        try:
            return session.get('http://127.0.0.1:50121/version', timeout=1).status_code == 200
        except requests.RequestException:
            return False
    try:
        if ready():
            raise RuntimeError('50121は既に使用中。共有のVOICEVOXには接続せず、所有者の終了を待つ')
        launcher = ROOT/'build/season-stock/voicevox_local.py'
        if not launcher.exists():
            raise FileNotFoundError('ローカル起動器をbuild/season-stockへ用意してください')
        log = (OUT/'voicevox_start.log').open('w', encoding='utf8')
        engine = subprocess.Popen(['C:/Users/issak/Tools/uv-python/cpython-3.11.16-windows-x86_64-none/python.exe', str(launcher)],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(50):
            if ready():
                break
            if engine.poll() is not None:
                break
            time.sleep(1)
        if not ready():
            raise RuntimeError('VOICEVOXの起動に失敗')
        synth.VOICEVOX_URL = 'http://127.0.0.1:50121'
        for label, key in desired:
            spec = specs[key]
            g.LIST_TOPICS[key] = spec
            folder = OUT/label
            folder.mkdir(exist_ok=True)
            doc = g.build_narration(key)
            for seg in doc['segments']:
                seg['speaker'] = 2
            g.VOICE_CREDIT = __import__('duo').credit(doc['segments'])
            name_reading_guard.validate_dialogue(doc)
            errors = sanity_material.check(doc, sanity_material.grounding([doc]))
            if errors:
                raise ValueError(errors)
            write(folder/'material.json', spec)
            write(folder/'narration.json', doc)
            sys.argv = ['synthesize_narration.py', '--narration', str(folder/'narration.json'), '--out-dir', str(folder/'audio')]
            synth.main()
            audio = __import__('season_stock').read(folder/'audio/manifest.json')
            if any(not s.get('file') or not s.get('duration') for s in audio['segments']):
                raise ValueError('実音声の欠測')
            durations = g.plan_durations(audio['segments'])
            gate = short_content.assess(doc, durations, spec)
            item = dict(name=label, key=key, material_checks=errors, content=gate)
            report['samples'].append(item)
            if gate['reasons']:
                item['rejected'] = gate['reasons']
                continue
            sys.argv = ['generate_asset_video.py', '--topic', key, '--narration', str(folder/'narration.json'),
                        '--audio-dir', str(folder/'audio'), '--out', str(folder)]
            g.main()
            video = folder/f'collespo_asset_{key}.mp4'
            item['video'] = str(video.relative_to(OUT))
            item['upload_gate'] = short_content.validate_upload(video)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
            item['decode_ok'] = True
            # 完成MP4から各場面の入り・中央を抽出。機械検査と人の目の根拠を分ける。
            stills = []
            elapsed = 0.0
            for i, (seg, duration) in enumerate(zip(doc['segments'], durations)):
                for tag, offset in [('start', min(1.3, duration/3)), ('middle', duration/2)]:
                    stamp = elapsed+offset
                    path = folder/f'frame_{i:02d}_{tag}.png'
                    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(stamp),'-i',str(video),'-frames:v','1',str(path)], check=True)
                    stills.append(dict(path=str(path.relative_to(OUT)), seconds=stamp))
                elapsed += duration
            item['frames'] = stills
            # 停止した本文画面も原寸で検査する。
            layout = []
            for i, (seg, duration) in enumerate(zip(doc['segments'], durations)):
                r3.set_program_clock(sum(durations[:i]))
                r3.set_caption(seg['text'] if seg['kind'] != 'outro' else '', duration, sum(durations), speaker=2)
                im = g.render_v3(min(3.0,duration/2), seg['kind'], seg['meta'], spec, key, seg, duration)
                layout.extend(v3_rules.check_layout(im))
            item['layout_checks'] = layout
            write(OUT/'manifest.json', report)
    finally:
        if engine and engine.poll() is None:
            engine.terminate()
            engine.wait(timeout=20)
        if engine:
            report['owned_voicevox'] = dict(pid=engine.pid, stopped=engine.poll() is not None, returncode=engine.returncode)
        if log:
            log.close()
        if only:
            report['samples'].extend(row for row in previous_report.get('samples', []) if row['name'] != only)
            report['samples'].sort(key=lambda row:row['name'])
        write(OUT/'manifest.json', report)
        requests.sessions.Session.request = original_request


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['a_hitting', 'b_pitching', 'c_club'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'render.log').open('w', encoding='utf8', buffering=1) as output:
        sys.stdout = sys.stderr = output
        try:
            run(args.only)
        except BaseException:
            traceback.print_exc()
            raise
