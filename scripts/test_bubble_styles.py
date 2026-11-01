"""Portable caption comparison and reading checks using bundled fonts only."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
import characters as c
import ps_brand_components as fonts
import review_render_v3 as r3

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_bubble',ROOT/'scripts/fixtures/bubble/legacy.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class Bubbles(unittest.TestCase):
    def setUp(self):
        fonts._cache.clear()
        self.fonts = patch.dict(fonts.FONT_CANDIDATES, {
            'jp':[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')],
            'latin':[str(ROOT/'assets/fonts/Oswald[wght].ttf')],
            'serif':[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]})
        self.fonts.start()
        self.env = patch.dict(os.environ,{'COLLESPO_EXPR':'','COLLESPO_BUBBLE':''})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.fonts.stop(); fonts._cache.clear()

    def test_default_unknown_and_empty_are_pixel_identical(self):
        for who in c.NAMES:
            for text in ('第3戦は2対1でした。',''):
                for mode in ('','unknown'):
                    os.environ['COLLESPO_BUBBLE'] = mode
                    a = Image.new('RGB',(1080,1920),(30,50,60)); b = a.copy()
                    c.bubble(a,who,text); legacy.bubble(b,who,text)
                    self.assertIsNone(ImageChops.difference(a,b).getbbox())

    def test_both_speakers_patterns_and_bright_backgrounds(self):
        for who in c.NAMES:
            for style,pattern in [('slant','stripes'),('glass','stripes'),('glass','lights')]:
                for bg in ((20,35,50),(255,255,255)):
                    os.environ.update(COLLESPO_BUBBLE=style,COLLESPO_GLASS_BACKGROUND=pattern)
                    im = Image.new('RGB',(1080,1920),bg)
                    c.bubble(im,who,'山本由伸は6回を投げて8奪三振。勝ち投手でした。')
                    report = im.info['bubble_style']
                    self.assertGreaterEqual(report['contrast'],4.5)
                    self.assertGreaterEqual(report['name_contrast'],4.5)
                    self.assertTrue(report['full_text'])
                    self.assertLessEqual(im.info['duo_caption']['rows'],3)
                    self.assertIsNone(ImageChops.difference(im.crop((0,0,1080,1200)),Image.new('RGB',(1080,1200),bg)).getbbox())

    def test_long_text_is_not_silently_truncated(self):
        os.environ['COLLESPO_BUBBLE'] = 'glass'
        with self.assertRaisesRegex(ValueError,'全文'):
            c.bubble(Image.new('RGB',(1080,1920)),'metan','試合の結果を確認しました。'*50)

    def test_soccer_v5_default_pixels_and_opt_in_connection(self):
        import soccer_v5_cards as v5
        scope = dict(vars(v5))
        source = ROOT/'scripts/fixtures/bubble/soccer_presenter.py'
        exec(compile(source.read_text(encoding='utf-8'),str(source),'exec'),scope)
        try:
            for text,hide in [('日本時間23時、ブライトンとアーセナルです。',False),('',False),('非表示',True)]:
                for mode in ('','unknown'):
                    os.environ['COLLESPO_BUBBLE'] = mode
                    r3.set_program_clock(0);r3.set_caption(text,5,5,hide_caption=hide)
                    r3.set_program_clock(1)
                    a = Image.new('RGB',(1080,1920),(20,40,30));b=a.copy()
                    v5._presenter(a,1);scope['_presenter'](b,1)
                    self.assertIsNone(ImageChops.difference(a,b).getbbox())
            for style in ('slant','glass'):
                os.environ['COLLESPO_BUBBLE'] = style
                r3.set_program_clock(0);r3.set_caption('日本時間23時にキックオフです。',5,5)
                r3.set_program_clock(1)
                im=Image.new('RGB',(1080,1920),(20,40,30));v5._presenter(im,1)
                self.assertEqual(im.info['bubble_style']['style'],style)
        finally:r3.set_program_clock(None)

    def test_render_workflows_pass_repository_variables(self):
        for p in (ROOT/'.github/workflows').glob('*.yml'):
            source = p.read_text(encoding='utf-8')
            if 'COLLESPO_SHORT_LOOK:' in source:
                self.assertIn("COLLESPO_BUBBLE: ${{ vars.COLLESPO_BUBBLE || '' }}",source,p.name)
                self.assertIn("COLLESPO_GLASS_BACKGROUND: ${{ vars.COLLESPO_GLASS_BACKGROUND || 'stripes' }}",source,p.name)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
