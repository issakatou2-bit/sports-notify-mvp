"""長編の新しい見た目（COLLESPO_STYLE=v2）の回帰。代表長編の全部の札を描き、形と動きを確かめる。

切替は読み込み時に決まるので、別のプロセスで v2 を入れて描く。切替なしでは今の長編のままであることも見る。
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
os.environ['COLLESPO_SAMPLE_ONLY'] = 'true'
import soccer_national_long as long, render_soccer_national_long as rl
import longform_render_v3 as v3
from test_soccer_national_numbers import fixture_sheet, AS_OF
doc = long.dialogue(long.material('brazil', AS_OF, fixture_sheet()))
rl.prepare(doc)
out = dict(panels={}, entering={}, pixels={})
for key, panel in doc['panels'].items():
    seg = next(s for s in doc['segments'] if s['panel'] == key)
    page = v3.paginate([seg])[0]
    still = v3.render_line(8, page, topic=doc['top'], panel=panel, panel_t=8, chapters=doc['chapters'], dur=10)
    first = v3.render_line(0.05, page, topic=doc['top'], panel=panel, panel_t=0.05, chapters=doc['chapters'], dur=10)
    out['panels'][key] = (still.info.get('longform_v2') or {}).get('layout')
    out['entering'][key] = (first.info.get('longform_v2') or {}).get('entering')
    # 札の中（左上寄り）が入りの途中で still と違うか＝動いたか。
    box = (80, 100, 1440, 850)
    out['pixels'][key] = first.crop(box).tobytes() != still.crop(box).tobytes()
print(json.dumps(out, ensure_ascii=False))
'''


def probe(style):
    env = {k: v for k, v in os.environ.items() if not k.startswith('COLLESPO')}
    env.update(PYTHONUTF8='1')
    if style:
        env['COLLESPO_STYLE'] = style
    run = subprocess.run([sys.executable, '-c', PROBE, str(ROOT)], capture_output=True, text=True,
                         encoding='utf-8', env=env, timeout=600)
    if run.returncode:
        raise AssertionError(run.stderr[-3000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class LongformV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = probe('v2')

    def test_every_national_panel_has_its_number_layout(self):
        layouts = self.v2['panels']
        self.assertTrue(layouts)
        self.assertEqual(layouts['opening'], 'opening')
        self.assertEqual(layouts['focus_intro'], 'players')
        self.assertEqual(layouts['history'], 'matches')
        self.assertEqual(layouts['kickoff'], 'kickoff')
        for key, layout in layouts.items():
            if key.startswith('position_'):
                self.assertEqual(layout, 'roster', key)
            elif key.startswith('focus_') and key != 'focus_intro':
                self.assertEqual(layout, 'player', key)

    def test_card_slides_in_once_per_position_and_otherwise_stays(self):
        for key, moved in self.v2['pixels'].items():
            # 同じ位置の2枚目以降は名札一覧が同じなので、光る選手だけ変えて札は動かさない。
            later = key.startswith('position_') and not key.endswith('_0')
            with self.subTest(key=key):
                self.assertEqual(moved, not later)
                self.assertEqual(self.v2['entering'][key], True)

    def test_default_long_form_is_unchanged_without_the_switch(self):
        plain = probe(None)
        self.assertTrue(all(layout is None for layout in plain['panels'].values()))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
