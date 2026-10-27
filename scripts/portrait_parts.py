"""parts.jsonだけから部品を解決し、描画前に組合せを検査する。"""
import json
from pathlib import Path

from PIL import Image


def load_parts(folder):
    return json.loads((Path(folder) / 'parts.json').read_text(encoding='utf-8'))


def validate_parts(data, files, *, context='平時'):
    catalog = {r['file']: r for r in data['catalog']}
    if len(files) != len(set(files)):
        raise ValueError('同じ部品の重複')
    if any(f not in catalog for f in files):
        raise ValueError('未登録の部品（白目・黒目は分離せず目セットを選択）')
    selected = [catalog[f] for f in files]
    rules = data['rules']
    if len({rules['directions'][f] for f in files} - {'共通'}) > 1:
        raise ValueError('正面と上向きの混在')
    for group in rules['exclusive_groups'].values():
        if len(set(group) & set(files)) > 1:
            raise ValueError('同じ部位の重複')

    def matches(selector):
        key, value = selector.split(':', 1)
        if key == 'category':
            return any(r['category'] == value and r['bbox'] for r in selected)
        sources = [s for r in selected for s in r['source_layers']]
        if key == 'source':
            return value in sources
        if key == 'source_prefix':
            return any(s.startswith(value) for s in sources)
        raise ValueError('不明な検査指定')

    for f in files:
        if not all(matches(s) for s in rules['requires'][f]):
            raise ValueError('必要な部品がない')
        if any(matches(s) for s in rules['forbids'][f]):
            raise ValueError('組めない部品')
        eye = catalog[f]
        if eye['slot'] == 'eye' and eye.get('mood') not in ('平時', '非平時'):
            raise ValueError('目の用途が未確認')
        if eye.get('mood') == '非平時' and context not in rules['nonordinary_contexts']:
            raise ValueError('虚ろな目は非平時の場面だけ（普段の感情・事実説明は禁止）')
    arms = [r for r in selected if r['slot'] in ('arm_front', 'arm_back') and r['bbox']]
    if sum(r['file'] in rules['pointing_arms'] for r in arms) > rules['max_pointing_arms']:
        raise ValueError('指さしは同時に1本まで')
    if len(arms) == 2:
        pair = sorted(r['file'] for r in arms)
        if pair not in rules['allowed_arm_pairs']:
            raise ValueError('両手が別々の意味になる組合せ')
    return selected


def compose_parts(folder, data, files, *, context='平時'):
    # 検査が完了するまでPNGを開かない。
    selected = validate_parts(data, files, context=context)
    image = Image.new('RGBA', data['size'])
    for record in sorted(selected, key=lambda r: r['order']):
        with Image.open(Path(folder) / record['file']) as layer:
            image = Image.alpha_composite(image, layer.convert('RGBA'))
    return image
