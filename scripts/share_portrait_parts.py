"""APSC共通形式へ変換し、指定先へ全部品をコピー（既定はbuild内）。

共通portrait_parts.pyは変更しない。catalog版parts.jsonはcatalog.jsonとして保持。
python scripts/share_portrait_parts.py --destination build/shared-portraits
"""
import argparse
import copy
import itertools
import json
from pathlib import Path
import shutil

from portrait_parts import load_parts

ROOT = Path(__file__).resolve().parent.parent
SHARED = Path('C:/Users/issak/Tools/shared-portraits')


def common_manifest(data):
    records = data['catalog']
    catalog = {r['file']: r for r in records}
    metan = data['source']['file'].startswith('四国')
    parts, slots = {}, {}
    def slot_for(r):
        slot, f = r['slot'], r['file']
        if slot == 'head':
            if '枝豆_' in f:
                return 'head_accessory'
            if '髪留め' in f:
                return 'head_accessory'
            for text, key in [('ツインドリル右', 'hair_right'), ('ツインドリル左', 'hair_left'),
                              ('ポニテ', 'hair_ponytail'), ('うさみみ', 'head_ears'), ('ヘッドドレス', 'head_dress')]:
                if text in f:
                    return key
        if slot == 'cheek' and 'かげり' in f:
            return 'cheek_shadow'
        if slot == 'prop':
            return 'prop_back' if '右腕' in f else 'prop_front'
        return slot
    for r in records:
        slot = slot_for(r)
        name = Path(r['file']).stem.removeprefix('差分_')
        slots[r['file']] = (slot, name)
        parts.setdefault(slot, {})[name] = r['file']
    # 共通resolverではoutfitは1つ。素体と衣装を1選択のファイル配列にする。
    if metan:
        bare = next(r['file'] for r in records if r['file'].endswith('_素体.png'))
        for name, file in parts['outfit'].items():
            if 'その他の服' in file and file != bare:
                parts['outfit'][name] = [bare, file]
    def seq(value):
        return value if isinstance(value, list) else [value]
    choices = [(slot, name, seq(value)) for slot, entries in parts.items() for name, value in entries.items()]
    rules = []
    def matches(r, selector):
        key, value = selector.split(':', 1)
        if key == 'category':
            return r['category'] == value and bool(r['bbox'])
        return any(s == value if key == 'source' else s.startswith(value) for s in r['source_layers'])
    def conflicts(a, b):
        ra, rb = catalog[a], catalog[b]
        if a == b:
            return True
        if ra['direction'] != rb['direction'] and '共通' not in (ra['direction'], rb['direction']):
            return True
        if ra['exclusive_group'] and ra['exclusive_group'] == rb['exclusive_group']:
            return True
        if any(matches(rb, s) for s in ra['forbids']) or any(matches(ra, s) for s in rb['forbids']):
            return True
        if {ra['slot'], rb['slot']} == {'arm_front', 'arm_back'} and ra['bbox'] and rb['bbox']:
            return sorted([a, b]) not in data['rules']['allowed_arm_pairs']
        return False
    for (sa, na, fa), (sb, nb, fb) in itertools.combinations(choices, 2):
        if not any(conflicts(a, b) for a in fa for b in fb):
            continue
        if sa == sb:
            # 単一選択部位も明示。fx等の複数選択にも効く。
            rules.append(dict(exclusive={sa: [[na, nb]]}))
        else:
            rules.append(dict(when={sa: na, sb: nb}, reject=True, message='向き・部位・服・腕の組合せが不適切'))
    for slot, name, files in choices:
        for file in files:
            for selector in catalog[file]['requires']:
                if any(matches(catalog[f], selector) for f in files):
                    continue
                allowed = [(s, n) for s, n, fs in choices if any(matches(catalog[f], selector) for f in fs)]
                assert len({s for s, _ in allowed}) == 1, selector
                rules.append(dict(when={slot: name}, requires={allowed[0][0]: [n for _, n in allowed]}))
    order = sorted(parts, key=lambda s: min(catalog[f]['order'] for _, _, fs in choices for f in fs if slots[f][0] == s))
    def selection(files):
        face = {s: [] for s in parts}
        for file in files:
            s, n = slots[file]
            if s in ('fx',):
                face[s] = face[s] + [n]
            else:
                assert not face[s], (s, files)
                face[s] = n
        mouth = face.get('mouth')
        if mouth:
            face['mouth'] = [mouth] * 3
        return face
    presets = {}
    for direction, kinds in data['presets'].items():
        for kind, entries in kinds.items():
            for name, entry in entries.items():
                if entry['status'] == '提案':
                    prefix = '' if direction in ('共通', '正面') else '上向き_'
                    presets[prefix + ('' if kind == 'expressions' else 'pose_') + name] = selection(entry['files'])
    m = dict(schema_version=114, size=data['size'], base=None, parts=parts, order=order,
             defaults=copy.deepcopy(presets['neutral']), presets=presets, rules=rules,
             eye_moods={mood: [slots[f][1] for f in files] for mood, files in data['eye_moods'].items()},
             emphatic_eyes=[slots[f][1] for f in data['emphatic_eyes']],
             outfit_usage={n: ('必要時のみ' if any(data['outfit_usage'].get(f) == '必要時のみ' for f in fs) else '既定')
                           for s, n, fs in choices if s == 'outfit'},
             provenance=dict(source=data['source'], catalog='catalog.json'),
             notes=['hair_*・head_*・cheek_shadow・prop_*は重ね順を守る追加部位。共通resolverは任意の部位キーに対応。',
                    '必要時のみの服を除くのはコレスポ側の運用。全素材は手動で選択可能。',
                    '表情案のmouthは静止見本の同じ口を3段階へ配置。台本の口パクは各部品を明示する。'])
    return m


def export(destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SHARED / 'portrait_parts.py', destination / 'portrait_parts.py')
    shutil.copy2(SHARED / '部品の書き方.md', destination / '部品の書き方.md')
    for who in ('四国めたん', 'ずんだもん'):
        folder = ROOT / 'assets/portraits' / who
        data = load_parts(folder)
        common = common_manifest(data)
        text = json.dumps(common, ensure_ascii=False, indent=2) + '\n'
        (folder / 'common.parts.json').write_text(text, encoding='utf-8')
        target = destination / who
        target.mkdir(exist_ok=True)
        for file in folder.rglob('*.png'):
            relative = file.relative_to(folder)
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target / relative)
        (target / 'parts.json').write_text(text, encoding='utf-8')
        shutil.copy2(folder / 'parts.json', target / 'catalog.json')
    (destination / 'README.md').write_text(
        '# 10/27 共通立ち絵の受渡し\n\n四国めたん/・ずんだもん/は全新旧PNGと共通parts.json。\n'
        '元catalog定義はcatalog.json。共通portrait_parts.pyは原本から無変更でコピー。\n'
        '既存の雨衣/・README.md・portrait_parts.pyを上書きせず、人物フォルダを共通置き場へコピーする。\n'
        'コレスポ自動動画は必要時のみの服を使用しない。手動使用は場面の理由と本人への見本提示が必要。\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'build/shared-portraits')
    export(parser.parse_args().destination)
