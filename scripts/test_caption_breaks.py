"""Offline phrase/unit/page regressions; fixed font and model, no Git history."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import caption_breaks as cb
import captions
import review_render_v3 as r3
import ps_brand_components as fonts
import bubble_styles as bs
import characters

ROOT=Path(__file__).resolve().parents[1]
TEXTS=[
    '山本由伸は6回を投げて8奪三振。勝ち投手でした。',
    '大谷翔平は3打数1安打。第3戦の先発は未確認です。',
    '1位、松井裕樹、1回3分の1　0奪三振　自責0　1被安打　ホールド。',
    '報道によると、第3戦で大谷翔平を休ませることを協議する見込みと報じられています。',
    '日本時間23時00分、ブライトンとアーセナルの試合です。',
    '9月19日の試合は3対2でした。打率は.280で、45本塁打でした。',
]


class CaptionBreaks(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'COLLESPO_BUBBLE':'glass','COLLESPO_SLANT_VARIANT':'cream','COLLESPO_CAPTION_BREAKS':''});self.env.start()
        fonts._cache.clear()
        self.fonts=patch.dict(fonts.FONT_CANDIDATES,{'jp':[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]});self.fonts.start()

    def tearDown(self):
        self.fonts.stop();fonts._cache.clear();self.env.stop();r3.set_program_clock(None)

    def test_pages_lines_and_srt_keep_phrases_units_and_every_character(self):
        d=ImageDraw.Draw(Image.new('RGB',(1080,1920)))
        for text in TEXTS:
            for limit in (16,25,38):
                pages=cb.pages(text,limit)
                self.assertEqual(cb.violations(text,pages),[])
            pages=r3.caption_chunks(text)
            self.assertEqual(cb.violations(text,pages),[])
            for page in pages:
                rows=r3._caption_lines(d,page,30,550)
                lines=[''.join(run for run,_ in row) for row in rows]
                self.assertEqual(cb.violations(page,lines),[])
            cues=captions.split_text(text)
            self.assertEqual(cb.violations(text,cues),[])
            for cue in cues:
                lines=captions.wrap_line(cue).split('\n')
                self.assertEqual(cb.violations(cue,lines),[])

    def test_expected_phrase_examples_and_page_preference(self):
        self.assertEqual(cb.phrases('山本由伸は6回を投げて8奪三振。'),('山本由伸は','6回を','投げて','8奪三振。'))
        text='今日は試合です。明日の先発は未確認ですが、予定を紹介します。'
        self.assertTrue(cb.pages(text,22)[0].endswith('。'))
        text='報道によると、第3戦で大谷翔平を休ませることを協議する見込みと報じられています。'
        self.assertEqual(cb.pages(text,30)[0],'報道によると、')
        self.assertEqual(cb.phrases('報道によると、'),('報道によると、',))
        for unit in ('3打数','1回3分の1','23時00分','3対2','1被安打','6奪三振','.280','38.4%','9月19日','2得点','1アシスト','3ホールド','2四球','150球'):
            self.assertEqual(cb.phrases(unit),(unit,))

    def test_checker_rejects_bad_manual_breaks(self):
        self.assertTrue(cb.violations('3打数',['3','打数']))
        self.assertTrue(cb.violations('1回3分の1',['1回3分','の1']))
        self.assertTrue(cb.violations('山本由伸は',['山本由','伸は']))
        self.assertTrue(cb.violations('.280',['.','280']))

    def test_geometry_variants_names_and_motion(self):
        self.assertLessEqual(bs.geometry()[0],characters.BUBBLE[0])
        self.assertGreaterEqual(bs.geometry()[0],r3.LEFT-8)
        self.assertLessEqual(bs.geometry()[2],r3.SAFE_RIGHT)
        self.assertLess(bs.geometry()[3]-bs.geometry()[1],characters.BUBBLE[3]-characters.BUBBLE[1])
        for who in characters.NAMES:
            for style,variant in [('glass','glass'),('slant','dark'),('slant','band'),('slant','glass'),('slant','cream')]:
                im=Image.new('RGB',(1080,1920),(230,240,220))
                bs.draw(im,who,'3打数1安打。',style=style,variant=variant)
                meta=im.info['bubble_style']
                self.assertGreaterEqual(meta['contrast'],4.5)
                self.assertGreaterEqual(meta['name_contrast'],4.5)
                self.assertEqual(meta['name_ground'],list(characters.COLORS[who]))
        for pattern in ('stripes','lights'):
            with patch.dict(os.environ,{'COLLESPO_GLASS_BACKGROUND':pattern}):
                a=Image.new('RGB',(1080,1920),(20,40,30));b=a.copy()
                bs.draw(a,'metan','3打数1安打。',seconds=0);bs.draw(b,'metan','3打数1安打。',seconds=8)
                self.assertNotEqual(a.crop(bs.geometry()).tobytes(),b.crop(bs.geometry()).tobytes())
                self.assertEqual(a.crop((0,0,1080,1200)).tobytes(),b.crop((0,0,1080,1200)).tobytes())

    def test_longform_and_duo_share_phrase_breaks(self):
        import longform_render_v3 as lr
        import generate_longform as gl
        import duo_presenter as duo
        with patch.object(lr,'font',r3.font),patch.object(gl,'font',r3.font):
            seg={'text':TEXTS[3]*4,'speaker':2}
            for paginate in (lr.paginate,gl.paginate):
                values=paginate([seg]);pages=[''.join(s['_lines']) for s in values]
                self.assertEqual(cb.violations(seg['text'],pages),[])
                for s in values:self.assertEqual(cb.violations(''.join(s['_lines']),s['_lines']),[])
                self.assertAlmostEqual(sum(s['_share'] for s in values),1)
        r3.set_program_clock(0);r3.set_caption(TEXTS[3],12,12,speaker=3)
        r3.set_program_clock(4)
        im=Image.new('RGB',(1080,1920),(20,40,30));duo.caption(im,4)
        self.assertTrue(im.info['v3_layout'])

    def test_legacy_bubble_opt_in_uses_readable_name_ground(self):
        with patch.dict(os.environ,{'COLLESPO_BUBBLE':'','COLLESPO_CAPTION_BREAKS':'bunsetsu'}):
            for who in characters.NAMES:
                im=Image.new('RGB',(1080,1920),(20,40,30))
                characters.bubble(im,who,'3打数1安打。')
                self.assertEqual(im.info['name_tag']['color'],list(characters.COLORS[who]))
                self.assertGreaterEqual(im.info['name_tag']['contrast'],4.5)


if __name__=='__main__':unittest.main(argv=[__file__])
