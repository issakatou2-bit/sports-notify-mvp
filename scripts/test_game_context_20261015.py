"""10/15公開長編の時点混同と材料欠落の回帰例。通信なし。"""
import copy
import json
from pathlib import Path
import unittest
import game_fact_guard as guard
FIX=json.loads((Path(__file__).parent/'fixtures/fact-guards/20261015_numbers.json').read_text(encoding='utf-8'))
class GameContext(unittest.TestCase):
    def dialogue(self,text,material=None):
        return {'mode':'numbers','segments':[{'text':text,'panel':'race'}],
                'game_material':guard.material(material or FIX,'numbers')}
    def test_publication_incident(self):
        for name in ('大谷','大谷翔平','ドジャース'):
            with self.subTest(name=name):
                self.assertTrue(guard.check(self.dialogue(f'負ければ終わりの試合で、{name}が3回出塁したのだ。')))
        self.assertTrue(guard.check(self.dialogue('大谷は負けたら敗退の試合で1安打を打った。')))
    def test_future_negation_and_unrelated_subject(self):
        for text in ('次の試合はドジャースが負ければ終わりです。',
                     '明日の負ければ終わりの試合で、大谷が出塁できるか。',
                     '負ければ終わりの試合ではなかった。大谷は3出塁した。',
                     '負ければ終わりの試合で、大谷が3回出塁したの？',
                     'ドジャースは0勝3敗。今日の大谷は3出塁した。',
                     '大谷は負ければ終わりの試合で出塁したわけではない。',
                     '村上は負ければ終わりの試合で3回出塁した。'):
            with self.subTest(text=text):self.assertFalse(guard.check(self.dialogue(text)))
    def test_missing_stale_and_late_are_not_guessed(self):
        for key,value in (('date','2026-10-14'),('series',[])):
            m=copy.deepcopy(FIX);m['race'][key]=value
            self.assertFalse(guard.check(self.dialogue('負ければ終わりの試合で、大谷が3回出塁した。',m)))
        for played,need in ((4,4),(5,4),(None,4),(3,None)):
            m=copy.deepcopy(FIX);m['race']['series'][0].update(played=played,need=need)
            self.assertFalse(guard.check(self.dialogue('負ければ終わりの試合で、大谷が3回出塁した。',m)))
    def test_serialized_runs_and_missing(self):
        m=copy.deepcopy(FIX);m['players'][0]['game_facts']['runs']=1
        d=self.dialogue('大谷は無得点です。',m)
        self.assertEqual(d['game_material']['players'][0]['runs'],1)
        self.assertTrue(guard.check(d))
        m['players'][0]['game_facts']['runs']=None
        self.assertEqual(guard.review(self.dialogue('大谷は無得点です。',m))['omit'],[1])
if __name__=='__main__':unittest.main(argv=[__file__])
