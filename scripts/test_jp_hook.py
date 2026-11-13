"""日本人選手の数字の回の1枚目：v3の大きな数字が材料と一致、v2で大きく描く、題の頭の【】。外部通信なし。"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import jp_stock as jp

TAGS = {'best': '今季最高', 'month': '月別の成績', 'vs': '相手別の成績', 'home': '本拠地と敵地', 'daynight': '昼と夜',
        'half': '前半と後半', 'streak': '連続記録', 'compare': '2人を比べる'}

PROBE = r'''
import json, sys
from pathlib import Path
from unittest.mock import patch
root = Path(sys.argv[1])
sys.path[:0] = [str(root/'scripts'), str(root)]
import jp_stock as jp, generate_asset_video as asset, review_render_v3 as r3, v3_rules as rules
topics = jp.build()['topics']
asset.VOICE_CREDIT = 'x'
def frame(spec):
    key = spec['key']
    with patch.dict(asset.LIST_TOPICS, {key: spec}):
        nar = asset.build_narration(key)
    seg = nar['segments'][0]
    r3.set_program_clock(0); r3.set_caption(seg['text'], 40, 40*len(nar['segments']))
    with patch.dict(asset.LIST_TOPICS, {key: spec}):
        return asset.render_v3(1.0, seg['kind'], seg['meta'], spec, key, seg=seg, dur=40)
out = []
for kind in ('streak', 'win', 'month', 'compare'):
    spec = next(t for t in topics if t['stock_kind'] == kind)
    im = frame(spec)
    plain = dict(spec, v3={k: v for k, v in spec['v3'].items() if k in ('source',)})
    out.append(dict(kind=kind, hook=(im.info.get('asset_v4') or {}).get('v2_hook'), errors=[str(e) for e in rules.check_layout(im)+rules.check_spacing(im)] if r3.STYLE_V2 else [],
                    big_box=[e['box'] for e in im.info['v3_layout'] if e['role'] == 'number'],
                    same_as_plain=im.convert('RGB').tobytes() == frame(plain).convert('RGB').tobytes()))
print(json.dumps(out))
'''


def probe(style):
    env = dict(os.environ, PYTHONUTF8='1', COLLESPO_SHORT_LOOK='v4')
    env.pop('COLLESPO_STYLE', None)
    if style:
        env['COLLESPO_STYLE'] = style
    run = subprocess.run([sys.executable, '-c', PROBE, str(ROOT)], env=env, capture_output=True, text=True,
                         encoding='utf-8', timeout=900)
    if run.returncode:
        raise AssertionError(run.stderr[-2000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class HookData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topics = jp.build()['topics']

    def test_big_matches_material(self):
        for t in self.topics:
            v = t['v3']
            self.assertRegex(v['big'], r'^[\d./\-]+$', t['key'])
            self.assertTrue(v['who'] and v['sub'], t['key'])
            self.assertLessEqual(len(v['chips']), 3)
            for chip in v['chips']:
                self.assertRegex(chip['score'], r'^[\d./\-]+$')
                self.assertTrue(chip['label'])
            text = ' '.join([t['title'], t['intro'], *[b for _, b in t['items']]])
            # 大きな数字は題・説明・項目のどこかにある数字（作らない）。2人比べの「A/B」は両方が材料にある。
            for part in re.split('/', v['big']):
                self.assertIn(part, text, (t['key'], v['big']))
            if t['stock_kind'] == 'streak':
                self.assertEqual(v['big'], str(t['streak_length']))
            if t['stock_kind'] == 'win':
                self.assertIn(f"{v['big']}勝", t['title'])
            self.assertIn('source', v)

    def test_title_starts_with_specific_bracket(self):
        for t in self.topics:
            m = re.match(r'【([^】]+)】', t['title'])
            self.assertTrue(m, t['title'])
            kind = t['stock_kind']
            want = ('本塁打と勝敗' if t['comparison_group'] == 'hitting' else '先発と勝敗') if kind == 'win' else TAGS.get(kind)
            if kind == 'vs':
                want = '相手別の成績'
            self.assertEqual(m[1], want, t['title'])
            self.assertLessEqual(len(t['title']), 100)
            self.assertFalse(re.search(r'衝撃|緊急|まさか', t['title']))
            self.assertFalse(jp.expression_errors(t))


class HookRender(unittest.TestCase):
    def test_v2_draws_big_name_and_number(self):
        for row in probe('v2'):
            hook = row['hook']
            self.assertIsNotNone(hook, row['kind'])
            self.assertGreaterEqual(hook['who_size'], 72)
            self.assertGreaterEqual(hook['big_size'], 200)
            self.assertEqual(row['errors'], [], row['kind'])
            x0, y0, x1, y1 = row['big_box'][0]
            self.assertGreaterEqual(y1-y0, 160)
            self.assertLessEqual(y1, 1020)

    def test_without_v2_the_picture_is_unchanged(self):
        for row in probe(None):
            self.assertTrue(row['same_as_plain'], row['kind'])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
