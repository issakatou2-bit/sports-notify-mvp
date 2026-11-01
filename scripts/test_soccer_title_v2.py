"""保存材料と旧コードを使い、既定off・主語・1試合・検索名を確認。送信なし。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

import soccer_title_v2 as v2

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT/'scripts/fixtures'/name).read_text(encoding='utf8'))


def original(name):
    result = subprocess.run(['git','show','HEAD:scripts/'+name+'.py'], cwd=ROOT,
        capture_output=True, check=True)
    module = types.ModuleType('baseline_'+name)
    module.__file__ = str(ROOT/'scripts'/(name+'.py'))
    exec(compile(result.stdout.decode('utf8'), module.__file__, 'exec'), module.__dict__)
    return module


class Tests(unittest.TestCase):
    def test_explicit_names_and_ambiguous_names(self):
        for full, short in [('久保建英','久保'),('三笘薫','三笘'),('鎌田大地','鎌田'),('遠藤航','遠藤')]:
            self.assertEqual(v2.player_name(full), short)
        for name in ['鈴木彩艶','鈴木唯人','佐野航大','佐野海舟','知らない選手']:
            self.assertEqual(v2.player_name(name), name)
        self.assertEqual(v2.club_name('Real Sociedad'), 'ソシエダ')

    def test_new_same_surname_in_roster_keeps_full(self):
        import notability_engine
        with patch.object(notability_engine,'JP_PLAYERS_SOCCER',[dict(name_jp='久保建英'),dict(name_jp='久保裕也')]):
            self.assertEqual(v2.player_name('久保建英'),'久保建英')

    def test_default_and_off_match_original(self):
        import soccer_selected_preview as preview
        import soccer_results as results
        import soccer_results_render as render
        old_preview, old_results, old_render = map(original, ('soccer_selected_preview','soccer_results','soccer_results_render'))
        for setting in ('', 'off', 'true', 'ON'):
            with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':setting}):
                self.assertFalse(v2.enabled())
                data=read('soccer-daily/20261025.json')
                self.assertEqual(preview.program(data)['narration'], old_preview.program(data)['narration'])
                data=read('soccer-results/run-40249272204.json')
                self.assertEqual(results.title(data),old_results.title(data))
                self.assertEqual(render.production_narration(data),old_render.production_narration(data))

    def test_one_person_one_game_and_original_material_unchanged(self):
        import short_content
        import soccer_results
        for fixture in ('run-38817456251.json','run-40249272204.json'):
            data=read('soccer-results/'+fixture); before=copy.deepcopy(data)
            soccer_results.validate_data(data)
            with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'on'}):
                focus=v2.result_focus(data); narr=v2.result_narration(data)
            self.assertGreaterEqual(len(short_content.information(narr,data)),3)
            self.assertEqual({str(s['meta']['event_id']) for s in narr['segments'] if 'event_id' in s['meta']}, {focus['game_id']})
            self.assertFalse(any(s['kind'] in ('roster','other-results','flash-results') for s in narr['segments']))
            self.assertEqual(data,before)
            self.assertTrue(narr['title'].startswith(v2.player_name(focus['name'])))

    def test_preview_facts_not_predicted_appearance(self):
        data=read('soccer-daily/20261025.json'); before=copy.deepcopy(data)
        focus=v2.preview_head(data)
        self.assertNotIn('先発',focus['head'])
        self.assertNotIn('今夜の注目試合',focus['head'])
        self.assertNotIn('ほか',focus['head'])
        self.assertEqual(data,before)
        for game in data['games']:
            game['jp_by_side']={'home':[], 'away':[]}
        self.assertEqual(v2.preview_head(data)['name'],'')
        self.assertRegex(v2.preview_head(data)['head'],r'^d+位.+対d+位.+｜(勝点差|勝点で並ぶ)')

    def test_no_unconfirmed_cl_line_or_win(self):
        data=read('soccer-daily/20261025.json')
        for g in data['games']:
            g.pop('cl_line',None); g.pop('home_standing',None); g.pop('away_standing',None)
        head=v2.preview_head(data)['head']
        self.assertNotIn('CL圏',head)
        self.assertNotIn('勝利',head)

    def test_full_name_in_metadata(self):
        import upload_youtube
        for fixture in ('run-38817456251.json','run-40249272204.json'):
            data=read('soccer-results/'+fixture)
            folder=ROOT/'build/title-v2-results-test'/fixture;folder.mkdir(parents=True,exist_ok=True)
            path=folder/'material.json';path.write_text(json.dumps(data),encoding='utf8')
            with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'on'}):
                meta=upload_youtube.build_metadata(str(path),'10月26日','soccer_results',narration_path='')['snippet']
            name=v2.result_focus(data)['name']
            self.assertIn(name,meta['description'])
            self.assertIn(name,meta['tags'])
            self.assertLessEqual(len(meta['title']),100)
            self.assertTrue(meta['title'].startswith(v2.player_name(name)))

    def test_daily_metadata_keeps_search_name(self):
        import upload_youtube
        data=read('soccer-daily/20261022.json')
        folder=ROOT/'build/title-v2-metadata-test';folder.mkdir(parents=True,exist_ok=True)
        material=folder/'material.json';material.write_text(json.dumps(data),encoding='utf8')
        with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'on'}):
            meta=upload_youtube.build_metadata(str(material),'10月22日','daily',sport='soccer',narration_path='')['snippet']
        self.assertTrue(meta['title'].startswith('鎌田が今季FPL集計3アシスト'))
        self.assertIn('鎌田大地',meta['tags'])
        self.assertIn('鎌田大地',meta['description'])

    def test_headlines_use_existing_badges_and_no_empty_rows(self):
        import soccer_selected_preview as preview
        import soccer_results_render as render
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'on','COLLESPO_SOLO_HOST':'metan','COLLESPO_SOCCER_LOOK':'v6'}), patch.object(r3,'LOOK','v4'):
            data=read('soccer-daily/20261022.json');plan=preview.program(data)
            seg=plan['narration']['segments'][0]
            r3.set_caption(seg['text'],10,55,speaker=2);r3.set_program_clock(3)
            im=slots.frame(3,seg,plan)
            self.assertEqual(slots.check_frame(im,plan),[])
            self.assertEqual(im.info['soccer_title_v2'],v2.preview_head(data)['head'])
            data=read('soccer-results/run-38817456251.json');narr=v2.result_narration(data)
            seg=narr['segments'][0];r3.set_caption(seg['text'],10,60,speaker=2)
            clubs=render.resolve_clubs(data);im=render.frame(3,seg,data,clubs)
            self.assertEqual(render.validate_frame(im,data,clubs),[])
        r3.set_program_clock(None);r3.set_caption('',0,0)

    def test_switch_off_metadata_matches_old_code(self):
        import upload_youtube
        old=original('upload_youtube')
        folder=ROOT/'build/title-v2-off-test';folder.mkdir(parents=True,exist_ok=True)
        material=folder/'material.json'
        for kind,fixture in [('daily','soccer-daily/20261022.json'),('soccer_results','soccer-results/run-38817456251.json')]:
            material.write_text(json.dumps(read(fixture)),encoding='utf8')
            with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'off'}):
                self.assertEqual(upload_youtube.build_metadata(str(material),'10月22日',kind,sport='soccer',narration_path=''),
                                 old.build_metadata(str(material),'10月22日',kind,sport='soccer',narration_path=''))

    def test_description_keeps_only_the_featured_player_and_game(self):
        import soccer_results
        data=read('soccer-results/run-40249272204.json');before=copy.deepcopy(data)
        with patch.dict(os.environ, {'COLLESPO_SOCCER_TITLE_V2':'on'}):
            description='\n'.join(soccer_results.description_lines(data))
        self.assertIn('水多海斗',description)
        self.assertIn('マルセイユ対ルアーブル',description)
        self.assertNotIn('田中碧',description)
        self.assertNotIn('クリスタルパレス17本',description)
        self.assertEqual(data,before)

    def test_goal_pages_keep_order_and_balance_the_last_page(self):
        data=read('soccer-results/run-40249272204.json')
        narr=v2.result_narration(data)
        pages=[s['meta']['goals'] for s in narr['segments'] if s['kind']=='followup-detail']
        self.assertEqual([len(p) for p in pages],[3,2,2])
        self.assertEqual([g['minute'] for p in pages for g in p],['5','33','50','55','77','86','89'])

    def test_no_japanese_card_without_material_insight_is_held(self):
        data=read('soccer-daily/20261025.json')
        for g in data['games']:
            g.update(jp_by_side={'home':[], 'away':[]},season_players=[],reasons=[])
            for key in ('home_standing','away_standing','cl_line','relegation_line','phase','phase_source'):
                g.pop(key,None)
        with self.assertRaisesRegex(ValueError,'見どころ'):
            v2.preview_head(data)

    def test_insufficient_material_is_held(self):
        data=read('soccer-results/run-40249272204.json')
        focus=v2.result_focus(data);g=focus['game'];p=focus['lead']
        data['games']=[dict(g,goals=[],match_stats=None,players=[p])]
        p={k:v for k,v in p.items() if k not in ('shots','on_target','saves','conceded','minutes')}
        data['games'][0]['players']=[p];data['players']=[p];data.pop('preview_followup',None)
        with self.assertRaisesRegex(ValueError,'3件未満'):
            v2.result_narration(data)

    def test_japanese_card_without_insight_is_held(self):
        data=read('soccer-daily/20261022.json')
        for g in data['games']:
            g.update(season_players=[],reasons=[])
            for key in ('home_standing','away_standing','cl_line','relegation_line','phase','phase_source'):
                g.pop(key,None)
        with self.assertRaisesRegex(ValueError,'見どころ'):
            v2.preview_head(data)

    def test_metadata_does_not_require_video_encoder(self):
        import run_checks
        for script in ('upload_youtube.py','soccer_results.py'):
            self.assertNotIn('imageio_ffmpeg',run_checks._third_party(script))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
