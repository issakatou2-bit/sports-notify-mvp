"""初動の欠測を0と集計しない。素材日で公開後時間を代用しない。"""
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import early_views as ev

UTC=dt.timezone.utc
NOW=dt.datetime(2026,10,12,0,30,tzinfo=UTC)


def observed(views=0,privacy='public',published='2026-10-12T00:00:00Z'):
    return {'views':views,'privacy':privacy,'published_at':published,'seconds':40,'availability':'ok'}


class EarlyMetrics(unittest.TestCase):
    def test_missing_and_invalid_counts_are_not_zero(self):
        for value in (None,'',False,True,-1,'-1','broken','1.5'):
            self.assertIsNone(ev.count(value))
        self.assertEqual(ev.count('0'),0)
        self.assertEqual(ev.count(0),0)
        self.assertEqual(ev.count('123'),123)

    def test_api_keeps_missing_not_returned_and_real_zero_distinct(self):
        response={'items':[{'id':'zero','statistics':{'viewCount':'0'},'snippet':{'publishedAt':'2026-10-12T00:00:00Z'},'status':{'privacyStatus':'public'}},
                           {'id':'missing','statistics':{},'status':{'privacyStatus':'public'}},
                           {'id':'private','statistics':{'viewCount':'1'},'status':{'privacyStatus':'private'}}]}
        with patch.object(ev,'get',return_value=response) as get:
            out=ev.stats_for(['zero','missing','private','not-returned'])
        self.assertEqual(out['zero']['views'],0)
        self.assertIsNone(out['zero']['likes'])
        self.assertIsNone(out['missing']['views'])
        self.assertEqual(out['missing']['availability'],'views_missing')
        self.assertEqual(out['not-returned']['availability'],'not_returned')
        self.assertEqual(ev.views_for(list(out),out),[0])
        self.assertIn('snippet',get.call_args.kwargs['part'])
        self.assertIn('status',get.call_args.kwargs['part'])

    def test_one_failed_batch_does_not_hide_the_other(self):
        ids=[f'id{i}' for i in range(51)]
        with patch.object(ev,'get',side_effect=[TimeoutError('fixture'),{'items':[{'id':'id50','statistics':{'viewCount':'9'},'status':{'privacyStatus':'public'}}]}]):
            out=ev.stats_for(ids)
        self.assertEqual(out['id0']['availability'],'fetch_failed')
        self.assertEqual(ev.views_for(ids,out),[9])

    def test_actual_publication_hour_and_slot_are_used(self):
        rows=[('2000-01-01','morning','now','fixture')]
        got={'now':observed(0)}
        old={'runs':{'2026-10-11T0030':{'observed_at':'2026-10-11T00:30:00Z','videos':[
            {'kind':'morning',**observed(10,published='2026-10-11T00:00:00Z')},
            {'kind':'longform',**observed(999,published='2026-10-11T00:00:00Z')}]}}}
        result=ev._same_age(old,rows,got,NOW)
        self.assertEqual(result[('morning',0)][:2],(0,10))
        self.assertNotIn(('longform',0),result)
        # 同じ素材日でも公開後の時間帯が違う動画を比べない。
        got['now']=observed(20,published='2026-10-11T22:00:00Z')
        self.assertFalse(ev._same_age(old,rows,got,NOW))

    def test_missing_legacy_time_and_nonpublic_future_never_enter_age_comparison(self):
        old={'runs':{'2026-10-11T0030':{'videos':[{'date':'2026-10-11','kind':'morning','views':0}]}}}
        rows=[('2026-10-12','morning','id','fixture')]
        self.assertFalse(ev._same_age(old,rows,{'id':observed(0)},NOW))
        for value in (observed(0,privacy='private'),observed(None),observed(0,published='broken'),
                      observed(0,published='2026-10-13T00:00:00Z')):
            self.assertFalse(ev._same_age(old,rows,{'id':value},NOW))

    def test_timezone_is_required_and_offsets_are_equal(self):
        self.assertIsNone(ev.timestamp('2026-10-12T00:00:00'))
        self.assertEqual(ev.timestamp('2026-10-12T09:00:00+09:00'),ev.timestamp('2026-10-12T00:00:00Z'))

    def test_per_video_read_time_is_used_instead_of_the_end_of_the_run(self):
        old={'runs':{'2026-10-11T0030':{'videos':[{'kind':'morning',**observed(10,published='2026-10-11T00:00:00Z')}]}}}
        value=observed(0);value['observed_at']='2026-10-12T00:30:00Z'
        result=ev._same_age(old,[('old-date','morning','id','fixture')],{'id':value},NOW+dt.timedelta(hours=1))
        self.assertEqual(result[('morning',0)][:2],(0,10))

    def test_same_id_in_two_ledger_kinds_is_one_video(self):
        ledger={'longform':{'2099-01-01':{'video_id':'same','title':'old'}},
                'longform_reviewed':{'2099-01-01':{'video_id':'same','title':'reviewed'}}}
        with patch.object(ev,'load',side_effect=[ledger,{}]):rows=ev.collect(7)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][1],'longform_reviewed')

    def test_main_summary_and_store_preserve_missing_and_zero(self):
        rows=[('2099-01-01','morning','zero','zero'),('2099-01-01','morning','missing','missing'),
              ('2099-01-01','morning','private','private'),('2099-01-01','daily','failed','failed')]
        got={'zero':observed(0,published='2026-10-11T18:00:00Z'),
             'missing':observed(None),'private':observed(9,privacy='private'),
             'failed':{'availability':'fetch_failed','views':None}}
        stdout=io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            out=pathlib.Path(td)/'metrics.json';summary=pathlib.Path(td)/'summary.md'
            with patch.dict(os.environ,{'YOUTUBE_API_KEY':'fixture','GITHUB_STEP_SUMMARY':str(summary)}), \
                 patch.object(sys,'argv',['early','--out',str(out)]),patch.object(ev,'collect',return_value=rows), \
                 patch.object(ev,'stats_for',return_value=got),contextlib.redirect_stdout(stdout):
                self.assertEqual(ev.main(),0)
            saved=json.loads(out.read_text(encoding='utf-8'))
            videos=list(saved['runs'].values())[0]['videos']
            md=summary.read_text(encoding='utf-8')
        self.assertEqual(videos[0]['views'],0)
        self.assertIsNone(videos[1]['views'])
        self.assertIn('公開・取得済み1本',stdout.getvalue())
        self.assertIn('|2026-10-12|1/',md)  # JSTの公開日、台帳の2099年ではない
        self.assertIn('未取得',md)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
