"""数字の札を縮めず、横棒と順位札で描く試験。通信・音声・公開なし。"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
import json
import re
import review_render_v3 as r3
import soccer_national_topics as topics
import soccer_national_topics_render as render

events = json.load(open('../data/mlb_market_followups.json', encoding='utf-8'))['events']
scenes = 0
problems = []
bars = []
ranks = []
sizes = []
for event in events:
    doc = topics.mlb_narration('followup-' + event)
    clubs = render.clubs_for(doc)
    for i, seg in enumerate(doc['segments'][:-1]):
        r3.set_caption(seg['text'], 5, 60, speaker=seg['speaker'])
        im = render.frame(1.5, seg, doc, clubs, i, len(doc['segments']))
        scenes += 1
        scale = im.info.get('short_cast_body_scale', 1.0)
        if scale != 1.0:
            problems.append([event, i, 'short_cast_body_scale', scale])
        errors = render.validate_frame(im, clubs, doc)
        if errors:
            problems.append([event, i, 'validate_frame', errors])
        rows = [list(row) for row in seg['meta']['rows'] if row[0] != '出典']
        if im.info.get('fact_bars'):
            bars.append([event, i, im.info.get('fact_bars_highlight'), rows])
        if im.info.get('fact_ranking'):
            ranks.append([event, i, im.info.get('fact_ranking_highlight'), rows])
        for entry in im.info.get('v3_layout', []):
            if entry['role'] not in ('supplement', 'national_fact'):
                continue
            box = entry['box']
            if box[1] < 390 or box[1] > 980:
                continue
            text = str(entry['text'])
            size = entry.get('v5_font') or (box[3] - box[1])
            if entry['role'] == 'supplement' and size < 36:
                problems.append([event, i, 'small_label', text, size])
            if entry['role'] == 'national_fact' and re.fullmatch(r'\d+(?:\.\d+)?', text) and size < 56:
                problems.append([event, i, 'small_value', text, size])
            sizes.append([entry['role'], text, size])
print(json.dumps(dict(scenes=scenes, problems=problems, bars=bars, ranks=ranks, sizes=sizes), ensure_ascii=False))
"""


class FactBars(unittest.TestCase):
    def probe(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith('COLLESPO_')}
        env.update(PYTHONUTF8='1', COLLESPO_STYLE='v2', COLLESPO_SOCCER_LOOK='v6',
                   COLLESPO_SOCCER_FOCUS='on', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan')
        result = subprocess.run([sys.executable, '-c', PROBE], cwd=str(ROOT / 'scripts'), env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_every_material_scene_keeps_full_size_and_passes_checks(self):
        report = self.probe()
        self.assertEqual(report['problems'], [])
        self.assertGreaterEqual(report['scenes'], 60)

    def test_yearly_counts_are_drawn_as_bars_and_highlight_the_last_year(self):
        report = self.probe()
        years = [row for event, _, _, row in report['bars']
                 if event == 'imanaga-hr-2026' and [r[1] for r in row] == ['27本', '31本', '35本']]
        self.assertTrue(years)
        self.assertEqual(years[0][0], ['2024年', '27本'])
        highlights = [h for event, _, h, _ in report['bars'] if event == 'imanaga-hr-2026']
        self.assertIn('2026年', highlights)

    def test_ranking_cards_highlight_the_main_player_without_the_big_card(self):
        report = self.probe()
        ranking = [row for event, _, _, row in report['ranks'] if event == 'imanaga-hr-2026']
        self.assertTrue(ranking)
        self.assertEqual([r[1] for r in ranking[0]], ['37本', '35本', '35本'])
        hero = [h for event, _, h, _ in report['ranks'] if event == 'imanaga-hr-2026']
        self.assertTrue(hero)
        self.assertTrue(any('今永昇太' in name for name in hero))
        self.assertTrue(any(size >= 88 for role, text, size in report['sizes'] if role == 'national_fact'
                            and re.fullmatch(r'\d+', text)))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
