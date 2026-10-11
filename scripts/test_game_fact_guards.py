"""夜点検の実誤りを固定材料で再現。通信/LLM呼出し/公開なし。"""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import comment_actors
import game_fact_guard as gg
import local_voices as lv
import mlb_buzz as buzz
import numbers_material as nm
import soccer_venue as venue
import verify_numbers

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = json.loads((ROOT/'scripts/fixtures/fact-guards/night_failures.json').read_text(encoding='utf-8'))


def series():
    return buzz.series_facts(FIX['game'], FIX['series_status_fixture'], FIX['result'])


def dialogue(*lines, players=(), ps=None, panel='score'):
    return {'mode':'voices', 'game_material':{'players':list(players), 'series':ps or {}},
            'segments':[{'text':line,'panel':panel} for line in lines]}


class GameFacts(unittest.TestCase):
    def test_saved_box_keeps_zero_hits_one_run(self):
        players = buzz.batting_facts(FIX['box'])
        self.assertEqual((players[0]['hits'], players[0]['runs']), (0,1))
        self.assertEqual(players[0]['name'], '大谷翔平')
        self.assertIn('大谷', players[0]['aliases'])
        bad = dialogue('大谷は0安打です。', FIX['bad_lines'][2], players=players)
        self.assertTrue(gg.check(bad))
        self.assertFalse(gg.check(dialogue('大谷は0安打ですが1得点です。', players=players)))
        self.assertTrue(gg.check(dialogue('大谷は2得点です。', players=players)))

    def test_unknown_runs_is_not_zero_and_pitcher_is_separate(self):
        p={'name':'大谷翔平','type':'batter','runs':None}
        self.assertTrue(gg.check(dialogue('大谷翔平は無得点です。', players=[p])))
        self.assertFalse(gg.check(dialogue('大谷翔平は無得点です。', players=[dict(p,runs=0)])))
        self.assertFalse(gg.check(dialogue('山本由伸は無失点です。', players=[{'name':'山本由伸','type':'pitcher','r':1}])))

    def test_numbers_material_preserves_runs_and_daily_comparison(self):
        p={'name':'大谷翔平','type':'batter','runs':1,'hits':0,'headline':'3打数0安打'}
        evidence=gg.material({'players':[{'name':p['name'],'_row':p}]}, 'numbers')
        self.assertEqual(evidence['players'][0]['runs'],1)
        self.assertEqual(nm._numbers(p)['得点'],1)
        d=dialogue('大谷は無得点です。', players=evidence['players'])
        self.assertTrue(verify_numbers.check(d))  # 季節のfactsが空でも、今回の材料は検査する

    def test_official_fourth_game_states(self):
        ps=series()
        self.assertEqual(ps['game_number'],4)
        self.assertEqual(ps['before_by_team']['ホワイトソックス'],{'wins':2,'losses':1})
        self.assertEqual(ps['after_by_team']['ホワイトソックス'],{'wins':2,'losses':2})
        self.assertFalse(ps['is_decider'])
        self.assertEqual(ps['next_game_number'],5)
        for line in FIX['bad_lines'][:2]:
            self.assertTrue(gg.check(dialogue(line,ps=ps)))
        self.assertTrue(gg.check(dialogue('第5戦で村上が先制した。',ps=ps)))
        self.assertTrue(gg.check(dialogue('シリーズは2勝2敗。','その試合で先制した。',ps=ps,panel='news')))

    def test_before_after_next_and_necessary_win_are_distinct(self):
        ps=series()
        for line in ['第4戦の試合前はホワイトソックスが2勝1敗でした。',
                     '第4戦の試合後は2勝2敗です。次の第5戦で決着します。',
                     'ガーディアンズは負けたら終わりの第4戦でした。',
                     'ホワイトソックスは試合前2勝1敗。ガーディアンズは1勝2敗。']:
            with self.subTest(line=line):
                self.assertFalse(gg.check(dialogue(line,ps=ps)))
        self.assertTrue(gg.check(dialogue('ホワイトソックスは負けたら終わりの第4戦でした。',ps=ps)))

    def test_zero_hits_does_not_deny_runs_double_negative_or_other_batter(self):
        players=buzz.batting_facts(FIX['box'])
        self.assertFalse(gg.check(dialogue('大谷は無得点ではない。',players=players)))
        self.assertFalse(gg.check(dialogue('別の打者は無得点です。',players=players)))
        self.assertTrue(gg.check(dialogue('大谷は得点していない。',players=players)))

    def test_missing_series_leader_is_not_guessed_from_todays_winner(self):
        ss=dict(FIX['series_status_fixture'], wins=3,losses=1,isTied=False)
        ps=buzz.series_facts(FIX['game'], ss, FIX['result'])
        self.assertNotIn('before_by_team',ps)
        ss['winningTeam']={'id':145}  # 今日敗れたCWSがシリーズではリードしている
        ps=buzz.series_facts(FIX['game'],ss,FIX['result'])
        self.assertEqual(ps['after_by_team']['ホワイトソックス']['wins'],3)
        ss['winningTeam']={'id':999}
        self.assertNotIn('before_by_team',buzz.series_facts(FIX['game'],ss,FIX['result']))

    def test_two_way_uses_batting_runs(self):
        p={'name':'大谷翔平','type':'two_way','hits':0,'batting':{'runs':1,'hits':0}}
        row=gg.material({'players':[{'name':p['name'],'_row':p}]},'numbers')['players'][0]
        self.assertEqual(row['runs'],1)
        self.assertTrue(gg.check(dialogue('大谷は無得点です。',players=[row])))

    def test_strict_cli_rejects_actual_failure(self):
        d=dialogue(FIX['bad_lines'][1],ps=series())
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'dialogue.json'
            p.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
            run=subprocess.run([sys.executable,str(ROOT/'scripts/verify_numbers.py'),'--dialogue',str(p),'--strict'],
                               capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(run.returncode,1)
        self.assertIn('不一致',run.stdout)


class ActorsAndVenue(unittest.TestCase):
    def test_fan_and_ambiguous_yankee(self):
        # 原文Yankeeと実誤訳は点検記録。原文全体は未保存のため短い試験文で文脈を再現。
        self.assertTrue(comment_actors.check('Thanks to that Yankee',FIX['bad_lines'][3],
                                            'The fan was ejected after fan interference.'))
        self.assertTrue(comment_actors.check('The crowd helped us win','選手が勝利を助けた'))
        self.assertFalse(comment_actors.check('The crowd cheered the player','観客が選手に声援を送った'))
        self.assertFalse(comment_actors.check('The Yankees player helped us win','ヤンキースの選手が勝たせてくれた'))
        self.assertFalse(comment_actors.check('Thanks to that Yankee','ヤンキースの人のおかげ'))
        self.assertFalse(comment_actors.check('The crowd cheered Ohtani','大谷選手に歓声が上がった'))
        self.assertFalse(comment_actors.check('The crowd cheered Ohtani','大谷選手は声援を受けた'))

    def test_translation_path_drops_wrong_parent_but_keeps_good_item(self):
        response=NS(stop_reason='end_turn',content=[NS(type='text',text='1|称賛|'+FIX['bad_lines'][3]+'\n2|中立|観客が退場になった\n3|称賛|大谷は最高')])
        client=NS(messages=NS(create=lambda **kw:response))
        items=[{'title':'Thanks to that Yankee','reply_texts':['The fan was ejected']},
               {'title':'Ohtani is great','reply_texts':[]}]
        with patch.object(lv.token_log,'allowed',return_value=True), patch.object(lv.token_log,'record'):
            out=lv.translate(client,copy.deepcopy(items))
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]['ja'],'大谷は最高')

    def test_lens_home_from_material_and_aliases(self):
        g=FIX['soccer']
        self.assertEqual(venue.roles(g)['home'],'RC Lens')
        self.assertIn('RC Lens',venue.instruction(g))
        for line in [FIX['soccer_bad'],'リヨンがランスを迎える。','OLは本拠地でLensと対戦する。','Lensは敵地でOLと対戦する。']:
            with self.subTest(line=line): self.assertTrue(venue.check(line,g))
        for line in ['LensがOLを迎える。','リヨンは敵地でランスと対戦する。','RC Lens対OLです。',
                     'OLはLensに迎えられる。','Lensは敵地のOLを迎える。']:
            with self.subTest(line=line): self.assertFalse(venue.check(line,g))
        self.assertFalse(venue.check('スタッド・ランスがOLを迎える。',dict(g,home_team_name='Stade de Reims')))

    def test_neutral_or_unknown_is_not_inferred_from_order(self):
        self.assertTrue(venue.check('OLがLensを迎える。',{'matchup':'OL vs Lens'}))
        self.assertTrue(venue.check('OLの本拠地です。',dict(FIX['soccer'],neutral_site=True)))
        self.assertIn('中立地',venue.instruction(dict(FIX['soccer'],neutral_site=True)))

    def test_engine_uses_same_venue_guard(self):
        sys.path.insert(0,str(ROOT))
        import notability_engine as ne
        self.assertEqual(ne.host_reversed(FIX['soccer_bad'],FIX['soccer']),venue.check(FIX['soccer_bad'],FIX['soccer']))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
