"""杯戦の未登録相手を救い、所属の誤認・読み検査の迂回を防ぐ。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
os.environ['COLLESPO_SOCCER_LOOK']='v5'
os.environ['COLLESPO_SHORT_LOOK']='v4'
import club_display_names as clubs
import name_reading_guard as readings
import soccer_selection as selection
import soccer_slots_v4 as slots


def game(home='Unregistered Cup Club',away='Mainz',ident='cup'):
    return dict(game_id=ident,competition_code='DFB',league='DFBポカール',
                home_team_name=home,away_team_name=away,start_time_utc='2026-10-28T19:45:00Z',
                phase='knockout',phase_source='Round of 32')


def select(games):
    return selection.select(dict(generated_at='2026-10-28T09:00:00Z',games=games),availability={})


class Tests(unittest.TestCase):
    def test_unknown_opponent_survives_on_either_side_and_records_fallback(self):
        for home,away,side in [('Unregistered Cup Club','Mainz','home'),('Mainz','Unregistered Cup Club','away')]:
            with self.subTest(side=side):
                source=game(home,away);data=select([source])
                self.assertEqual(data['preview_selection']['selected_ids'],['cup'])
                self.assertTrue(data['games'][0]['is_notable'])
                self.assertEqual(data['preview_selection']['rescued'][0]['clubs'],{side:'Unregistered Cup Club'})
                self.assertEqual(data['club_registration_check']['missing'][0]['club'],'Unregistered Cup Club')
                self.assertFalse(data['preview_selection']['rejected'])
                self.assertNotIn('preview_name_fallbacks',source)

    def test_unknown_non_japanese_is_still_rejected_even_with_high_score_or_flag(self):
        for row in [game(away='FC Bayern München II'),game(away='Manchester City FC')]:
            row.update(jp_by_side={'home':[],'away':[]},away_has_jp=True)
            data=select([row])
            self.assertFalse(data['preview_selection']['selected_ids'])
            self.assertFalse(data['preview_selection']['rescued'])
            self.assertIn('未登録',data['preview_selection']['rejected'][0]['reason'])

    def test_sporting_substring_is_not_a_japanese_club(self):
        for name in ('Sporting de Alcázar','Sporting Hortaleza','Sporting Gijón','Mallorca','FC Augsburg'):
            self.assertFalse(any(selection.members(game(name,'Unknown FC')).values()),name)
            self.assertFalse(select([game(name,'Unknown FC')])['preview_selection']['selected_ids'])

    def test_missing_reading_and_ambiguous_or_empty_name_stay_blocked(self):
        original=clubs.lookup
        def lookup(name):
            if name=='Broken FC':return dict(id=name,display='表示だけ',reading='')
            return original(name)
        with patch.object(clubs,'lookup',side_effect=lookup):
            for name in ('Broken FC','','BRE',None):
                self.assertFalse(select([game(home=name)])['preview_selection']['selected_ids'])

    def test_fallback_deduplicates_and_reselection_keeps_records(self):
        a=game();b=dict(a,game_id='duplicate')
        data=select([a,b])
        self.assertEqual(data['preview_selection']['selected_ids'],['cup'])
        again=selection.select(data,availability={})
        self.assertEqual(again['preview_selection'],data['preview_selection'])

    def test_score_and_time_gates_still_apply_and_rescue_is_visible(self):
        row=game();row.pop('phase');row.pop('phase_source')
        data=select([row])
        self.assertFalse(data['preview_selection']['selected_ids'])
        self.assertEqual(len(data['preview_selection']['rescued']),1)
        self.assertEqual(data['preview_selection']['rescued'][0]['outcome'],'below_threshold')
        self.assertFalse(data['preview_selection']['rescued'][0]['selected'])
        self.assertEqual(data['games'][0]['preview_rating']['score'],27)
        row['status']='POSTPONED'
        self.assertFalse(select([row])['preview_selection']['rescued'])

    def test_registered_cup_names_have_readings_sources_and_exact_identity(self):
        # 主リーグ96・既存追加77を保持し、新しい杯戦9クラブだけ増やす。
        self.assertGreaterEqual(len(clubs.rows()),182)
        self.assertIsNotNone(clubs.lookup('Celtic FC'))
        for name in ('SG Sonnenhof Großaspach','VfL Bochum','Karlsruher SC','Holstein Kiel',
                     '1. FC Magdeburg','Tavernes de la Valldigna','Alcoyano','Dynamo Dresden','VfL Wolfsburg'):
            row=clubs.lookup(name)
            self.assertEqual(row['id'],name)
            self.assertTrue(row['source'].startswith('https://'))
            self.assertNotIn('?',row['display'])
            self.assertTrue(row['reading'])
            readings.assert_known(row['display'],[('club',row['display'])])
        self.assertEqual(clubs.lookup('UE Tavernes')['id'],'Tavernes de la Valldigna')

    def test_fallback_program_preserves_original_display_and_passes_reading_and_frame_checks(self):
        import review_render_v3 as r3
        # 既存の部分一致表示ではアトレティコへ化ける名前も、そのまま表示する。
        row=game('Atlético Unregistered','Mainz')
        row.update(home_standing={'rank':1,'points':9},away_standing={'rank':2,'points':8})
        data=select([row]);plan=slots.program('preview',data)
        self.assertEqual(plan['clubs']['Atlético Unregistered']['name_jp'],'Atlético Unregistered')
        self.assertIn('Atlético Unregistered',plan['narration']['title'])
        self.assertIn('Atlético Unregistered',plan['narration']['segments'][1]['meta']['home'])
        self.assertNotIn('Atlético Unregistered',''.join(s['text'] for s in plan['narration']['segments']))
        self.assertIn('ホームのクラブ',plan['narration']['segments'][1]['text'])
        readings.validate_dialogue(plan['narration'])
        self.addCleanup(r3.set_caption,'',0,0)
        self.addCleanup(r3.set_program_clock,None)
        for index,seg in enumerate(plan['narration']['segments']):
            r3.set_caption(seg['text'],12,40,speaker=2,hide_caption=seg['kind']=='outro')
            r3.set_program_clock(3)
            im=slots.frame(3,seg,plan)
            self.assertFalse(slots.check_frame(im,plan))
            if os.environ.get('CUP_CLUB_PREVIEW_DIR'):
                out=Path(os.environ['CUP_CLUB_PREVIEW_DIR']);out.mkdir(parents=True,exist_ok=True)
                im.save(out/f'fallback-{index}.png')
        # 新しい日本語名も同じ札と読み検査を通る。読みを省略した救済は使わない。
        for name in ('SG Sonnenhof Großaspach','VfL Bochum','Karlsruher SC','Holstein Kiel',
                     '1. FC Magdeburg','Tavernes de la Valldigna','Alcoyano','Dynamo Dresden','VfL Wolfsburg'):
            registered=select([game(home=name)])
            self.assertFalse(registered['preview_selection']['rescued'])
            plan=slots.program('preview',registered)
            readings.validate_dialogue(plan['narration'])
            seg=plan['narration']['segments'][1]
            r3.set_caption(seg['text'],12,40,speaker=2)
            r3.set_program_clock(3)
            im=slots.frame(3,seg,plan)
            self.assertFalse(slots.check_frame(im,plan),name)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
