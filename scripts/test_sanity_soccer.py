"""10/24の指摘文面と保存材料。実API・投稿なしで停止可否まで確認する。"""
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
import sanity_material
import soccer_match_interest as interest
import soccer_sanity_material as soccer

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/fact-guards/sanity_soccer_20261024.json').read_text(encoding='utf-8'))


class SoccerSanity(unittest.TestCase):
    def setUp(self):
        self.document = dict(date_jst='2026-10-24', soccer_v4_mode='preview',
                             soccer_material=soccer.compact(FIXTURE['data']),
                             segments=[dict(text=FIXTURE['text'])])
        self.issue = copy.deepcopy(FIXTURE['issue'])

    def run_sanity(self, text=None, why=None, material=True, findings=True):
        with tempfile.TemporaryDirectory() as tmp:
            doc = copy.deepcopy(self.document)
            if text:
                doc['segments'][0]['text'] = text
            issue = dict(self.issue, where=doc['segments'][0]['text'])
            if why:
                issue['why'] = why
            if not material:
                doc.pop('soccer_material')
                doc['soccer_v4_mode'] = ''
            path = Path(tmp)
            (path/'narration.json').write_text(json.dumps(doc), encoding='utf-8')
            with patch.object(sys, 'argv', ['sanity', '--strict', '--general', '--kind', 'daily_soccer',
                    '--narration', str(path/'narration.json'), '--out', str(path/'report.json'),
                    '--hold-record', str(path/'hold.json')]), \
                 patch.dict(os.environ, ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=''), \
                 patch.object(sanity, 'general', return_value=[issue] if findings else []):
                code = sanity.main()
            return code, json.loads((path/'report.json').read_text(encoding='utf-8'))

    def test_fixed_original_high_is_supported_warning(self):
        code, report = self.run_sanity()
        self.assertEqual(code, 0)
        self.assertFalse(report['upload_held'])
        self.assertFalse(report['blocking_issues'])
        self.assertEqual(report['odd'][0]['verification'], '材料で裏付け済み（誤検出）')
        self.assertEqual(report['odd'][0]['severity'], 'high')
        self.assertTrue(any(s.get('games') for s in report['materials']))

    def test_reversed_ranks_hold_even_without_ai_finding(self):
        text = '首位アストンヴィラ対12位マンチェスターC、勝点差13。'
        code, report = self.run_sanity(text, findings=False)
        self.assertNotEqual(code, 0)
        self.assertTrue(report['upload_held'])
        self.assertTrue(report['contradictions'])

    def test_correct_named_ranks_and_point_gap_are_supported(self):
        text = '12位アストンヴィラ対首位マンチェスターC、勝点差13。'
        for why in ('順位が違う', '勝点差が違う', '順位と勝点差が違う'):
            with self.subTest(why=why):
                self.assertEqual(self.run_sanity(text, why)[0], 0)

    def test_missing_material_unknown_target_and_wrong_gap_hold(self):
        self.assertNotEqual(self.run_sanity(material=False)[0], 0)
        self.assertNotEqual(self.run_sanity(why='所属が違う')[0], 0)
        self.assertNotEqual(self.run_sanity(FIXTURE['text'].replace('差13', '差14'), '勝点差が違う')[0], 0)

    def test_stale_material_is_not_used(self):
        self.document['soccer_material']['date_jst'] = '2026-10-23'
        self.assertEqual(soccer.grounding([self.document]), [])

    def test_material_of_another_document_cannot_exempt_this_one(self):
        self.document['date_jst'] = '2026-10-25'
        materials = [dict(self.document['soccer_material'], sport='soccer')]
        reviewed, _ = sanity_material.assess([self.issue], [self.document], materials)
        self.assertFalse(reviewed[0]['supported'])

    def test_partial_quote_is_matched_to_its_game_context(self):
        materials = sanity_material.grounding([self.document])
        issue = dict(self.issue, where='首位チームと12位の対戦。')
        reviewed, _ = sanity_material.assess([issue], [self.document], materials)
        self.assertTrue(reviewed[0]['supported'])
        self.document['segments'][0]['text'] = 'アストンヴィラは12位、マンチェスターCは首位。'
        issue['where'] = 'アストンヴィラは12位'
        reviewed, _ = sanity_material.assess([issue], [self.document], materials)
        self.assertTrue(reviewed[0]['supported'])

    def test_actual_ai_prompt_receives_soccer_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'narration.json'
            path.write_text(json.dumps(self.document), encoding='utf-8')
            response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')])
            with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
                 patch('backstage_guard.create', return_value=response) as create, \
                 patch.object(sanity.token_log, 'record'):
                self.assertEqual(sanity.general([str(path)], 'TEST'), [])
            prompt = create.call_args.kwargs['messages'][0]['content']
            for expected in ('soccer', 'アストンヴィラ', 'マンチェスター・シティ',
                             '2026-10-24T09:54:14.816416+00:00', 'points_back', 'football-data.org'):
                self.assertIn(expected, prompt)

    def test_race_boundary_uses_team_positions_and_points(self):
        data = dict(date_jst='2026-10-24', updated_at='2026-10-24T10:15:58+00:00',
            competitions=[dict(lines=[dict(at=4, inside=[dict(position=4, team_en='Aston Villa FC', points=15)],
                outside=[dict(position=5, team_en='Manchester City FC', points=14)])])])
        self.document['soccer_material'] = soccer.compact(data)
        text = '4位のアストンヴィラと5位のマンチェスターCの勝点差は1。'
        self.assertEqual(self.run_sanity(text, '順位と勝点差が違う')[0], 0)
        self.assertNotEqual(self.run_sanity(text.replace('4位', '6位'), '順位が違う')[0], 0)

    def test_new_reasons_name_each_rank_for_both_home_away_orders(self):
        for ranks in ((12, 1), (1, 12), (1, 2), (4, 5), (17, 18), (3, 5)):
            game = copy.deepcopy(FIXTURE['data']['games'][0])
            for side, rank in zip(('home', 'away'), ranks):
                game[side+'_standing']['rank'] = rank
                game[side+'_standing']['points_back'] = 0 if side == 'home' else 1
            game.update(cl_line=4, relegation_line=18)
            reason = interest.decide(game)['reasons'][0]['text']
            self.assertIn('アストンヴィラ', reason)
            self.assertIn('マンチェスターC', reason)
            self.assertIn(('首位' if ranks[0] == 1 else f'{ranks[0]}位')+'アストンヴィラ', reason)
            self.assertIn(('首位' if ranks[1] == 1 else f'{ranks[1]}位')+'マンチェスターC', reason)
            material = dict(soccer.compact(dict(FIXTURE['data'], games=[game])), sport='soccer')
            self.assertTrue(soccer.review(reason, [material], '順位が違う'))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
