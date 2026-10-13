"""終了前/鮮度/二重投稿/未知の成績/決勝点を固定材料で検査。"""
import copy
import json
from pathlib import Path
import unittest

import soccer_now as now

ROOT = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def setUp(self):
        self.boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        self.summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        self.clock = now.results.utc('2026-09-20T17:15:00Z')

    def test_saved_finished(self):
        data, errors = now.build(self.boards,self.summaries,self.clock)
        self.assertFalse(errors); self.assertEqual(len(data),1)
        g = data[0]['games'][0]
        self.assertEqual(g['id'],'401876452')
        self.assertEqual(g['winner_goal']['side'],'home')
        self.assertEqual(data[0]['players'][0]['contribution'],2)
        self.assertIsNone(data[0]['players'][0]['minutes'])
        self.assertEqual(g['rank_changes'],[])

    def test_not_finished_future_stale_duplicate(self):
        for clock in ('2026-09-20T17:10:00Z','2026-09-20T18:12:00Z'):
            data,_ = now.build(self.boards,self.summaries,now.results.utc(clock))
            self.assertEqual(data,[])
        self.assertEqual(now.build(self.boards,self.summaries,self.clock,{'401876452':{'status':'pending'}})[0],[])
        b = copy.deepcopy(self.boards)
        for board in b.values():
            for e in board['events']: e['competitions'][0]['status']['type']['completed'] = False
        self.assertEqual(now.build(b,self.summaries,self.clock)[0],[])

    def test_unknown_and_goal_sequence(self):
        d,_ = now.build(self.boards,self.summaries,self.clock); g = d[0]['games'][0]
        g['players'][0]['goals'] = None
        summary = self.summaries[g['id']].get('summary',self.summaries[g['id']])
        self.assertIsNone(now.enrich(g,summary)['players'][0]['contribution'])
        g['goals_complete'] = False
        self.assertIsNone(now.enrich(g,summary)['winner_goal'])

    def test_quote_match_and_review(self):
        d,_ = now.build(self.boards,self.summaries,self.clock); d = d[0]
        f = json.loads((ROOT/'scripts/fixtures/soccer-now/voices.json').read_text(encoding='utf8'))
        self.assertEqual(now.attach_voices(d,f['video'],f['comments'],sample=True)['voices'],[])
        for v in f['comments']:
            v['semantic_review'] = dict.fromkeys(('noncritical','no_abuse','faithful','actors','names'),True)
            v['semantic_review']['sha256'] = now.voices.review_hash(v)
        now.attach_voices(d,f['video'],f['comments'],sample=True)
        self.assertEqual(len(d['voices']),3)
        f['comments'][0]['ja'] = '上田は99得点'
        now.attach_voices(d,f['video'],f['comments'],sample=True)
        self.assertEqual(len(d['voices']),2)
        self.assertTrue(d['sample_fictional'])

    def test_watch_window_and_gates(self):
        e = next(e for b in self.boards.values() for e in b['events'] if str(e['id'])=='401876452')
        e = copy.deepcopy(e); e['competitions'][0]['status']['type'] = {'state':'pre','completed':False}
        start = now.results.utc(e['date'])
        self.assertEqual(now.watch_delay([e],start+now.timedelta(minutes=80)),300)
        self.assertIsNone(now.watch_delay([e],start+now.timedelta(minutes=211)))
        with self.assertRaises(ValueError): now.publish({'sample_fictional':True},ROOT/'build/no',{})

    def test_rank_snapshots(self):
        data,_ = now.build(self.boards,self.summaries,self.clock); g = data[0]['games'][0]
        a = dict(competition=g['league'],season=2026,played=4,rank=8,source='fixture',as_of=g['start_utc'])
        a['as_of'] = (now.results.utc(g['start_utc'])-now.timedelta(hours=1)).isoformat()
        b = dict(a,played=5,rank=9,as_of=g['finished_utc'])
        self.assertEqual(now.rank_changes(g,{'away':dict(before=a,after=b)})[0]['after'],9)
        for field,value in [('season',None),('competition','CL'),('played',6),('as_of',a['as_of'])]:
            with self.subTest(field=field):
                bad = dict(b); bad[field] = value
                self.assertEqual(now.rank_changes(g,{'away':dict(before=a,after=bad)}),[])

    def test_render_uses_bundled_font_and_badges(self):
        import short_saved_render as sr
        sr.setup()
        data,_ = now.build(self.boards,self.summaries,self.clock); d=data[0]
        d['sample_fictional']=True
        import v3_rules as rules
        for s in now.narration(d)['segments']:
            im = now.frame(d,1.8,s)
            self.assertFalse(rules.check_layout(im)+rules.check_spacing(im))


if __name__ == '__main__': unittest.main(argv=['test_soccer_now'])
