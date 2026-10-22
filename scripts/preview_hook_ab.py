"""保存済み材料だけでA/B原稿・動画を作る。公開・材料取得・有料APIは持たない。"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

import hook_ab


def build_pair(kind, day, topic=None):
    spec = None
    if kind == 'morning_press':
        import generate_morning_short as g
        import daily_v3
        data = json.loads(Path('data/morning_recap.json').read_text(encoding='utf-8'))
        data['reporters'] = json.loads(Path('data/local_reporters.json').read_text(encoding='utf-8'))
        # 見本も現在のデザイン設定で作る。未採用の描画へ切り替えない。
        base = g.build_narration(data, 'press')
        daily_v3.prepare(data, base, 'press')
    else:
        import generate_asset_video as g
        if not topic:
            topic = next(k for k in g.LIST_TOPICS if k.startswith('season_player_'))
        if not topic.startswith('season_player_'):
            raise ValueError('選手シーズンまとめのトピックを指定してください')
        spec = g.LIST_TOPICS[topic]
        base = g.build_narration(topic)
        for seg in base['segments']:
            seg.setdefault('speaker', 2)
    import host_split
    import ui_tone
    base = host_split.adapt(base, kind, day)
    base = ui_tone.narration(base)
    return {v: hook_ab.prepare(copy.deepcopy(base), kind, day, spec, preview=v) for v in ('A', 'B')}, topic


def commands(kind, topic, narration, audio, out):
    synth = [sys.executable, 'scripts/synthesize_narration.py', '--narration', str(narration), '--out-dir', str(audio)]
    render = [sys.executable, 'scripts/generate_morning_short.py', '--mode', 'press'] if kind == 'morning_press' else [sys.executable, 'scripts/generate_asset_video.py', '--topic', topic]
    render += ['--narration', str(narration), '--audio-dir', str(audio), '--out', str(out)]
    return [synth, render]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=hook_ab.KINDS, required=True)
    parser.add_argument('--day', default='2026-10-23')
    parser.add_argument('--topic')
    parser.add_argument('--out', default='build_reports/hook_ab_samples')
    parser.add_argument('--render', action='store_true', help='既存の音声合成・描画を実行。公開しない')
    args = parser.parse_args()
    pair, topic = build_pair(args.kind, args.day, args.topic)
    for variant, narration in pair.items():
        out = Path(args.out)/(topic or args.kind)/variant
        out.mkdir(parents=True, exist_ok=True)
        saved = out/'narration.json'
        saved.write_text(json.dumps(narration, ensure_ascii=False, indent=2), encoding='utf-8')
        print(variant, narration['hook_ab'])
        steps = commands(args.kind, topic, saved, out/'audio', out)
        (out/'commands.json').write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding='utf-8')
        # Windows/PowerShellでも実行できる表示。実行時は文字列でなく引数配列を渡す。
        for command in steps:
            print('& ' + ' '.join("'"+str(x).replace("'", "''")+"'" for x in command))
            if args.render:
                subprocess.run(command, check=True)
                if command == steps[0]:
                    manifest = json.loads((out/'audio'/'manifest.json').read_text(encoding='utf-8'))
                    if not manifest.get('segments') or any(not s.get('file') for s in manifest['segments']):
                        raise SystemExit('音声を作れませんでした。A/Bの比較に使う無音動画は作らず終了します。')


if __name__ == '__main__':
    main()
