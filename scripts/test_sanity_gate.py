"""1件1ファイルの停止履歴、限定再点検、費用上限、経路検査。外部接続なし。"""
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sanity
import sanity_material as material
import sanity_recheck as recheck
import sanity_refresh as refresh
import sanity_sources as sources
import sanity_workflows as workflows

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'scripts/fixtures/sanity_false_stops'


class SanityGate(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        old = Path.cwd()
        os.chdir(self.folder.name)
        self.addCleanup(os.chdir, old)

    def run_gate(self, document, issues, refreshed=None, retry_issues=None):
        Path('narration.json').write_text(json.dumps(document), encoding='utf8')
        original = material.grounding([document])
        with patch.object(sys, 'argv', sanity.command('test', 'narration.json', 'report.json', 'hold.json')[1:]), \
             patch.dict(os.environ, ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=''), \
             patch.object(sanity, 'general', return_value=issues), \
             patch.object(refresh, 'refresh', return_value=(refreshed if refreshed is not None else original,
                          [dict(status='offline fixture')])) as download, \
             patch.object(recheck, 'ai_review', return_value=(retry_issues or [], dict(calls=1, status='offline fixture'))) as ai, \
             patch('sys.stdout', new_callable=io.StringIO):
            code = sanity.main()
        return code, json.loads(Path('hold.json').read_text(encoding='utf8')), download, ai

    def test_every_saved_incident_and_real_contradiction(self):
        files = sorted(FIXTURES.glob('*.json'))
        self.assertGreaterEqual(len(files), 25)
        for path in files:
            with self.subTest(case=path.name):
                case = json.loads(path.read_text(encoding='utf8'))
                code, hold, download, ai = self.run_gate(case['document'], case['issues'])
                self.assertEqual(bool(code), case['expected_held'], hold)
                self.assertEqual(hold['status'], 'held' if case['expected_held'] else 'passed')
                self.assertLessEqual(download.call_count, 1)
                self.assertLessEqual(ai.call_count, 1)
                self.assertEqual(len(hold['attempts']), 2 if download.called else 1)

    def test_one_refresh_removes_false_hold_and_records_both_attempts(self):
        case = json.loads((FIXTURES/'true_points.json').read_text(encoding='utf8'))
        doc = case['document']
        # 原稿15、旧材料16。取得し直した公式材料15で決着する。
        rows = copy.deepcopy(material.grounding([doc]))
        for source in rows:
            for comp in source.get('competitions') or []:
                for player in comp.get('jp') or []:
                    if player['name'] == '三笘薫':
                        player['points'] = 15
        code, hold, download, ai = self.run_gate(doc, [], rows)
        self.assertEqual(code, 0)
        download.assert_called_once()
        ai.assert_not_called()
        self.assertTrue(hold['attempts'][0]['contradictions'])
        self.assertFalse(hold['attempts'][1]['contradictions'])
        self.assertEqual(hold['attempts'][1]['lines'][0]['lines'], [1])

    def test_unknown_current_season_high_gets_one_short_retry_and_warns(self):
        text = '架空太郎は今季55本塁打です。'
        issue = dict(kind=material.FACT, severity='high', where=text, why='今季成績が学習知識と違う')
        doc = dict(date_jst='2026-10-25', sanity_materials=[], segments=[
            dict(text='再点検へ送らない別の行です。'), dict(text=text), dict(text='別の締めです。')])
        code, hold, download, ai = self.run_gate(doc, [issue], retry_issues=[issue])
        self.assertEqual(code, 0)
        download.assert_called_once()
        ai.assert_called_once()
        targets = ai.call_args.args[0]
        self.assertEqual([s['text'] for d in targets for s in d['segments']], [text])
        self.assertTrue(hold['attempts'][1]['odd'][0]['recheck_findings'])
        self.assertEqual(hold['attempts'][1]['lines'][0]['lines'], [2])

    def test_internal_arithmetic_never_depends_on_ai_retraction(self):
        code, hold, _, ai = self.run_gate(dict(segments=[dict(text='2＋3＝6。')], sanity_materials=[]), [])
        self.assertEqual(code, 1)
        ai.assert_not_called()
        self.assertIn('計算', ' '.join(hold['reasons']))

    def test_other_documents_cannot_supply_fresh_evidence(self):
        doc = dict(date_jst='2026-10-25', sanity_materials=[], segments=[dict(text='今季55本塁打。')])
        other = dict(source='fresh but other', document_key='other', players=[dict(name='他人')])
        code, hold, _, _ = self.run_gate(doc, [dict(kind=material.FACT, severity='high',
            where='今季55本塁打。', why='今季成績')], [other])
        self.assertEqual(code, 0)
        self.assertTrue(hold['attempts'][1]['odd'][0]['material_missing'])

    def test_weekly_final_scores_survive_capture_and_each_day_keeps_its_own_game(self):
        games = [dict(game_id='1', date_jst='2026-10-23', home_team_name='ホーム', away_team_name='アウェー',
                      score=8, final_score=dict(home=2, away=1)),
                 dict(game_id='2', date_jst='2026-10-24', home_team_name='ホーム', away_team_name='アウェー',
                      score=9, final_score=dict(home=5, away=4))]
        doc = sources.attach(dict(segments=[
            dict(text='ホーム対アウェーは2対1。', meta=dict(date='2026-10-23')),
            dict(text='ホーム対アウェーは5対4。', meta=dict(date='2026-10-24'))]),
            dict(date_jst='2026-10-24', games=games))
        self.assertEqual(self.run_gate(doc, [])[0], 0)
        doc['segments'][0]['text'] = 'ホーム対アウェーは5対4。'
        self.assertEqual(self.run_gate(doc, [])[0], 1)

    def test_affiliation_particles_past_and_negation_do_not_create_false_holds(self):
        for text, code in [('投手はブリュワーズに所属しています。', 0),
                           ('投手は今季もブリュワーズ所属です。', 0),
                           ('投手は昨年レイズ所属でした。', 0),
                           ('投手はレイズ所属ではありません。', 0),
                           ('投手はレイズ所属です。', 1)]:
            with self.subTest(text=text):
                doc = dict(date_jst='2026-10-25', segments=[dict(text=text)],
                    sanity_materials=[dict(players=[dict(name='投手', team_name='ブリュワーズ')])])
                self.assertEqual(self.run_gate(doc, [])[0], code)


class RecheckBudget(unittest.TestCase):
    def test_real_request_is_short_single_call_and_cost_is_bounded(self):
        text = '架空太郎は今季55本塁打です。'
        doc = dict(segments=[dict(text=text, _sanity_original_line=7)], sanity_materials=[])
        issue = dict(where=text, why='今季成績')
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')],
                                   usage=SimpleNamespace(input_tokens=200, output_tokens=20))
        create = Mock(return_value=response)
        client = Mock(return_value=SimpleNamespace(messages=SimpleNamespace(create=create)))
        with patch.dict(sys.modules, anthropic=SimpleNamespace(Anthropic=client)), \
             patch('token_log.allowed', return_value=True), patch('token_log.record'):
            findings, info = recheck.ai_review([doc], [issue], [], 'TEST')
        self.assertEqual(findings, [])
        create.assert_called_once()
        self.assertEqual(client.call_args.kwargs['max_retries'], 0)
        args = create.call_args.kwargs
        self.assertEqual(args['max_tokens'], recheck.MAX_OUTPUT_TOKENS)
        content = args['messages'][0]['content']
        self.assertLessEqual(len(content.encode('utf8')), recheck.MAX_INPUT_BYTES)
        self.assertIn('"line": 7', content)
        self.assertLessEqual(info['estimated_upper_usd'], .03)
        self.assertGreater(info['actual_usd'], 0)

    def test_oversized_or_expensive_request_never_calls_api(self):
        doc = dict(segments=[dict(text='長'*10000)], sanity_materials=[])
        with patch.dict(sys.modules, anthropic=SimpleNamespace(Anthropic=Mock())) as modules, \
             patch('token_log.allowed', return_value=True):
            _, info = recheck.ai_review([doc], [], [], 'TEST')
            modules['anthropic'].Anthropic.assert_not_called()
        self.assertEqual(info['calls'], 0)

    def test_rejected_response_still_costs_one_call_and_never_regenerates(self):
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text='材料にないので省く')],
                                   usage=SimpleNamespace(input_tokens=200, output_tokens=20))
        create = Mock(return_value=response)
        client = Mock(return_value=SimpleNamespace(messages=SimpleNamespace(create=create)))
        with patch.dict(sys.modules, anthropic=SimpleNamespace(Anthropic=client)), \
             patch('token_log.allowed', return_value=True), patch('token_log.record') as record:
            _, info = recheck.ai_review([], [], [], 'TEST')
        create.assert_called_once()
        record.assert_called_once()
        self.assertEqual(info['calls'], 1)
        self.assertEqual(info['status'], '取得失敗')
        self.assertGreater(info['actual_usd'], 0)


class RefreshTests(unittest.TestCase):
    def now(self):
        return patch.object(refresh, 'datetime', Mock(wraps=datetime,
            now=Mock(return_value=datetime(2026, 10, 25, 6, tzinfo=timezone.utc))))

    def test_refresh_table_and_roster_without_writing_or_mutating_input(self):
        comp = dict(code='PL', jp=[dict(name='三笘薫', club_jp='ブライトン', position=3, points=16)])
        doc = dict(date_jst='2026-10-25', segments=[dict(text='三笘薫のブライトン。3位で勝点16。')],
                   sanity_materials=[dict(sport='soccer', competitions=[comp])])
        original = material.grounding([doc]); before = copy.deepcopy(original)
        table = dict(standings=[dict(type='TOTAL', table=[dict(position=3, points=16,
                     playedGames=8, team=dict(name='Brighton & Hove Albion FC'))])])
        teams = dict(teams=[dict(name='Brighton & Hove Albion FC', squad=[dict(name='Kaoru Mitoma')])])
        with self.now(), patch.dict(os.environ, FOOTBALL_DATA_API_KEY='TEST'), \
             patch.object(refresh, 'fetch', side_effect=lambda u,h=None: table if u.endswith('/standings') else teams) as get:
            rows, log = refresh.refresh([doc], original)
        self.assertEqual(original, before)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(any(s.get('refresh_category') == '順位表' for s in rows))
        self.assertTrue(any(s.get('refresh_category') == '名簿' for s in rows), log)
        self.assertTrue(all(sources.for_document(doc, [r]) for r in rows))

    def test_failure_retains_evidence_and_historical_day_cannot_be_overwritten(self):
        doc = dict(date_jst='2026-10-25', segments=[dict(text='ワールドシリーズ第1戦。')],
                   sanity_materials=[dict(series=[dict(round='W')])])
        original = material.grounding([doc])
        with self.now(), patch.object(refresh, 'fetch', side_effect=OSError('offline')) as fetch:
            rows, log = refresh.refresh([doc], original)
        self.assertEqual(rows, original)
        fetch.assert_called_once()
        self.assertIn('取得失敗', log[0]['status'])
        doc['date_jst'] = '2026-10-24'
        with self.now(), patch.object(refresh, 'fetch') as fetch:
            refresh.refresh([doc], original)
        fetch.assert_not_called()

    def test_refresh_ps_roster_and_results_from_provider_responses(self):
        final = dict(gamePk=1, gameType='W', gamesInSeries=7, seriesGameNumber=1,
            officialDate='2026-10-24', status=dict(abstractGameState='Final'), teams=dict(
                home=dict(team=dict(id=158, name='Milwaukee Brewers'), isWinner=True, score=3),
                away=dict(team=dict(id=139, name='Tampa Bay Rays'), isWinner=False, score=2)))
        nxt = copy.deepcopy(final)
        nxt.update(gamePk=2, officialDate='2026-10-25', seriesGameNumber=2,
                   status=dict(abstractGameState='Preview'))
        person = dict(id=1, name='投手', team_name='旧球団')
        game = dict(gamePk=99, home=dict(name_jp='ホーム'), away=dict(name_jp='アウェー'),
                    score=dict(home=0, away=0))
        doc = dict(date_jst='2026-10-25', segments=[dict(text='投手のワールドシリーズ。ホーム対アウェー。')],
            sanity_materials=[dict(sport='baseball', series=[dict(round='W')], players=[person], games=[game])])
        score = copy.deepcopy(final)
        score['gameDate'] = '2026-10-25T01:00:00Z'

        def provider(url, headers=None):
            if '/people/' in url:
                return dict(people=[dict(id=1, currentTeam=dict(id=158, name='Milwaukee Brewers'))])
            return dict(dates=[dict(games=[score] if 'gamePk=' in url else [final, nxt])])
        with self.now(), patch.object(refresh, 'fetch', side_effect=provider) as get:
            rows, log = refresh.refresh([doc], material.grounding([doc]))
        self.assertEqual(get.call_count, 3)
        self.assertEqual({r.get('refresh_category') for r in rows if r.get('refresh_category')},
                         {'PS', '名簿', '試合結果'}, log)
        self.assertTrue(any(p.get('team_name') == 'ブリュワーズ' for s in rows for p in s.get('players') or []))
        self.assertTrue(any((g.get('final_score') or {}).get('home') == 3 for s in rows for g in s.get('games') or []))

    def test_soccer_result_is_refetched_with_its_event_id(self):
        game = dict(id='123', league='PL', home=dict(name_jp='ホーム'), away=dict(name_jp='アウェー'),
                    score=dict(home=0, away=0))
        doc = dict(date_jst='2026-10-25', segments=[dict(text='ホーム対アウェーは2対1。')],
                   sanity_materials=[dict(sport='soccer', games=[game])])
        answer = dict(header=dict(competitions=[dict(competitors=[dict(homeAway='home', score='2'),
                                                                     dict(homeAway='away', score='1')])]))
        with self.now(), patch.dict(os.environ, FOOTBALL_DATA_API_KEY=''), \
             patch.object(refresh, 'fetch', return_value=answer) as get:
            rows, log = refresh.refresh([doc], material.grounding([doc]))
        get.assert_called_once()
        self.assertIn('event=123', get.call_args.args[0])
        self.assertTrue(any(r.get('refresh_category') == '試合結果' for r in rows), log)

    def test_transfer_never_carries_old_club_rank_into_new_roster(self):
        doc = dict(date_jst='2026-10-25', segments=[dict(text='三笘薫のリバプール。5位で勝点12。')],
            sanity_materials=[dict(sport='soccer', competitions=[dict(code='PL', jp=[dict(
                name='三笘薫', club_jp='ブライトン', position=3, points=16)])])])
        table = dict(standings=[dict(type='TOTAL', table=[dict(position=3, points=16,
                     playedGames=8, team=dict(name='Brighton & Hove Albion FC'))])])
        teams = dict(teams=[dict(name='Liverpool FC', squad=[dict(name='Kaoru Mitoma')])])
        with self.now(), patch.dict(os.environ, FOOTBALL_DATA_API_KEY='TEST'), \
             patch.object(refresh, 'fetch', side_effect=lambda u,h=None: table if u.endswith('/standings') else teams):
            rows, _ = refresh.refresh([doc], material.grounding([doc]))
        self.assertFalse(material.check(doc, rows))
        for source in rows:
            for comp in source.get('competitions') or []:
                for player in comp.get('jp') or []:
                    if player.get('club_jp') == 'リバプール':
                        self.assertIsNone(player.get('position'))
                        self.assertIsNone(player.get('points'))

    def test_new_table_also_replaces_preview_game_standings(self):
        saved = json.loads((FIXTURES/'20261024_soccer_preview.json').read_text(encoding='utf8'))
        doc = copy.deepcopy(saved['document'])
        doc['date_jst'] = '2026-10-25'
        source = doc['sanity_materials'][0]
        source['date_jst'] = '2026-10-25'
        game = source['games'][0]
        game['home_standing']['rank'] = 1
        game['away_standing']['rank'] = 12
        doc['segments'][0]['text'] = '12位アストンヴィラ対首位マンチェスターC、勝点差13。'
        self.assertTrue(material.check(doc, material.grounding([doc])))
        table = dict(standings=[dict(type='TOTAL', table=[
            dict(position=12, points=3, playedGames=8, team=dict(name='Aston Villa FC')),
            dict(position=1, points=16, playedGames=8, team=dict(name='Manchester City FC'))])])
        with self.now(), patch.dict(os.environ, FOOTBALL_DATA_API_KEY='TEST'), \
             patch.object(refresh, 'fetch', side_effect=lambda u,h=None: table if u.endswith('/standings') else dict(teams=[])):
            rows, _ = refresh.refresh([doc], material.grounding([doc]))
        self.assertFalse(material.check(doc, rows))


class WorkflowContract(unittest.TestCase):
    def test_current_workflows_and_mutated_bypass(self):
        self.assertEqual(workflows.errors(ROOT), [])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT/'.github/workflows', root/'.github/workflows')
            (root/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/soccer_now.py', root/'scripts/soccer_now.py')
            target = root/'.github/workflows/soccer_daily.yml'
            original = target.read_text(encoding='utf8')
            for mutation in (original.replace('--general --strict', '--strict'),
                             original.replace('--hold-record build/sanity_soccer_hold.json', ''),
                             original.replace('--narration build/soccer_narration.json', '--narration wrong.json'),
                             original.replace('--kind daily_soccer', '--kind daily'),
                             original.replace('--kind daily --sport soccer', '--kind weekly --sport soccer'),
                             original.replace("steps.sanity.outcome == 'success'", 'true'),
                             original.replace('python scripts/sanity.py', 'echo disabled')):
                target.write_text(mutation, encoding='utf8')
                self.assertTrue(workflows.errors(root))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
