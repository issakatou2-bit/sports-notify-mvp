"""配布PSD全差分を非破壊で部品化する。既存PNGと旧JSONキーは保持。

python scripts/export_all_portrait_parts.py --source <PSDのディレクトリ>
新部品の組立てはcatalogのorder順。旧「体」は頬・髪などを含むため混用しない。
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'build_reports/portrait_parts_20261027'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(name):
    return re.sub(r'[<>:"/\\|?*]', lambda m: {'<': '＜', '>': '＞'}.get(m[0], '_'), name.lstrip('*!'))


def meaning(name):
    # 作者の層名と本人指定で意味が明確なものに限定。
    for word, text in [('ぐるぐる', '混乱'), ('青ざめ', 'ピンチ'), ('赤面', '照れ'),
                       ('ほっぺ赤め', '照れ'), ('汗', '焦り'), ('涙', '悲しみ'),
                       ('困り', '困る'), ('こまり', '困る'), ('怒り', '怒り'),
                       ('おこ', '怒り'), ('にっこり', '笑顔'), ('指さし', '指示'),
                       ('指差す', '指示'), ('腕組み', '腕組み')]:
        if word in name:
            return text
    return '未定'


def write_json(path, value):
    if isinstance(value, dict) and 'catalog' in value:
        add_compatibility_keys(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def add_compatibility_keys(data):
    """APSCと同名の部位索引。腕の前後はPSDの重ね順で定義する。"""
    slots = {'目': 'eye', '眉': 'brow', '口': 'mouth', '顔色': 'cheek',
             '汗': 'fx', '涙': 'fx', '右腕': 'arm_back', '左腕': 'arm_front',
             '髪・輪郭': 'head', '枝豆': 'head', 'アクセサリ': 'head',
             '体・服': 'outfit', '小物': 'prop'}
    for slot in slots.values():
        data[slot] = {}
    rules = dict(data.get('rules', {}))
    rules.update(exclusive_groups={}, directions={}, requires={}, forbids={})
    for r in data['catalog']:
        r['slot'] = slots[r['category']]
        data[r['slot']].setdefault(r['direction'], []).append(r['file'])
        if r['exclusive_group']:
            rules['exclusive_groups'].setdefault(r['exclusive_group'], []).append(r['file'])
        rules['directions'][r['file']] = r['direction']
        rules['requires'][r['file']] = r['requires']
        rules['forbids'][r['file']] = r['forbids']
    data['rules'] = rules
    from portrait_parts import apply_usage_policy
    apply_usage_policy(data)


def legacy_body_sources(source_file):
    from psd_tools import PSDImage
    result = []

    def walk(node, prefix=()):
        for layer in node:
            path = prefix + (layer.name,)
            if layer.is_group():
                walk(layer, path)
            elif layer.is_visible() and not any(n.lstrip('*!') in ('目', '眉', '口', '右腕', '左腕') for n in prefix):
                result.append('/'.join(path))
    walk(PSDImage.open(source_file))
    return result


def write_upper(out, data):
    upper = dict(size=data['size'], origin=[0, 0],
                 catalog=[dict(r, file=Path(r['file']).name) for r in data['catalog'] if r['direction'] == '上向き'],
                 common_catalog='../parts.json', constraints=data['constraints'],
                 schema_version=data['schema_version'],
                 rules={k: data['rules'][k] for k in ('nonordinary_contexts', 'max_pointing_arms')})
    upper['rules'].update(pointing_arms=[], allowed_arm_pairs=[])
    write_json(out / '上向き/parts.json', upper)


def export(who, source):
    from psd_tools import PSDImage
    from build_portrait_parts import SETS, find
    psd = PSDImage.open(source / f'{who}.psd')
    out = ROOT / 'assets/portraits' / who
    legacy = json.loads((out / 'parts.json').read_text(encoding='utf-8'))
    old = {p.name: digest(p) for p in out.glob('*.png') if not p.name.startswith('差分_')}
    assert len(old) == 21, (who, len(old))
    records, leaves, covered = [], [], set()
    nodes = []

    def walk(node, paths=(), ids=()):
        for i, layer in enumerate(node):
            path, index = paths + (layer.name,), ids + (i,)
            nodes.append((layer, path, index))
            if layer.is_group():
                walk(layer, path, index)
            else:
                leaves.append('/'.join(path))
    walk(psd)
    # 非表示の頭内も描画可能にする。各葉自体の絵には兄弟の表示を持ち込まない。
    for layer, _, _ in nodes:
        if layer.is_group():
            layer.visible = True

    def save(image, path, index, category, sources=None, suffix=None):
        assert image is not None
        image = image.convert('RGBA')
        assert image.size == psd.size
        direction = '上向き' if '*頭_上向き' in path else ('正面' if '*頭_正面向き' in path else '共通')
        folder = out / '上向き' if direction == '上向き' else out
        folder.mkdir(parents=True, exist_ok=True)
        label = suffix or '_'.join(clean(n) for n in path)
        file = folder / ('差分_' + label + '.png')
        assert not any(r['file'] == file.relative_to(out).as_posix() for r in records)
        image.save(file, optimize=True)
        source_paths = sources or ['/'.join(path)]
        covered.update(source_paths)
        record = dict(file=file.relative_to(out).as_posix(), category=category,
                      source_layers=source_paths, meaning=meaning(path[-1]),
                      direction=direction, order=list(index),
                      exclusive_group=f'{direction}:{category}',
                      bbox=image.getbbox(), sha256=digest(file))
        if not record['bbox']:
            assert '非表示' in path[-1], path
            record['meaning'] = '非表示（透明）'
        records.append(record)

    for layer, path, index in nodes:
        if layer.is_group():
            continue
        if who == '四国めたん' and '*目セット' in path:
            continue
        if any(n.lstrip('*!') in ('右腕', '左腕') for n in path[:-1]):
            category = '右腕' if any(n.lstrip('*!') == '右腕' for n in path[:-1]) else '左腕'
            if path[-1] in ('まんじゅう', 'まんじゅう袋'):
                category = '小物'
        elif any(n.lstrip('*!') in ('目', '眉', '口', '顔色', '枝豆') for n in path[:-1]):
            category = path[-2].lstrip('*!')
        elif path[-1] in ('汗', '涙'):
            category = path[-1]
        elif '頭部アクセサリ' in path:
            category = 'アクセサリ'
        elif path[-1] == '!頭' or '髪' in path[-1] or 'ドリル' in path[-1] or 'ポニテ' in path[-1]:
            category = '髪・輪郭'
        else:
            category = '体・服'
        layer.visible = True
        save(layer.composite(viewport=(0, 0, *psd.size), force=True), path, index, category)

    if who == '四国めたん':
        group = find(psd, '*目セット')
        whites = [l for l in group if not l.is_group()]
        pupils = find(group, '!黒目')
        for white, pupil in itertools.product(whites, pupils):
            for l in whites:
                l.visible = l is white
            for l in pupils:
                l.visible = l is pupil
            base = '!目/*目セット/'
            paths = [base + white.name, base + '!黒目/' + pupil.name]
            save(group.composite(viewport=(0, 0, *psd.size), force=True),
                 ('!目', '*目セット', white.name + '+' + pupil.name), (7, 7), '目', paths,
                 '目セット_' + clean(white.name) + '_' + clean(pupil.name))

    assert set(leaves) == covered, (set(leaves) - covered, covered - set(leaves))
    # 旧キーを残し、旧ファイルの元層も記録。旧下地の定義は専用スクリプト参照。
    legacy_metadata = {}
    spec = SETS[who]
    for name in old:
        if name == '体.png':
            paths = legacy_body_sources(source / f'{who}.psd')
            category = '旧下地'
        else:
            category, tag = name[:-4].split('_', 1)
            target = spec[category][tag]
            matches = [('/'.join(p), idx) for _, p, idx in nodes
                       if p[-1] == target and (category.endswith('腕') and any(category in n for n in p[:-1])
                       or not category.endswith('腕') and any(n.lstrip('*!') == category for n in p[:-1]))
                       and '*頭_上向き' not in p]
            paths = [p for p, _ in matches]
            assert len(paths) == 1, (name, paths)
        legacy_metadata[name] = dict(category=category, source_layers=paths,
                                     meaning=meaning(paths[0]), direction='正面' if who == 'ずんだもん' else '共通',
                                     sha256=old[name], exclusive_group=f'旧:{category}')
    # 再抽出でもキャラJSONで確認済みの用途指定を保持する。
    previous = {r['file']: r for r in legacy.get('catalog', [])}
    for record in records:
        if record['category'] == '目':
            for key in ('mood', 'mood_note'):
                if key in previous.get(record['file'], {}):
                    record[key] = previous[record['file']][key]
    legacy.update(schema_version=3, catalog=records, legacy_metadata=legacy_metadata,
                  source=dict(file=f'{who}.psd', sha256=digest(source / f'{who}.psd'),
                              leaf_count=len(leaves), covered_leaf_count=len(covered)),
                  composition=dict(origin=[0, 0], order='catalog.orderの昇順（PSDの下から上）',
                                   legacy='旧21部品と新catalogは別の組立て。旧体には顔色・髪・服・装飾が焼込み済み。'),
                  constraints=[
                      '同じexclusive_groupは1枚だけ。小物・アクセサリ・髪は個別に選択可。',
                      '正面と上向きの頭・目・眉・口・顔色・枝豆・汗・涙を混在させない。共通の体・腕は利用可。',
                      'めたんの白目・黒目は目セット合成済み。目セットと他の目を同時使用しない。',
                      'ずんだもんの腕組みは右腕非表示。前傾用ポケットは体前傾、直立用は体直立。',
                      'めたんの白ロリ服とその他の服は排他。その他の服は素体と衣装1枚を重ね、白ロリ用腕を使わない。',
                      'めたんのかげりは顔色に追加可。髪留めフリルと髪留めハートは排他。',
                      '非表示PNGは透明の選択肢。ポニテ用の髪は作者の注記通り配置加工が必要。元座標のまま保管。'])
    enrich_catalog(records)
    write_json(out / 'parts.json', legacy)
    if who == 'ずんだもん':
        write_upper(out, legacy)
    assert all(digest(out / n) == h for n, h in old.items())
    return out, legacy


def enrich_catalog(records):
    for r in records:
        parents = r['source_layers'][0].split('/')[:-1]
        if any(n.lstrip('*!') in ('右腕', '左腕') for n in parents) and r['category'] != '小物':
            r['category'] = '右腕' if any(n.lstrip('*!') == '右腕' for n in parents) else '左腕'
            r['exclusive_group'] = f"{r['direction']}:{r['category']}"
        if r['category'] in ('アクセサリ', '小物', '髪・輪郭') or r['source_layers'][0].endswith('/かげり'):
            r['exclusive_group'] = None
        src = r['source_layers'][0]
        r['requires'] = []
        r['forbids'] = []
        if '腕組み' in src:
            r['forbids'] = ['category:右腕']
        if '前傾用' in src:
            r['requires'] = ['source:!体/*体前傾']
        if '直立用' in src:
            r['requires'] = ['source:!体/*体直立']
        if '*白ロリ服/' in src:
            r['forbids'] = ['source_prefix:*その他の服/']
        if '*その他の服/' in src:
            r['forbids'] = ['source_prefix:*白ロリ服/']
            if not src.endswith('/!素体'):
                r['requires'] = ['source:*その他の服/!素体']
        if src.endswith(('髪留めフリル', '髪留めハート')):
            r['exclusive_group'] = '共通:髪留め'
        if '*その他の服/' in src and not src.endswith('/!素体'):
            r['exclusive_group'] = '共通:その他の衣装'
        elif src.endswith('/!素体'):
            r['exclusive_group'] = None


def sheet(items, title, path, face=False):
    font = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 15)
    w, h = (260, 350) if face else (260, 460)
    canvas = Image.new('RGB', (w * 4, 38 + h * ((len(items) + 3) // 4)), '#e8e8e8')
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 7), title, font=font, fill='black')
    for i, (label, im) in enumerate(items):
        x, y = (i % 4) * w, 38 + (i // 4) * h
        if face:
            im = im.crop((160, 0, 950, 680 if im.height == 1820 else 760))
        im.thumbnail((w - 12, h - 52))
        canvas.paste(im, (x + (w - im.width) // 2, y), im)
        lines = [s[:19] for s in label.splitlines()] if '\n' in label else [label[k:k+19] for k in range(0, len(label), 19)]
        for j, line in enumerate(lines[:2]):
            draw.text((x + 5, y + h - 48 + j * 20), line, font=font, fill='black')
    canvas.save(path)


def proposals(out, data):
    from portrait_parts import compose_parts
    records = data['catalog']
    who = out.name
    all_proposals = data['presets']
    for direction, entries in all_proposals.items():
        faces, poses = [], []
        for kind, target in [('expressions', faces), ('poses', poses)]:
            for name, entry in entries[kind].items():
                if entry['status'] == '提案':
                    target.append((name, compose_parts(out, data, entry['files'],
                                   context=entry.get('context', '平時'))))
        sheet(faces, f'{who} {direction} 表情案', REPORT / f'{who}_{direction}_expressions.png', face=True)
        sheet(poses, f'{who} {direction} ポーズ案（PSDの左右）', REPORT / f'{who}_{direction}_poses.png')
        # 全部品の位置・形を確認するための接触表。葉の欠落はJSONで照合。
        applicable = [r for r in records if r['direction'] in ('共通', direction)]
        for page, start in enumerate(range(0, len(applicable), 16)):
            samples = [(r['file'].replace('差分_', '').replace('.png', ''), Image.open(out / r['file']).convert('RGBA')) for r in applicable[start:start+16]]
            sheet(samples, f'{who} {direction} 全部品 {page+1}', REPORT / f'{who}_{direction}_parts_{page+1:02d}.png')
        facial = [r for r in applicable if r['category'] in ('目', '口', '眉', '顔色', '汗', '涙', '枝豆')]
        for page, start in enumerate(range(0, len(facial), 16)):
            samples = [(Path(r['file']).stem.replace('差分_', ''), Image.open(out / r['file']).convert('RGBA')) for r in facial[start:start+16]]
            sheet(samples, f'{who} {direction} 顔差分 {page+1}', REPORT / f'{who}_{direction}_faceparts_{page+1:02d}.png', face=True)
        all_proposals[direction] = entries
    write_json(REPORT / f'{who}_proposals.json', all_proposals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--review-only', action='store_true', help='既存catalogから一覧だけを再生成')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    for who in ('四国めたん', 'ずんだもん'):
        if args.review_only:
            out = ROOT / 'assets/portraits' / who
            data = json.loads((out / 'parts.json').read_text(encoding='utf-8'))
            enrich_catalog(data['catalog'])
            write_json(out / 'parts.json', data)
            if who == 'ずんだもん':
                write_upper(out, data)
        else:
            if args.source is None:
                parser.error('部品の抽出には--sourceが必要')
            out, data = export(who, args.source)
        proposals(out, data)
        print(who, len(data['catalog']), 'parts; all leaves covered; legacy hashes unchanged', flush=True)


if __name__ == '__main__':
    main()
