"""3案の文字領域、色/略称、Bとの違い、実寸/2倍、本番未接続を検査。"""
import ast
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import preview_mlb_badges2 as preview


class Badges2(unittest.TestCase):
    def test_all_30_teams_and_small_letter_clearance(self):
        for tid in preview.ne.MLB_TEAM_NAME_JP:
            pixels=[preview.previous.badge(tid,'B').tobytes()]
            for v in preview.VARIANTS:
                im=preview.badge(tid,v);c=im.info['check']
                self.assertEqual(im.size,(96,38))
                self.assertEqual(c['abbr'],preview.ne.MLB_TEAM_ABBR[tid])
                self.assertGreaterEqual(c['text_ratio'],4.5)
                self.assertGreaterEqual(c['edge_ratio'],3)
                self.assertGreater(c['text_box'][0],c['motif_box'][2]+3)
                doubled=im.resize((192,76),Image.Resampling.NEAREST)
                self.assertEqual(doubled.resize(im.size,Image.Resampling.NEAREST).tobytes(),im.tobytes())
                pixels.append(im.tobytes())
            self.assertEqual(len(set(pixels)),4)

    def test_production_does_not_import_either_preview(self):
        for path in (ROOT/'scripts').glob('*.py'):
            if path.name.startswith(('test_','preview_')):continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node,ast.Import):
                    self.assertFalse(any(a.name.split('.')[-1] in ('preview_mlb_badges','preview_mlb_badges2') for a in node.names),path.name)
                if isinstance(node,ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[-1],('preview_mlb_badges','preview_mlb_badges2'),path.name)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
