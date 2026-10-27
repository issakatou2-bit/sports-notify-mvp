"""部品の欠落・座標変更・向き混在・腕組みの二重腕を検出する。"""
import hashlib
import json
from pathlib import Path
import unittest

from PIL import Image

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
                    self.assertGreaterEqual(sum(e['status'] == '提案' for e in entries.values()), 13)
                    for name, entry in entries.items():
                        if entry['status'] != '提案':
                            continue
                        with self.subTest(who=who, direction=direction, kind=kind, name=name):
                            selected = [catalog[f] for f in entry['files']]
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


if __name__ == '__main__':
    # run_checksは共通の一時ディレクトリをargv[1]で渡す。
    unittest.main(argv=[__file__])
