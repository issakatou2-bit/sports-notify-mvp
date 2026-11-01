import copy
import sys
import unittest
from unittest.mock import patch

import generate_morning_short as g
import hook_ab
import press_hook
from hook_ab_test_support import DAY, HookFixtureTestCase, press_data


class PressHookTest(HookFixtureTestCase):
    def setUp(self):
        super().setUp()
        self.data=press_data()
        self.a=g.build_narration(self.data,'press')
        self.b=hook_ab.prepare(self.a,'morning_press',DAY,preview='B')
        self.assertEqual(self.b['hook_ab']['ab_variant'],'B')
        g.set_spoken('')
        self.addCleanup(g.set_spoken,'')

    def frame(self,t,meta=None):
        return g.render_intro(min(1,t),meta or self.b['segments'][0]['meta'],[],
                              {'reporters':self.data['reporters']},elapsed=t)

    def test_main_headline_is_large_from_first_frame_then_full_quote(self):
        meta=self.b['segments'][0]['meta']
        full=meta['source_headlines'][0]['jp']
        for t in (0,1,2.9):
            info=self.frame(t).info['press_hook']
            self.assertEqual(info['kind'],'headline_main')
            self.assertEqual(info['font_size'],96)
            self.assertLessEqual(len(info['title_lines']),2)
            self.assertIn('大谷翔平',''.join(info['title_lines']))
            self.assertIn('感謝',''.join(info['title_lines']))
            for x,y,right,bottom in info['boxes']:
                self.assertLessEqual(right,g.W-80)
                self.assertLess(bottom,850)
        with patch.object(g,'render_headlines',wraps=g.render_headlines) as render:
            info=self.frame(3.5).info['press_hook']
            self.assertEqual(info['kind'],'headline_detail')
            self.assertEqual(info['headline'],full)
            self.assertEqual(render.call_args.args[1],meta['source_headlines'])

    def test_long_headline_wraps_without_reducing_font_or_losing_text(self):
        meta=copy.deepcopy(self.b['segments'][0]['meta'])
        title='大谷翔平のユニフォームが200万ドル超で落札、史上最高額を更新'
        meta['source_headlines'][0]['jp']=title
        pages={}
        for t in (0,0.5,1,1.5,2,2.9):
            info=self.frame(t,meta).info['press_hook']
            pages[info['page']]=info['title_lines']
            self.assertLessEqual(len(info['title_lines']),2)
            self.assertEqual(info['font_size'],96)
        self.assertEqual(''.join(''.join(pages[i]) for i in sorted(pages)),title)

    def test_a_keeps_existing_cover_and_does_not_call_b_renderer(self):
        a=hook_ab.prepare(self.a,'morning_press','2026-10-23',preview='A')
        with patch.dict('os.environ',{},clear=True):
            disabled=hook_ab.prepare(self.a,'morning_press','2026-10-23')
        self.assertEqual(a['segments'],self.a['segments'])
        self.assertEqual(disabled['segments'],self.a['segments'])
        meta=self.a['segments'][0]['meta']
        with patch.object(press_hook,'frame',side_effect=AssertionError('AがBの描画を呼びました')):
            for t in (1,3,5,8):
                expected=self.frame(t,meta).tobytes()
                self.assertEqual(self.frame(t,a['segments'][0]['meta']).tobytes(),expected)
                self.assertEqual(self.frame(t,disabled['segments'][0]['meta']).tobytes(),expected)

    def test_caption_does_not_leave_first_digit_of_next_sentence(self):
        # 90字目が次文の「1」になる境界を、日々変わる投稿から切り離す。
        segment={'text':'あ'*(g.SPOKEN_MAX-2)+'。1年前の今日。'}
        original=segment['text']
        self.assertTrue(original[:g.SPOKEN_MAX].endswith('。1'))
        caption=press_hook.caption_prefix(original,g.SPOKEN_MAX)
        self.assertTrue(caption.endswith('。…'))
        self.assertNotIn('。1',caption)
        self.assertEqual(segment['text'],original)
        g.set_spoken(original)
        _,draw=g.base(0)
        self.assertNotIn('。1',''.join(g.spoken_lines(draw)))
        for text in ('2語の感謝メッセージ。','1年前の今日。','23:00の試合。','0-1で終了。','防御率4.92。'):
            self.assertEqual(press_hook.caption_prefix(text,90),text)
        for text,limit in [('防御率4.92を記録',5),('開始23:00です',5),('結果0-1です',4)]:
            self.assertFalse(press_hook.caption_prefix(text,limit).rstrip('…')[-1:].isdigit())

    def test_existing_modern_quote_validation_and_three_second_boundary(self):
        import daily_v3
        import review_render_v3 as r3
        for look in ('v3','v4'):
            with patch.dict('os.environ',{'COLLESPO_PRESS_DESIGN':'v3'}),patch.object(r3,'LOOK',look):
                a=g.build_narration(self.data,'press')
                b=hook_ab.prepare(a,'morning_press','2026-10-23',preview='B')
                design=daily_v3.prepare(self.data,b,'press')
                recorder=hook_ab.SceneRecorder()
                for t in (0,1,2.9,3,3.5):
                    im=daily_v3.frame(t,b['segments'][0],design,7)
                    recorder.observe(im,round(t*24),24,0)
                self.assertEqual(recorder.starts,[0,3])


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
