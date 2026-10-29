"""連番・確定できる局面・表の字サイズ・干渉・停止を固定材料で検査。"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import asset_v4_cards as old
import game_ui_short as ui
import generate_asset_video as asset
import review_render_v3 as r3
from preview_game_ui_short import scenes

ROOT=Path(__file__).resolve().parents[1]


def fixture(name='ws849804'):
    return json.loads((ROOT/'scripts/fixtures/game-ui-short'/f'{name}.json').read_text(encoding='utf-8'))['topic']


class GameUI(unittest.TestCase):
    def setUp(self):
        self.look=patch.multiple(r3,LOOK='v4',CONTENT_BOTTOM=1150,SOURCE_BOTTOM=1218);self.look.start()
        r3.set_program_clock(None);r3.set_caption('',0,0)

    def tearDown(self):
        r3.set_program_clock(None);r3.set_caption('',0,0);self.look.stop()

    def test_actual_order_and_removed_scenes(self):
        for name in ('ws849804','ordinary849802','few849802'):
            spec=fixture(name);segments=scenes(spec)
            self.assertEqual([s['meta']['game_ui_number'] for s in segments],list(range(1,len(segments)+1)))
        segments=scenes(fixture())
        doubled=[segments[0],copy.deepcopy(segments[0]),segments[-1]]
        doubled[0]['meta']['screen']=doubled[1]['meta']['screen']='same'
        got=ui.annotate(doubled,fixture())
        self.assertEqual([s['meta']['game_ui_number'] for s in got],[1,1,2])
        spec=fixture()
        spec['game_v4']['score']['innings'].append({'num':10,'away':0,'home':0})
        got=scenes(spec)
        self.assertEqual([s['meta']['game_ui_number'] for s in got],[1,2,4,5])

    def test_result_panel_never_repeats_series_fact(self):
        for name in ('ordinary849802','few849802'):
            spec=fixture(name)
            for state,tag,series in (
                ('2勝0敗','ワールドシリーズ2勝0敗','シリーズはブリュワーズの2勝0敗'),
                ('1勝0敗','ワールドシリーズ先勝','シリーズはブリュワーズの1勝0敗'),
                ('4勝0敗','ワールドシリーズ突破','ブリュワーズが4勝0敗でワールドシリーズ突破'),
            ):
                with self.subTest(name=name,tag=tag):
                    spec['v3']['tag']=tag
                    spec['items'][0][1]=spec['items'][0][1].split('　シリーズは')[0].split('　ブリュワーズが')[0]+'　'+series
                    with patch.object(ui,'text',wraps=ui.text) as drawn:
                        ui.frame(1,'intro',{},spec,'PSの話題')
                    notes=[call.args[3] for call in drawn.call_args_list if 900<=call.args[2]<=1005]
                    self.assertEqual(notes,[series])
                    self.assertEqual(sum(line.count(state) for line in notes),1)

    def test_result_panel_keeps_distinct_fact_and_single_available_line(self):
        spec=fixture()
        with patch.object(ui,'text',wraps=ui.text) as drawn:
            ui.frame(1,'intro',{},spec,'PSの話題')
        notes=[call.args[3] for call in drawn.call_args_list if 900<=call.args[2]<=1005]
        self.assertEqual(notes,[spec['v3']['tag'],'シリーズはブリュワーズの3勝0敗'])
        spec['items'][0][1]=spec['items'][0][1].split('　シリーズは')[0]
        self.assertEqual(ui.result_notes(spec,ui.cover._game_result(spec['items'])),[spec['v3']['tag']])
        spec['v3'].pop('tag')
        self.assertEqual(ui.result_notes(spec,ui.cover._game_result(spec['items'])),[])

    def test_red_is_decisive_and_once(self):
        self.assertEqual(ui.series_status(fixture()),'世界一に王手')
        self.assertIsNone(ui.series_status(fixture('ordinary849802')))
        for score,game,expect in [('2勝0敗',2,None),('4勝0敗',4,'世界一'),('5勝0敗',5,None)]:
            spec=fixture();spec['items'][0][1]=spec['items'][0][1].replace('3勝0敗',score)
            spec['label']=f'ワールドシリーズ第{game}戦'
            self.assertEqual(ui.series_status(spec),expect)
        spec=fixture();spec['items'][0][1]=spec['items'][0][1].replace('シリーズはブリュワーズ','シリーズはレイズ')
        self.assertIsNone(ui.series_status(spec))
        spec=fixture();segments=scenes(spec);bands=[]
        for seg in segments:
            im=ui.frame(1,seg['kind'],seg['meta'],spec,'PSの話題')
            if im.info['game_ui']['status']:bands.append(im.info['game_ui']['number'])
        self.assertEqual(bands,[4])

    def test_scoreboard_pixels_and_fonts_unchanged(self):
        spec=fixture();before=old.score(2,spec,'PSの話題')
        after=ui.frame(2,'list',{'start':0,'count':1,'game_ui_number':2},spec,'PSの話題')
        # 角丸の外の背景の時間変化・旧版の光は表の字/罫線ではない。
        box=(r3.LEFT+3,360,r3.SAFE_RIGHT-3,803)
        self.assertEqual(before.crop(box).tobytes(),after.crop(box).tobytes())
        def sizes(im):
            return [(e['text'],e['box'],e.get('v4_font')) for e in im.info['v3_layout'] if 360<=e['box'][1]<=802]
        self.assertEqual(sizes(before),sizes(after))
        self.assertIn(46,[v[2] for v in sizes(after)])
        self.assertIn(76,[v[2] for v in sizes(after)])

    def test_still_content_after_slide_and_lower_pixels(self):
        spec=fixture()
        r3.set_program_clock(1)
        for seg in scenes(spec):
            a=ui.frame(.3,seg['kind'],seg['meta'],spec,'PSの話題')
            b=ui.frame(2,seg['kind'],seg['meta'],spec,'PSの話題')
            self.assertEqual(a.crop((0,236,1080,1029)).tobytes(),b.crop((0,236,1080,1029)).tobytes())
            # 入りで字幕・キャラ・出典・帯を動かさない（同じ時計・話者）。
            start=ui.frame(.1,seg['kind'],seg['meta'],spec,'PSの話題')
            settled=ui.frame(1,seg['kind'],seg['meta'],spec,'PSの話題')
            self.assertEqual(start.info.get('duo_portraits'),settled.info.get('duo_portraits'))
            self.assertEqual(start.crop((0,1040,1080,1920)).tobytes(),settled.crop((0,1040,1080,1920)).tobytes())

    def test_complete_saved_game_also_keeps_optional_cards(self):
        spec=json.loads((ROOT/'scripts/fixtures/game-ui-short/ws849804.json').read_text(encoding='utf-8'))['full_topic']
        for i,(head,body) in enumerate(spec['items']):
            im=ui.frame(1,'list',{'start':i,'count':1,'game_ui_number':i+2},spec,'PSの話題')
            self.assertEqual(im.info['game_ui']['number'],i+2)
        # 描画検査は閉じ括弧や語を重ねず、既存の引用符の装飾だけを許す。

    def test_overflow_overlap_and_face_stop(self):
        spec=fixture();im=ui.frame(1,'intro',{},spec,'PSの話題')
        for entry in ({'role':'text','box':[900,500,1100,550],'text':'overflow'},
                      {'role':'text','box':im.info['duo_portraits'][0]['box'],'text':'face'},
                      {'role':'text','box':[80,550,300,700],'text':'overlap'}):
            bad=im.copy();bad.info=copy.deepcopy(im.info);bad.info['v3_layout'].append(entry)
            with self.assertRaises(ValueError):ui.validate(bad)
        spec['v3']['tag']='長すぎる札'*100
        with self.assertRaisesRegex(ValueError,'字幅超過|札の幅'):
            ui.frame(1,'intro',{},spec,'PSの話題')

    def test_other_topics_use_original_route(self):
        spec={'style':'v3','spotlight':True,'items':[],'intro':'投手の成績です。'}
        with patch.dict(asset.LIST_TOPICS,{'x':spec}),patch.object(ui,'frame',side_effect=AssertionError('game route leaked')),patch.object(r3,'intro',side_effect=RuntimeError('original route')):
            with self.assertRaisesRegex(RuntimeError,'original route'):
                asset.render_v3(1,'intro',{},spec,'x')

    def test_long_matchup_and_optional_numeric_cards(self):
        import v3_rules
        spec=json.loads((ROOT/'scripts/fixtures/v3-rules/game-v4.json').read_text(encoding='utf-8'))['topics'][1]
        im=ui.frame(1,'intro',{'game_ui_number':1},spec,'PSの話題')
        texts=[e for e in im.info['v3_layout'] if e.get('text') in ('ガーディアンズ','ホワイトソックス') and 450<=e['box'][1]<=510]
        self.assertEqual({e['v4_font'] for e in texts},{44})
        self.assertGreater(len({e['box'][1] for e in texts}),1)
        for i,(head,body) in enumerate(spec['items']):
            for page in range(ui.item_pages(spec,head,body)):
                im=ui.frame((page+.5)*20/ui.item_pages(spec,head,body),'list',
                            {'start':i,'count':1,'game_ui_number':i+2},spec,'PSの話題')
                self.assertFalse(v3_rules.check_spacing(im))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
