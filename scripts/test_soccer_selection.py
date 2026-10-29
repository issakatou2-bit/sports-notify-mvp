import os
import copy
import json
from datetime import date
from urllib.error import HTTPError
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['COLLESPO_SOCCER_LOOK']='v5'
os.environ['COLLESPO_SHORT_LOOK']='v4'
import soccer_selection as select
import soccer_extra_fixtures as extra
import soccer_slots_v4 as slots
import notability_engine as ne
import healthcheck as hc


def game(ident='derby',home='Manchester City FC',away='Manchester United FC',code='PL'):
    return dict(game_id=ident,competition_code=code,league=next(c['name'] for c in select.competitions() if c['code']==code),home_team_name=home,away_team_name=away,
                start_time_utc='2026-10-12T14:00:00Z',home_standing=None,away_standing=None,is_notable=True)
def material(games):return dict(generated_at='2026-10-12T10:00:00Z',games=games)


class Tests(unittest.TestCase):
    def test_non_japanese_derby_is_selected_and_voiced_without_fictional_person(self):
        data=select.select(material([game()]),availability={})
        self.assertEqual(data['preview_selection']['count'],1)
        self.assertFalse(data['games'][0]['preview_rating']['japanese'])
        plan=slots.program('preview',data)
        self.assertIn('マンチェスター',plan['narration']['title'])
        self.assertNotIn('日本人選手',plan['narration']['segments'][0]['text'])
        self.assertTrue(any('マンチェスターダービー' in s['text'] for s in plan['narration']['segments']))
        self.assertEqual(select.assessment(data,'2026-10-12')[0],'required')

    def test_two_ordinary_matches_are_not_padded_and_empty_day_skips(self):
        rows=[game(str(i),'Cagliari Calcio','Torino FC','SA') for i in range(2)]
        data=select.select(material(rows),availability={})
        self.assertEqual(data['preview_selection']['count'],0)
        self.assertIn('しきい値',select.assessment(data,'2026-10-12')[2])
        self.assertEqual(select.assessment(select.select(material([]),availability={}),'2026-10-12')[0],'skip')

    def test_maximum_and_score_order_knockout_requires_evidence(self):
        rows=[game(str(i)) for i in range(4)]
        for i,row in enumerate(rows):row['start_time_utc']=f'2026-10-12T14:0{i}:00Z'
        rows[-1].update(competition_code='CL',league='チャンピオンズリーグ',phase='knockout',phase_source='Quarterfinals')
        data=select.select(material(rows),availability={})
        self.assertEqual(data['preview_selection']['selected_ids'],['3','0','1','2'])
        weak=game(code='EL',home='Torino FC',away='US Lecce');weak['phase']='knockout'
        self.assertEqual(select.score(weak)['score'],20)
        weak['phase_source']='Round of 16';self.assertEqual(select.score(weak)['score'],35)

    def test_japanese_expectation_and_fresh_availability(self):
        row=game('kamada','Crystal Palace FC','Nottingham Forest FC')
        row['season_players']=[dict(name='鎌田大地',club='Crystal Palace FC',scope='season',goals=0,assists=3,minutes=400,out=False,source='fixture',as_of='2026-10-12T10:00:00Z')]
        available=dict(source='https://fantasy.premierleague.com/api/bootstrap-static/',updated_at='2026-10-12T10:00:00Z',players={'鎌田大地':dict(club_jp='Crystal Palace FC',minutes=400,out=False,chance_next=75)})
        data=select.select(material([row]),availability=available)
        self.assertEqual(data['preview_selection']['count'],1)
        self.assertEqual(data['games'][0]['preview_rating']['interest']['player']['name'],'鎌田大地')
        self.assertIn('japanese_available',[f['key'] for f in data['games'][0]['preview_rating']['factors']])
        for stamp in ('2026-10-09T10:00:00Z','2026-10-13T10:00:00Z'):
            changed=dict(available,updated_at=stamp)
            self.assertNotIn('japanese_available',[f['key'] for f in select.score(row,changed)['factors']])
        injured=material([row])
        available['players']['鎌田大地']['out']=True
        unavailable=select.select(injured,availability=available)
        self.assertIn('鎌田大地',unavailable['games'][0]['preview_out_names'])
        self.assertIsNone(unavailable['games'][0]['preview_rating']['interest']['player'])
        self.assertNotIn('鎌田大地',[n for values in select.visible_members(unavailable['games'][0]).values() for n in values])

    def test_unknown_names_source_failure_and_stale_material_not_called_no_fixture(self):
        data=select.select(material([game(home='Unknown FC')]),availability={})
        self.assertEqual(select.assessment(data,'2026-10-12')[0],'unknown')
        failed=select.select(dict(material([]),source_errors=[{'competition':'EL'}]),availability={})
        self.assertEqual(select.assessment(failed,'2026-10-12')[0],'unknown')
        self.assertEqual(select.assessment(failed,'2026-10-13')[0],'unknown')
        soon=game();soon['start_time_utc']='2026-10-12T10:59:00Z'
        self.assertEqual(select.select(material([soon]),availability={})['preview_selection']['count'],0)

    def test_extra_el_fixture_home_away_and_international_recognition(self):
        comp=next(c for c in select.competitions() if c['code']=='EL')
        event=dict(id='42',date='2026-10-12T14:00:00Z',competitions=[dict(competitors=[dict(homeAway='away',team=dict(id='2',displayName='Manchester United')),dict(homeAway='home',team=dict(id='1',displayName='Tottenham Hotspur'))],notes=[dict(headline='Round of 16')],status={'type':{'completed':False}})])
        data=extra.supplement(material([]),{'EL':{'events':[event]}})
        self.assertEqual(data['games'][0]['home_team_name'],'Tottenham Hotspur FC')
        self.assertEqual(data['games'][0]['away_team_name'],'Manchester United FC')
        self.assertEqual(data['games'][0]['phase'],'knockout');self.assertTrue(ne.is_soccer_league(comp['name']))
        self.assertEqual(len(extra.supplement(data,{'EL':{'events':[event]}})['games']),1)
        self.assertTrue(extra.supplement(material([]),{'EL':ValueError('bad')})['source_errors'])

    def test_cup_round_from_season_slug(self):
        # DFB・国王杯はラウンドを season.slug にだけ持つ。リーグの「〜round」は杯戦扱いしない。
        def ev(slug):return dict(id='7',date='2026-10-28T19:45:00Z',season=dict(slug=slug),competitions=[dict(competitors=[dict(homeAway='home',team=dict(id='1',displayName='Bayern Munich')),dict(homeAway='away',team=dict(id='2',displayName='1. FC Magdeburg'))],status={'type':{'completed':False}})])
        dfb=next(c for c in select.competitions() if c['code']=='DFB')
        bl1=next(c for c in select.competitions() if c['code']=='BL1')
        cup=extra.parse({'events':[ev('second-round')]},dfb)[0]
        self.assertEqual((cup['phase'],cup['phase_source']),('knockout','second round'))
        self.assertNotIn('phase',extra.parse({'events':[ev('second-round')]},bl1)[0])
        self.assertNotIn('phase',extra.parse({'events':[ev('2026-27')]},dfb)[0])

    def test_single_day_fetch_deduplicates_and_never_masks_partial_failure(self):
        comp=next(c for c in select.competitions() if c['code']=='PL')
        event={'id':'42'}
        with patch.object(extra.results,'fetch_json',return_value={'events':[event]}) as fetch:
            self.assertEqual(extra.fetch_board(comp,date(2026,10,13)),{'events':[event]})
            self.assertEqual([c.args[0].split('dates=')[1] for c in fetch.call_args_list],['20261013&limit=100','20261014&limit=100'])
        error=HTTPError('https://example.invalid',400,'Bad Request',None,None)
        with patch.object(extra.results,'fetch_json',side_effect=[{'events':[]},error]):
            with self.assertRaises(HTTPError):extra.fetch_board(comp,date(2026,10,13))
        failed=extra.supplement(material([]),{'PL':error})
        self.assertEqual(failed['fixture_coverage'][0]['status'],'failed')
        self.assertIn('HTTP 400',failed['source_errors'][0]['reason'])
        empty=extra.supplement(material([]),{'PL':{'events':[]}})
        self.assertEqual(empty['fixture_coverage'][0]['status'],'no_games')
        self.assertEqual(empty['fixture_coverage'][0]['label'],'試合なし')
        self.assertFalse(empty['source_errors'])
        stale=dict(material([]),source_errors=[{'competition':'PL','reason':'old'},{'competition':'EL','reason':'keep'}])
        refreshed=extra.supplement(stale,{'PL':{'events':[]}})
        self.assertEqual(refreshed['source_errors'],[{'competition':'EL','reason':'keep'}])
        malformed=extra.supplement(material([]),{'PL':{}})
        self.assertEqual(malformed['fixture_coverage'][0]['status'],'failed')

    def test_source_text_survives_windows_encoding(self):
        for name in ('soccer_v5_cards.py','soccer_extra_fixtures.py','test_soccer_selection.py'):
            source=(select.ROOT/'scripts'/name).read_text(encoding='utf8')
            self.assertNotIn('?'*3,source,name)
            self.assertNotIn('\ufffd',source,name)

    def test_tonight_selected_two_games_render_every_screen_and_clubs_in_reasons(self):
        import soccer_v5_cards as cards
        import review_render_v3 as r3
        source=json.loads((select.ROOT/'scripts/fixtures/soccer-interest/saved-preview-20261013.json').read_text(encoding='utf8'))
        data=select.select(source,availability={})
        self.assertEqual(data['preview_selection']['selected_ids'],['575345','575346'])
        plan=slots.program('preview',data)
        self.addCleanup(r3.set_caption,'',0,0);self.addCleanup(r3.set_program_clock,None)
        for seg in plan['narration']['segments']:
            for t in (0,.35,1.5,3):
                r3.set_caption(seg['text'],12,40,speaker=2,hide_caption=seg['kind']=='outro')
                r3.set_program_clock(t)
                im=slots.frame(t,seg,plan)
                self.assertFalse(slots.check_frame(im,plan))
        seg=copy.deepcopy(plan['narration']['segments'][1])
        seg['meta']['interest']['reasons']=[{'text':'アトレティコ・マドリードの注目試合'}]
        im=slots.frame(3,seg,plan)
        self.assertFalse(slots.check_frame(im,plan))
        self.assertTrue(any(b['inline'] and b['club_id']==plan['clubs']['アトレティコ・マドリード']['team_en'] for b in im.info['v4_badges']))
        with self.assertRaisesRegex(ValueError,'クラブ名は札'):
            cards.text(im,100,100,'アトレティコ・マドリードの注目試合')

    def test_health_uses_same_selection_and_skip_is_excluded(self):
        for rows,want in (([game()],(1,0)),([],(0,1)),([game(home='Unknown FC')],(1,0))):
            data=select.select(material(rows),availability={})
            with patch.object(hc,'load',side_effect=lambda p:data if p=='data/soccer_games.json' else {}),patch.object(hc,'EXPECTED_DAILY',[]):
                _,missing,skipped,_=hc.check_videos('2026-10-12')
                self.assertEqual((missing,skipped),want)

    def test_workflow_gate_and_thumbnail_do_not_require_japanese(self):
        import yaml
        wf=yaml.safe_load((select.ROOT/'.github/workflows/soccer_daily.yml').read_text(encoding='utf8'))
        steps=wf['jobs']['build']['steps'];gate=next(s for s in steps if s.get('id')=='gate')
        self.assertIn('scripts/soccer_selection.py',gate['run'])
        self.assertIn('--github-output',gate['run'])
        self.assertIn("count != '0'",next(s for s in steps if s.get('name')=='Vertical thumbnail')['if'])
if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
