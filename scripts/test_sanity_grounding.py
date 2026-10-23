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

    def run_sanity(self, text=None, issues=None):
        document = copy.deepcopy(self.document)
        document['segments'][0]['text'] = text or FIXTURE['text']
        Path('narration.json').write_text(json.dumps(document), encoding='utf-8')
        args = ['sanity.py', '--general', '--strict', '--narration', 'narration.json',
                '--out', 'data/sanity.json', '--hold-record', 'build/sanity_hold.json', '--kind', 'daily']
        with patch.object(sys, 'argv', args), \
             patch.object(sanity, 'general', return_value=issues if issues is not None else [FIXTURE['issue']]):
            code = sanity.main()
        return code, json.loads(Path('data/sanity.json').read_text(encoding='utf-8'))

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
        self.assertEqual(report['unconfirmed_issues'][0]['severity'], 'high')
        self.assertFalse(report['unconfirmed_issues'][0]['confirmed'])
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
        self.assertEqual(code, 0)
        self.assertFalse(report['materials'])

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
