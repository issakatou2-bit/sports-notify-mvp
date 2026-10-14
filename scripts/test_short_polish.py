"""10/14の選定事故・同球団の名字・画面ごとの効果音を固定材料で検査。"""
import copy
import json
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import club_display_names as clubs
from japanese_team_names import team_names
import soccer_selection as selection

ROOT=Path(__file__).resolve().parents[1]


class ShortPolish(unittest.TestCase):
    def material(self):
        return json.loads((ROOT/'scripts/fixtures/soccer-interest/saved-preview-20261014.json').read_text(encoding='utf8'))

    def test_every_current_league_and_european_club_has_display_and_reading(self):
        groups=json.loads((ROOT/'data/soccer_club_coverage.json').read_text(encoding='utf8'))['competitions']
        self.assertEqual({k:len(v) for k,v in groups.items()},dict(PL=20,PD=20,SA=20,BL1=18,FL1=18,CL=36,EL=36,UECL=36))
        for code,names in groups.items():
            for name in names:
                with self.subTest(competition=code,club=name):
                    row=clubs.lookup(name)
                    self.assertIsNotNone(row)
                    self.assertTrue(row['display']);self.assertTrue(row['reading'])
        self.assertEqual(clubs.display('Aston Villa FC'),'アストン・ヴィラ')
        self.assertEqual(clubs.display('Manchester City FC'),'マンチェスター・シティ')

    def test_october_14_selects_four_distinct_cards_without_changing_input(self):
        source=self.material();before=copy.deepcopy(source)
        selected=selection.select(source,availability={})
        self.assertEqual(source,before)
        self.assertEqual(selected['preview_selection']['threshold'],30)
        self.assertEqual(selected['preview_selection']['selected_ids'],['575353','575350','575352','575354'])
        self.assertEqual(selected['preview_selection']['rejected'],[])
        self.assertEqual(selected['club_registration_check']['missing'],[])

    def test_seven_day_warning_and_only_unregistered_match_is_excluded(self):
        source=self.material();good=source['games'][0];bad=copy.deepcopy(good)
        bad.update(game_id='bad',home_team_name='未登録FC')
        future=copy.deepcopy(bad);future.update(game_id='future',home_team_name='先の未登録FC',start_time_utc='2026-10-20T02:00:00Z')
        outside=copy.deepcopy(future);outside.update(game_id='outside',home_team_name='範囲外FC',start_time_utc='2026-10-22T02:00:00Z')
        source['games']=[good,bad,future,outside]
        selected=selection.select(source,availability={})
        self.assertEqual(selected['preview_selection']['selected_ids'],[good['game_id']])
        self.assertEqual({r['club'] for r in selected['club_registration_check']['missing']},{'未登録FC','先の未登録FC'})

    def test_preview_uses_saved_facts_and_ignores_ai_claims(self):
        with patch.dict(os.environ,{'COLLESPO_SHORT_LOOK':'v4','COLLESPO_SOCCER_LOOK':'v5'}):
            import soccer_slots_v4 as slots
            import review_render_v3 as r3
            source=self.material()
            for game in source['games']:game['ai_summary']='全クラブが総当たり。出場確定。999得点。'
            with patch.object(r3,'LOOK','v4'):
                plan=slots.program('preview',selection.select(source,availability={}))
            segments=plan['narration']['segments'];text=''.join(s['text'] for s in segments)
            self.assertEqual(sum(s['kind']=='preview' for s in segments),4)
            self.assertIn('ホーム側は8位、アウェー側は11位',text)
            self.assertIn('リバプールは昨季CLリーグフェーズ3位',text)
            self.assertNotIn('総当たり',text);self.assertNotIn('999',text)
            self.assertEqual(plan['narration']['duration_budget']['limit'],55)

    def test_dodgers_use_surnames_commas_and_one_prominence_order(self):
        original=['大谷翔平','佐々木朗希','山本由伸'];before=list(original)
        self.assertEqual(team_names(original,'ドジャース'),'大谷、山本、佐々木のドジャース')
        self.assertEqual(team_names(list(reversed(original)),'ドジャース'),'大谷、山本、佐々木のドジャース')
        self.assertEqual(original,before)
        self.assertEqual(team_names(['大谷翔平'],'ドジャース'),'大谷翔平のドジャース')
        self.assertEqual(team_names([],'ドジャース'),'ドジャース')
        self.assertEqual(team_names(['鈴木誠也','今永昇太'],'カブス'),'鈴木、今永のカブス')
        from japanese_team_names import surnames
        import notability_engine as ne
        self.assertTrue(all(p['name_jp'] in surnames() for p in ne.JP_PLAYERS_MLB))

    def test_ps_scoreboard_and_narration_share_name_format(self):
        import ps_unified_v3 as ps
        card=dict(layout='facts',items=[],scoreboard=dict(rows=[dict(abbr='LAD',name='ドジャース',wins=2,players=['佐々木朗希','大谷翔平','山本由伸'])]))
        self.assertEqual(ps.rows(card),[('LAD　大谷、山本、佐々木のドジャース','2勝')])

    def test_mlb_affiliation_reason_uses_short_team_phrase(self):
        import notability_engine as ne
        game=ne.Game('fixed','MLB','119','147','ドジャース','ヤンキース')
        with patch.object(ne,'recently_played',return_value=set()):
            reasons=ne.rule_japanese_player(game,{'119':['大谷翔平','佐々木朗希','山本由伸']})
        self.assertEqual(reasons[0].text,'大谷、山本、佐々木のドジャース')

    def test_v4_ps_focus_draws_short_names_even_without_content_flag(self):
        import short_v4_cards as cards
        import review_render_v3 as r3
        card=dict(label='PS予告',scoreboard=dict(need=3,rows=[dict(abbr='LAD',team_id='119',name='ドジャース',wins=2,players=['佐々木朗希','山本由伸','大谷翔平'])]))
        with patch.object(r3,'LOOK','v4'), patch.object(cards,'text',wraps=cards.text) as painted:
            image=cards.focus(1.5,card,dict(v3={}))
        self.assertIn('大谷、山本、佐々木のドジャース',[c.args[3] for c in painted.call_args_list])
        words=[row.get('text','') for row in image.info['v3_layout']]
        self.assertIn('大谷、山本、佐々木の',words)  # 球団名は既存の札描画へ分かれる。
        self.assertFalse(any('大谷翔平・' in w for w in words))

    def test_partial_seven_day_fetch_retains_other_days(self):
        import soccer_extra_fixtures as extra
        from datetime import date
        competition=selection.competitions()[0]
        responses=[{'events':[{'id':'fixed'}]}, ValueError('取得失敗')]+[{'events':[]}]*6
        with patch.object(extra.results,'fetch_json',side_effect=responses):
            board=extra.fetch_board(competition,date(2026,10,14),days=8)
        self.assertEqual(board['events'],[{'id':'fixed'}])
        self.assertEqual(board['source_errors'][0]['day'],'2026-10-15')

    def test_one_quiet_transition_and_quote_keeps_original_time(self):
        import review_render_v3 as r3
        import v3_slot_render as common
        rows=[('成績','3安打'),('予定','明日'),('番記者','「引用です」')]
        self.assertEqual(common.cues(rows,[0,2,5]),[(0.,'transition','b',-10),(5,'notify','a',-3)])
        spec=dict(v3=dict(chips=[dict(win=True,win_explanation='根拠')],big='3',tag='注目'))
        sounds=r3.cues('intro',spec)
        self.assertEqual(sum(s[1]=='transition' for s in sounds),1)
        self.assertFalse(any(s[1]=='swish' for s in sounds))
        self.assertTrue({'pop','roll','stop','marker'}.issubset({s[1] for s in sounds}))
        self.assertEqual(r3.outro_cues(),[(0.,'transition','b',-10),(1.8,'marker','a',-4)])

    def test_longform_group_has_no_row_swishes_and_quotes_stay(self):
        import longform_render_v3 as longform
        sounds=longform.cues({},dict(type='group',rows=[{}, {}, {}]))
        self.assertEqual(sounds,[(0.,'transition','b',-10)])
        quote=longform.cues({},dict(type='quote',tone='引用'))
        self.assertTrue(any(s[1]=='notify' for s in quote))
        self.assertFalse(any(s[1]=='swish' for s in quote))
        self.assertFalse(any(s[1]=='transition' for s in longform.cues({},dict(type='group'),panel_since=3)))


if __name__=='__main__':unittest.main(argv=[__file__])
