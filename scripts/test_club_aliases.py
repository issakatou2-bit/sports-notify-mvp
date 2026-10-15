"""ESPNの別名漏れと、未登録を勝手に候補へ結び付けないことを固定材料で検査。"""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import club_display_names as clubs
import soccer_selection as selection

ROOT=Path(__file__).resolve().parents[1]
INCIDENT={
    'Atlético Madrid':'Club Atlético de Madrid',
    'Barcelona':'FC Barcelona',
    'Bayern Munich':'FC Bayern München',
    'Brest':'Stade Brestois 29',
    'Deportivo':'RC Deportivo La Coruña',
    'FC Cologne':'1. FC Köln',
    'Hamburg SV':'Hamburger SV',
    'Racing Santander':'Real Racing Club de Santander',
    'Rayo Vallecano':'Rayo Vallecano de Madrid',
    'SV Elversberg':'SV 07 Elversberg',
    'Schalke 04':'FC Schalke 04',
    'Werder Bremen':'SV Werder Bremen',
}


class ClubAliases(unittest.TestCase):
    def material(self,names):
        return dict(generated_at='2026-10-15T13:15:00Z',games=[
            dict(game_id=str(i),competition_code='CL',league='CL',status='TIMED',
                 home_team_name=name,away_team_name='Arsenal FC',
                 start_time_utc='2026-10-15T18:00:00Z',jp_by_side={'home':[],'away':[]})
            for i,name in enumerate(names)])

    def select_all(self,source):
        cfg=selection.policy();cfg.update(threshold=0,max_games=20)
        return selection.select(source,cfg=cfg)

    def test_all_twelve_incident_names_are_registered_with_display_and_reading(self):
        for name,ident in INCIDENT.items():
            with self.subTest(name=name):
                row=clubs.lookup(name)
                self.assertIsNotNone(row)
                self.assertEqual(row['id'],ident)
                self.assertTrue(row['display']);self.assertTrue(row['reading'])
                self.assertIn(name,row['aliases'])

    def test_all_twelve_pass_registration_gate_and_remain_selection_candidates(self):
        source=self.material(INCIDENT);before=copy.deepcopy(source)
        result=self.select_all(source)
        self.assertEqual(source,before)
        self.assertEqual(result['club_registration_check']['missing'],[])
        self.assertEqual(result['preview_selection']['rejected'],[])
        self.assertEqual(set(result['preview_selection']['selected_ids']),{str(i) for i in range(12)})

    def test_saved_espn_names_cover_every_current_club_in_all_eight_competitions(self):
        fixture=json.loads((ROOT/'scripts/fixtures/club-alias/espn-names-20261015.json').read_text(encoding='utf8'))
        coverage=json.loads((ROOT/'data/soccer_club_coverage.json').read_text(encoding='utf8'))['competitions']
        self.assertEqual(set(fixture['competitions']),set(coverage))
        for code,expected in coverage.items():
            names=fixture['competitions'][code]
            self.assertEqual(set(names.values()),set(expected),code)
            self.assertEqual(len(names),len(expected),code)
            for name,ident in names.items():
                with self.subTest(competition=code,name=name):
                    row=clubs.lookup(name)
                    self.assertIsNotNone(row)
                    self.assertEqual(row['id'],ident)
                    self.assertTrue(row['display']);self.assertTrue(row['reading'])
        for ident,names in fixture['scoreboard_names'].items():
            for name in names:
                with self.subTest(raw_espn_name=name):
                    self.assertEqual((clubs.lookup(name) or {}).get('id'),ident)

    def test_user_display_names_are_preserved(self):
        for name,want in [('Aston Villa FC','アストンヴィラ'),
                          ('Manchester City FC','マンチェスターC'),
                          ('Manchester United FC','マンチェスターU')]:
            self.assertEqual(clubs.display(name),want)

    def test_candidates_normalize_accents_prefixes_and_containment(self):
        for name,ident in [('CF Atletico Madrid','Club Atlético de Madrid'),
                           ('SV Barcelona','FC Barcelona'),
                           ('FC Barcelona B','FC Barcelona'),
                           ('SV Werder Bremen II','SV Werder Bremen'),
                           ('FC Koln II','1. FC Köln')]:
            with self.subTest(name=name):
                self.assertIsNone(clubs.lookup(name))
                self.assertIn(ident,[r['id'] for r in clubs.candidates(name)])
        self.assertEqual(clubs.candidates(''),[])
        self.assertEqual(clubs.candidates('未登録クラブXYZ'),[])

    def test_suggestions_appear_in_json_and_warning_but_do_not_register_club(self):
        result=self.select_all(self.material(['FC Barcelona B','Arsenal FC']))
        missing=result['club_registration_check']['missing']
        self.assertEqual([r['club'] for r in missing],['FC Barcelona B'])
        self.assertIn('FC Barcelona',[r['id'] for r in missing[0]['candidates']])
        warning=selection.registration_warning(missing[0])
        self.assertIn('候補：バルセロナ (FC Barcelona)',warning)
        self.assertIn('試合 0',warning)
        self.assertEqual(result['preview_selection']['selected_ids'],['1'])
        self.assertEqual(result['preview_selection']['rejected'],[
            dict(id='0',reason='クラブの表示名/読みが未登録')])
        self.assertIsNone(clubs.lookup('FC Barcelona B'))

    def test_unrelated_warning_and_ambiguous_short_name_stay_unregistered(self):
        result=self.select_all(self.material(['未登録クラブXYZ']))
        row=result['club_registration_check']['missing'][0]
        self.assertEqual(row['candidates'],[])
        self.assertNotIn('候補：',selection.registration_warning(row))
        self.assertIsNone(clubs.lookup('BRE'))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
