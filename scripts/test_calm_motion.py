"""Opus-32（279）：動きを「見やすく・静かに」と、クラブの表示名の検査。

python -m pytest scripts/test_calm_motion.py（collespo の作業場所で）。
描画の検査は日本語の書体が無い環境では飛ばす。
"""
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import calm_motion as calm  # noqa: E402
import notability_engine as ne  # noqa: E402

ON = {'COLLESPO_MOTION': 'on'}
OFF = {'COLLESPO_MOTION': ''}


def has_font():
    try:
        import ps_brand_components as pb
        pb.font(40)
        return True
    except Exception:
        return False


class PlanTest(unittest.TestCase):
    def test_parts_split_by_characters(self):
        plan = calm.plan_from_parts('あいう。かき。', ['あいう。', 'かき。'])
        self.assertEqual([idx for _, _, idx in plan], [0, 1])
        self.assertAlmostEqual(plan[0][1], 4 / 7)

    def test_parts_must_match_the_narration(self):
        self.assertEqual(calm.plan_from_parts('あいう。', ['あいう', 'え']), [])

    def test_markers_do_not_guess(self):
        text = '今シーズンの成績は、鈴木誠也が143試合、今永昇太が32登板。'
        plan = calm.plan_from_markers(text, ['鈴木誠也', '今永昇太'])
        self.assertEqual([idx for _, _, idx in plan], [None, 0, 1])
        self.assertEqual(calm.plan_from_markers(text, ['鈴木誠也', '大谷翔平']), [])
        self.assertEqual(calm.plan_from_markers(text, ['今永昇太', '鈴木誠也']), [])

    def test_same_rule_as_ps_program_focus_at(self):
        """今の同期の決まり（ps_program.focus_at）と同じ行を返す。"""
        import ps_program as pp
        plan = calm.plan_from_markers('前置き。Aの話。Bの話。', ['Aの話', 'Bの話'])
        for k in range(101):
            self.assertEqual(calm.focus_at(plan, k / 100), pp.focus_at(plan, k / 100))


class WeightTest(unittest.TestCase):
    timeline = [(1.0, 3.0, 0), (3.0, 6.0, 1)]

    def test_one_card_at_a_time_and_smooth(self):
        prev = None
        for n in range(0, 7 * 30):
            w = calm.weights(self.timeline, n / 30, 2)
            self.assertLessEqual(sum(1 for x in w if x > 0.001), 1, n / 30)
            if prev is not None:
                self.assertLessEqual(max(abs(a - b) for a, b in zip(w, prev)), 0.45)   # 1コマで半分以上は跳ばない
            prev = w

    def test_switch_has_time_to_settle(self):
        fade = calm.TUNING['focus_fade']
        self.assertTrue(0.8 <= fade <= 1.0)
        self.assertEqual(calm.weights(self.timeline, 3.0, 2), [0.0, 0.0])
        self.assertAlmostEqual(calm.weights(self.timeline, 3.0 + fade / 2, 2)[1], 1.0)
        self.assertAlmostEqual(calm.weights(self.timeline, 3.0 - fade / 2, 2)[0], 1.0)

    def test_nothing_before_cards_settle(self):
        tl = calm.to_seconds([(0, .5, 0), (.5, 1, 1)], 4.0, settle=1.0)
        self.assertEqual(tl[0][0], 1.0)

    def test_off_means_no_focus_and_current_values(self):
        with patch.dict(os.environ, OFF):
            self.assertIsNone(calm.focus_for(2, 'あ。い。', 4, 2, parts=['あ。', 'い。']))
            self.assertEqual(calm.value('slide_distance', 1.0), 1.0)
            self.assertEqual(calm.value('background_speed', 1.0), 1.0)
        with patch.dict(os.environ, ON):
            self.assertIsNotNone(calm.focus_for(2, 'あ。い。', 4, 2, parts=['あ。', 'い。']))

    def test_tuning_is_quiet(self):
        t = calm.TUNING
        self.assertTrue(1.03 <= t['focus_scale'] <= 1.05)
        self.assertLessEqual(t['slide_distance'], 0.6)
        self.assertLessEqual(t['overshoot'], 0.6)
        self.assertLessEqual(t['background_speed'], 0.2)

    def test_fractional_scale_keeps_center_and_fixed_sampling_grid(self):
        from PIL import Image, ImageDraw
        import numpy as np
        card = Image.new('RGBA', (201, 101))
        ImageDraw.Draw(card).rectangle((20, 20, 180, 80), fill='white')
        sizes = set()
        for own in (.01, .05, .1, .25, .5, .75, 1):
            out, dw, dh = calm.styled(card, own, 0)
            sizes.add(out.size)
            alpha = np.asarray(out.getchannel('A'), dtype=float)
            yy, xx = np.indices(alpha.shape)
            # 画素の中心を比較。丸めた寸法の奇偶で中心が0.5pxずれない。
            self.assertAlmostEqual(float((xx*alpha).sum()/alpha.sum())-dw/2, 100, delta=.04)
            self.assertAlmostEqual(float((yy*alpha).sum()/alpha.sum())-dh/2, 50, delta=.04)
        self.assertEqual(len(sizes), 1)

    def test_no_overshoot_and_smoother_stop(self):
        values = [calm._smooth(i/100) for i in range(101)]
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[0], values[-1]), (0, 1))
        self.assertLess(values[1]-values[0], .00002)
        self.assertEqual(calm.TUNING['overshoot'], 0)
        self.assertEqual(calm.TUNING['presenter_bob'], 0)


@unittest.skipUnless(has_font(), '日本語の書体が無い')
class RenderTest(unittest.TestCase):
    topic = 'season_team_112'   # カブス（一覧2項目×3画面・日本人選手2人）

    @classmethod
    def setUpClass(cls):
        import generate_asset_video as g
        cls.g = g
        cls.spec = g.LIST_TOPICS[cls.topic]
        cls.segs = g.build_narration(cls.topic)['segments']

    def seg_seconds(self, seg):
        return dict(seg, duration=max(6.0, len(seg['text']) * 0.14))

    def render(self, seg, t):
        return self.g.render_v3(t, seg['kind'], seg['meta'], self.spec, self.topic, seg=seg, dur=seg['duration'] + 1)

    def timeline(self, seg):
        import review_render_v3 as r3
        g = self.g
        if seg['kind'] == 'list':
            name, start, count = seg['meta']['topic'], seg['meta']['start'], seg['meta']['count']
            chunk = g.list_items(name)[start:start + count]
            plan = calm.plan_from_parts(seg['text'], [g._list_item_speech(self.spec, h, b) for h, b in chunk])
            heads = [h for h, _ in chunk]
        else:
            rows = self.spec['japanese'][:3]
            heads = [r['name'] for r in rows]
            plan = calm.plan_from_markers(seg['text'], heads)
        settle = r3.T_CARD0 + (len(heads) - 1) * r3.T_CARD_GAP + r3.SLIDE
        return calm.to_seconds(plan, seg['duration'], settle), heads

    def test_spoken_item_is_the_lifted_card(self):
        """読み上げている項目と、大きくなっている札が一致する（各区切りの真ん中で描いて確かめる）。"""
        with patch.dict(os.environ, ON):
            checked = 0
            for seg in self.segs:
                if seg['kind'] not in ('list', 'people'):
                    continue
                seg = self.seg_seconds(seg)
                tl, heads = self.timeline(seg)
                self.assertTrue(tl, seg['text'])
                errors = calm.check_sync(lambda t: self.render(seg, t), tl, len(heads), heads)
                self.assertEqual(errors, [], seg['text'])
                checked += len(tl)
            self.assertGreaterEqual(checked, 8)

    def test_lifted_card_stays_inside_safe_area_and_screen_does_not_move(self):
        import review_render_v3 as r3
        with patch.dict(os.environ, ON):
            seg = self.seg_seconds(next(s for s in self.segs if s['kind'] == 'list'))
            tl, _ = self.timeline(seg)
            a, b, idx = tl[0]
            im = self.render(seg, (a + b) / 2)
            box = im.info['v3_focus'][0]['box']
            self.assertGreaterEqual(box[0], 0)
            self.assertLessEqual(box[2], r3.SAFE_RIGHT)
            self.assertLessEqual(box[3], r3.CONTENT_BOTTOM)
            # 見出し（画面の上の文字）は、上がっている間も同じ場所
            heads = [e['box'] for e in im.info['v3_layout'] if e['role'] == 'header']
            still = self.render(seg, 0.05)
            self.assertEqual(heads, [e['box'] for e in still.info['v3_layout'] if e['role'] == 'header'])

    def test_off_draws_the_same_picture_as_today(self):
        with patch.dict(os.environ, OFF):
            for seg in self.segs:
                if seg['kind'] not in ('list', 'people'):
                    continue
                seg = self.seg_seconds(seg)
                for t in (0.2, 1.5, 4.0):
                    with_seg = self.g.render_v3(t, seg['kind'], seg['meta'], self.spec, self.topic, seg=seg, dur=8)
                    without = self.g.render_v3(t, seg['kind'], seg['meta'], self.spec, self.topic)
                    self.assertEqual(with_seg.tobytes(), without.tobytes())
                    self.assertNotIn('v3_focus', with_seg.info)


class ClubNameTest(unittest.TestCase):
    def test_aston_villa_uses_display_name(self):
        self.assertEqual(ne.club_name_jp('Aston Villa FC'), 'アストンヴィラ')
        self.assertEqual(ne.club_display_text('次の試合　ブライトン 対 アストン・ヴィラ'), '次の試合　ブライトン 対 アストンヴィラ')

    def test_soccer_preview_items_have_no_old_name(self):
        import generate_asset_video as g
        text = json.dumps(g.soccer_opening_items() + g.soccer_last_season_items(), ensure_ascii=False)
        self.assertNotIn('アストン・ヴィラ', text)

    def test_ticker_passes_the_table(self):
        import review_render_v3 as r3
        if not has_font():
            self.skipTest('日本語の書体が無い')
        from PIL import Image
        im = Image.new('RGB', (r3.W, r3.H))
        r3.ticker(im, 1.0, '次の試合　ブライトン 対 アストン・ヴィラ', once=True)
        self.assertEqual(r3.LAST_TICKER[0][0], '次の試合　ブライトン 対 アストンヴィラ')

    def test_display_table_file_is_the_one_place(self):
        """data/club_display_names.json があれば、それを通す（題・説明欄・帯・画面が同じ表）。"""
        from scripts import club_display_names as names
        import upload_youtube as up
        self.assertEqual(names.display('Manchester City FC'),'マンチェスターC')
        self.assertEqual(names.display('Paris Saint-Germain FC'),'パリ・サンジェルマン')
        self.assertEqual(ne.club_display_text('マンチェスター・シティ 対 アストン・ヴィラ'),
                         'マンチェスターC 対 アストンヴィラ')
        self.assertEqual(up.club_display_description('マンチェスター・シティの試合'),'マンチェスターCの試合')
        with patch.object(names,'text_pairs',return_value={'アストン・ヴィラ':'Aヴィラ'}):
            self.assertEqual(ne.club_display_text('アストン・ヴィラの試合'),'Aヴィラの試合')



if __name__ == '__main__':
    unittest.main(argv=[__file__])
