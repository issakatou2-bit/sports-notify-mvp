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
        data['short_content_version'] = '1108'
        original = copy.deepcopy(data)
        document = results.production_narration(data)
        self.common_ending(document)
        self.assertEqual(document['segments'][0]['text'], '水多海斗、1アシスト。')
        self.assertTrue(document['opening_check']['passed'])
        self.assertIn('点差を縮めました', ''.join(s['text'] for s in document['segments']))
        self.assertEqual(data, original)
        from test_soccer_race_length import material
        plan = slots.race_program(dict(material(28),short_content_version='1108'))
        self.common_ending(plan['narration'])
        table = plan['narration']['segments'][1]['meta']
        self.assertTrue(table['progressive_rows'])
        self.assertTrue(3 <= len(table['rows']) <= 4)
        self.assertIn(table['primary'], [r['team'] for r in table['rows']])
        self.assertIn('5位と6位',table['leading_text'])
        for row,text in zip(table['rows'],table['row_texts']):
            if row.get('played') is None:
                self.assertNotIn('試合',text)
            else:
                self.assertIn(str(row['played'])+'試合',text)
        self.assertEqual(sum('勝点5差' in seg['text'] for seg in plan['narration']['segments']),1)

    def test_press_keeps_source_topics_and_common_outro_after_drawing_preparation(self):
        row = dict(jp='ピート・クロウ＝アームストロングが受賞。カブスの選手では2人目。',
                   uri='fixture:award', outlet='試験媒体', author='検査記者')
        data = dict(players=[], date_jst='2026-11-08', reporters=dict(posts=[row], headlines=[],short_content_version='1108'))
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
        fixture['data']['voices']['short_content_version'] = '1108'
        document = morning.build_narration(fixture['data'], 'voices')
        ending = self.common_ending(document)
        self.assertTrue(any(s.get('speaker') == 3 for s in document['segments']))
        daily_v3.prepare(fixture['data'], document, 'voices')
        self.common_ending(document)
        self.assertEqual(morning.plan_durations([dict(ending, duration=1.2)]), [2])

    def test_race_selects_the_leads_league_and_keeps_fallback_table_separate(self):
        import short_renewal
        from test_soccer_race_length import material
        first = dict(material(28),short_content_version='1108')
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
        self.assertEqual(table['meta']['lines'][0][0],soccer_race.lead(first)[1]['line'])
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

    def test_new_common_outro_uses_its_existing_length_gate(self):
        import soccer_minimum
        from test_soccer_race_length import material
        data = dict(material(28), short_content_version='1108')
        document = slots.race_program(data)['narration']
        self.assertEqual(soccer_minimum.target_seconds(document), 19)
        audio = [dict(seg, duration=20/len(document['segments'])) for seg in document['segments']]
        with patch.object(soccer_minimum, 'candidates') as unused:
            _, _, skip = soccer_minimum.fit('race', data, document, audio, '.',
                measure=lambda mode, data, narr, voices: [row['duration'] for row in voices])
        self.assertFalse(skip)
        unused.assert_not_called()
        for row in audio:
            row['duration'] = 18/len(audio)
        with patch.object(soccer_minimum, 'candidates', return_value=[]):
            self.assertTrue(soccer_minimum.fit('race', data, document, audio, '.',
                measure=lambda mode, data, narr, voices: [row['duration'] for row in voices])[2])

    def test_explicit_empty_saved_squad_does_not_use_todays_roster(self):
        data = json.loads((ROOT/'scripts/fixtures/soccer-slots/preview.json').read_text(encoding='utf-8'))
        original = copy.deepcopy(data)
        with patch('notability_engine.jp_players_for_club', return_value=[dict(name_jp='現在の名簿の選手')]):
            document = slots.preview_program(data)['narration']
        first = next(seg for seg in document['segments'] if seg['kind']=='preview')
        self.assertEqual(first['meta']['jp']['away'], [])
        self.assertEqual(data, original)

    def test_normal_results_cli_marks_new_material_and_legacy_input_stays_readable(self):
        import tempfile
        import soccer_results
        import soccer_result_followup
        folder = ROOT/'scripts/fixtures/soccer-results'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'material.json'
            arguments = ['results','--date','2026-09-20','--scoreboards',str(folder/'scoreboards.json'),
                         '--summaries',str(folder/'summaries.json'),'--out',str(output)]
            with patch.object(sys,'argv',arguments), patch.object(soccer_result_followup,'load_preview',return_value=None):
                soccer_results.main()
            material = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(material['short_content_version'],'1108')
        soccer_results.validate_data(material)
        self.assertTrue(results.production_narration(material)['opening_check']['passed'])
        legacy = json.loads((folder/'run-40249272204.json').read_text(encoding='utf-8'))
        self.assertNotIn('opening_check',results.production_narration(legacy))
        legacy['selection_policy']='japanese_goal_or_assist'
        self.assertTrue(results.production_narration(legacy)['opening_check']['passed'])

    def test_voices_collection_cli_serializes_the_new_material_version(self):
        import tempfile
        import local_voices
        fixture = json.loads((ROOT/'scripts/fixtures/comment/voices-20261024.json').read_text(encoding='utf-8'))
        material = copy.deepcopy(fixture['data']['voices'])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'voices.json'
            with patch.object(sys,'argv',['voices','--out',str(output)]), patch.object(local_voices,'build',return_value=material):
                local_voices.main()
            collected = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(collected['short_content_version'],'1108')
        document = morning.build_narration(dict(fixture['data'],voices=collected),'voices')
        self.assertEqual(document['short_content_version'],'1108')
        self.assertTrue(any(seg.get('speaker')==3 for seg in document['segments']))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
