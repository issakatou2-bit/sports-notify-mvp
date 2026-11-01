"""30球団の色/略称の同一性、小さい字の収まり、三案の差、本番未接続を検査。"""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import preview_mlb_badges as preview
from PIL import ImageColor


class Badges(unittest.TestCase):
    def test_all_30_teams_identity_contrast_and_distinct_shapes(self):
        self.assertEqual(len(preview.ne.MLB_TEAM_NAME_JP),30)
        for tid in preview.ne.MLB_TEAM_NAME_JP:
            pixels=[]
            for variant in ('A','B','C'):
                im=preview.badge(tid,variant);check=im.info['check']
                self.assertEqual(check['team_id'],tid)
                self.assertEqual(check['abbr'],preview.ne.MLB_TEAM_ABBR[tid])
                self.assertEqual(check['primary'],ImageColor.getrgb(preview.ne.MLB_TEAM_COLOR[tid]))
                self.assertGreaterEqual(check['text_ratio'],4.5)
                self.assertGreaterEqual(check['edge_ratio'],3)
                pixels.append(im.tobytes())
            self.assertEqual(len(set(pixels)),3,tid)

    def test_existing_renderers_unchanged_and_do_not_import_preview(self):
        frozen=json.loads((ROOT/'scripts/fixtures/mlb-badge/protected-source.json').read_text(encoding='utf8'))
        for name,expected in frozen.items():
            text=(ROOT/name).read_text(encoding='utf8').replace('\r\n','\n')
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),expected,name+"（意図した直しなら python scripts/update_protected_hashes.py --write）")
            for n in ast.walk(ast.parse(text)):
                if isinstance(n,ast.Import):self.assertFalse(any(a.name=='preview_mlb_badges' for a in n.names))
                if isinstance(n,ast.ImportFrom):self.assertNotEqual(n.module,'preview_mlb_badges')


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
