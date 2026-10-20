"""Offline synthetic cases: never contact Buffer or any SNS."""
import sys
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import social_audit as a

NOW = a.instant('2026-10-17T12:00:00Z')
TEXT = '10/17更新｜明日のMLB\nhttps://www.youtube.com/watch?v=abcdefghijk\nhttps://collespo.com/'
def fixture():
    posts = {s: [] for s in a.CHANNELS}
    posts['twitter'] = [dict(id='test-post', channelId=a.CHANNELS['twitter'],
        status='sent', text=TEXT, sentAt='2026-10-17T08:00:00Z', dueAt=None)]
    ledger = {'deliveries': {'2026-10-17:daily:twitter':
        {'post_id':'test-post', 'text':TEXT, 'youtube_id':'abcdefghijk', 'state':'sent'}}}
    return posts, ledger, {'daily':{'2026-10-17':{'video_id':'abcdefghijk'}}}

class AuditTests(unittest.TestCase):
    def setUp(self): self.posts, self.ledger, self.videos = fixture()
    def run_audit(self): return a.audit(self.posts,self.ledger,self.videos,NOW)
    def post(self): return self.posts['twitter'][0]
    def test_healthy(self): self.assertEqual(self.run_audit(),{'checked':1,'findings':[]})
    def test_apsc_even_registered(self):
        self.post()['text'] += '\n【応用情報】APSC'
        self.assertIn('コレスポ本文の形式外',self.run_audit()['findings'][0]['reasons'])
    def test_unledgered_scheduled(self):
        self.post().update(id='unknown',status='scheduled',dueAt='2026-12-01T00:00:00Z')
        self.assertIn('台帳にない投稿・予約',self.run_audit()['findings'][0]['reasons'])
    def test_old_sent_excluded(self):
        self.post()['sentAt']='2026-10-10T11:59:59Z'
        self.assertEqual(self.run_audit()['checked'],0)
    def test_boundary_and_old_creation_recent_publication(self):
        self.post().update(sentAt='2026-10-10T12:00:00Z',createdAt='2025-01-01T00:00:00Z')
        self.assertEqual(self.run_audit()['checked'],1)
    def test_missing_sent_timestamp(self):
        self.post()['sentAt']=None
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_missing_scheduled_timestamp(self):
        self.post().update(status='scheduled',dueAt=None)
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_wrong_channel(self):
        self.post()['channelId']='other'
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_missing_channel(self):
        del self.posts['tiktok']
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_ledger_service_isolation(self):
        self.ledger['deliveries']={'date:daily:tiktok':next(iter(self.ledger['deliveries'].values()))}
        self.assertTrue(self.run_audit()['findings'])
    def test_unowned_video(self):
        self.post()['text']=TEXT.replace('abcdefghijk','xxxxxxxxxxx')
        self.assertTrue(self.run_audit()['findings'])
    def test_brand_url_spoof(self):
        self.post()['text']=TEXT.replace('https://collespo.com/','https://evil.invalid/collespo.com/')
        self.assertIn('コレスポ本文の形式外',self.run_audit()['findings'][0]['reasons'])
    def test_actual_caption_formats(self):
        for caption in ['今夜の欧州サッカー','現地の報道','現地の反応','PS対戦表・日程','今日の日本人選手']:
            with self.subTest(caption=caption):
                self.post()['text']=caption+'\nhttps://youtu.be/abcdefghijk\ncollespo.com'
                next(iter(self.ledger['deliveries'].values()))['text']=self.post()['text']
                self.assertFalse(self.run_audit()['findings'])
    def test_duplicate_conflict(self):
        duplicate=deepcopy(self.post()); duplicate['text']='APSC'
        self.posts['twitter'].append(duplicate)
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_duplicate_identical(self):
        self.posts['twitter'].append(deepcopy(self.post()))
        self.assertEqual(self.run_audit()['checked'],1)
    def test_invalid_registry(self):
        self.videos={}
        with self.assertRaises(a.Incomplete): self.run_audit()
    def test_page_readonly_query_and_pagination(self):
        calls=[]
        def query(q):
            calls.append(q)
            return {'posts':{'edges':[{'node':deepcopy(self.post())}],
                'pageInfo':{'hasNextPage':len(calls)==1,'endCursor':'cursor1'}}}
        self.assertEqual(len(a.fetch_posts(query,a.CHANNELS['twitter'])),2)
        self.assertIn('after:"cursor1"',calls[1])
        self.assertTrue(all(q.startswith('query {') and 'mutation' not in q for q in calls))
    def test_page_limit(self):
        def query(q): return {'posts':{'edges':[],'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}
        with self.assertRaises(a.Incomplete): a.fetch_posts(query,a.CHANNELS['twitter'],max_pages=1)
    def test_repeated_cursor(self):
        def query(q): return {'posts':{'edges':[],'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}
        with self.assertRaises(a.Incomplete): a.fetch_posts(query,a.CHANNELS['twitter'])
    def test_error_redaction(self):
        def query(q): raise RuntimeError('SECRET_TOKEN')
        with self.assertRaises(a.Incomplete) as caught: a.fetch_posts(query,a.CHANNELS['twitter'])
        self.assertNotIn('SECRET_TOKEN',str(caught.exception))
    def test_cli_three_core_exit_codes_no_network(self):
        with tempfile.TemporaryDirectory() as temp, patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            root=Path(temp)
            for name,data in [('ledger',self.ledger),('published',self.videos)]:
                (root/name).write_text(json.dumps(data))
            args=['--ledger',str(root/'ledger'),'--published',str(root/'published'),
                  '--fixture',str(root/'posts'),'--now',NOW.isoformat()]
            for variant,expected in [('healthy',0),('foreign',1),('unknown',1)]:
                posts=deepcopy(self.posts)
                if variant=='foreign': posts['twitter'][0]['text']='【応用情報】APSC'
                if variant=='unknown': posts['twitter'][0].update(id='unknown',status='scheduled',dueAt=NOW.isoformat())
                (root/'posts').write_text(json.dumps(posts))
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(a.main(args),expected)
            (root/'posts').write_text('{}')
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(a.main(args),2)

if __name__ == '__main__': unittest.main(argv=[sys.argv[0]])
