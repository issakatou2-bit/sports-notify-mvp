"""Portable motion contract: fixed material + bundled fonts, no saved local audio."""
import json
from contextlib import ExitStack
import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
import motion as m

ROOT=Path(__file__).resolve().parents[1]
ROWS=[dict(key=str(i),title=n,body='確認用の固定材料',metric=f'{i+1}安打',anchor=n)
      for i,n in enumerate(('上の選手','真ん中の選手','下の選手'))]


class Motion(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'COLLESPO_MOTION':'on','COLLESPO_SHORT_LOOK':'v4','COLLESPO_SOCCER_LOOK':'v5','COLLESPO_EXPR':'','COLLESPO_BUBBLE':'glass'})
        self.env.start();m.SPEECH.clear()
        import review_render_v3 as r3
        self.look=patch.object(r3,'LOOK','v4');self.look.start()

    def tearDown(self):
        self.env.stop();self.look.stop();m.SPEECH.clear();m.HIGHLIGHTS.clear()
        import review_render_v3 as r3
        r3.set_caption('',0,0);r3.set_program_clock(None)

    def test_off_is_exact_and_returns_original(self):
        im=Image.new('RGB',(1080,1920),(11,33,54))
        for flag in ('','off','ON','unknown'):
            with patch.dict(os.environ,{'COLLESPO_MOTION':flag}):
                self.assertIs(m.list_frame(im,1,ROWS,'一覧'),im)
                self.assertIs(m.background(im,5),im)
                self.assertIsNone(m.transition(im.tobytes(),im,2))
        with patch.dict(os.environ,{},clear=True):
            self.assertIs(m.list_frame(im,1,ROWS,'一覧'),im)

    def test_sync_is_explicit_and_rejects_wrong_or_overlapping_cues(self):
        cues=[m.Cue(str(i),.8+i*2,2.4+i*2,r['anchor']) for i,r in enumerate(ROWS)]
        m.validate_cues(ROWS,cues,7)
        with self.assertRaises(ValueError):m.validate_cues(ROWS,[m.Cue('1',0,2,'上の選手')],7)
        with self.assertRaises(ValueError):m.validate_cues(ROWS,[cues[0],m.Cue('1',1,3,'真ん中の選手')],7)
        self.assertIsNone(m.cue_for(ROWS[0],'一覧です。',4))

    def test_every_frame_active_row_is_safe_and_chrome_is_identical(self):
        im=Image.new('RGB',(1080,1920),(12,24,36))
        cues=[m.Cue(str(i),.8+i*2,2.4+i*2,r['anchor']) for i,r in enumerate(ROWS)]
        seen=set();max_speed=0;last=1
        for k in range(7*30):
            frame=m.list_frame(im,k/30,ROWS,'一覧',cues,7)
            info=frame.info['motion']
            self.assertEqual(info['source_size'],(1736,1808))
            self.assertEqual(info['zoom'],1.)
            self.assertEqual(info['crop'],(0,0,868,904))
            self.assertLessEqual(info['row_scale'],1.04)
            self.assertLessEqual(sum(v>0 for v in info['weights']),1)
            if info['active'] is not None:seen.add(info['active'])
            self.assertEqual(frame.crop((0,1200,1080,1920)).tobytes(),im.crop((0,1200,1080,1920)).tobytes())
            max_speed=max(max_speed,abs(info['zoom']-last)*30);last=info['zoom']
        self.assertEqual(seen,{'0','1','2'})
        self.assertLess(max_speed,1.)
        self.assertTrue(m.list_frame(im,.7,ROWS,'一覧',cues,7).info['motion']['overview'])

    def test_transition_endpoints_and_fixed_caption_for_both_styles(self):
        old=Image.new('RGB',(1080,1920),(5,25,45));new=Image.new('RGB',old.size,(80,90,100))
        new.info['duo_portraits']=[dict(box=[700,1031,944,1280])]
        n=round(m.SETTINGS['transition']*30)
        for style in ('glass','slant'):
            start=Image.frombytes('RGB',old.size,m.transition(old.tobytes(),new,0,30,style))
            expected=new.copy();expected.paste(old.crop(m.VIEW),m.VIEW[:2])
            expected.paste(new.crop((700,1031,944,1280)),(700,1031))
            self.assertEqual(start.tobytes(),expected.tobytes())
            self.assertEqual(start.crop((0,1200,1080,1920)).tobytes(),new.crop((0,1200,1080,1920)).tobytes())
            self.assertEqual(start.crop((700,1031,944,1280)).tobytes(),new.crop((700,1031,944,1280)).tobytes())
            self.assertEqual(m.transition(old.tobytes(),new,n-1,30,style),new.tobytes())

    def test_subtitle_pages_never_choose_an_ambiguous_row(self):
        import review_render_v3 as r3
        r3.set_caption('上の選手と真ん中の選手の一覧です。',4,4)
        self.assertEqual(m.caption_cues(ROWS,4),[])

    def test_three_real_adapters_fixed_material(self):
        import review_render_v3 as r3
        import soccer_slots_v4 as slots
        from test_reddit_reaction import preview
        import player_story_render as reddit
        import bignumber_render as bn
        import ps_brand_components as fonts
        fonts.FONT_CANDIDATES['jp']=[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
        fonts.FONT_CANDIDATES['latin']=[str(ROOT/'assets/fonts/Oswald[wght].ttf')];fonts._cache.clear()
        narr=preview()
        for seg in narr['segments']:
            if seg['kind'] not in ('intro','fan'):continue
            r3.set_program_clock(0);r3.set_caption(seg['text'],4,30,speaker=2);r3.set_program_clock(1)
            im=reddit.frame(1,seg,narr)
            self.assertIn('motion',im.info)
            self.assertTrue(any('YouTube' in e['text'] for e in im.info['motion']['texts']))
            if seg['kind']=='fan':self.assertIsNotNone(im.info['motion']['active'])
        material=json.loads((ROOT/'scripts/fixtures/soccer-slots/preview.json').read_text(encoding='utf8'))
        plan=slots.program('preview',material)
        for seg in plan['narration']['segments']:
            if seg['kind'] not in ('cover','preview'):continue
            r3.set_program_clock(0);r3.set_caption(seg['text'],4,30);r3.set_program_clock(1)
            im=slots.frame(1,seg,plan);self.assertIn('motion',im.info)
        data=json.loads((ROOT/'scripts/fixtures/bignumber/morning_recap.json').read_text(encoding='utf8'))
        narr=bn._gms().build_narration(dict(data,players=bn._gms().sort_players(data['players'])),'players')
        # Force the already supported editorial sequence, independent of today's data.
        with patch.dict(os.environ,{'COLLESPO_PLAYERS_DESIGN':'bignumber'}):
            narr=bn._gms().build_narration(dict(data,players=bn._gms().sort_players(data['players'])),'players')
            scenes=bn.scenes_from_morning(data,narr)
            selected=[s for s in scenes if s['kind'] in ('ranking','hero','list')]
            self.assertTrue(selected)
            for sc in selected:
                r3.set_program_clock(0);r3.set_caption(sc['say'],4,30);r3.set_program_clock(1)
                im=bn.scene(1,dict(sc,dur=4));self.assertIn('motion',im.info)
            rows=next(s['motion_rows'] for s in scenes if s['kind']=='hero')
            for row in rows:
                person=next(p for p in data['players'] if p['name']==row['anchor'])
                self.assertIn(person['headline'],row['body'])

    def test_workflow_gate_and_no_frame_freeze(self):
        import video_common as vc
        self.assertFalse(vc.anim_step(29,30)[1])
        with patch.dict(os.environ,{'COLLESPO_MOTION':''}):self.assertTrue(vc.anim_step(29,30)[1])
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            text=path.read_text(encoding='utf8')
            renderers=('generate_video.py','generate_morning_short.py','generate_asset_video.py','generate_longform.py','soccer_now.py','japan_reacts.py')
            if 'COLLESPO_BUBBLE:' in text or any(name in text for name in renderers):
                self.assertIn("COLLESPO_MOTION: ${{ vars.COLLESPO_MOTION || '' }}",text,path.name)

    def test_other_lists_and_fixed_heading_do_not_clip(self):
        import review_render_v3 as r3
        import soccer_slots_v4 as slots
        for mode,kind in (('race','standings'),('week','jp_roster')):
            data=json.loads((ROOT/f'scripts/fixtures/soccer-slots/{mode}.json').read_text(encoding='utf8'))
            plan=slots.program(mode,data)
            selected=[s for s in plan['narration']['segments'] if s['kind']==kind]
            self.assertTrue(selected)
            for seg in selected:
                r3.set_program_clock(0);r3.set_caption(seg['text'],4,30);r3.set_program_clock(1)
                im=slots.frame(1,seg,plan)
                if 1<len(seg['meta']['rows'])<=8:self.assertIn('motion',im.info)
        blank=Image.new('RGB',(1080,1920))
        a=m.list_frame(blank,.8,ROWS,'固定した見出し')
        b=m.list_frame(blank,1.5,ROWS,'固定した見出し',[m.Cue('0',.8,3,'上の選手')],4)
        self.assertEqual(a.crop((72,236,940,304)).tobytes(),b.crop((72,236,940,304)).tobytes())
        eight=[dict(key=str(i),title=f'{i+1}位 選手の名前',body='所属クラブ',metric='3安打',anchor=f'選手{i}') for i in range(8)]
        blank.info['duo_portraits']=[dict(box=[700,1040,950,1280])]
        for i in (0,7):
            frame=m.list_frame(blank,1.4,eight,'8人の一覧',[m.Cue(str(i),.8,3,f'選手{i}')],4)
            self.assertIsNotNone(frame.info['motion']['active'])

    def test_numeric_effect_uses_existing_highlight_and_landscape_chrome_is_fixed(self):
        import fan_events
        import review_render_v3 as r3
        face=m.font(40)
        fan_events.TRACK[:]=[dict(start=0,end=4,text='3安打。',speech=3,decision=dict(highlights=['3安打']))]
        m.HIGHLIGHTS[:]=fan_events.TRACK
        try:
            r3.set_program_clock(.24)
            self.assertGreater(m.number_font(face,'3').size,face.size)
            self.assertIs(m.number_font(face,'2'),face)
            r3.set_program_clock(2)
            self.assertIs(m.number_font(face,'3'),face)
        finally:fan_events.TRACK.clear()
        old=Image.new('RGB',(1920,1080),(10,20,30));new=Image.new('RGB',old.size,(100,90,80))
        frame=Image.frombytes('RGB',old.size,m.transition(old.tobytes(),new,4,30,'glass'))
        self.assertEqual(frame.crop((0,800,1920,1080)).tobytes(),new.crop((0,800,1920,1080)).tobytes())

    def test_motion_alone_uses_same_fact_decision_without_enabling_expression(self):
        import fan_events
        data=dict(players=[dict(name='大谷翔平',type='batter',hits=3,ab=4,hr=0)])
        text='大谷翔平は3安打。'
        with patch.dict(os.environ,{'COLLESPO_EXPR':'fan'}):expected=fan_events.decision(text,data)
        m.prepare_highlights(data,[dict(text=text,duration=3)],[4])
        self.assertEqual(m.HIGHLIGHTS[0]['decision'],expected)
        self.assertFalse(fan_events.enabled())

    def test_camera_does_not_jump_at_portrait_horizontal_threshold(self):
        from test_reddit_reaction import preview
        import review_render_v3 as r3
        narr=preview();seg=narr['segments'][1]
        r3.set_caption(seg['text'],4,30)
        rows,heading,_,duration,_,soccer=m.adapt('reddit',0,(seg,narr),{})
        blank=Image.new('RGB',(1080,1920));blank.info['duo_portraits']=[dict(box=[702,1031,944,1281])]
        previous=None;largest=0
        for k in range(12):
            t=.8+k/30
            frame=m.list_frame(blank,t,rows,heading,[m.Cue('0',.8,3,rows[0]['anchor'])],duration,False,soccer)
            y=frame.info['motion']['crop'][1]
            if previous is not None:largest=max(largest,abs(y-previous))
            previous=y
        self.assertLess(largest,20)

    def test_default_pixels_match_portable_frozen_base(self):
        import review_render_v3 as r3
        import player_story_render as reddit
        from test_reddit_reaction import preview
        import soccer_slots_v4 as slots
        import bignumber_render as bn
        import ps_brand_components as fonts
        fonts.FONT_CANDIDATES['jp']=[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
        fonts.FONT_CANDIDATES['latin']=[str(ROOT/'assets/fonts/Oswald[wght].ttf')];fonts._cache.clear()
        reference=json.loads((ROOT/'scripts/fixtures/motion/off-reference.json').read_text(encoding='utf8'))['functions']
        originals=[]
        for module,functions in reference.items():
            module=importlib.import_module(module);scope=dict(vars(module))
            for name,source in functions.items():
                exec(compile(source,'frozen-off-reference','exec'),scope)
                originals.append((module,name,scope[name]))
        n=preview();seg=n['segments'][1]
        plan=slots.program('preview',json.loads((ROOT/'scripts/fixtures/soccer-slots/preview.json').read_text(encoding='utf8')))
        rank=[dict(rank=i+1,name=r['title'],abbr='LAD',score=r['metric'],team_id='119') for i,r in enumerate(ROWS)]
        cases=[(seg['text'],lambda t:reddit.frame(t,seg,n)),
               (plan['narration']['segments'][1]['text'],lambda t:slots.frame(t,plan['narration']['segments'][1],plan)),
               ('今日の勝利貢献順位です。',lambda t:bn.scene(t,dict(kind='ranking',ranking=rank,dur=4)))]
        for style in ('','slant','glass'):
            with patch.dict(os.environ,{'COLLESPO_MOTION':'','COLLESPO_BUBBLE':style,'COLLESPO_SLANT_VARIANT':'cream'}):
                for text,draw in cases:
                    for t in (0,.35,.8,1.5):
                        r3.set_program_clock(0);r3.set_caption(text,4,30);r3.set_program_clock(t)
                        new=draw(t)
                        with ExitStack() as stack:
                            for module,name,function in originals:stack.enter_context(patch.object(module,name,function))
                            old=draw(t)
                        self.assertEqual(new.tobytes(),old.tobytes(),(style,text,t))


if __name__=='__main__':unittest.main(argv=[__file__])
