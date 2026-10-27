"""部品の欠落・座標変更・向き混在・腕組みの二重腕を検出する。"""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
from portrait_parts import compose_parts, load_parts, validate_parts

ROOT = Path(__file__).resolve().parent.parent


class PortraitCatalogTest(unittest.TestCase):
    def test_catalog_and_proposals(self):
        for who in ('四国めたん', 'ずんだもん'):
            out = ROOT / 'assets/portraits' / who
            data = json.loads((out / 'parts.json').read_text(encoding='utf-8'))
            catalog = {r['file']: r for r in data['catalog']}
            self.assertEqual(len(catalog), len(data['catalog']))
            slots = ('eye', 'brow', 'mouth', 'cheek', 'fx', 'arm_front', 'arm_back', 'head', 'outfit', 'prop')
            indexed = [f for slot in slots for files in data[slot].values() for f in files]
            self.assertCountEqual(indexed, catalog)
            covered = {s for r in catalog.values() for s in r['source_layers']}
            self.assertEqual(len(covered), data['source']['leaf_count'])
            for file, r in {**catalog, **data['legacy_metadata']}.items():
                with self.subTest(who=who, file=file):
                    p = out / file
                    self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), r['sha256'])
                    with Image.open(p) as im:
                        self.assertEqual(list(im.size), data['size'])
                        self.assertEqual(im.mode, 'RGBA')
                        if file in catalog:
                            self.assertEqual(list(im.getbbox()) if im.getbbox() else None, r['bbox'])
                            if not im.getbbox():
                                self.assertIn('非表示', ''.join(r['source_layers']))
            proposals = json.loads((ROOT / f'build_reports/portrait_parts_20261027/{who}_proposals.json').read_text(encoding='utf-8'))
            for direction, kinds in proposals.items():
                for kind, entries in kinds.items():
                    self.assertGreaterEqual(sum(e['status'] == '提案' for e in entries.values()), 7)
                    for name, entry in entries.items():
                        if entry['status'] != '提案':
                            continue
                        with self.subTest(who=who, direction=direction, kind=kind, name=name):
                            selected = [catalog[f] for f in entry['files']]
                            validate_parts(data, entry['files'])
                            self.assertTrue(all(r['direction'] in ('共通', direction) for r in selected))
                            groups = [r['exclusive_group'] for r in selected if r['exclusive_group']]
                            self.assertEqual(len(groups), len(set(groups)))
                            if name == 'udegumi':
                                self.assertFalse(any(r['category'] == '右腕' for r in selected))
                            rules = data['rules']
                            for files in rules['exclusive_groups'].values():
                                self.assertLessEqual(len(set(files) & set(entry['files'])), 1)
                            def matches(selector):
                                key, value = selector.split(':', 1)
                                if key == 'category':
                                    return any(r['category'] == value for r in selected)
                                sources = [s for r in selected for s in r['source_layers']]
                                if key == 'source':
                                    return value in sources
                                self.assertEqual(key, 'source_prefix')
                                return any(s.startswith(value) for s in sources)
                            for file in entry['files']:
                                self.assertTrue(all(matches(s) for s in rules['requires'][file]))
                                self.assertFalse(any(matches(s) for s in rules['forbids'][file]))

    def test_reject_before_opening_images(self):
        out = ROOT / 'assets/portraits/ずんだもん'
        data = load_parts(out)
        def find(text):
            return next(r['file'] for r in data['catalog'] if text in r['file'])
        eye = find('正面向き_目_基本目.png')
        bad = [
            [eye, eye],
            [eye, find('上向き_目_普通目.png')],
            [find('右腕_下.png'), find('右腕_横.png')],
            [find('左腕_腕組み'), find('右腕_下.png')],
            [find('右腕_指さし横'), find('左腕_あごに指')],
            ['白目.png', '黒目.png'],
        ]
        with patch('portrait_parts.Image.open', side_effect=AssertionError('描画を開始した')):
            for files in bad:
                with self.subTest(files=files), self.assertRaises(ValueError):
                    compose_parts(out, data, files)
        emphatic = find('正面向き_目_見開き.png')
        for context in ('平時', '怒り', '混乱', 'がーん'):
            validate_parts(data, [emphatic], context=context)
        for flag in ('factual', 'listener'):
            with self.assertRaises(ValueError):
                validate_parts(data, [emphatic], **{flag: True})
        self.assertEqual(data['eye_moods']['非平時'], [])
        # 前腕にも指さしが追加された場合でも、2本目を止める。
        front = find('左腕_基本.png')
        data['rules']['pointing_arms'].append(front)
        with self.assertRaisesRegex(ValueError, '同時に1本'):
            validate_parts(data, [find('右腕_指さし横'), front])

    def test_presets_and_mood_are_character_owned(self):
        for who in ('四国めたん', 'ずんだもん'):
            data = load_parts(ROOT / 'assets/portraits' / who)
            self.assertTrue(all(r.get('mood') in ('平時', '非平時')
                                for r in data['catalog'] if r['slot'] == 'eye'))
            for direction, kinds in data['presets'].items():
                proposals = json.loads((ROOT / f'build_reports/portrait_parts_20261027/{who}_proposals.json').read_text('utf-8'))
                self.assertEqual(proposals[direction], kinds)
                faces = kinds['expressions']
                signatures = [frozenset(faces[n]['files']) for n in ('chui', 'setsumei', 'yobikake')]
                self.assertEqual(len(set(signatures)), 3)
                for name in ('heart', 'kirakira'):
                    self.assertEqual(faces[name]['status'], '無し')
                if who == '四国めたん':
                    self.assertEqual(faces['udegumi']['status'], '無し')

    def test_hollow_eyes_and_restricted_outfits(self):
        data = load_parts(ROOT / 'assets/portraits/四国めたん')
        hollow = data['eye_moods']['非平時']
        self.assertEqual(len(hollow), 7)
        for file in hollow:
            with self.assertRaises(ValueError):
                validate_parts(data, [file])
            validate_parts(data, [file], context='異変')
            with self.assertRaises(ValueError):
                validate_parts(data, [file], context='異変', factual=True)
        catalog = data['catalog']
        bare = next(r['file'] for r in catalog if r['file'].endswith('_素体.png'))
        for r in catalog:
            if r.get('usage') == '必要時のみ':
                files = [bare] if r['file'] == bare else [bare, r['file']]
                with self.assertRaisesRegex(ValueError, '自動動画'):
                    validate_parts(data, files)
                validate_parts(data, files, automatic=False)

    def test_common_composer_and_manifest(self):
        import importlib.util
        from share_portrait_parts import common_manifest
        spec = importlib.util.spec_from_file_location('apsc_common', ROOT / 'tools/portrait-common/portrait_parts.py')
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        for who in ('四国めたん', 'ずんだもん'):
            folder = ROOT / 'assets/portraits' / who
            raw = load_parts(folder)
            m = common_manifest(raw)
            self.assertEqual(m, json.loads((folder / 'common.parts.json').read_text('utf-8')))
            indexed = {f for entries in m['parts'].values() for item in entries.values() for f in common.values(item)}
            self.assertEqual(indexed, {r['file'] for r in raw['catalog']})
            composer = common.Composer(folder)
            composer.manifest = common.normalize(m)
            for direction, kinds in raw['presets'].items():
                for kind, entries in kinds.items():
                    for name, entry in entries.items():
                        if entry['status'] != '提案':
                            continue
                        prefix = '' if direction in ('共通', '正面') else '上向き_'
                        preset = prefix + ('' if kind == 'expressions' else 'pose_') + name
                        with self.subTest(who=who, preset=preset):
                            image = composer.image(preset)
                            expected = compose_parts(folder, raw, entry['files'])
                            self.assertEqual(image.tobytes(), expected.tobytes())
            # 共通resolverでも向き混在と両手の衝突を拒否する。
            if who == 'ずんだもん':
                upper_eye = next(n for n in m['parts']['eye'] if '上向き' in n)
                with self.assertRaises(ValueError):
                    composer.image(face={'eye': upper_eye})


if __name__ == '__main__':
    # run_checksは共通の一時ディレクトリをargv[1]で渡す。
    unittest.main(argv=[__file__])
