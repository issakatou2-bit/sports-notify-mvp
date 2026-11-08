"""刷新の2秒フック、得点の意味、順次表示。通信・音声合成なし。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import short_renewal as renewal
import soccer_results_render as render
import review_render_v3 as r3


def data():
    material = json.loads((ROOT/'scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf-8'))
    return dict(material, short_content_version='1108')


class Renewal(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,dict(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4',COLLESPO_HOST_SPLIT='',COLLESPO_SOLO_HOST='metan'))
        self.env.start();self.addCleanup(self.env.stop)
        self.look=patch.object(r3,'LOOK','v4');self.look.start();self.addCleanup(self.look.stop)
        self.addCleanup(r3.set_program_clock,None)

    def test_registered_players_reach_name_and_number_in_two_seconds_on_paper(self):
        import notability_engine as ne
        rows=json.loads((ROOT/'data/soccer_player_names.json').read_text(encoding='utf-8'))['players']
        for player in rows:
            item=renewal.hook(player['name_jp'],1,'得点')
            with self.subTest(name=player['name_jp']):self.assertTrue(renewal.opening_check(item)['passed'])
        self.assertTrue(renewal.opening_check(renewal.hook('日本代表',28,'人'))['passed'])
        bad=renewal.hook(rows[0]['name_jp'],1,'得点');bad['text']='こんにちは。今日は結果を紹介します。'+bad['text']
        self.assertFalse(renewal.opening_check(bad)['passed'])
        self.assertTrue(ne.apply_readings('語る上で'))

    def test_press_keeps_the_full_name_with_a_numeric_first_hook(self):
        body='ピート・クロウ＝アームストロングが受賞。カブスの選手では2人目。'
        data=dict(reporters=dict(posts=[dict(jp=body,uri='fixture:award',outlet='試験媒体')]))
        doc=dict(segments=[dict(kind='intro',text=body,speaker=2,meta={}),dict(kind='outro',text='旧い締め',speaker=2,meta={})])
        result=renewal.morning(doc,data,'press')
        self.assertEqual(result['segments'][0]['text'],'2人目、ピート・クロウ＝アームストロング。')
        self.assertEqual(result['segments'][0]['meta']['opening_hook']['context'],'カブスの受賞記録')
        self.assertTrue(result['opening_check']['passed'])
        import generate_morning_short as morning
        ending=dict(result['segments'][-1],duration=1.2)
        self.assertLessEqual(morning.plan_durations([ending])[0],2)

    def test_press_upload_uses_the_same_article_as_the_script(self):
        import tempfile
        import upload_youtube as upload
        import morning_content
        body='ピート・クロウ＝アームストロングが受賞。カブスの選手では2人目。'
        material=dict(reporters=dict(posts=[dict(jp=body,uri='fixture:award',outlet='試験媒体')]))
        segments=morning_content.press_segments(material,{})+[dict(kind='outro',text='続き',speaker=2,meta={})]
        doc=renewal.morning(dict(segments=segments),material,'press')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,COLLESPO_MLB_TITLE_V2='on'):
            folder=Path(directory);(folder/'games.json').write_text('{"games":[]}',encoding='utf-8')
            (folder/'narration.json').write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
            result=upload.build_metadata(str(folder/'games.json'),'11月8日',kind='morning',morning_mode='press',morning_players=[],narration_path=str(folder/'narration.json'))
        self.assertIn('クロウ',result['snippet']['title'])
        self.assertIn('1件の報道',result['snippet']['description'])
        self.assertNotIn('スキーンズ',result['snippet']['title'])

    def test_starting_only_is_held_and_material_is_kept(self):
        material=data()
        for p in material['players']:p.update(goals=0,assists=0)
        original=copy.deepcopy(material)
        self.assertEqual(render.production_narration(material)['segments'],[])
        self.assertEqual(material,original)

    def test_production_hook_is_same_in_script_and_first_frame(self):
        material=data();original=copy.deepcopy(material)
        doc=render.production_narration(material)
        first=doc['segments'][0];item=first['meta']['opening_hook']
        self.assertEqual(first['text'],item['text']);self.assertTrue(doc['opening_check']['passed'])
        r3.set_program_clock(0);r3.set_caption(first['text'],2,20)
        im=render.frame(0,first,material)
        self.assertEqual(im.info['opening_hook'],item)
        import soccer_v5_cards as cards
        self.assertGreater(sum(count for count,color in im.crop((100,850,750,1100)).getcolors(162500) if color==cards.LIME),100)
        self.assertEqual(material,original)
        self.assertNotIn('登録',doc['segments'][-1]['text'])
        self.assertLessEqual(len(doc['segments'][-1]['text']),16)

    def test_only_confirmed_goal_changes_are_described(self):
        p=dict(name='鎌田大地',club='クリスタル・パレス',side='home',status='starter',goals=1,assists=0)
        def goal(side,minute,name='',japanese=False):
            return dict(side=side,minute=minute,scorer=name,japanese_goal=japanese,japanese_assists=[],own_goal=False)
        goals=[goal('home','14'),goal('away','50'),goal('home','70','鎌田大地',True)]
        game=dict(home=dict(name_jp=p['club']),away=dict(name_jp='相手'),score=dict(home=2,away=1),goals=goals,goals_complete=True)
        text,shown=renewal.impact_units(game,p)
        self.assertEqual(text,['この得点でクリスタル・パレスは2対1と勝ち越しました。'])
        self.assertEqual(shown,[goals[-1]])
        game['goals_complete']=False
        self.assertEqual(renewal.impact_units(game,p),([],[]))
        self.assertNotIn('今季',''.join(text));self.assertNotIn('日本人記録',''.join(text))

    def test_season_total_requires_same_club_competition_and_post_match_source(self):
        game=dict(league='PL',league_jp='プレミアリーグ',finished_utc='2026-11-07T16:00:00Z')
        p=dict(name='鎌田大地',club='クリスタル・パレス',goals=1,assists=0)
        self.assertEqual(renewal.season_context(game,p),[])
        row=dict(name=p['name'],club=p['club'],scope='season',source='fixture:official',season='2026/27',competition='PL',as_of='2026-11-07T17:00:00Z',goals=3)
        game['season_players']=[row]
        self.assertEqual(renewal.season_context(game,p)[0]['value'],'今季3得点')
        for change in [dict(as_of='2026-11-07T15:00:00Z'),dict(competition='CL'),dict(source=''),dict(club='アーセナル')]:
            game['season_players']=[dict(row,**change)]
            self.assertEqual(renewal.season_context(game,p),[])

    def test_race_has_three_or_four_rows_and_japanese_club_is_primary(self):
        from test_soccer_race_length import material
        import soccer_slots_v4 as slots
        original=dict(material(28),short_content_version='1108');saved=copy.deepcopy(original)
        plan=slots.race_program(original);segs=plan['narration']['segments']
        self.assertEqual([s['kind'] for s in segs],['cover','standings','outro'])
        meta=segs[1]['meta'];self.assertTrue(3<=len(meta['rows'])<=4)
        primary=next(r for r in meta['rows'] if r['team']==meta['primary'])
        self.assertEqual((primary['position'],primary['points']),(9,13))
        self.assertEqual(original,saved)
        self.assertTrue(plan['narration']['opening_check']['passed'])

    def test_table_values_wait_for_their_spoken_row(self):
        from test_soccer_race_length import material
        import soccer_slots_v4 as slots
        plan=slots.race_program(dict(material(28),short_content_version='1108'));seg=plan['narration']['segments'][1]
        r3.set_program_clock(0);r3.set_caption(seg['text'],12,20,caption_units=seg['caption_units'])
        early=slots.frame(0,seg,plan)
        self.assertLessEqual(len(early.info['readable_rows']),1)
        import soccer_readable
        self.assertEqual(soccer_readable.check_frame(early,plan['clubs']),[])
        self.assertNotIn('13',[e['text'] for e in early.info['v3_layout']])
        r3.set_program_clock(12);late=slots.frame(12,seg,plan)
        self.assertEqual(len(late.info['readable_rows']),len(seg['meta']['rows']))
        self.assertEqual(soccer_readable.check_frame(late,plan['clubs']),[])
        self.assertIn('13',[e['text'] for e in late.info['v3_layout']])



if __name__=='__main__':unittest.main(argv=[__file__])
