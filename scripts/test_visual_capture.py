"""Regression failures from APSC and first-pass geometry; no visual approval."""
import json
from pathlib import Path
import sys
import unittest
import asyncio
import io

from visual_capture import layout_issues


class VisualRegression(unittest.TestCase):
    def test_empty_site_cannot_report_success(self):
        import tempfile
        from types import SimpleNamespace
        from visual_capture import capture_pwa
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'No HTML pages'):
                asyncio.run(capture_pwa(SimpleNamespace(site=Path(tmp),include='*.html')))

    def test_japanese_instructions_survive_shell_encoding(self):
        doc = (Path(__file__).parents[1] / 'docs/VISUAL_CHECK.md').read_text(encoding='utf-8')
        self.assertIn('画面と遷移', doc)
        self.assertNotIn('????', doc)
    def test_known_failures(self):
        fixture = Path(__file__).parent / 'fixtures/visual/failures.json'
        for case in json.loads(fixture.read_text(encoding='utf-8')):
            with self.subTest(case=case['name']):
                kinds = {p['kind'] for p in layout_issues(case['layout'])}
                self.assertIn(case['expected'], kinds)

    def test_existing_renderer_caption_collision_is_checked(self):
        from visual_capture import renderer_layout
        frame={'v3_layout':[{'role':'text','box':[10,10,300,80],'text':'source'},
                            {'role':'caption','box':[10,50,300,120],'text':'caption'}]}
        self.assertIn('overlap', {r['kind'] for r in layout_issues(renderer_layout(frame))})

    def test_real_video_sampling_and_no_frame_files(self):
        import shutil
        import tempfile
        import subprocess
        from types import SimpleNamespace
        from visual_capture import video_capture
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg/ffprobe not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); video=root/'sample.mp4'; out=root/'out'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:size=64x96:rate=10:duration=1',
                            '-f','lavfi','-i','color=blue:size=64x96:rate=10:duration=1',
                            '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0',
                            '-threads','1','-pix_fmt','yuv420p',str(video)],check=True)
            video_capture(SimpleNamespace(video=video,out=out,timeline=None))
            manifest=json.loads((out/'video/sample-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['extracted_files'],0)
            self.assertTrue(any('head' in reasons for reasons in manifest['samples'].values()))
            self.assertTrue(any('tail' in reasons for reasons in manifest['samples'].values()))
            self.assertTrue(any(.85 < cut < 1.15 for cut in manifest['cuts']))
            self.assertTrue(any('transition' in reasons for reasons in manifest['samples'].values()))
            self.assertEqual(list(out.rglob('*.png')),[])
            self.assertTrue(list(out.rglob('*contact-*.jpg')))

    def test_corrected_layout(self):
        self.assertEqual(layout_issues({'width':1080,'height':1920,'boxes':[
            {'id':'caption','rect':[50,1200,700,160],'avoid':['face']},
            {'id':'face','rect':[800,1400,250,520],'role':'character','facing':'left'},
            {'id':'number','rect':[100,400,240,80],'role':'number','max_number_width':240}
        ]}), [])

    def test_contact_sheet_pagination(self):
        import tempfile
        from PIL import Image
        from visual_capture import sheet
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); image=root/'sample.png'; Image.new('RGB',(10,20),'red').save(image)
            sheet([(str(i),image) for i in range(49)], root/'contact.jpg')
            self.assertEqual(len(list(root.glob('contact-*.jpg'))),3)
            self.assertEqual(len(list(root.glob('*.png'))),1)

    def test_rejected_snapshot_cannot_be_used_as_approved_baseline(self):
        import tempfile
        from PIL import Image
        from visual_capture import compare
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); current=root/'current'; baseline=root/'baseline'; out=root/'comparison'
            current.mkdir();baseline.mkdir()
            Image.new('RGB',(10,20),'white').save(current/'screen.png')
            Image.new('RGB',(10,20),'white').save(baseline/'screen.jpg')
            (baseline/'inventory.json').write_text(json.dumps({'images':[{'image':'screen.png','approved':False}]}),encoding='utf-8')
            compare(current,baseline,out)
            review=json.loads((out/'review.json').read_text(encoding='utf-8'))
            self.assertEqual(review['images'][0]['baseline'],'unapproved')
            self.assertEqual(review['images'][0]['verdict'],'未確認')
            self.assertFalse((out/'screen.jpg').exists())

    def test_tall_capture_stitches_last_partial_viewport_without_repetition(self):
        import tempfile
        from PIL import Image
        from visual_capture import capture_page

        class Page:
            y = 0

            async def evaluate(self, expression, value=None):
                if expression == 'scrollY': return self.y
                if value is not None:
                    self.y = min(value, 190)
                elif 'scrollTo' in expression:
                    self.y = 0
                else:
                    return 250

            async def wait_for_timeout(self, value):
                pass

            async def screenshot(self, **kwargs):
                image = Image.new('RGB', (2,60))
                for y in range(60):
                    for x in range(2): image.putpixel((x,y),(self.y+y,0,0))
                stream=io.BytesIO(); image.save(stream,format='PNG'); return stream.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stitched.png'
            # Force the real tall-page path at tiny dimensions for a cheap regression.
            asyncio.run(capture_page(Page(),path,2,60,1,tall_threshold=200))
            with Image.open(path) as image:
                self.assertEqual(image.size,(2,250))
                for y in range(250): self.assertEqual(image.getpixel((0,y)),(y,0,0))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
