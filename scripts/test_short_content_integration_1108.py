"""本線の共通締めと、型別の内容編集を同じ生成入口で確認する。通信なし。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]
import short_common
import generate_morning_short as morning
import daily_v3
import soccer_results_render as results
import soccer_slots_v4 as slots


class Integration(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, {
            'COLLESPO_SOCCER_LOOK': 'v6', 'COLLESPO_SOCCER_FOCUS': 'on',
            'COLLESPO_SHORT_LOOK': 'v4', 'COLLESPO_HOST_SPLIT': '',
            'COLLESPO_SOLO_HOST': 'metan', 'COLLESPO_COMMENTS_DESIGN': 'comments',
            'COLLESPO_PRESS_DESIGN': 'v3'})
        context.start()
        self.addCleanup(context.stop)

    def common_ending(self, document):
        endings = [s for s in document['segments'] if s['kind'] == 'outro']
        self.assertEqual(len(endings), 1)
        self.assertEqual(endings[0]['text'], short_common.OUTRO_TEXT)
        self.assertEqual(endings[0]['min_duration'], 2)
        self.assertTrue(endings[0]['meta']['short_outro'])
        self.assertFalse(any(s.get('meta', {}).get('continuation') for s in document['segments']))
        return endings[0]

    def test_results_and_race_keep_content_with_one_common_outro(self):
        data = json.loads((ROOT / 'scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf-8'))
        original = copy.deepcopy(data)
        document = results.production_narration(data)
        self.common_ending(document)
        self.assertEqual(document['segments'][0]['text'], '水多海斗、1アシスト。')
        self.assertTrue(document['opening_check']['passed'])
        self.assertIn('点差を縮めました', ''.join(s['text'] for s in document['segments']))
        self.assertEqual(data, original)
        from test_soccer_race_length import material
        plan = slots.race_program(material(28))
        self.common_ending(plan['narration'])
        table = plan['narration']['segments'][1]['meta']
        self.assertTrue(table['progressive_rows'])
        self.assertTrue(3 <= len(table['rows']) <= 4)
        self.assertIn(table['primary'], [r['team'] for r in table['rows']])

    def test_press_keeps_source_topics_and_common_outro_after_drawing_preparation(self):
        row = dict(jp='ピート・クロウ＝アームストロングが受賞。カブスの選手では2人目。',
                   uri='fixture:award', outlet='試験媒体', author='検査記者')
        data = dict(players=[], date_jst='2026-11-08', reporters=dict(posts=[row], headlines=[]))
        original = copy.deepcopy(data)
        document = morning.build_narration(data, 'press')
        self.assertTrue(document['opening_check']['passed'])
        self.assertTrue(document['source_topics'])
        ending = self.common_ending(document)
        daily_v3.prepare(data, document, 'press')
        self.common_ending(document)
        self.assertEqual(morning.plan_durations([dict(ending, duration=1.2)]), [2])
        self.assertEqual(data, original)

    def test_voices_keep_two_speakers_and_one_common_outro(self):
        fixture = json.loads((ROOT / 'scripts/fixtures/comment/voices-20261024.json').read_text(encoding='utf-8'))
        document = morning.build_narration(fixture['data'], 'voices')
        ending = self.common_ending(document)
        self.assertTrue(any(s.get('speaker') == 3 for s in document['segments']))
        daily_v3.prepare(fixture['data'], document, 'voices')
        self.common_ending(document)
        self.assertEqual(morning.plan_durations([dict(ending, duration=1.2)]), [2])

    def test_race_selects_the_leads_league_and_keeps_fallback_table_separate(self):
        import short_renewal
        from test_soccer_race_length import material
        first = material(28)
        later = copy.deepcopy(first['competitions'][0])
        later.update(code='PL', name_jp='プレミアリーグ')
        later['jp'][0]['name']='遠藤航'
        first['competitions'][0]['jp']=[]
        first['competitions'].append(later)
        first['picked'].append('PL')
        plan=slots.race_program(first)
        table=plan['narration']['segments'][1]
        self.assertTrue(table['meta']['title'].startswith('プレミアリーグ'))
        import soccer_race
        self.assertEqual(table['meta']['gap'],'は'+soccer_race.phrase(soccer_race.lead(first)[1]))
        self.assertEqual(plan['narration']['segments'][0]['meta']['opening_hook']['subject'],'遠藤航')
        first['competitions'][1]['jp']=[]
        plan=slots.race_program(first)
        cover,table=plan['narration']['segments'][:2]
        self.assertIsNot(cover,table)
        self.assertEqual((cover['kind'],table['kind']),('cover','standings'))
        self.assertNotIn('opening_hook',table['meta'])
        comp=first['competitions'][0];line=comp['lines'][0]
        boundary=[r for r in line['inside']+line['outside'] if r['position'] in (line['at'],line['at']+1)]
        self.assertEqual(cover['meta']['opening_hook']['value'],abs(boundary[0]['points']-boundary[1]['points']))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
