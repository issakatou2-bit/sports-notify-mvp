"""v5の5枠・全クラブ・効果・幅・数字と、v4/legacyの基点画素の回帰。"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
FIX=ROOT/'scripts/fixtures/soccer-slots'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_native():
    import soccer_slots_v4 as slots
    import soccer_results as results
    import soccer_results_render as rr
    import soccer_voices as voices
    import soccer_voices_render as vr
    import review_render_v3 as r3
    checks=[]
    for mode in ('preview','race','week'):
        plan=slots.program(mode,read(FIX/(mode+'.json')))
        for seg in plan['narration']['segments']:
            checks.append((mode,seg,lambda t,s=seg,p=plan:slots.frame(t,s,p),lambda im,p=plan:slots.check_frame(im,p)))
    data=results.build(read(ROOT/'scripts/fixtures/soccer-results/scoreboards.json'),read(ROOT/'scripts/fixtures/soccer-results/summaries.json'),'2026-09-20')
    clubs=rr.resolve_clubs(data)
    for seg in rr.narration(data)['segments']:
        checks.append(('results',seg,lambda t,s=seg,d=data,c=clubs:rr.frame(t,s,d,c),lambda im,d=data,c=clubs:rr.validate_frame(im,d,c)))
    data=vr.prepare(voices.sample_input(ROOT/'scripts/fixtures/soccer-voices/fictional.json'));clubs=vr.clubs_for(data)
    for seg in voices.narration(data)['segments']:
        checks.append(('voices',seg,lambda t,s=seg,d=data,c=clubs:vr.frame(t,s,d,c,20),lambda im,d=data,c=clubs:vr.check_frame(im,d,c)))
    try:
        for mode,seg,draw,check in checks:
            for t in (0,.35,.8,1.4,1.9,2.2,3,18):
                r3.set_program_clock(0);r3.set_caption(seg['text'],20,100,speaker=2,hide_caption=seg['kind']=='outro');r3.set_program_clock(t)
                im=draw(t);errors=check(im)
                if errors:raise AssertionError((mode,seg['kind'],t,errors))
                if not im.info.get('soccer_v5'):raise AssertionError('v5へ接続されていません')
        return len(checks)*8
    finally:r3.set_caption('',0,0);r3.set_program_clock(None)


class V5(unittest.TestCase):
    def test_preview_cli_handles_native_video_reports(self):
        import preview_soccer_v5 as preview
        with tempfile.TemporaryDirectory() as directory:
            report=dict(mode='native-mode',seconds=20,screens=4)
            with patch.object(sys,'argv',['preview_soccer_v5','--out',directory]),patch.object(preview,'audio_for',return_value=[]),patch('soccer_results_render.ensure_ffmpeg'),patch('soccer_results_render.render_video',return_value=report),patch('soccer_slots_v4.render_video',return_value=report):
                self.assertEqual(preview.main(),0)
            data=read(Path(directory)/'confirmation.json')
            self.assertEqual([p['mode'] for p in data['previews']],['preview','race','week','results','voices'])
            self.assertFalse(data['published'])
    def test_native_every_slot_every_phase(self):
        self.assertGreaterEqual(validate_native(),200)

    def test_all_96_badges_contrast_and_white_edges(self):
        import soccer_v5_cards as c
        from PIL import Image
        clubs={x['team_en']:x for x in c.original.load_clubs().values()}
        self.assertEqual(len(clubs),96)
        for club in clubs.values():
            for variant in ('A','B'):
                im=Image.new('RGB',(400,200),c.PITCH)
                c.scarf(im,(30,30,300,120),club,variant=variant,fringe=True)
                entry=im.info['v5_contrasts'][0]
                self.assertGreaterEqual(entry['text_ratio'],4.5,club['team_en'])
                self.assertGreaterEqual(entry['edge_ratio'],3,club['team_en'])
                if club.get('primary'):self.assertEqual(entry['base'],__import__('PIL.ImageColor',fromlist=['getrgb']).getrgb(club['primary']))
        for name in ('Real Madrid CF','Leeds United FC','Crystal Palace FC'):
            # パレスのmainは青/赤。白を使った見本の条件でも消えないことを別に検査する。
            for white in (False,True):
                club=dict(clubs[name]);club.update(primary='#FFFFFF') if white else None
                im=Image.new('RGB',(400,200),c.PITCH);c.scarf(im,(30,30,300,120),club)
                entry=im.info['v5_contrasts'][0]
                self.assertGreaterEqual(entry['text_ratio'],4.5)
                if sum(entry['base'])>700:
                    self.assertEqual(entry['outline'],(0,0,0))
                    self.assertEqual(im.getpixel((30+round(89*c.SLANT),30)),(0,0,0))
        club=dict(team_en='Unknown',abbr='UNK',primary=None,secondary=None)
        self.assertEqual(c.colors(club)[0],(70,78,78))

    def test_two_variants_only_pattern_differs(self):
        import soccer_v5_cards as c
        from PIL import Image
        club=c.original.load_clubs()['Real Madrid CF']
        a,b=(Image.new('RGB',(400,200),c.PITCH) for _ in range(2))
        c.scarf(a,(30,30,300,120),club,variant='A');c.scarf(b,(30,30,300,120),club,variant='B')
        self.assertNotEqual(a.tobytes(),b.tobytes())
        self.assertEqual(a.info['v5_contrasts'][0]['secondary'],b.info['v5_contrasts'][0]['secondary'])

    def test_long_text_stops_before_drawing_and_italic_ink_fits(self):
        import soccer_v5_cards as c
        im=c.canvas(3,{})
        before=im.tobytes()
        with self.assertRaisesRegex(ValueError,'描画停止'):c.text(im,72,300,'長い文字'*100,40,width=60)
        self.assertEqual(before,im.tobytes())
        box=c.text(im,72,300,'19:30',220,width=200,number=True)
        self.assertLessEqual(box[2]-box[0],200)
        self.assertLess(im.info['v3_layout'][-1]['v5_font'],220)
        runs,width,box=c.measure('勝点412',32)
        self.assertEqual(len(runs),2)
        self.assertEqual(Path(runs[1][1].path).name,'BarlowCondensed-ExtraBoldItalic.ttf')
        self.assertEqual(c.screen_text('得点🙂'),'得点')

    def test_scarf_wipe_keeps_header_caption_portrait_fixed(self):
        import soccer_v5_cards as c
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        plan=slots.program('preview',read(FIX/'preview.json'));seg=plan['narration']['segments'][1]
        r3.set_caption(seg['text'],12,40);im=slots.frame(3,seg,plan)
        old=__import__('PIL.Image',fromlist=['Image']).new('RGB',im.size,(120,10,10)).tobytes()
        for t in (0,.1,.3,.59,.6):
            effect=__import__('PIL.Image',fromlist=['Image']).frombytes('RGB',im.size,c.scarf_transition(old,im,t))
            self.assertEqual(effect.crop((0,0,1080,236)).tobytes(),im.crop((0,0,1080,236)).tobytes())
            self.assertEqual(effect.crop((0,1150,1080,1920)).tobytes(),im.crop((0,1150,1080,1920)).tobytes())
        self.assertEqual(c.scarf_transition(old,im,.6),im.tobytes())
        r3.set_caption('',0,0)

    def test_badge_identity_offset_overflow_and_added_number_rejected(self):
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        plan=slots.program('preview',read(FIX/'preview.json'));seg=plan['narration']['segments'][1]
        r3.set_program_clock(0);r3.set_caption(seg['text'],12,40);r3.set_program_clock(3)
        im=slots.frame(3,seg,plan)
        bad=copy.deepcopy(im);bad.info['v4_badges'][0]['club_id']='wrong'
        self.assertTrue(slots.check_frame(bad,plan))
        bad=copy.deepcopy(im);bad.info['v4_badges'][0]['box'][2]-=40
        self.assertTrue(slots.check_frame(bad,plan))
        bad=copy.deepcopy(im);bad.info['v3_layout'].append(dict(role='text',text='987654321',box=[100,1100,500,1160]))
        errors=slots.check_frame(bad,plan)
        self.assertTrue(any('numbers_missing_from_material' in e for e in errors if isinstance(e,dict)))
        self.assertTrue(any(e.get('text')=='987654321' for e in errors if isinstance(e,dict)))
        bad=copy.deepcopy(im)
        layer=bad.info['duo_layer'][0];x,y=layer['at']
        bad.info['v3_layout'].append(dict(role='text',text='1',box=[x,y+25,x+220,min(1150,y+120)]))
        self.assertTrue(any('covered_by_presenter' in e for e in slots.check_frame(bad,plan) if isinstance(e,dict)))
        r3.set_caption('',0,0);r3.set_program_clock(None)

    def test_protected_v4_modules_and_common_functions_unchanged(self):
        frozen=read(FIX/'v5-protected-source.json')
        for path,want in frozen['files'].items():
            value=(ROOT/path).read_text(encoding='utf-8').replace('\r\n','\n')
            self.assertEqual(hashlib.sha256(value.encode()).hexdigest(),want,path)
        for path,functions in frozen['functions'].items():
            value=(ROOT/path).read_text(encoding='utf-8').replace('\r\n','\n')
            nodes={n.name:n for n in ast.parse(value).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
            for name,want in functions.items():
                source=ast.get_source_segment(value,nodes[name])
                self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),want,path+':'+name)


def main():
    if '--native-only' in sys.argv:
        print('ok soccer v5 native phases',validate_native());return 0
    if '--v5-child' in sys.argv:
        unittest.main(argv=[sys.argv[0]],verbosity=1);return 0
    failed=0;counts={}
    for look in ('v3','v4'):
        env=dict(os.environ,COLLESPO_SHORT_LOOK=look,COLLESPO_SOCCER_LOOK=look,COLLESPO_DUO='off')
        proc=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/soccer_pixel_regression.py')],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        if proc.returncode:print('NG',look,proc.stderr[-1200:]);failed+=1;continue
        got=json.loads(proc.stdout[proc.stdout.index('{'):]);counts[look]=len(got)
        frozen=read(FIX/'v5-base-pixels.json')
        # 字の画素はOSの共通書体で変わる。Windowsの基点92コマを実測比較、他OSは保護ソースも検査。
        if sys.platform==frozen['platform'] and got!=frozen['looks'][look]:
            print('NG pixels',look,[k for k in got if got[k]!=frozen['looks'][look].get(k)]);failed+=1
    proc=subprocess.run([sys.executable,'-X','utf8',__file__,'--v5-child'],env=dict(os.environ,COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_DUO='off'),cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if proc.returncode:print('NG v5',proc.stderr[-8000:]);failed+=1
    else:print('v5',proc.stderr.strip().splitlines()[-1])
    print(('NG' if failed else 'ok')+' soccer v5 / v4-legacy pixels '+str(counts))
    return bool(failed)


if __name__=='__main__':raise SystemExit(main())
