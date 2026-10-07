"""今後に生きる決まり。6種類のv3を固定材料で毎回検査する。"""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bignumber_render as bn
import daily_v3
import generate_asset_video as asset
import generate_morning_short as g
import ps_program as ps
import ps_unified_v3 as unified
import review_render_v3 as r3
import v3_rules as rules
import v3_slot_render as common

ROOT=Path(__file__).resolve().parents[1]
ENV={'COLLESPO_PLAYERS_DESIGN':'bignumber','COLLESPO_COMMENTS_DESIGN':'comments',
     'COLLESPO_PRESS_DESIGN':'v3','COLLESPO_PS_DESIGN':'v3'}


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def daily_cases():
    cases=[]
    data=read('scripts/fixtures/bignumber/morning_recap.json')
    data['players']=g.sort_players(data['players'])
    with patch.dict(os.environ,ENV),patch.object(g,'week_line',return_value=('',[])):
        nar=g.build_narration(data,'players')
    scenes=bn.scenes_from_morning(data,nar)
    cases.append(dict(name='players',exclude='morning',segments=nar['segments'],multi=True,
                      frames=[lambda t,s=s:bn.scene(t,s) for s in scenes],quotes=[]))
    for mode,filename in [('voices','local_voices-preview.json'),('press','local_reporters-preview.json')]:
        material=read('scripts/fixtures/comment/'+filename)
        data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}
        with patch.dict(os.environ,ENV):
            nar=g.build_narration(data,mode);design=daily_v3.prepare(data,nar,mode)
        quotes=[v['said'] for s in nar['segments'] for v in s['meta'].get('quote_rows',[]) if v.get('read') and not v.get('fact')]
        cases.append(dict(name=mode,exclude='morning_'+mode,segments=nar['segments'],multi=True,
                          frames=[lambda t,s=s,d=design:daily_v3.frame(t,s,d,20) for s in nar['segments']],quotes=quotes))
    saved=read('scripts/fixtures/ps-design/2026-10-07.json')
    for slot in ('forecast','situation'):
        with patch.dict(os.environ,ENV):
            program=ps.prepare(saved['snapshot'],saved['evidence'],slot,datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        ps.check_program(program)
        cards=[s['meta']['card'] for s in program['segments']]
        cases.append(dict(name=slot,exclude='daily' if slot=='forecast' else 'postseason',segments=program['segments'],multi=True,
                          frames=[lambda t,c=c:unified.frame(t,c) for c in cards],quotes=[v['quote'] for c in cards for v in c.get('items',[]) if 'quote' in v]))
    return cases


def asset_cases():
    cases=[]
    for spec in read('scripts/fixtures/v3-rules/assets.json')['topics']:
        key=spec['key'];spec=copy.deepcopy(spec)
        with patch.dict(asset.LIST_TOPICS,{key:spec}):
            nar=asset.build_narration(key)
        frames=[]
        for seg in nar['segments']:
            def render(t,s=seg,v=spec,k=key):
                with patch.dict(asset.LIST_TOPICS,{k:v}):
                    return asset.render_v3(t,s['kind'],s['meta'],v,k)
            frames.append(render)
        cases.append(dict(name='asset:'+key,exclude=spec.get('lineup_kind',''),segments=nar['segments'],multi=bool(spec.get('teams') or spec.get('series_key') or spec.get('game') or not spec.get('team_id')),
                          frames=frames,quotes=[b for _,b in spec['items'] if str(b).startswith('「')],spec=spec))
    return cases


class V3Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=daily_cases()+asset_cases()

    def test_multiple_clubs_use_brand_background(self):
        for case in self.cases:
            if not case['multi']:continue
            for draw in case['frames']:
                with self.subTest(slot=case['name']),patch.object(r3,'background',wraps=r3.background) as background:
                    draw(3)
                    self.assertTrue(background.call_args_list)
                    self.assertTrue(all(c.args[1] is None for c in background.call_args_list),background.call_args_list)

    def test_quotes_appear_once_and_disclaimer_is_not_spoken(self):
        for case in self.cases:
            with self.subTest(slot=case['name']):
                self.assertFalse(rules.check_quotes(case['quotes']))
                self.assertNotIn('コレスポの見解ではありません',''.join(s['text'] for s in case['segments']))
        self.assertTrue(rules.check_quotes(['「同じ引用」','同じ引用']))

    def test_every_frame_and_card_has_safe_positions(self):
        for case in self.cases:
            for index,draw in enumerate(case['frames']):
                for t in (.1,3,7,11,15,19):
                    with self.subTest(slot=case['name'],screen=index,time=t):
                        self.assertFalse(rules.check_layout(draw(t)))
        bad=r3.background(0,None)
        r3.record_box(bad,'text',(0,300,1000,1300),'はみ出し')
        self.assertTrue(rules.check_layout(bad))

    def test_all_pages_keep_complete_cards_and_text(self):
        rows=[('長い引用','「'+'全文を残して安全域でページを分ける。'*18+'」')]+[(f'DS 第{i}戦','2勝　大谷翔平・佐々木朗希・山本由伸') for i in range(1,6)]
        spec={'heading':'全画面の検査'};pages=common.paginate(spec,rows)
        self.assertGreater(len(pages),1)
        self.assertEqual({cell['row'] for p in pages for cell in p},set(range(len(rows))))
        for i in range(len(pages)):
            self.assertFalse(rules.check_layout(common.frame(i*4+3,spec,rows,'検査')))
        self.assertFalse(common.check_pages(spec,rows))

    def test_marks_require_an_explanation(self):
        for case in self.cases:
            with self.subTest(slot=case['name']),patch.object(r3.ImageDraw.ImageDraw,'ellipse') as ellipse:
                for draw in case['frames']:draw(3)
                ellipse.assert_not_called()
            if case.get('spec'):
                self.assertFalse(rules.check_marks(case['spec']))
        spec={'v3':{'chips':[{'label':'ドジャース','score':'2勝','win':True}]}}
        with patch.object(r3.ImageDraw.ImageDraw,'ellipse') as ellipse:
            r3.intro(3,spec,'予告');ellipse.assert_not_called()
        self.assertFalse(any(c[1]=='pop' for c in r3.cues('intro',spec)))
        self.assertTrue(rules.check_marks({'v3':{'chips':[{'label':'○','score':'2勝'}]}}))

    def test_each_slot_uses_shared_outro_text_renderer_and_cues(self):
        for case in self.cases:
            self.assertEqual(case['segments'][-1]['text'],r3.OUTRO_TEXT,case['name'])
            with patch.object(r3,'outro',return_value=object()) as outro:
                case['frames'][-1](3)
                outro.assert_called_once()
                self.assertEqual(outro.call_args.args[2],case['exclude'])
                self.assertIn('VOICEVOX',outro.call_args.args[3])
        sentinel=[(0,'transition','b',-6)]
        with patch.object(r3,'outro_cues',return_value=sentinel) as cues:
            self.assertEqual(bn.cues({'kind':'outro'}),sentinel);cues.assert_called_with('morning')
            for exclude in ('daily','postseason'):
                self.assertEqual(unified.cues({'outro':True,'lineup_kind':exclude}),sentinel);cues.assert_called_with(exclude)
            for mode in ('voices','press'):
                with patch('sound_mix.mix_file',return_value='mixed'):
                    daily_v3.mix('audio',[{'kind':'outro','speaker':2}],[5],{'mode':mode},ROOT/'build')
                cues.assert_called_with('morning_'+mode)
            r3.cues('outro',{'lineup_kind':'asset'});cues.assert_called_with('asset')
        # 動画のPS切替処理が、共通の締めへ日程の帯を重ねない。
        closing=r3.outro(3,{},'daily')
        with patch.object(r3,'ticker') as ticker:
            raw=unified.transition(closing.tobytes(),closing,6,6,30,'明日の試合')
            ticker.assert_not_called()
        self.assertEqual(raw,closing.tobytes())

    def test_material_speech_numbers_match_its_items(self):
        for case in self.cases:
            if case.get('spec'):
                self.assertFalse(rules.check_speech(case['spec'],case['spec']['items']))
        spec=copy.deepcopy(next(c['spec'] for c in self.cases if c.get('spec',{}).get('spotlight')))
        spec['speech']['この試合の投球']='99奪三振でした。'
        self.assertTrue(rules.check_speech(spec,spec['items']))


if __name__=='__main__':unittest.main(argv=[__file__])
