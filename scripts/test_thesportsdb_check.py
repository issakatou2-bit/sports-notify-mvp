"""Fixed result fixtures. No credentials, network, host fonts or Git history."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import urllib.error

import thesportsdb_check as t

EVENTS = json.loads((Path(__file__).parent/'fixtures/thesportsdb/events.json').read_text(encoding='utf-8'))['events']


def game():
    return dict(id='401878778',league='PL',start_utc='2026-09-19T14:00Z',score={'home':1,'away':0},
                home={'name_en':'Everton'},away={'name_en':'Ipswich Town'})


class Check(unittest.TestCase):
    def test_match_and_mismatch_leave_primary_unchanged(self):
        g = game(); original = copy.deepcopy(g)
        self.assertEqual(t.compare(g,EVENTS)['status'],'matched')
        events = copy.deepcopy(EVENTS);events[1]['intAwayScore']='2'
        self.assertEqual(t.compare(g,events)['status'],'mismatch')
        self.assertEqual(g,original)

    def test_not_found_nonfinal_unknown_and_ambiguous_are_not_matches(self):
        self.assertEqual(t.compare(game(),[])['status'],'not_found')
        for field,value in [('intHomeScore',None),('strStatus','NS'),('intAwayScore',True)]:
            events=copy.deepcopy(EVENTS);events[1][field]=value
            self.assertEqual(t.compare(game(),events)['status'],'not_final')
        self.assertEqual(t.compare(game(),EVENTS+[EVENTS[1]])['status'],'ambiguous')
        for field,value in [('dateEvent','2026-09-20'),('idLeague','4335'),('strHomeTeam','Everton Women')]:
            events=copy.deepcopy(EVENTS);events[1][field]=value
            self.assertEqual(t.compare(game(),events)['status'],'not_found')
        g=game();g['home'],g['away']=g['away'],g['home']
        self.assertEqual(t.compare(g,EVENTS)['status'],'not_found')
        g=game();g['home']['name_en']=''
        self.assertEqual(t.compare(g,EVENTS)['status'],'primary_invalid')
        g=game();g['score']['home']=None
        self.assertEqual(t.compare(g,EVENTS)['status'],'primary_invalid')

    def test_start_day_is_utc_not_result_edition(self):
        g=game();g['start_utc']='2026-09-20T00:30:00+09:00';g['date_jst']='2026-09-21'
        self.assertEqual(t.group(g),('4328','2026-09-19'))
        g['start_utc']='2026-09-20T00:30:00'
        self.assertIsNone(t.group(g))

    def test_fetch_once_per_league_day_and_report_warning_only(self):
        g=game();bad=copy.deepcopy(g);bad['id']='wrong';bad['score']['away']=3
        data={'games':[g,bad]};saved=copy.deepcopy(data)
        with patch('builtins.print'),patch.object(t,'report'),patch('urllib.request.urlopen') as network:
            fetch=unittest.mock.Mock(return_value=(EVENTS,'fixture'))
            result=t.check(data,fetch)
            self.assertEqual(fetch.call_count,1)
            network.assert_not_called()
        self.assertEqual(data,saved);self.assertEqual(result['mismatches'],1)
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':str(Path(td)/'summary.md')}),patch('builtins.print') as output:
            t.report(result)
            self.assertIn('mismatch',(Path(td)/'summary.md').read_text(encoding='utf-8'))
            self.assertTrue(any('::warning::' in str(c) for c in output.call_args_list))

    def test_off_does_not_read_write_or_fetch(self):
        with patch.dict(os.environ,{'COLLESPO_THESPORTSDB_CHECK':''}),patch.object(t.urllib.request,'urlopen') as fetch,patch.object(Path,'read_text') as read,patch('builtins.print'):
            self.assertEqual(t.main(),0);fetch.assert_not_called();read.assert_not_called()

    def test_429_stops_all_further_calls_and_request_cap(self):
        with tempfile.TemporaryDirectory() as td:
            f=t.Fetcher(td)
            with patch.object(t.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('fixture',429,'limited',{},None)) as get:
                self.assertEqual(f.get(('4328','2026-09-19'))[1],'rate_limited')
                self.assertEqual(f.get(('4335','2026-09-19'))[1],'rate_limited')
                self.assertEqual(get.call_count,1)
            f=t.Fetcher(td);f.count=10
            with patch.object(t.urllib.request,'urlopen') as get:
                self.assertEqual(f.get(('4328','2026-09-19'))[1],'request_cap');get.assert_not_called()

    def test_cache_and_request_spacing(self):
        with tempfile.TemporaryDirectory() as td:
            f=t.Fetcher(td)
            # 実際のJSON保存時間やPC負荷で、必要な待機時間は短くなる。時計を固定して間隔を検査する。
            with patch.object(t.urllib.request,'urlopen',side_effect=lambda *a,**kw:io.BytesIO(json.dumps({'events':EVENTS}).encode())) as get,patch.object(t.time,'sleep') as sleep,patch.object(t.time,'monotonic',side_effect=[100,100.05,100.05]):
                self.assertEqual(f.get(('4328','2026-09-19'))[1],'fetched')
                self.assertEqual(f.get(('4328','2026-09-19'))[1],'cached')
                f.get(('4328','2026-09-20'))
                self.assertEqual(get.call_count,2);self.assertGreater(sleep.call_args.args[0],2)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
