"""10/25 run40169031031の4件と、所属・順位・勝敗の作り物。実APIなし。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sanity
import sanity_material as material
import sanity_sources as sources
import soccer_sanity_material as soccer

FIXTURE = json.loads((Path(__file__).parent/'fixtures/fact-guards/sanity_longform_20261025.json').read_text(encoding='utf-8'))


class AllMaterials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = Path.cwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old)
        self.day = '2026-10-25'
        self.rows = [dict(source='data/postseason.json', date_jst=self.day,
                         retrieved_at=FIXTURE['postseason']['updated_at'],
                         source_url='https://statsapi.mlb.com/api/v1/schedule',
                         series=FIXTURE['postseason']['series']),
                     dict(soccer.compact(FIXTURE['soccer']), sport='soccer')]

    def document(self, issue, **extra):
        text = issue['where']
        if 'イプスウィッチは' in text:
            text = '前田大然のイプスウィッチ。'+text
        return dict(date_jst=self.day, segments=[dict(text=text)],
                    sanity_materials=copy.deepcopy(self.rows), **extra)

    def run_sanity(self, doc, issues, kind='longform'):
        Path('narration.json').write_text(json.dumps(doc), encoding='utf-8')
        with patch.object(sys, 'argv', ['sanity', '--strict', '--general', '--kind', kind,
                '--narration', 'narration.json', '--out', 'report.json', '--hold-record', 'hold.json']), \
             patch.dict(os.environ, ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=''), \
             patch.object(sanity, 'general', return_value=issues):
            code = sanity.main()
        return code, json.loads(Path('report.json').read_text(encoding='utf-8'))

    def test_four_original_high_warn_for_every_kind(self):
        for kind in ('longform', 'daily', 'daily_soccer', 'morning_voices', 'morning_press',
                     'soccer_race', 'soccer_results', 'soccer_jp_week', 'weekly', 'asset'):
            for issue in FIXTURE['cases']:
                with self.subTest(kind=kind, where=issue['where']):
                    code, report = self.run_sanity(self.document(issue), [issue], kind)
                    self.assertEqual(code, 0)
                    self.assertFalse(report['blocking_issues'])
                    self.assertTrue(report['odd'][0]['supported'])
                    self.assertEqual(report['odd'][0]['severity'], 'high')
                    self.assertEqual(json.loads(Path('hold.json').read_text())['status'], 'passed')

    def test_wrong_affiliation_rank_points_boundary_and_series_stop_without_ai(self):
        for text in ('前田大然のセルティック。', '遠藤航のリバプール。4位で勝点12。',
                     '三笘薫のブライトン。3位で勝点15。',
                     '遠藤航のリバプール。5位で勝点12。チャンピオンズリーグ圏内まで勝点2。',
                     'ワールドシリーズはブリュワーズが0勝2敗でリード。'):
            with self.subTest(text=text):
                doc = self.document(dict(where=text))
                code, report = self.run_sanity(doc, [])
                self.assertEqual(code, 1)
                self.assertTrue(report['contradictions'])
                self.assertTrue(report['upload_held'])

    def test_real_thirty_separate_speaker_lines_do_not_hold(self):
        transcript = json.loads((Path(__file__).resolve().parent/
            'fixtures/fact-guards/sanity_longform_transcript_20261025.json').read_text(encoding='utf-8'))
        doc = self.document(FIXTURE['cases'][0])
        doc['segments'] = transcript['segments']
        code, report = self.run_sanity(doc, FIXTURE['cases'])
        self.assertEqual(code, 0, report['contradictions'])
        self.assertTrue(all(i['supported'] for i in report['odd']))

    def test_empty_material_high_is_warning_but_impossible_score_still_stops(self):
        for issue in FIXTURE['cases']:
            doc = self.document(issue)
            doc['sanity_materials'] = []
            code, report = self.run_sanity(doc, [dict(issue, supported=True, material_missing=False)])
            self.assertEqual(code, 0)
            self.assertEqual(report['material_status'][0]['status'], '材料が空')
            self.assertTrue(report['odd'][0]['material_missing'])
            self.assertFalse(report['odd'][0]['supported'])
            self.assertIn('材料不足', report['odd'][0]['verification'])
        doc['segments'] = [dict(text='防御率150。')]
        self.assertEqual(self.run_sanity(doc, [])[0], 1)

    def test_other_document_same_day_cannot_supply_an_exemption(self):
        issue = FIXTURE['cases'][0]
        a, b = self.document(issue), self.document(issue)
        b['sanity_materials'] = []
        b['kind'] = 'another'
        reviewed, errors = material.assess([issue], [b], material.grounding([a, b]))
        self.assertFalse(errors)
        self.assertFalse(reviewed[0]['supported'])
        self.assertTrue(reviewed[0]['material_missing'])

    def test_empty_containers_are_also_material_shortage(self):
        issue = FIXTURE['cases'][0]
        doc = self.document(issue)
        reviewed, _ = material.assess([issue], [doc], [dict(series=[], games=[], competitions=[])])
        self.assertTrue(reviewed[0]['material_missing'])
        self.assertFalse(material.blocking(reviewed[0]))

    def test_other_sport_material_does_not_hide_missing_ps_or_roster(self):
        for issue, rows in ((FIXTURE['cases'][0], self.rows[1:]),
                            (FIXTURE['cases'][2], self.rows[:1])):
            doc = self.document(issue)
            doc['sanity_materials'] = rows
            code, report = self.run_sanity(doc, [issue])
            self.assertEqual(code, 0)
            self.assertTrue(report['odd'][0]['material_missing'])
            self.assertIn('材料が空', report['material_status'][0]['categories'].values())

    def test_original_input_saved_with_timestamp_and_not_reloaded(self):
        doc = dict(date_jst=self.day, segments=[dict(text=FIXTURE['cases'][0]['where'])])
        doc['sanity_materials'] = sources.capture(doc, dict(date=self.day, _sanity_sources=self.rows))
        Path('data').mkdir()
        Path('data/postseason.json').write_text('{"date":"2026-10-25","series":[]}', encoding='utf-8')
        evidence = material.grounding([doc])
        self.assertEqual(evidence[0]['series'][0]['teams'][0]['wins'], 2)
        self.assertEqual(evidence[1]['retrieved_at'], FIXTURE['soccer']['updated_at'])
        self.assertEqual(evidence[1]['date_jst'], '2026-10-24')

    def test_actual_prompt_all_materials_and_current_fact_rule(self):
        doc = self.document(FIXTURE['cases'][0])
        Path('narration.json').write_text(json.dumps(doc), encoding='utf-8')
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')])
        with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
             patch('backstage_guard.create', return_value=response) as create, \
             patch.object(sanity.token_log, 'record'):
            sanity.general(['narration.json'], 'TEST')
        prompt = create.call_args.kwargs['messages'][0]['content']
        for expected in ('材料が今の事実', '学習した知識の所属・順位・結果で材料に反論しない',
                         'ブリュワーズ', '前田大然', 'イプスウィッチ', '三笘薫', '遠藤航',
                         FIXTURE['soccer']['updated_at'], '"diff": 4', '"wins": 2'):
            self.assertIn(expected, prompt)

    def test_iso_label_and_no_type_flag_still_receive_current_sources(self):
        Path('data').mkdir()
        Path('data/postseason.json').write_text(json.dumps(FIXTURE['postseason']), encoding='utf-8')
        soccer_data = dict(FIXTURE['soccer'], date_jst=self.day)
        Path('data/soccer_race.json').write_text(json.dumps(soccer_data), encoding='utf-8')
        doc = dict(label=self.day, segments=[dict(text='前田大然のイプスウィッチ。')])
        evidence = material.grounding([doc])
        self.assertTrue(any(s.get('series') for s in evidence))
        self.assertTrue(any(s.get('competitions') for s in evidence))
        self.assertEqual(material.document_day(doc), self.day)

    def test_compact_keeps_match_result_and_roster_used_by_other_soccer_types(self):
        game = dict(id='123', score=dict(home=2, away=1), players=[dict(name='選手')],
                    home=dict(name_jp='ホーム'), away=dict(name_jp='アウェー'))
        data = dict(date_jst=self.day, generated_at=self.day+'T06:00:00Z',
                    games=[game], rows=[dict(name='選手', club='クラブ', result='勝ち')])
        doc = sources.attach(dict(label=self.day, segments=[dict(text='結果です。')]), data, sport='soccer')
        evidence = material.grounding([doc])
        self.assertTrue(any(s.get('games') == [game] for s in evidence))
        self.assertTrue(any(s.get('rows') == data['rows'] for s in evidence))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
