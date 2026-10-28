"""共通道具で見本を合成し、目と服の分類一覧を再生成する。"""
import hashlib
import importlib.util
import json
from pathlib import Path

from export_all_portrait_parts import REPORT, ROOT, sheet
from portrait_parts import compose_parts, load_parts


def review(package):
    spec = importlib.util.spec_from_file_location('shared_common', package / 'portrait_parts.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    samples, evidence = [], {}
    for who in ('四国めたん', 'ずんだもん'):
        folder = ROOT / 'assets/portraits' / who
        data = load_parts(folder)
        composer = common.Composer(package / who)
        samples.append((who + ' neutral', composer.image()))
        if who == 'ずんだもん':
            samples.append(('ずんだもん 上向き', composer.image('上向き_neutral')))
        for direction, kinds in data['presets'].items():
            neutral = kinds['expressions']['neutral']['files']
            catalog = {r['file']: r for r in data['catalog']}
            items = []
            for r in data['catalog']:
                if r['slot'] != 'eye' or r['direction'] not in ('共通', direction):
                    continue
                files = [f for f in neutral if catalog[f]['slot'] != 'eye'] + [r['file']]
                label = Path(r['file']).stem.removeprefix('差分_').replace('頭_正面向き_目_', '').replace('頭_上向き_目_', '')
                label += '\n' + ('emphatic_eyes' if r['emphatic'] else 'mood: ' + r['mood'])
                items.append((label, compose_parts(folder, data, files, context='異変')))
            path = REPORT / f'{who}_{direction}_目の区分.png'
            sheet(items, f'{who} {direction} 10/27 目の区分', path, face=True)
            evidence[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if who == '四国めたん':
            neutral = data['presets']['共通']['expressions']['neutral']['files']
            stripped = [f for f in neutral if catalog[f]['slot'] not in ('outfit', 'arm_front', 'arm_back')]
            bare = next(r['file'] for r in data['catalog'] if r['file'].endswith('_素体.png'))
            items = []
            for r in data['catalog']:
                if r['slot'] != 'outfit':
                    continue
                if r['usage'] == '既定':
                    files = neutral
                else:
                    files = stripped + ([bare] if r['file'] == bare else [bare, r['file']])
                label = Path(r['file']).stem.removeprefix('差分_') + '\n' + r['usage']
                items.append((label, compose_parts(folder, data, files, automatic=False)))
            path = REPORT / '四国めたん_服の区分.png'
            sheet(items, '白ロリ服＝既定 / その他＝必要時のみ（自動動画は選択禁止）', path)
            evidence[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = REPORT / '共通形式_合成見本.png'
    sheet(samples, '共通portrait_parts.py（無変更）で合成', path)
    evidence[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (REPORT / 'shared_review_hashes.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    review(ROOT / 'build/shared-portraits')
