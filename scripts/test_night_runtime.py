"""㉙の定時経路。欠測/曖昧さは行を外し、取得値との矛盾だけ止める。"""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import backstage_guard as backstage
import game_fact_guard as facts
import generate_dialogue as gd
import numbers_material as nm
import soccer_venue as venue
import test_game_fact_guards as fixtures

ROOT=pathlib.Path(__file__).resolve().parent.parent
FIX=json.loads((ROOT/'scripts/fixtures/fact-guards/runtime_false_positives.json').read_text(encoding='utf-8'))
PLAYERS=[{'name':'大谷翔平','aliases':['大谷'],'type':'batter','hits':0,'runs':1},
         {'name':'鈴木誠也','type':'batter','runs':2}]


class Runtime(unittest.TestCase):
    def test_score_false_positives(self):
        for line in FIX['score_ok']:
            with self.subTest(line=line):
                d=fixtures.dialogue(line,players=PLAYERS)
                self.assertFalse(facts.check(d))
                self.assertFalse(facts.review(d)['omit'])

    def test_season_sentence_does_not_hide_current_contradiction(self):
        d=fixtures.dialogue('大谷は今季100得点です。大谷はこの試合2得点です。',players=PLAYERS)
        self.assertTrue(facts.check(d))

    def test_series_false_positives(self):
        for line in FIX['series_ok']:
            with self.subTest(line=line):
                self.assertFalse(facts.check(fixtures.dialogue(line,ps=fixtures.series())))
        self.assertTrue(facts.check(fixtures.dialogue('地区シリーズ第5戦でした。',ps=fixtures.series())))

    def test_unknown_value_omits_only_assertion_and_logs(self):
        d=fixtures.dialogue('大谷は無得点です。','安打はありませんでした。',players=[dict(PLAYERS[0],runs=None)])
        logs=[]
        clean,errors=facts.prepare(d,log=logs.append)
        self.assertFalse(errors)
        self.assertEqual([s['text'] for s in clean['segments']],['安打はありませんでした。'])
        self.assertEqual(d['segments'][0]['text'],'大谷は無得点です。')
        self.assertIn('未取得',logs[0])

    def test_unavailable_series_record_is_not_known_contradiction(self):
        ps=dict(fixtures.series(),before_by_team={})
        clean,errors=facts.prepare(fixtures.dialogue('試合前は2勝1敗でした。','第4戦です。',ps=ps),log=lambda _:None)
        self.assertFalse(errors)
        self.assertEqual(len(clean['segments']),1)

    def test_known_contradiction_still_stops(self):
        d=fixtures.dialogue('大谷は無得点です。','大谷は2得点です。',players=PLAYERS)
        clean,errors=facts.prepare(d,log=lambda _:None)
        self.assertEqual(len(errors),2)
        self.assertEqual(len(clean['segments']),2)  # 矛盾を黙って成功に変えない

    def test_whole_uncertain_script_uses_available_hits(self):
        d=fixtures.dialogue('大谷は無得点です。',players=[dict(PLAYERS[0],runs=None)])
        clean,errors=facts.prepare(d,log=lambda _:None)
        self.assertFalse(errors)
        self.assertEqual([s['text'] for s in clean['segments']],['大谷翔平は0安打です。'])
        self.assertFalse(facts.check(clean))

    def test_not_knowing_pitch_type_is_not_a_production_excuse(self):
        import longform_editorial
        d=fixtures.dialogue('打者には球種が分からないというコメントです。',players=PLAYERS)
        d['mode']='numbers'
        clean,errors=facts.prepare(d,log=lambda _:None)
        self.assertFalse(errors)
        self.assertFalse(longform_editorial.check(clean))
        self.assertEqual(len(clean['segments']),1)
        self.assertTrue(clean['fact_review']['warnings'])

    def test_generic_welcome_is_not_a_venue_claim(self):
        for game in (fixtures.FIX['soccer'],{'matchup':'OL vs Lens'},dict(fixtures.FIX['soccer'],neutral_site=True)):
            for line in FIX['venue_ok']:
                with self.subTest(game=game,line=line):self.assertFalse(venue.check(line,game))
        self.assertTrue(venue.check('OLがLensを迎える。',fixtures.FIX['soccer']))

    def test_backstage_normal_words_and_diagnostics(self):
        for line in FIX['backstage_ok']:self.assertFalse(backstage.violations(line))
        dirty=NS(content=[NS(type='text',text='めたん：材料にない。\nめたん：大谷は1得点です。')])
        audit={}
        clean=backstage.guard_response(lambda:dirty,lambda:dirty,label='fixture',mode='lines',diagnostics=audit)
        self.assertTrue(audit['filtered'])
        self.assertEqual(gd.parse(backstage.response_text(clean))[0]['text'],'大谷は1得点です。')

    def test_all_backstage_dialogue_uses_verified_values_and_still_writes(self):
        row={'name':'大谷翔平','type':'batter','hits':0,'runs':1}
        m={'players':[{'name':row['name'],'type':'batter','_row':row}], 'rare':[],'trends':[]}
        ps={'jp1':{'type':'star','name':row['name'],'menu':'今日の成績'}}
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            out=pathlib.Path(td)/'dialogue.json'
            with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}), \
                 patch.object(sys,'argv',['dialogue','--mode','numbers','--out',str(out)]), \
                 patch.object(gd,'anthropic',NS(Anthropic=lambda **_:object())), \
                 patch.object(gd,'_ask',side_effect=backstage.BackstageError('fixture')), \
                 patch.object(nm,'load',return_value=m),patch.object(nm,'has_enough',return_value=True), \
                 patch.object(nm,'outline',return_value='fixture'),patch.object(nm,'facts',return_value='fixture'), \
                 patch.object(nm,'panels',return_value=ps),patch.object(nm,'meta',return_value={'mode':'numbers'}), \
                 patch.object(nm,'checkable',return_value={row['name']:{'安打':0,'得点':1}}), \
                 patch.object(gd.token_log,'allowed',return_value=True),patch.object(gd.token_log,'summary_line',return_value='fixture'):
                self.assertEqual(gd.main(),0)
            saved=json.loads(out.read_text(encoding='utf-8'))
        text=''.join(s['text'] for s in saved['segments'])
        self.assertIn('0安打',text);self.assertIn('1得点',text)
        self.assertFalse(backstage.violations(text))
        self.assertFalse(facts.check(saved))

    def test_strict_cli_omits_unknown_but_never_saves_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'dialogue.json'
            args=[sys.executable,str(ROOT/'scripts/verify_numbers.py'),'--dialogue',str(p),'--strict','--omit-unsupported']
            d=fixtures.dialogue('大谷は無得点です。','大谷は0安打です。',players=[dict(PLAYERS[0],runs=None)])
            p.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
            run=subprocess.run(args,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(len(json.loads(p.read_text(encoding='utf-8'))['segments']),1)
            d=fixtures.dialogue('大谷は無得点です。',players=PLAYERS)
            original=json.dumps(d,ensure_ascii=False)
            p.write_text(original,encoding='utf-8')
            run=subprocess.run(args,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(run.returncode,1)
            self.assertEqual(p.read_text(encoding='utf-8'),original)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
