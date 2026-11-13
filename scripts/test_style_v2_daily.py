"""毎日の注目試合（generate_video）と週間まとめ（generate_weekly）の新しい見た目（v2）の回帰。

切替は読み込み時に決まるので、別のプロセスで描く。
v2 では橙・緑・斜線の地が無く、紺の地に黄1色だけ。切替なしでは従来の橙の絵のまま。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, sys
sys.path[:0] = [sys.argv[1] + '/scripts', sys.argv[1]]
import generate_video as dv
import generate_weekly as wk
meta = {"hook": {"big": "山本由伸が8奪三振", "sub_jp": "ドジャース"},
        "top_game": {"matchup": "ドジャース 対 パドレス", "time": "明日 8:00", "series": "3連戦の2戦目"},
        "base": {"games": 12}}
verdict = {"decided": 5, "home_wins": 3, "away_wins": 2, "draws": 0, "one_run": 2, "shutouts": 1,
           "top_game": {"home": 9, "away": 7, "abbr": "LAD"},
           "streaks": [{"team": "ドジャース", "n": 4, "kind": "連勝", "result": "勝ち 5-3", "won": True},
                       {"team": "パドレス", "n": 3, "kind": "連敗", "result": "負け 2-4", "won": False}]}
frames = {
    "daily_intro": dv.render_intro(1, "10月14日", meta),
    "daily_recap": dv.render_recap(1, meta),
    "weekly_intro": wk.render_intro(1, "保存材料の週次まとめ"),

    "weekly_verdict": wk.render_verdict(1, verdict),
}
out = {}
for k, im in frames.items():
    if im is None:
        continue
    px = im.convert("RGB")
    w, h = px.size
    n = orange = green = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            r, g, b = px.getpixel((x, y))
            n += 1
            if r > 200 and 110 < g < 215 and b < 100 and r > g + 35:
                orange += 1
            if g > r + 25 and g > b + 25 and r < 170 and b > g * 0.6:
                green += 1
    out[k] = dict(n=n, orange=orange, green=green, corner=list(px.getpixel((5, 5))))
print(json.dumps(out))
'''


def probe(v2):
    env = {k: v for k, v in os.environ.items() if not k.startswith('COLLESPO')}
    env['PYTHONUTF8'] = '1'
    if v2:
        env['COLLESPO_STYLE'] = 'v2'
    r = subprocess.run([sys.executable, '-I', '-c', PROBE, str(ROOT)], env=env, capture_output=True,
                       text=True, encoding='utf-8', cwd=str(ROOT))
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class DailyWeeklyV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = probe(True)
        cls.v1 = probe(False)

    def test_v2_has_no_orange_or_green(self):
        for k, s in self.v2.items():
            self.assertLess(s['orange'] / s['n'], 0.0005, (k, s))
            self.assertLess(s['green'] / s['n'], 0.0005, (k, s))

    def test_v2_background_is_navy_not_old_dark(self):
        for k, s in self.v2.items():
            r, g, b = s['corner']
            self.assertGreater(b, r + 8, (k, s))
            self.assertNotEqual((r, g, b), (11, 14, 20), (k, s))

    def test_default_is_unchanged_orange(self):
        for k, s in self.v1.items():
            self.assertIn(s["corner"], ([11, 14, 20], [14, 18, 26]), (k, s))
            self.assertGreater(s['orange'], 0, (k, s))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
