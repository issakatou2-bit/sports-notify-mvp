"""偽応答・保存材料だけで角度と事実照合を試す。外部通信/音声禁止。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import soccer_preview_angles as a
import soccer_preview as api
import soccer_selected_preview as preview

ROOT=Path(__file__).resolve().parents[1]
NOW='2026-11-05T10:00:00+00:00'


def game():
    return dict(game_id='123', competition_code='PD', league='ラ・リーガ',
                home_team_name='Real Sociedad', away_team_name='Real Madrid CF',
                start_time_utc='2026-11-06T20:00:00+00:00', start_time_jst='11/07 05:00',
                jp_by_side=dict(home=['久保建英'], away=[]), home_standing={}, away_standing={}, reasons=[], is_notable=True)


def fixture(g=None):
    return dict(generated_at=NOW, games=[g or game()], preview_selection=dict(selected_ids=['123']))


def evidence(payload, source='fake football-data.org'):
    return dict(source=source, retrieved_at=NOW, payload=payload)


def table():
    return dict(competition=dict(code='PD'), season=dict(id=1, startDate='2026-08-01', endDate='2027-06-01'),
                standings=[dict(type='HOME', table=[]), dict(type='TOTAL', table=[
                    dict(position=3, points=22, team=dict(name='FC Barcelona')),
                    dict(position=4, points=21, team=dict(name='Real Madrid CF')),
                    dict(position=5, points=20, team=dict(name='Real Sociedad'))])])


def finished(n=5):
    return [dict(id=i+1, competition=dict(code='PD'), season=dict(id=1), status='FINISHED',
                 utcDate=f'2026-10-{i+1:02}T20:00:00+00:00',
                 homeTeam=dict(name='Real Sociedad'), awayTeam=dict(name='Real Madrid CF'),
                 score=dict(fullTime=dict(home=i % 3, away=1))) for i in range(n)]


class Angles(unittest.TestCase):
    def setUp(self):
        for guard in (patch('socket.socket.connect', side_effect=AssertionError('通信禁止')),
                      patch('requests.sessions.Session.request', side_effect=AssertionError('通信禁止')),
                      patch('urllib.request.urlopen', side_effect=AssertionError('通信禁止')),
                      patch.dict(os.environ, COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_LOOK='v6',
                                 COLLESPO_SOCCER_FOCUS='on', COLLESPO_SOLO_HOST='metan')):
            guard.start(); self.addCleanup(guard.stop)

    def attached(self, g=None, results=None):
        return a.attach(fixture(g), results=results or {})

    def test_points_order_and_title_numbers_in_body(self):
        g=game(); g['preview_angle_context']=dict(standings=evidence(table()), finished=evidence(dict(matches=finished())))
        data=self.attached(g); g=data['games'][0]; facts=a.chosen(g,NOW)
        self.assertEqual([f['kind'] for f in facts], ['points','form','above'])
        self.assertEqual(facts[0]['values']['gap'],1)
        self.assertIn('勝点1差の4位',a.headline(g,NOW))
        self.assertIn('4位',facts[0]['text']); self.assertIn('勝点差は1',facts[0]['text'])
        self.assertTrue(all(f['source'] and f['retrieved_at'] for f in facts))

    def test_finished_only_correct_season_and_competition(self):
        for bad in ('status','season','competition','future','missing_score','duplicate'):
            matches=finished()
            if bad=='status': matches[0]['status']='IN_PLAY'
            if bad=='season': matches[0]['season']['id']=0
            if bad=='competition': matches[0]['competition']['code']='CL'
            if bad=='future': matches[0]['utcDate']='2026-11-07T20:00:00+00:00'
            if bad=='missing_score': matches[0]['score']['fullTime']['home']=None
            if bad=='duplicate': matches[0]=copy.deepcopy(matches[1])
            g=game(); g['preview_angle_context']=dict(standings=evidence(table()),finished=evidence(dict(matches=matches)))
            self.assertNotIn('form',[f['kind'] for f in self.attached(g)['games'][0]['preview_angles']],bad)
        g=game(); g['preview_angle_context']=dict(standings=evidence(table()),finished=evidence(dict(matches=finished()+[finished()[0]])))
        forms=[f for f in self.attached(g)['games'][0]['preview_angles'] if f['kind']=='form']
        self.assertEqual(forms[0]['values']['form'],['D','L','W','D','L'])

    def test_stale_wrong_competition_group_and_zero_do_not_become_ranks(self):
        for mutate in ('stale','competition','season','group','zero','bool'):
            st=evidence(table())
            if mutate=='stale':st['retrieved_at']='2026-10-01T00:00:00Z'
            if mutate=='competition':st['payload']['competition']['code']='CL'
            if mutate=='season':st['payload']['season']['endDate']='2026-06-01'
            if mutate=='group':st['payload']['standings'][1]['table'].pop()
            if mutate=='zero':st['payload']['standings'][1]['table'][1]['position']=0
            if mutate=='bool':st['payload']['standings'][1]['table'][1]['points']=True
            g=game();g['preview_angle_context']=dict(standings=st)
            self.assertNotIn('points',[f['kind'] for f in self.attached(g)['games'][0]['preview_angles']],mutate)

    def test_membership_not_predicted_appearance_and_cup(self):
        g=game();g['jp_by_side']['away']=['テスト選手'];g.update(competition_code='CL',league='チャンピオンズリーグ',phase='knockout',phase_source='saved fixture.stage')
        rows=self.attached(g)['games'][0]['preview_angles']
        self.assertEqual(rows[0]['kind'],'japanese_pair')
        self.assertIn('knockout',[r['kind'] for r in rows])
        self.assertNotIn('出場',rows[0]['text'])
        g['preview_out_names']=['テスト選手'];g.pop('phase_source')
        self.assertEqual(self.attached(g)['games'][0]['preview_angles'],[])

    def test_h2h_orientation_and_latest_finished(self):
        g=game(); matches=finished(2)
        matches[1].update(homeTeam=dict(name='Real Madrid CF'),awayTeam=dict(name='Real Sociedad'),score=dict(fullTime=dict(home=3,away=2)))
        g['preview_angle_context']=dict(h2h=evidence(dict(matches=matches)))
        row=self.attached(g)['games'][0]['preview_angles'][0]
        self.assertEqual(row['values']['score'],dict(home=3,away=2));self.assertIn('3対2',row['text'])
        matches[1]['homeTeam']['name']='FC Barcelona'
        self.assertEqual(self.attached(g)['games'][0]['preview_angles'][0]['values']['match_id'],1)

    def test_ledger_dedup_missing_stats_future_and_partial_wording(self):
        p=dict(name='久保建英',side='home',status='starter',goals=1,assists=None,stats_source='ESPN',appearance_evidence='ESPN starter')
        m=dict(id='1',league='PD',start_utc='2026-10-01T20:00:00Z',finished_utc='2026-10-01T22:00:00Z',home=dict(name_en='Real Sociedad'),players=[p])
        result=dict(generated_at=NOW,games=[m,copy.deepcopy(m)])
        row=self.attached(results=result)['games'][0]['preview_angles'][0]
        self.assertEqual(row['values']['appearances'],1);self.assertIn('保存済み結果の範囲',row['text']);self.assertNotIn('アシスト',row['text'])
        for key, value in [('finished_utc','2026-11-07T22:00:00Z'),('start_utc','2025-01-01T20:00:00Z')]:
            bad=copy.deepcopy(m);bad[key]=value
            self.assertEqual(a.ledger_rows(dict(games=[bad]),game(),NOW),[])
        bad=copy.deepcopy(m);bad['players'][0]['goals']=2
        self.assertEqual(a.ledger_rows(dict(games=[m,bad]),game(),NOW),[])

    def test_previous_season_and_empty_fallback(self):
        g=game(); g['reasons']=[dict(tag='quality',text='レアル・ソシエダ（昨季ラ・リーガ5位）とレアル・マドリード（昨季ラ・リーガ2位）')]
        self.assertTrue(any(r['kind']=='previous_season' for r in self.attached(g)['games'][0]['preview_angles']))
        g=self.attached()['games'][0]
        self.assertEqual(a.chosen(g,NOW),[]);self.assertTrue(a.headline(g,NOW).endswith('と対戦'))
        plan=preview.program(self.attached())
        self.assertNotIn('注目は',plan['narration']['segments'][1]['text'])

    def test_program_and_guard_recompute_numbers_names_title(self):
        g=game();g['preview_angle_context']=dict(standings=evidence(table()))
        data=self.attached(g);before=copy.deepcopy(data)
        plan=preview.program(data);doc=plan['narration']
        self.assertEqual(data,before);self.assertEqual(a.check(doc),[])
        import sanity_material
        self.assertEqual(sanity_material.check(doc, []),[])
        for field in ('body','title','values','name'):
            bad=copy.deepcopy(doc)
            if field=='body':bad['segments'][1]['text']=bad['segments'][1]['text'].replace('勝点20','勝点99')
            if field=='title':bad['title']=bad['title'].replace('勝点1差','勝点9差')
            if field=='values':bad['segments'][1]['meta']['preview_angles'][0]['values']['gap']=9
            if field=='name':bad['segments'][1]['text']=bad['segments'][1]['text'].replace('レアル・ソシエダ','違うクラブ').replace('ソシエダ','違うクラブ')
            self.assertTrue(a.check(bad),field)

    def test_api_budget_cache_failure_and_key_not_logged(self):
        first=game();second=copy.deepcopy(first);second['game_id']='456'
        response=Mock();response.json.return_value={}
        with patch.object(api,'_football_data_get',return_value=response) as get, patch('time.sleep') as wait:
            result=api.fetch_preview_context([first,second], 'fake-test-token')
        self.assertEqual(get.call_count,4);self.assertEqual(wait.call_count,4)
        self.assertEqual(len(result),2);self.assertNotIn('fake-test-token',json.dumps(result))
        with patch.object(api,'_football_data_get',side_effect=RuntimeError('403')) as get, patch('time.sleep'):
            self.assertEqual(api.fetch_preview_context([first],'fake-test-token')['123']['h2h'],{})
            self.assertEqual(get.call_count,3)
        with patch.object(api,'_football_data_get') as get:
            self.assertEqual(api.fetch_preview_context([first],''),{});get.assert_not_called()

    def test_fpl_is_separate_from_european_competition_and_stale_omitted(self):
        g=game();g.update(home_team_name='Brighton & Hove Albion FC',competition_code='EL',league='ヨーロッパリーグ',jp_by_side=dict(home=['三笘薫'],away=[]))
        g['season_players']=[dict(name='三笘薫',club='ブライトン',scope='season',goals=3,assists=1,minutes=600,
                                  source='https://fantasy.premierleague.com/api/bootstrap-static/',as_of=NOW)]
        data=self.attached(g);row=data['games'][0]['preview_angles'][0]
        self.assertEqual(row['kind'],'season_player');self.assertIn('今季FPL集計',row['text'])
        self.assertNotIn('ヨーロッパリーグ',row['text']);self.assertIn('FPL',data['source'])
        g['season_players'][0]['as_of']='2026-10-01T10:00:00Z'
        self.assertEqual(self.attached(g)['games'][0]['preview_angles'],[])

    def test_retrieved_after_fixture_snapshot_is_usable_and_cache_is_offline(self):
        st=evidence(table());st['retrieved_at']='2026-11-05T10:05:00+00:00'
        with patch.dict(os.environ,FOOTBALL_DATA_API_KEY='fake-test-token'), patch.object(api,'fetch_preview_context',return_value={'123':dict(standings=st)}):
            data=a.attach(fixture(),fetch=True,results={})
        self.assertEqual(data['games'][0]['preview_angles'][0]['kind'],'points')
        saved=dict(competitions=[dict(code='PD',preview_angle_context=dict(standings=evidence(table())))])
        with patch.object(a,'read',return_value=saved),patch.object(api,'fetch_preview_context') as get:
            data=self.attached()
        get.assert_not_called();self.assertEqual(data['games'][0]['preview_angles'][0]['kind'],'points')


if __name__=='__main__':
    unittest.main(argv=[__file__])
