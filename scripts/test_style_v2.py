"""新しい見た目（COLLESPO_STYLE=v2、11/10 本人了承）の回帰。

切替は読み込み時に決まるので、別のプロセスで v2 を入れて保存済みのサッカー画面を全部描き、
本番と同じ画面の検査が0件か、色と字幕の帯が新しい見た目かを確かめる。既定（切替なし）は変わらないことも見る。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, os, sys
sys.path[:0] = [sys.argv[1] + '/scripts', sys.argv[1]]
os.environ.update(COLLESPO_SOCCER_LOOK='v5', COLLESPO_SHORT_LOOK='v4')
from preview_soccer_selected import saved_cases
cases = saved_cases()
os.environ.update(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4', COLLESPO_MOTION='on',
                  COLLESPO_SOLO_HOST='metan', COLLESPO_DUO='off')
import preview_soccer_readability as preview
import soccer_slots_v4 as slots, soccer_results_render as results, soccer_readable as layout
import soccer_v5_cards as c
out = dict(frames=0, errors=[], pixels=[], variants=set())
for case in cases:
    for seg in case['narration']['segments']:
        preview.caption(seg)
        im = slots.frame(3, seg, case['plan']) if case.get('plan') else results.frame(3, seg, case['data'], case['clubs'])
        if im.info.get('soccer_readable'):
            out['errors'] += [[case['key'], seg['kind'], str(e)[:200]] for e in layout.check_frame(im, case['clubs'])]
        out['frames'] += 1
        out['variants'].add((im.info.get('bubble_style') or {}).get('variant'))
        out['pixels'].append(list(im.convert('RGB').getpixel((540, 40))))
out['variants'] = sorted(v for v in out['variants'] if v)
# 動き：入り（0.07秒）・説明中（3秒）・抜け（終わりの0.05秒前）。字幕の帯とキャラの所は動かさない。
import review_render_v3 as r3
case = cases[0]; seg = case['narration']['segments'][1]
preview.caption(seg); d = r3._CAPTION['duration']
draw = (lambda t: slots.frame(t, seg, case['plan'])) if case.get('plan') else (lambda t: results.frame(t, seg, case['data'], case['clubs']))
shots = {k: draw(t) for k, t in (('enter', .07), ('still', 3), ('exit', d - .05))}
out['slide'] = {k: (im.info.get('v2_slide') or {}).get('phase') for k, im in shots.items()}
if c.STYLE_V2:
    # 同じ時刻で「動き無し」に描いた絵と、胸上の下端より下（字幕の帯・出典）が同じか。キャラ・字幕は動かない。
    box = (0, layout.PORTRAIT[3] + 4, 1080, 1920)
    slide = layout.Screen._slide_v2
    layout.Screen._slide_v2 = lambda self, body, duration: self.im
    still = {k: draw(t) for k, t in (('enter', .07), ('exit', d - .05))}
    layout.Screen._slide_v2 = slide
    out['caption_fixed'] = all(shots[k].convert('RGB').crop(box).tobytes() == still[k].convert('RGB').crop(box).tobytes() for k in still)
else:
    out['caption_fixed'] = None
out['lime'] = list(c.LIME); out['slant'] = c.SLANT
print(json.dumps(out))
'''


def probe(style):
    env = dict(os.environ, PYTHONUTF8='1')
    env.pop('COLLESPO_STYLE', None)
    if style:
        env['COLLESPO_STYLE'] = style
    run = subprocess.run([sys.executable, '-c', PROBE, str(ROOT)], env=env, capture_output=True, text=True,
                         encoding='utf-8', timeout=900)
    if run.returncode:
        raise AssertionError(run.stderr[-2000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class StyleV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = probe('v2')
        cls.default = probe(None)

    def test_all_saved_soccer_scenes_pass_the_production_checks(self):
        self.assertGreaterEqual(self.v2['frames'], 30)
        self.assertEqual(self.v2['errors'], [])

    def test_navy_ground_one_accent_and_dark_caption_bar(self):
        self.assertEqual(self.v2['lime'], [214, 250, 70])
        self.assertEqual(self.v2['slant'], 0.0)
        self.assertEqual(self.v2['variants'], ['dark'])
        for r, g, b in self.v2['pixels']:
            self.assertLess(r, 40)
            self.assertGreater(b, r)   # 地は濃紺（青が赤より強い）

    def test_only_the_middle_slides_in_and_out(self):
        # 右から入り、説明中は止まり、終わりに左へ抜ける。字幕の帯から下（キャラ・出典）は動かない。
        self.assertEqual(self.v2['slide'], dict(enter='enter', still=None, exit='exit'))
        self.assertTrue(self.v2['caption_fixed'])

    def test_default_look_is_unchanged_without_the_switch(self):
        self.assertEqual(self.default['lime'], [196, 244, 76])
        self.assertNotEqual(self.default['slant'], 0.0)
        self.assertEqual(self.default['errors'], [])
        self.assertNotIn('dark', self.default['variants'] or ['cream'])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
