"""非公開のa/b/c見本。heavy_wait内で実行。VoiSona・外部API・投稿は呼ばない。"""
from datetime import date
import argparse
import json
from pathlib import Path
import os
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
OUT = ROOT/'build_reports/return_reason_20261101'
OUT.mkdir(parents=True, exist_ok=True)
# この制作プロセスの見た目。リポジトリ変数・設定ファイルは変更しない。
os.environ['COLLESPO_SHORT_LOOK'] = 'v4'
os.environ['COLLESPO_SOLO_HOST'] = 'metan'
os.environ['COLLESPO_HOST_SPLIT'] = ''
os.environ['COLLESPO_UI_VOICE_STOCK'] = ''
os.environ['COLLESPO_MOTION'] = 'on'
os.environ['PYTHONUTF8'] = '1'


def run(only=None):
    import requests
    os.environ['COLLESPO_OUTRO_NEXT'] = 'off'
    import offseason_news as n
    import generate_asset_video as g
    import synthesize_narration as synth
    import review_render_v3 as r3
    import short_content
    import sanity_material
    import v3_rules
    day = date(2026, 10, 30)
    jp, table = n.names()
    # MLB公式/BBWAAの公表内容をAPIの受賞行の形に写した過年度見本。
    # 2026年の未発表結果ではなく、APIで実際に受信した応答とも扱わない。
    source = 'https://www.mlb.com/awards/2025'
    confirmed = [('NLMVP', 660271, 'Shohei Ohtani'), ('ALMVP', 592450, 'Aaron Judge'),
                 ('ALCY', 669373, 'Tarik Skubal'), ('NLCY', 694973, 'Paul Skenes')]
    payloads = {award: {'awards': [dict(season='2025', rank=1, player=dict(id=ident, name=name))]}
                for award, ident, name in confirmed}
    awards = n.award_rows(payloads, 2025, jp, table)
    # cは過年度の期間まとめ。現行の直近7日ニュースとは別の非公開見本。
    moves = json.loads((ROOT/'scripts/fixtures/offseason-real/transactions.json').read_text(encoding='utf-8'))
    start, end = date(2025, 10, 29), date(2025, 12, 21)
    historical = n.transaction_rows(moves, start, end, jp, table, set())
    # 菅野の宣言・今永の宣言・村上の契約。実物に無い契約規模や経路は補わない。
    historical = [r for r in historical if r['raw']['id'] in (874305, 879420) or
                  (r['raw']['person']['fullName'] == 'Shota Imanaga' and r['raw']['typeCode'] == 'DFA')]
    # 保存応答だけを利用。未提供の成績は省略し、実数の代わりに試験値を入れない。
    def saved_stats(path, **params):
        ident = path.split('/')[1]
        saved = ROOT/'scripts/fixtures/offseason-real'/f'person_{ident}_season_{params["season"]}.json'
        return json.loads(saved.read_text(encoding='utf-8')) if saved.exists() else {}
    historical = n.enrich_transactions(historical, saved_stats)
    c = __import__('jp_future_series').topic(historical, end, 2025, state={})
    c['offseason']['window_start'] = str(start)
    c['offseason_sample'] = True
    c['label'] = c['heading'] = c['hook'] = '日本人選手の来季 第1回（2025年の過年度見本）'
    c['intro'] = n.sample_intro('transactions', 2025)
    c['source'] = 'MLB公式 / 2025年オフの過年度見本'
    c['v3']['source'] = '出典: MLB Stats API / 2025年10〜12月'
    specs = [c]
    report = dict(distribution='ローカル見本のみ。外部へ送信しない',
                  awards_note='2025年受賞結果の過年度動作見本。公式本文をAPI形状に転記。実API応答の確認ではない。',
                  awards_sources=[source, 'https://bbwaa.com/awards/'], samples=[])
    engine = None
    engine_log = None
    session = requests.Session()
    session.trust_env = False
    def ready():
        try:
            return session.get('http://127.0.0.1:50121/version', timeout=1).status_code == 200
        except requests.RequestException:
            return False
    try:
        if not ready():
            engine_log = (OUT/'voicevox_engine.log').open('w', encoding='utf-8')
            # Windowsの既知フォルダはLOCALAPPDATAでは切り替わらない。
            # 既存のローカル起動器がある時は、その作業場内保存を再利用する。
            launcher = ROOT/'build/offseason/voicevox_local.py'
            command = (['C:/Users/issak/Tools/uv-python/cpython-3.11.16-windows-x86_64-none/python.exe', str(launcher)]
                if launcher.exists() else ['C:/Users/issak/Tools/voicevox/windows-cpu/run.exe',
                '--host', '127.0.0.1', '--port', '50121', '--cpu_num_threads', '2', '--output_log_utf8'])
            engine = subprocess.Popen(command, cwd=ROOT,
                stdout=engine_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(40):
                if ready():
                    break
                if engine.poll() is not None:
                    break
                time.sleep(1)
        voice = ready()
        synth.VOICEVOX_URL = 'http://127.0.0.1:50121'
        for label, spec in zip(('series_2025',), specs):
            if only and label != only:
                continue
            folder = OUT/label
            folder.mkdir(exist_ok=True)
            if label.startswith('b_'):
                spec['offseason_sample'] = True
                spec['label'] = spec['heading'] = '2025年のMLB表彰の見本'
                spec['hook'] = '2025年の受賞結果'
                spec['intro'] = 'これは2025年のMLB表彰を使った動作見本です。2026年の受賞結果ではありません。'
                spec['source'] = 'MLB公式 / 2025年の受賞結果'
                spec['v3']['source'] = '出典: MLB.com/awards/2025 / 過年度見本'
            key = spec['key']
            g.LIST_TOPICS[key] = spec
            doc = g.build_narration(key)
            for seg in doc['segments']:
                seg['speaker'] = 2
            g.VOICE_CREDIT = __import__('duo').credit(doc['segments'])
            narration = folder/'narration.json'
            narration.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
            (folder/'material.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
            errors = sanity_material.check(doc, sanity_material.grounding([doc]))
            if errors:
                raise ValueError(errors)
            layout = []
            for index, seg in enumerate(doc['segments']):
                r3.set_program_clock(index*10)
                r3.set_caption(seg['text'] if seg['kind'] != 'outro' else '', 10, len(doc['segments'])*10, speaker=2)
                im = g.render_v3(3.0, seg['kind'], seg['meta'], spec, key, seg, 10)
                im.save(folder/f'{index:02d}_{seg["kind"]}.png')
                layout.extend(v3_rules.check_layout(im))
            sample = dict(name=label, material_checks=errors, layout_checks=layout, voice=voice)
            report['samples'].append(sample)
            if not voice:
                sample['unverified'] = 'VOICEVOXに接続できず、静止画と原稿のみ。実音声・実尺・完成動画は未確認。'
                continue
            sys.argv = ['synthesize_narration.py', '--narration', str(narration), '--out-dir', str(folder/'audio')]
            synth.main()
            manifest = json.loads((folder/'audio/manifest.json').read_text(encoding='utf-8'))
            if any(not s.get('file') or not s.get('duration') for s in manifest['segments']):
                raise ValueError('実音声が不足しています')
            durations = g.plan_durations(manifest['segments'])
            gate = short_content.assess(doc, durations, spec)
            sample['short_content'] = gate
            if gate['reasons']:
                sample['unverified'] = '情報・尺の下限または上限により制作を見送り'
                continue
            sys.argv = ['generate_asset_video.py', '--topic', key, '--narration', str(narration),
                        '--audio-dir', str(folder/'audio'), '--out', str(folder)]
            g.main()
            video = folder/f'collespo_asset_{key}.mp4'
            sample['completed_video'] = str(video.relative_to(OUT))
            sample['actual_content_check'] = short_content.validate_upload(video)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
    finally:
        if engine and engine.poll() is None:
            # 自分で起動したCPUエンジンだけ終了。共有VoiSona等には触れない。
            engine.terminate()
            engine.wait(timeout=20)
        if engine:
            report['owned_voicevox'] = dict(pid=engine.pid, returncode=engine.returncode, stopped=engine.poll() is not None)
        if engine_log:
            engine_log.close()
        if only and (OUT/'manifest.json').exists():
            previous = json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
            report['samples'].extend(s for s in previous['samples'] if s['name'] != only)
            report['samples'].sort(key=lambda s: s['name'])
        (OUT/'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['a_schedule', 'b_awards_2025', 'series_2025'])
    args = parser.parse_args()
    with (OUT/'render.log').open('w', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            run(args.only)
        except BaseException:
            traceback.print_exc()
            raise
