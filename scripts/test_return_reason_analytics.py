import sys
import unittest
from datetime import date
from unittest.mock import MagicMock
import return_reason_weekly as weekly

class WeeklyTest(unittest.TestCase):
    def test_missing_days_and_zero(self):
        result = weekly.summarize({'daily': {'2026-10-26': {'views':1000,'likes':4,'subscribedViews':0,'subscribersGainedByContentType':{'shorts':2}},'2026-10-27':{'views':500}}})[0]
        self.assertEqual(result['likes_per_1000_views'],4)
        self.assertEqual(result['subscribed_views_per_day'],0)
        self.assertEqual(result['registration_days'],1)
        self.assertEqual(result['registrations']['shorts'],2)

    def test_outro_groups_use_only_eligible_recorded_videos(self):
        record=lambda variant,eligible=True:dict(video_id=variant,outro_next=dict(enabled=True,eligible=eligible,variant=variant))
        published={'morning':{'a':record('generic'),'b':record('next'),'c':record('other',False)}}
        store={'days':{'2026-11-01':dict(range=['2026-10-01','2026-11-01'],videos=[dict(video='generic',views=100,likes=2),dict(video='next',views=200,likes=5),dict(video='other',views=999)])}}
        result=weekly.by_outro(store,published)
        self.assertEqual(set(result['groups']),{'generic','next'})
        self.assertEqual(result['groups']['next']['views'],200)
        self.assertEqual(result['range'],['2026-10-01','2026-11-01'])

    def test_query_failure_preserves_old(self):
        # Google SDK が無い環境でも、偽の受信口で照会契約を検査する。
        import types
        from unittest.mock import patch
        modules = {n:types.ModuleType(n) for n in ('google','google.oauth2','google.oauth2.credentials','googleapiclient','googleapiclient.discovery','googleapiclient.errors')}
        modules['google.oauth2.credentials'].Credentials=MagicMock()
        modules['googleapiclient.discovery'].build=MagicMock()
        modules['googleapiclient.errors'].HttpError=Exception
        with patch.dict(sys.modules, modules):
            import fetch_analytics as fetch
        yta=MagicMock()
        yta.reports().query().execute.side_effect=[{'columnHeaders':[{'name':'creatorContentType'},{'name':'subscribersGained'}],'rows':[['SHORTS',3],['VIDEO_ON_DEMAND',2],['LIVE_STREAM',4],['UNSPECIFIED',1]]}, RuntimeError()]
        rows=fetch.registration_daily(yta,date(2026,10,26),date(2026,10,27),'now')
        store={'daily':{'2026-10-27':{'views':8,'subscribersGainedByContentType':{'shorts':1}}}}
        fetch.merge_daily(store,rows)
        self.assertEqual(store['daily']['2026-10-27']['views'],8)
        self.assertEqual(store['daily']['2026-10-27']['subscribersGainedByContentType']['shorts'],1)
        self.assertEqual(rows['2026-10-26']['subscribersGainedByContentType'],dict(shorts=3,videoOnDemand=2,liveStream=4,unspecified=1))
        self.assertEqual(yta.reports().query.call_args.kwargs['dimensions'],'creatorContentType')
        # 未対応区分や空の応答は当日全体を欠測にし、4区分へ誤って寄せない。
        for response in ({'columnHeaders':[{'name':'creatorContentType'},{'name':'subscribersGained'}], 'rows':[['STORY',2]]}, {}):
            yta.reports().query().execute.side_effect=None
            yta.reports().query().execute.return_value=response
            self.assertEqual(fetch.registration_daily(yta,date(2026,10,27),date(2026,10,27),'now'),{})


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
