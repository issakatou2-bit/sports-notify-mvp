"""10/23のWS第1戦を保存材料と固定応答で検査。実API・投稿は呼ばない。"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sanity
import sanity_material
import verify_published

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'scripts/fixtures/fact-guards/sanity_ws_20261023.json').read_text(encoding='utf-8'))
EVENING = json.loads((ROOT / 'scripts/fixtures/fact-guards/sanity_evening_20261024.json').read_text(encoding='utf-8'))


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.old)
        Path('data').mkdir()
        Path('data/postseason.json').write_text(json.dumps(FIXTURE['postseason']), encoding='utf-8')
        self.document = dict(date_jst='2026-10-24', segments=[dict(text=FIXTURE['text'])])
        self.env = patch.dict(os.environ, dict(ANTHROPIC_API_KEY='TEST', GITHUB_RUN_ID='123',
                                             GITHUB_RUN_ATTEMPT='2', GITHUB_STEP_SUMMARY='summary.md'))
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_sanity(self, text=None, issues=None, kind='daily'):
        document = copy.deepcopy(self.document)
        document['segments'][0]['text'] = text or FIXTURE['text']
        Path('narration.json').write_text(json.dumps(document), encoding='utf-8')
        args = ['sanity.py', '--general', '--strict', '--narration', 'narration.json',
                '--out', 'data/sanity.json', '--hold-record', 'build/sanity_hold.json', '--kind', kind]
        with patch.object(sys, 'argv', args), \
             patch.object(sanity, 'general', return_value=issues if issues is not None else [FIXTURE['issue']]):
            code = sanity.main()
        return code, json.loads(Path('data/sanity.json').read_text(encoding='utf-8'))

    def test_evening_three_fixed_findings_warn_without_holding(self):
        Path('data/postseason.json').write_text(json.dumps(EVENING['postseason']), encoding='utf-8')
        for issue in EVENING['cases']:
            with self.subTest(mode=issue['mode'], text=issue['where']):
                # 本番voices/pressと同じく、トップレベルdate_jstはない。
                self.document = dict(segments=[dict(text=issue['where'], meta=dict(date='2026-10-24'))])
                code, report = self.run_sanity(issue['where'], [issue], kind='morning_' + issue['mode'])
                self.assertEqual(code, 0)
                self.assertFalse(report['blocking_issues'])
                self.assertFalse(report['upload_held'])
                self.assertIn(report['odd'][0], report['warnings'])
                self.assertEqual(report['odd'][0]['severity'], 'high')
                self.assertEqual(report['odd'][0]['kind'], sanity_material.CONTEXT)
                source = report['materials'][0]
                ws = source['series'][0]
                self.assertEqual(ws['round'], 'W')
                self.assertEqual(ws['played'], 1)
                self.assertEqual(ws['teams'][0]['wins'], 1)
                self.assertEqual(ws['next'], dict(day='10月25日', game=2))
                self.assertIn('statsapi.mlb.com', source['source_url'])
                self.assertEqual(source['retrieved_at'], EVENING['postseason']['updated_at'])
                self.assertEqual(report['date_jst'], '2026-10-24')
                self.assertEqual(json.loads(Path('build/sanity_hold.json').read_text())['status'], 'passed')
                self.assertIn('説明不足・文脈', Path('summary.md').read_text(encoding='utf-8'))

    def test_admitted_valid_claim_is_not_a_factual_error(self):
        issue = dict(EVENING['cases'][0], kind=sanity_material.FACT)
        code, report = self.run_sanity(issue['where'], [issue])
        self.assertEqual(code, 0)
        self.assertEqual(report['odd'][0]['kind'], sanity_material.CONTEXT)

    def test_context_findings_never_hold_at_any_severity(self):
        for severity in ('high', 'low'):
            issue = dict(EVENING['cases'][1], severity=severity)
            self.assertEqual(self.run_sanity(issue['where'], [issue])[0], 0)

    def test_negated_or_questioned_validity_does_not_release_factual_high(self):
        for why in ('この主張が成立するとは言えない。', '所属の誤りではないか。'):
            issue = dict(kind=sanity_material.FACT, severity='high', where='架空太郎はレイズ所属です。', why=why)
            self.assertEqual(self.run_sanity(issue['where'], [issue])[0], 1)

    def test_invented_score_and_affiliation_factual_high_hold(self):
        for text, why in (
            ('レイズはブリュワーズに3対2で勝ちました。', '公式材料はレイズ2対3ブリュワーズで、勝敗と得点が逆です。'),
            ('ジェイコブ・ミジオロウスキーはレイズの投手です。', '材料の所属はブリュワーズで、レイズという主張は誤りです。'),
        ):
            issue = dict(kind=sanity_material.FACT, severity='high', where=text, why=why)
            code, report = self.run_sanity(text, [issue])
            self.assertEqual(code, 1)
            self.assertTrue(report['upload_held'])
            self.assertEqual(report['blocking_issues'][0]['kind'], sanity_material.FACT)
            self.assertEqual(json.loads(Path('build/sanity_hold.json').read_text())['status'], 'held')

    def test_context_cannot_release_another_factual_high_or_material_ng(self):
        context = EVENING['cases'][0]
        fact = dict(kind=sanity_material.FACT, severity='high', where='架空太郎はレイズ所属です。', why='材料の所属と異なる')
        code, report = self.run_sanity(context['where'] + fact['where'], [context, fact])
        self.assertEqual(code, 1)
        self.assertEqual(report['blocking_issues'], [report['odd'][1]])
        text = FIXTURE['text'].replace('ワールドシリーズ', '地区シリーズ')
        code, report = self.run_sanity(text, [dict(context, where=text)])
        self.assertEqual(code, 1)
        self.assertTrue(report['contradictions'])

    def test_voices_and_press_real_prompt_get_official_ws_material(self):
        Path('data/postseason.json').write_text(json.dumps(EVENING['postseason']), encoding='utf-8')
        for mode in ('voices', 'press'):
            document = dict(segments=[dict(text='第1戦の話です。', meta=dict(date='2026-10-24'))])
            Path('narration.json').write_text(json.dumps(document), encoding='utf-8')
            response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')])
            with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
                 patch('backstage_guard.create', return_value=response) as create, \
                 patch.object(sanity.token_log, 'record'):
                self.assertEqual(sanity.general(['narration.json'], 'TEST'), [])
            prompt = create.call_args.kwargs['messages'][0]['content']
            for expected in ('"kind"', '事実の誤り', '説明不足・文脈', '成立する', 'NLCS',
                             'ワールドシリーズ', 'ブリュワーズ', 'レイズ', '10月25日',
                             '"played": 1', 'statsapi.mlb.com', EVENING['postseason']['updated_at']):
                self.assertIn(expected, prompt, mode)

    def test_missing_kind_is_recorded_as_invalid_response_warning(self):
        Path('narration.json').write_text(json.dumps(self.document), encoding='utf-8')
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text=json.dumps([dict(severity='high')]))])
        with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
             patch('backstage_guard.create', return_value=response), patch.object(sanity.token_log, 'record'):
            issues = sanity.general(['narration.json'], 'TEST')
        self.assertIn('必須のkind', issues[0]['why'])
        self.assertEqual(issues[0]['kind'], sanity_material.CONTEXT)

    def verify(self, **changes):
        if changes:
            p = Path('build/sanity_hold.json')
            hold = json.loads(p.read_text(encoding='utf-8'))
            hold.update(changes)
            p.write_text(json.dumps(hold), encoding='utf-8')
        with patch.object(sys, 'argv', ['verify_published.py', '--kind', 'daily',
                                       '--hold-record', 'build/sanity_hold.json']), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            code = verify_published.main()
        return code, output.getvalue()

    def test_saved_ws_claim_warns_and_allows_upload(self):
        code, report = self.run_sanity()
        self.assertEqual(code, 0)
        self.assertFalse(report['upload_held'])
        self.assertFalse(report['blocking_issues'])
        self.assertFalse(report['contradictions'])
        self.assertFalse(report['unconfirmed_issues'])
        self.assertEqual(report['odd'][0]['severity'], 'high')
        self.assertFalse(report['odd'][0]['confirmed'])
        self.assertTrue(report['odd'][0]['supported'])
        self.assertEqual(report['odd'][0]['verification'], '材料で裏付け済み（誤検出）')
        self.assertIn('材料で裏付け済み（誤検出）', Path('summary.md').read_text(encoding='utf-8'))
        self.assertEqual(report['materials'][0]['retrieved_at'], FIXTURE['postseason']['updated_at'])
        self.assertEqual(json.loads(Path('build/sanity_hold.json').read_text())['status'], 'passed')

    def test_real_prompt_contains_official_material_and_timestamp(self):
        Path('narration.json').write_text(json.dumps(self.document), encoding='utf-8')
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')])
        with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
             patch('backstage_guard.create', return_value=response) as create, \
             patch.object(sanity.token_log, 'record'):
            self.assertEqual(sanity.general(['narration.json'], 'TEST'), [])
        prompt = create.call_args.kwargs['messages'][0]['content']
        for expected in (FIXTURE['text'], 'ワールドシリーズ', 'レイズ', 'ブリュワーズ',
                         FIXTURE['postseason']['updated_at'], 'statsapi.mlb.com',
                         '本文に書かれていない'):
            self.assertIn(expected, prompt)

    def test_embedded_program_keeps_its_source_and_retrieval_time(self):
        self.document['ps_program'] = dict(date_jst='2026-10-23',
            retrieved_at='2026-10-23T18:01:00+09:00', source_url='https://statsapi.mlb.com/api/v1/schedule?season=2026',
            series=FIXTURE['postseason']['series'])
        source = sanity_material.grounding([self.document])[0]
        self.assertEqual(source['retrieved_at'], '2026-10-23T18:01:00+09:00')
        self.assertEqual(source['source_url'], self.document['ps_program']['source_url'])

    def test_missing_or_old_material_does_not_turn_high_into_a_fact(self):
        self.document['date_jst'] = '2026-11-01'
        self.assertEqual(sanity_material.grounding([self.document]), [])
        Path('data/postseason.json').write_text('invalid', encoding='utf-8')
        code, report = self.run_sanity()
        self.assertEqual(code, 1)
        self.assertFalse(report['materials'])
        self.assertTrue(report['blocking_issues'])

    def test_invented_stat_high_stops_and_verify_records_the_reason(self):
        text = '架空太郎は今季55本塁打です。'
        issue = dict(severity='high', where=text, why='作り物の成績に誤りがある')
        code, report = self.run_sanity(text, [issue])
        self.assertEqual(code, 1)
        self.assertFalse(report['impossible'])
        self.assertFalse(report['contradictions'])
        self.assertFalse(report['blocking_issues'][0]['confirmed'])
        self.assertFalse(report['blocking_issues'][0]['supported'])
        verify_code, output = self.verify()
        self.assertEqual(verify_code, 1)
        self.assertIn('常識点検による保留・アップロード未実行', output)
        self.assertIn(issue['why'], output)

    def test_partial_match_unknown_name_or_date_does_not_exempt_high(self):
        for text in (FIXTURE['text'] + 'で、架空太郎は今季55本塁打です。',
                     FIXTURE['text'].replace('レイズ', '架空球団'),
                     '10月23日の' + FIXTURE['text'],
                     '昨年の' + FIXTURE['text'],
                     '『' + FIXTURE['text'] + '』は誤りです。'):
            with self.subTest(text=text):
                code, report = self.run_sanity(text, [dict(FIXTURE['issue'], where=text)])
                self.assertEqual(code, 1)
                self.assertFalse(report['odd'][0]['supported'])

    def test_matching_date_and_reverse_pair_can_be_supported(self):
        text = '10月24日のレイズ対ブリュワーズはワールドシリーズ第1戦です。'
        code, report = self.run_sanity(text, [dict(FIXTURE['issue'], where=text)])
        self.assertEqual(code, 0)
        self.assertTrue(report['odd'][0]['supported'])

    def test_game_number_date_and_material_completeness_are_required(self):
        for changes in (dict(game=2), dict(day='10月25日'), dict(game=None), dict(day=None)):
            with self.subTest(changes=changes):
                snapshot = copy.deepcopy(FIXTURE['postseason'])
                snapshot['series'][0]['next'].update(changes)
                Path('data/postseason.json').write_text(json.dumps(snapshot), encoding='utf-8')
                code, report = self.run_sanity()
                self.assertEqual(code, 1)
                self.assertFalse(report['odd'][0]['supported'])

    def test_model_cannot_supply_its_own_exemption_or_quote_outside_the_script(self):
        code, report = self.run_sanity('架空太郎は今季55本塁打です。',
            [dict(FIXTURE['issue'], supported=True, confirmed=False,
                  verification='材料で裏付け済み（誤検出）')])
        self.assertEqual(code, 1)
        self.assertFalse(report['odd'][0]['supported'])

    def test_supported_quote_cannot_release_another_high(self):
        text = FIXTURE['text'] + '。架空太郎は今季55本塁打です。'
        issues = [FIXTURE['issue'], dict(severity='high', where='架空太郎は今季55本塁打',
                                        why='作り物の成績')]
        code, report = self.run_sanity(text, issues)
        self.assertEqual(code, 1)
        self.assertTrue(report['odd'][0]['supported'])
        self.assertEqual(len(report['blocking_issues']), 1)
        self.assertEqual(report['blocking_issues'][0]['why'], issues[1]['why'])

    def test_partial_quote_cannot_hide_negation_past_or_unverified_facts(self):
        for text in ('昨年の' + FIXTURE['text'],
                     '『' + FIXTURE['text'] + '』は誤りです。',
                     FIXTURE['text'] + 'で、架空太郎は55本塁打です。'):
            with self.subTest(text=text):
                code, report = self.run_sanity(text)
                self.assertEqual(code, 1)
                self.assertFalse(report['odd'][0]['supported'])

    def test_conflicting_material_cannot_support_claim(self):
        self.document['ps_program'] = dict(date_jst='2026-10-24',
            series=copy.deepcopy(FIXTURE['postseason']['series']))
        self.document['ps_program']['series'][0]['next']['game'] = 2
        code, report = self.run_sanity()
        self.assertEqual(code, 1)
        self.assertFalse(report['odd'][0]['supported'])

    def test_confirmed_round_mismatch_stops_and_verify_explains_hold(self):
        text = FIXTURE['text'].replace('ワールドシリーズ', '地区シリーズ')
        issue = dict(FIXTURE['issue'], where=text, why='シリーズ名が材料と異なる')
        code, report = self.run_sanity(text, [issue])
        self.assertEqual(code, 1)
        self.assertTrue(report['blocking_issues'][0]['confirmed'])
        self.assertTrue(report['contradictions'])
        self.assertFalse(Path('build/narration_skipped.txt').exists())
        verify_code, output = self.verify()
        self.assertEqual(verify_code, 1)
        self.assertIn('常識点検による保留・アップロード未実行', output)
        self.assertIn('シリーズ名が材料と不一致', output)
        self.assertIn('動画の保留', Path('summary.md').read_text(encoding='utf-8'))

    def test_impossible_number_and_material_ng_stop_without_ai(self):
        for text in ('打率1.5です。', FIXTURE['text'].replace('ワールドシリーズ', '地区シリーズ')):
            code, report = self.run_sanity(text, [])
            self.assertEqual(code, 1)
            self.assertTrue(report['impossible'] or report['contradictions'])

    def test_scoped_verification_does_not_confirm_unrelated_or_model_supplied_claim(self):
        text = FIXTURE['text'].replace('ワールドシリーズ', '地区シリーズ')
        self.document['segments'].append(dict(text=text))
        materials = sanity_material.grounding([self.document])
        reviewed, errors = sanity_material.assess([dict(FIXTURE['issue'], confirmed=True)], [self.document], materials)
        self.assertTrue(errors)
        self.assertFalse(reviewed[0]['confirmed'])

    def test_other_round_in_same_sentence_or_negation_is_not_a_contradiction(self):
        for text in ('地区シリーズを勝ち抜き、' + FIXTURE['text'],
                     'ブリュワーズ対レイズは地区シリーズではなくワールドシリーズ第1戦',
                     '昨年のブリュワーズ対レイズは地区シリーズでした。'):
            self.document['segments'] = [dict(text=text)]
            self.assertFalse(sanity_material.check(self.document, sanity_material.grounding([self.document])))

    def test_old_run_or_other_kind_hold_is_ignored_and_new_pass_clears_hold(self):
        self.run_sanity('打率1.5です。', [])
        for changes in (dict(run_id='122'), dict(run_id='123', run_attempt='1'),
                        dict(run_attempt='2', kind='daily_soccer')):
            _, output = self.verify(**changes)
            self.assertNotIn('常識点検による保留', output)
        self.run_sanity()
        self.assertEqual(json.loads(Path('build/sanity_hold.json').read_text())['status'], 'passed')

    def test_workflow_keeps_hold_separate_and_checks_before_no_games_skip(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/daily_notify.yml').read_text(encoding='utf-8'))
        steps = next(job['steps'] for job in workflow['jobs'].values() if any(
            s.get('id') == 'sanity' for s in job.get('steps', [])))
        gate = next(s for s in steps if s.get('id') == 'sanity')
        upload = next(s for s in steps if s.get('name') == 'Upload to YouTube')
        final = next(s for s in steps if s.get('name') == 'Confirm the video went out')
        artifact = next(s for s in steps if s.get('name') == 'Save video as artifact')
        self.assertIn('--hold-record build/sanity_hold.json', gate['run'])
        self.assertIn("steps.sanity.outcome == 'success'", upload['if'])
        self.assertIn('steps.sanity.outcome', final['run'])
        self.assertIn('--hold-record build/sanity_hold.json', final['run'])
        self.assertIn('build/sanity_hold.json', artifact['with']['path'])
        self.assertIn('data/sanity.json', artifact['with']['path'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
