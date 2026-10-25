"""本人が見つけた帯・小字・カード重複と、改ページの全件保持の回帰。"""
import copy
from collections import Counter
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
os.environ.setdefault('COLLESPO_SHORT_LOOK','v4')
import preview_soccer_readability as preview
from preview_soccer_selected import saved_cases
import soccer_readable as layout
import soccer_look
import soccer_slots_v4 as slots
import soccer_results_render as results
import review_render_v3 as r3


class Readable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4'):
            cls.cases=saved_cases()

    def setUp(self):
        env=patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',
                       COLLESPO_MOTION='on',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off')
        env.start();self.addCleanup(env.stop)
        self.addCleanup(r3.set_program_clock,None)
        self.addCleanup(r3.set_caption,'',0,0)

    def draw(self,case,seg,t=3):
        preview.caption(seg)
        return slots.frame(t,seg,case['plan']) if case.get('plan') else results.frame(t,seg,case['data'],case['clubs'])

    def test_all_saved_scenes_use_production_routes_without_changing_material(self):
        checked=0;failures=[]
        for case in self.cases:
            material=copy.deepcopy(case['data'])
            for seg in case['narration']['segments']:
                for t in (3,9):
                    try:im=self.draw(case,seg,t)
                    except ValueError as exc:
                        failures.append((case['key'],seg['kind'],t,str(exc)));continue
                    if not im.info.get('soccer_readable'):continue
                    self.assertNotIn('motion',im.info)
                    errors=layout.check_frame(im,case['clubs'])
                    if errors:failures.append((case['key'],seg['kind'],t,errors))
                    checked+=1
            self.assertEqual(case['data'],material)
        self.assertGreaterEqual(checked,20)
        self.assertFalse(failures,failures)

    def test_seven_people_remain_once_across_two_pages(self):
        case=next(c for c in self.cases if c['key']=='week')
        seg=next(s for s in case['narration']['segments'] if s['kind']=='jp_roster')
        frames=[self.draw(case,seg,t) for t in (3,9)]
        names=[r['name'] for im in frames for r in im.info['readable_rows']]
        self.assertEqual(Counter(names),Counter(r['name'] for r in seg['meta']['rows']))
        self.assertEqual([len(im.info['readable_rows']) for im in frames],[4,3])
        self.assertEqual(layout.minimum_seconds(seg),8)

    def test_goals_minutes_and_assists_are_all_retained(self):
        case=next(c for c in self.cases if c['key']=='goal')
        seg=next(s for s in case['narration']['segments'] if s['kind']=='result')
        frames=[self.draw(case,seg,t) for t in (3,9)]
        actual=[g for im in frames for g in im.info['soccer_goals']]
        self.assertCountEqual(actual,seg['meta']['goals'])
        body=''.join(e['text'] for im in frames for e in im.info['v3_layout'])
        self.assertIn('町野修斗',body);self.assertIn('宇野禅斗',body)
        self.assertEqual(layout.minimum_seconds(seg,case['data']),8)

    def test_large_score_is_one_pair(self):
        case=self.cases[0];seg=case['narration']['segments'][0]
        im=self.draw(case,seg)
        numbers=[e for e in im.info['v3_layout'] if e.get('v5_font')==246]
        self.assertEqual([e['text'] for e in numbers],['2-1'])

    def test_rejects_card_overlap_even_when_text_avoids_portrait(self):
        case=self.cases[0];im=self.draw(case,case['narration']['segments'][0])
        layout.c.rec(im,'card',(700,1620,940,1850))
        self.assertTrue(any('presenter_overlap' in e for e in layout.check_frame(im,case['clubs'])))

    def test_rejects_small_support_text_and_empty_bottom_band(self):
        case=self.cases[0];im=self.draw(case,case['narration']['segments'][0])
        layout.c.text(im,100,1560,'試合',26,role='supplement')
        im.info['duo_caption']['box'][3]=1456
        errors=layout.check_frame(im,case['clubs'])
        self.assertTrue(any('small_text' in e for e in errors))
        self.assertTrue(any('empty_below_caption' in e for e in errors))

    def test_eight_standings_rows_are_paginated_and_keep_points(self):
        case=next(c for c in self.cases if c['key']=='race')
        seg=copy.deepcopy(case['narration']['segments'][0]);spec=seg['meta']
        spec['rows']=[dict(spec['rows'][0],position=i,points=8) for i in range(1,9)]
        spec['shown']=[(1,8)];spec['lines']=[]
        frames=[self.draw(case,seg,t) for t in (3,9)]
        self.assertEqual([r['position'] for im in frames for r in im.info['readable_rows']],list(range(1,9)))
        for im in frames:self.assertFalse(layout.check_frame(im,case['clubs']))

    def test_v5_is_unchanged_until_explicit_v6_and_transition_does_not_overwrite(self):
        case=self.cases[0];seg=case['narration']['segments'][0]
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v5'):
            self.assertFalse(soccer_look.readable());self.assertNotIn('soccer_readable',self.draw(case,seg).info)
        soccer_look.activate();self.assertEqual(os.environ['COLLESPO_SOCCER_LOOK'],'v6')
        im=self.draw(case,seg)
        self.assertEqual(soccer_look.transition(None,im,90),im.tobytes())

    def test_video_time_reserves_four_seconds_per_page(self):
        case=next(c for c in self.cases if c['key']=='week')
        seg=next(s for s in case['narration']['segments'] if s['kind']=='jp_roster')
        with patch.object(slots,'durations',return_value=[3.0]):
            self.assertEqual(slots.video_times([seg],[dict(duration=2)]),[8.0])


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
