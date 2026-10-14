"""Fixed all-slot integration, geometry, defaults and workflow regressions."""
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import yaml
import preview_bubble_all as preview

ROOT=Path(__file__).resolve().parents[1]


def frozen(module):
    namespace=dict(vars(module))
    source=ROOT/'scripts/fixtures/bubble-all'/f'{module.__name__}.py'
    exec(compile(source.read_text(encoding='utf-8'),str(source),'exec'),namespace)
    return namespace


class AllBubbles(unittest.TestCase):
    def test_every_slot_has_both_styles_readable_inside_its_box(self):
        with preview.setup():
            import review_render_v3 as r3
            examples=preview.cases()
            names={name for name,_,_ in examples}
            required={'players','voices','press','forecast','situation','soccer-preview','soccer-race','soccer-week',
                      'soccer-v5-preview','soccer-v5-race','soccer-v5-week','soccer-results','soccer-result-followup',
                      'soccer-voices','soccer-now','japan-reacts','player-story','longform-v3-2','longform-v3-3',
                      'longform-legacy-2','longform-legacy-3','weekly-summary','weekly-verdict','daily-legacy','short-v3','short-duo'}
            self.assertTrue(required<=names,required-names)
            self.assertTrue(any(name.startswith('asset:season_') for name in names))
            for name,seg,render in examples:
                for style in ('slant','glass'):
                    with self.subTest(slot=name,style=style),patch.dict(os.environ,{'COLLESPO_BUBBLE':style}):
                        r3.set_program_clock(0);r3.set_caption(seg.get('text') or preview.TEXT,20,20,speaker=seg.get('speaker',2));r3.set_program_clock(2)
                        im=render(2);result=preview.inspect(im)
                        self.assertEqual(im.info['bubble_style']['style'],style)
                        self.assertEqual(result['bounds'],'PASS')
            r3.set_program_clock(None);r3.set_caption('',0)

    def test_longform_disabled_and_unknown_are_pixel_identical(self):
        with preview.setup():
            import generate_longform as old
            import longform_render_v3 as new
            previous_old=frozen(old);previous_new=frozen(new)
            for style in ('','unknown'):
                with patch.dict(os.environ,{'COLLESPO_BUBBLE':style,'COLLESPO_CAPTION_BREAKS':''}):
                    for speaker in (2,3):
                        seg={'kind':'talk','speaker':speaker,'text':preview.TEXT}
                        a=old.render_stage(1,seg,topic='固定試験')
                        b=previous_old['render_stage'](1,seg,topic='固定試験')
                        self.assertEqual(a.tobytes(),b.tobytes())
                        a=Image.new('RGB',(1920,1080),(25,40,35));b=a.copy();who=old._speaker(seg)
                        new.subtitle(a,ImageDraw.Draw(a),2,seg,who,20)
                        previous_new['subtitle'](b,ImageDraw.Draw(b),2,seg,who,20)
                        self.assertEqual(a.tobytes(),b.tobytes())
                    import bubble_styles as bs
                    im=Image.new('RGB',(1920,1080),(20,40,35))
                    self.assertIs(bs.narration_frame(im,seg,2,20),im)

    def test_longform_pages_keep_phrases_units_shares_and_motion(self):
        with preview.setup():
            import generate_longform as old
            import longform_render_v3 as new
            import caption_breaks as cb
            import bubble_styles as bs
            text=('山本由伸は1回3分の1を投げました。3打数1安打で、報道によると次の先発は未確認です。')*12
            for style in ('slant','glass'):
                with patch.dict(os.environ,{'COLLESPO_BUBBLE':style}):
                    for module in (old,new):
                        pages=module.paginate([{'text':text,'speaker':3,'kind':'talk'}])
                        values=[''.join(s['_lines']) for s in pages]
                        self.assertEqual(cb.violations(text,values),[])
                        self.assertAlmostEqual(sum(s['_share'] for s in pages),1)
                        self.assertEqual(len(module.paginate([{'text':'','speaker':2}])),1)
                        box=bs.longform_box(legacy=module is old)
                        self.assertTrue(0<=box[0]<box[2]<=1920)
                        self.assertTrue(0<=box[1]<box[3]<=1080)
                        for page in pages:
                            im=Image.new('RGB',(1920,1080),(240,245,235))
                            bs.draw(im,'zundamon',''.join(page['_lines']),box=box)
                            preview.inspect(im)
            with patch.dict(os.environ,{'COLLESPO_BUBBLE':'glass'}):
                a=Image.new('RGB',(1920,1080),(24,40,30));b=a.copy();box=bs.longform_box()
                bs.draw(a,'metan',preview.TEXT,seconds=0,box=box);bs.draw(b,'metan',preview.TEXT,seconds=8,box=box)
                self.assertNotEqual(a.crop(box).tobytes(),b.crop(box).tobytes())
                self.assertEqual(a.crop((0,0,1920,700)).tobytes(),b.crop((0,0,1920,700)).tobytes())

    def test_all_video_workflow_commands_receive_repository_variable(self):
        # Include direct renderers and the two watch/render wrappers.
        pattern=re.compile(r'python\s+scripts/(?:generate_[\w]*(?:video|short|weekly|longform|ps_preview)|ps_program|soccer_now|japan_reacts|\w+_render)\.py')
        checked=[]
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            doc=yaml.safe_load(path.read_text(encoding='utf-8'))
            for name,job in (doc.get('jobs') or {}).items():
                for step in job.get('steps') or []:
                    if not pattern.search(str(step.get('run',''))):continue
                    env={**(doc.get('env') or {}),**(job.get('env') or {}),**(step.get('env') or {})}
                    with self.subTest(workflow=path.name,job=name):
                        self.assertEqual(env.get('COLLESPO_BUBBLE'),"${{ vars.COLLESPO_BUBBLE || '' }}")
                    checked.append(path.name)
        self.assertTrue({'longform.yml','japan_reacts.yml','soccer_now.yml','weekly_summary.yml'}<=set(checked))


if __name__=='__main__':unittest.main(argv=[__file__])
