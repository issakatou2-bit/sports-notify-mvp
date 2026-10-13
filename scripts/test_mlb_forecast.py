import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import types
import unittest
from unittest.mock import patch

import mlb_forecast as f
import generate_morning_short as g
import morning_recap as mr
import bignumber_render as bn

FIX=Path(__file__).parent/'fixtures/mlb-forecast/roundtrip.json'


class ForecastTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(FIX.read_text(encoding='utf-8'))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        for i,row in enumerate(self.data['samples']):(self.folder/f'{i}.json').write_text(json.dumps(row),encoding='utf-8')
        self.env=patch.dict(os.environ,COLLESPO_MLB_FORECAST='check');self.env.start();self.addCleanup(self.env.stop)

    def forecast(self):
        return f.expectation([self.data['game']],self.data['created_at'],self.folder)

    def history(self):
        forecast=self.forecast()
        return {'2026-09-23':dict(forecast,video_id='fixture-video',preview_day='2026-09-22')}

    def test_roundtrip_binding_and_numeric_basis(self):
        game=self.data['game'];n=dict(segments=[dict(kind='game',text='先発の紹介。',meta=dict(game_index=0))])
        out=f.decorate(n,[game],self.data['created_at'],self.folder)
        forecast=out['mlb_forecast']
        self.assertEqual(forecast['threshold'],8)
        self.assertIn('平均8.3',forecast['basis'])
        self.assertEqual(len(forecast['samples']),3)
        ledger={'daily':{'2026-09-22':dict(video_id='fixture-video',preview_binding=f.binding(out))}}
        saved=f.snapshot(out,ledger)
        result=f.answer(self.data['result'],{'2026-09-23':saved})
        self.assertTrue(result['meta']['met'])
        out['segments'][0]['text']+='改変'
        with self.assertRaises(ValueError):f.snapshot(out,ledger)

    def test_miss_no_appearance_and_wrong_game(self):
        history=self.history();data=copy.deepcopy(self.data['result'])
        data['players'][0]['so']=4
        self.assertFalse(f.answer(data,history)['meta']['met'])
        for change in ({'game_ids':['other']},{'game_ids':['900001','900002']},{'ip':'0.0','gs':0,'hits':0,'er':0,'so':0},{'so':None}):
            d=copy.deepcopy(data);d['players'][0].update(change)
            self.assertIsNone(f.answer(d,history))
        self.assertIsNone(f.answer(dict(data,players=[]),history))
        self.assertIsNone(f.answer(data,{}))
        history['2026-09-23']['preview_day']='2026-09-21'
        self.assertIsNone(f.answer(data,history))

    def test_same_day_known_and_zero_out_start(self):
        today=copy.deepcopy(self.data['samples'][2])
        today.update(date_jst='2026-09-22',updated_at='2026-09-22T01:00:00Z')
        (self.folder/'3.json').write_text(json.dumps(today))
        self.assertEqual(len(self.forecast()['samples']),4)
        result=copy.deepcopy(self.data['result']);result['players'][0].update(ip='0.0',so=0)
        self.assertEqual(f.answer(result,self.history())['meta']['actual'],0)

    def test_short_sample_and_future_and_unconfirmed(self):
        (self.folder/'2.json').unlink()
        self.assertIsNone(self.forecast())
        future=copy.deepcopy(self.data['samples'][2]);future['updated_at']='2026-09-23T01:00:00Z'
        (self.folder/'2.json').write_text(json.dumps(future))
        self.assertIsNone(self.forecast())
        game=dict(self.data['game'],home_probable=None,jp_players=['山本由伸'])
        self.assertIsNone(f.expectation([game],self.data['created_at'],self.folder))

    def test_disabled_and_no_forecast_preserve_narration(self):
        n=dict(segments=[dict(kind='game',text='先発の紹介。',meta=dict(game_index=0))])
        with patch.dict(os.environ,COLLESPO_MLB_FORECAST=''):
            self.assertIs(f.decorate(n,[self.data['game']],self.data['created_at'],self.folder),n)
            self.assertIsNone(f.answer(self.data['result'],self.history()))

    def test_actual_morning_head_and_scene(self):
        with patch.object(f,'read',return_value=self.history()), patch.object(g,'week_line',return_value=('',[])):
            narration=g.build_narration(self.data['result'],'players')
        self.assertEqual(narration['segments'][0]['kind'],'forecast_check')
        scenes=bn.scenes_from_morning(self.data['result'],narration)
        self.assertEqual(scenes[0]['head'],'昨夜の注目数字の結果')
        self.assertEqual(scenes[0]['big'],'10')
        self.assertIn('期待 8奪三振以上',scenes[0]['chips'])
        with patch.object(bn.r3,'LOOK','v4'):
            image=bn.scene(2.5,scenes[0])
        self.assertEqual(image.size,(1080,1920))
        texts=''.join(str(r.get('text','')) for r in image.info.get('v3_layout',[]))
        self.assertIn('期待',texts)
        self.assertIn('8',texts)

    def test_official_game_log_ids(self):
        log=[dict(date='2026-09-22',team=dict(id=119),game=dict(gamePk=900001),stat=dict(inningsPitched='6.0',strikeOuts=10))]
        with patch.object(mr,'fetch_game_log',return_value=log):
            context=mr.fetch_context('808967',['pitching'],'2026','2026-09-22')
        self.assertEqual(context['game_ids'],['900001'])

    def test_ps_current_route(self):
        from test_ps_program import fixture
        import ps_program as ps
        snap,ev,now=fixture(29)
        selected=next(g for d in ev['schedule']['dates'] for g in d['games']
                      if g['gamePk']==1001)
        selected['teams']['home']['probablePitcher']=dict(id=808967,fullName='Yoshinobu Yamamoto')
        program=ps.prepare(snap,ev,'forecast',now,{})
        with patch.object(f,'past',return_value=[dict(p,day=s['date_jst'],source='fixture')
                         for s in self.data['samples'] for p in s['players']]):
            changed=f.decorate_program(program,ev,now.isoformat(),ps.content_key)
        self.assertIn('mlb_forecast',changed)
        self.assertIn('mlb_forecast',ps.script(changed))
        ps.check_program(changed)

    def test_disabled_render_pixels(self):
        original=subprocess.check_output(['git','show','11035100:scripts/bignumber_render.py'],cwd=f.ROOT).decode('utf-8')
        old=types.ModuleType('original_bn');old.__file__=bn.__file__
        exec(compile(original,'original_bn','exec'),old.__dict__)
        with patch.dict(os.environ,COLLESPO_MLB_FORECAST=''):
            narration=g.build_narration(self.data['result'],'players')
            before=old.scenes_from_morning(self.data['result'],narration)
            after=bn.scenes_from_morning(self.data['result'],narration)
            self.assertEqual(before,after)
            for scene in after:
                self.assertEqual(old.scene(1,scene).tobytes(),bn.scene(1,scene).tobytes())


if __name__=='__main__':unittest.main(argv=[__file__])
