"""実通信なし。今季集計の本人・季・出典・欠測・公開禁止を確認。"""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import soccer_national as n
import soccer_national_numbers as numbers
import soccer_national_pitch as pitch

AS_OF='2026-11-10T12:00:00+09:00'


def fixture_sheet():
    fixture=n.read(ROOT/'scripts/fixtures/soccer_national_numbers.json')
    roster=n.read(ROOT/'data/soccer_national_squad.json')
    def fetch(url):
        if url in fixture['responses']:return copy.deepcopy(fixture['responses'][url])
        raise OSError('fixtureにない取得は行いません')
    return numbers.collect(roster,AS_OF,fetch=fetch,fixture=True)


class Numbers(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,COLLESPO_SAMPLE_ONLY='true');self.env.start();self.addCleanup(self.env.stop)
        self.roster=n.read(ROOT/'data/soccer_national_squad.json')
        self.sheet=fixture_sheet()

    def test_fixture_matches_three_identities(self):
        self.assertEqual({r['name'] for r in self.sheet['players']},{'鈴木彩艶','鎌田大地','坂元達裕'})
        self.assertEqual(len(self.sheet['missing']),25)
        self.assertEqual(numbers.validate(self.sheet,self.roster,AS_OF),self.sheet)

    def test_only_season_integer_counts_and_missing_is_not_zero(self):
        self.assertEqual(numbers.values({'splits':{'categories':[]}}),{})
        self.assertEqual(numbers.values({'categories':[{'stats':[{'name':'goals','value':0}]}]}),{'goals':0})
        for value in (-1,True,1.5,'2'):
            with self.assertRaises(ValueError):numbers.values({'categories':[{'stats':[{'name':'goals','value':value}]}]})

    def test_conflicting_counts_rejected(self):
        with self.assertRaises(ValueError):numbers.values({'categories':[{'stats':[{'name':'goals','value':2},{'name':'totalGoals','value':3}]}]})

    def test_unexpected_api_shape_omits_numbers_and_keeps_all_missing(self):
        sheet=numbers.collect(self.roster,AS_OF,fetch=lambda url:[],fixture=True)
        self.assertFalse(sheet['players'])
        self.assertEqual(len(sheet['missing']),28)
        self.assertEqual(len(sheet['league_errors']),len(numbers.LEAGUES))

    def test_assists_alone_are_not_counted_as_confirmed_card_numbers(self):
        responses=n.read(ROOT/'scripts/fixtures/soccer_national_numbers.json')['responses']
        for payload in responses.values():
            if 'splits' in payload:payload['splits']['categories']=[{'stats':[{'name':'goalAssists','value':2}]}]
        sheet=numbers.collect(self.roster,AS_OF,fetch=lambda url:copy.deepcopy(responses.get(url)),fixture=True)
        self.assertFalse(sheet['players']);self.assertEqual(len(sheet['missing']),28)

    def test_raw_counts_identity_club_and_season_tamper_rejected(self):
        for field,value in [('values',{'goals':999}),('athlete_id','1'),('club','FC町田ゼルビア'),('season_year',2025),('scope','match')]:
            with self.subTest(field=field):
                sheet=copy.deepcopy(self.sheet);sheet['players'][0][field]=value
                with self.assertRaises((ValueError,KeyError)):numbers.validate(sheet,self.roster,AS_OF)

    def test_stale_future_and_duplicate_rejected(self):
        for at in ('2026-11-07T12:00:00+09:00','2026-11-13T12:00:00+09:00'):
            with self.assertRaises(ValueError):numbers.validate(self.sheet,self.roster,at)
        sheet=copy.deepcopy(self.sheet);sheet['players'].append(sheet['players'][0])
        with self.assertRaises(ValueError):numbers.validate(sheet,self.roster,AS_OF)

    def test_reference_must_identify_league_season_and_athlete(self):
        good=self.sheet['players'][0]
        for source in (good['source'].replace('/2026/','/2025/'),good['source'].replace('sports.core.api.espn.com','example.com'),good['source'].replace('/statistics','/events')):
            with self.assertRaises(ValueError):numbers.stats_url(source,good['league_slug'],2026,good['athlete_id'])
        team_source=good['source'].replace('/athletes/','/teams/'+good['team_id']+'/athletes/')+'/0'
        self.assertEqual(numbers.stats_url(team_source,good['league_slug'],2026,good['athlete_id'],good['team_id']),team_source)
        with self.assertRaises(ValueError):numbers.stats_url(team_source,good['league_slug'],2026,good['athlete_id'],'999')

    def test_fixture_cannot_enter_normal_narration(self):
        with patch.dict(os.environ,COLLESPO_SAMPLE_ONLY='false'):
            with self.assertRaisesRegex(ValueError,'sample_only'):numbers.validate(self.sheet,self.roster,AS_OF)

    def test_goal_hook_card_and_metadata_have_the_same_material(self):
        data=numbers.attach(n.squad(self.roster,{},AS_OF,4),self.sheet)
        doc=n.narration(data)
        self.assertEqual(n.check(doc),[])
        self.assertEqual(doc['segments'][0]['text'],'坂元達裕、今季7得点。')
        self.assertEqual(numbers.stat_line(data['players'][2]),'リーグ戦 11試合・7得点')
        self.assertIsNone(data['players'][0]['season_numbers'])
        altered=copy.deepcopy(doc);altered['national_material']['players'][2]['season_numbers']['values']['goals']=8
        self.assertTrue(n.check(altered))
        missing=copy.deepcopy(doc);missing['national_material'].pop('national_numbers')
        self.assertTrue(n.check(missing))

    def test_no_numbers_keeps_original_hook(self):
        data=n.squad(self.roster,{},AS_OF,0)
        self.assertIn('招集28人',pitch.segments(data)[0]['text'])
        self.assertEqual(numbers.stat_line(data['players'][0]),'')
        self.assertEqual(pitch.badge_for({'league':{'label':'旧札'},'season_numbers':{'league':'BEL','league_label':'ベルギー1部'}})['label'],'ベルギー1部')

    def test_gk_only_appearances(self):
        p={'position':'GK','season_numbers':{'values':{'appearances':8,'goals':9}}}
        self.assertEqual(numbers.metric(p),('appearances',8,'試合出場'))
        self.assertEqual(numbers.stat_line(p),'リーグ戦 8試合')
        data=numbers.attach(n.squad(self.roster,{},AS_OF,0),self.sheet)
        doc=n.narration(data)
        self.assertEqual(doc['segments'][0]['text'],'鈴木彩艶、今季8試合。')
        self.assertEqual(n.check(doc),[])

    def test_known_zero_goals_do_not_outrank_positive_appearances(self):
        zero=dict(name='zero',position='FW',season_numbers={'values':{'goals':0}})
        keeper=dict(name='keeper',position='GK',season_numbers={'values':{'appearances':8}})
        self.assertEqual(numbers.featured({'players':[zero,keeper]}),keeper)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
