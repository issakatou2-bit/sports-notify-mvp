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
        {'post_id':'test-post', 'text':TEXT, 'youtube_id':'abcdefghijk', 'state':'sent', 'checked_at':'2026-10-17T08:00:00Z'}}}
    return posts, ledger, {'daily':{'2026-10-17':{'video_id':'abcdefghijk'}}}

class AuditTests(unittest.TestCase):
    def setUp(self): self.posts, self.ledger, self.videos = fixture()
    def run_audit(self): return a.audit(self.posts,self.ledger,self.videos,NOW)
    def post(self): return self.posts['twitter'][0]
    def set_service(self, service, text, post_id=None, ledger_text=None,
                    youtube_id='abcdefghijk'):
        pid = post_id or service + '-post'
        self.posts[service] = [dict(id=pid, channelId=a.CHANNELS[service],
            status='sent', text=text, sentAt='2026-10-17T08:00:00Z', dueAt=None)]
        self.ledger['deliveries']['2026-10-17:daily:' + service] = {
            'post_id': pid, 'text': ledger_text if ledger_text is not None else text,
            'youtube_id': youtube_id, 'state': 'sent',
            'checked_at': '2026-10-17T08:00:00Z'}
        return self.posts[service][0]
    def test_healthy(self): self.assertEqual(self.run_audit(),{'checked':1,'findings':[],'handled':0})
    def test_instagram_linkless_caption_is_valid(self):
        self.set_service('instagram',
            '10/17更新｜ファンのコメント欄\n現地のファンの声をそのまま訳しました。\n#MLB')
        self.assertEqual(self.run_audit()['findings'], [])
    def test_tiktok_line_breaks_and_missing_link_are_valid(self):
        self.set_service('tiktok',
            '10/17更新｜PSの話題 試合とシリーズの状況を公式の数字で紹介します。 #MLB',
            ledger_text='10/17更新｜PSの話題\n試合とシリーズの状況を公式の数字で紹介します。\n#MLB')
        self.assertEqual(self.run_audit()['findings'], [])
    def test_apsc_caption_stays_flagged(self):
        self.set_service('instagram',
            '【応用情報 セキュリティ】APSC\n解説はYouTubeで https://www.youtube.com/channel/x',
            post_id='apsc-ig')
        self.assertIn('コレスポ本文の形式外', self.run_audit()['findings'][0]['reasons'])
    def test_known_handled_is_removed_and_counted(self):
        self.post()['text'] += '\n【応用情報】APSC'
        result = a.audit(self.posts, self.ledger, self.videos, NOW,
                         known={'test-post'})
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['handled'], 1)
    def test_unledgered_collespo_caption_remains(self):
        self.posts['instagram'] = [dict(id='new-ig', channelId=a.CHANNELS['instagram'],
            status='scheduled', dueAt='2026-12-01T00:00:00Z',
            text='10/19更新｜PSの話題\n試合とシリーズの状況を公式の数字で紹介します。 #MLB')]
        self.assertIn('台帳にない投稿・予約', self.run_audit()['findings'][0]['reasons'])
    def test_apsc_even_registered(self):
        self.post()['text'] += '\n【応用情報】APSC'
        self.assertIn('コレスポ本文の形式外',self.run_audit()['findings'][0]['reasons'])
    def test_unledgered_scheduled(self):
        self.post().update(id='unknown',status='scheduled',dueAt='2026-12-01T00:00:00Z')
        self.assertIn('台帳にない投稿・予約',self.run_audit()['findings'][0]['reasons'])
    def test_old_sent_excluded(self):
        self.post()['sentAt']='2026-10-10T11:59:59Z'
        with self.assertRaises(a.Incomplete): self.run_audit()
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
        self.ledger['deliveries']['date:daily:tiktok']['checked_at'] = '2026-10-01T00:00:00Z'
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
        self.assertIn('after: "cursor1"',calls[1])
        self.assertTrue(all(q.startswith('{ posts(') and 'mutation' not in q for q in calls))
    def test_same_query_as_daily_and_response_counts(self):
        import buffer_daily
        calls = []
        def query(q):
            calls.append(q)
            node = deepcopy(self.post())
            del node['channelId']  # recent_posts relies on the channel filter.
            node['externalLink'] = 'https://example.invalid/post'
            return {'posts': {'edges': [{'node': node}],
                    'pageInfo': {'hasNextPage': len(calls) % 2 == 1,
                                 'endCursor': 'cursor1'}}}
        with patch.object(buffer_daily, 'graphql', side_effect=query):
            expected = buffer_daily.recent_posts(a.CHANNELS['twitter'])
        actual = a.fetch_posts(query, a.CHANNELS['twitter'])
        self.assertEqual(len(expected), len(actual))
        for daily, audit in zip(calls[:2], calls[2:]):
            # Compare all arguments, including filter, sort and page cursor.
            self.assertEqual(''.join(daily.split('edges')[0].split()),
                             ''.join(audit.split('edges')[0].split()))
            self.assertNotIn('status:', audit)
            self.assertIn('dueAt sentAt', audit)
        self.posts['twitter'] = actual
        self.assertEqual(self.run_audit()['checked'], 1)  # identical IDs deduplicated

    def test_empty_recent_service_even_when_another_service_reads(self):
        self.ledger['deliveries']['2026-10-17:daily:instagram'] = {
            'state': 'sent', 'checked_at': NOW.isoformat()}
        with self.assertRaisesRegex(a.Incomplete, 'instagram'):
            self.run_audit()

    def test_ledger_sent_window(self):
        entry = {'state': 'sent', 'checked_at': '2026-10-10T12:00:00Z'}
        self.assertTrue(a.recent_delivery(entry, NOW))
        entry['checked_at'] = '2026-10-10T11:59:59Z'
        self.assertFalse(a.recent_delivery(entry, NOW))
        self.assertTrue(a.recent_delivery({'state': 'sent', 'reserved_at': NOW.isoformat()}, NOW))
        with self.assertRaises(a.Incomplete):
            a.recent_delivery({'state': 'sent'}, NOW)

    def test_non_target_status_from_unfiltered_query(self):
        for status in ['draft', 'error', 'failed', 'rejected', 'not_sent']:
            self.posts['tiktok'] = [dict(self.post(), channelId=a.CHANNELS['tiktok'], status=status)]
            self.assertEqual(self.run_audit()['checked'], 1)

    def test_page_limit(self):
        def query(q): return {'posts':{'edges':[],'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}
        with self.assertRaises(a.Incomplete): a.fetch_posts(query,a.CHANNELS['twitter'],max_pages=1)
    def test_repeated_cursor(self):
        def query(q): return {'posts':{'edges':[],'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}
        with self.assertRaises(a.Incomplete): a.fetch_posts(query,a.CHANNELS['twitter'])
    def test_error_redaction(self):
        def query(q): raise RuntimeError('SECRET_TOKEN')
        with self.assertRaises(a.Incomplete) as caught:
            a.fetch_posts(query,a.CHANNELS['twitter'],retry_delay=0)
        self.assertNotIn('SECRET_TOKEN',str(caught.exception))
        self.assertIn('段階=送信',str(caught.exception))
    def test_cli_three_core_exit_codes_no_network(self):
        with tempfile.TemporaryDirectory() as temp, patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            root=Path(temp)
            for name,data in [('ledger',self.ledger),('published',self.videos)]:
                (root/name).write_text(json.dumps(data))
            (root/'known').write_text(json.dumps({'handled': {}}))
            args=['--ledger',str(root/'ledger'),'--published',str(root/'published'),
                  '--fixture',str(root/'posts'),'--now',NOW.isoformat(),
                  '--known',str(root/'known')]
            for variant,expected in [('healthy',0),('foreign',1),('unknown',1)]:
                posts=deepcopy(self.posts)
                if variant=='foreign': posts['twitter'][0]['text']='【応用情報】APSC'
                if variant=='unknown': posts['twitter'][0].update(id='unknown',status='scheduled',dueAt=NOW.isoformat())
                (root/'posts').write_text(json.dumps(posts))
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(a.main(args),expected)
            for ledger in [self.ledger, {'deliveries': {}}]:
                (root/'ledger').write_text(json.dumps(ledger))
                (root/'posts').write_text(json.dumps({s: [] for s in a.CHANNELS}))
                output = io.StringIO()
                with contextlib.redirect_stdout(output): self.assertEqual(a.main(args), 2)
                self.assertIn('読めなかった', output.getvalue())
                self.assertNotIn('異常なし', output.getvalue())
                for service in a.CHANNELS:
                    self.assertIn(service + ': 読めた投稿 0件', output.getvalue())
            (root/'posts').write_text('{}')
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(a.main(args),2)

    def test_cli_known_handled_prints_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in [('ledger', self.ledger), ('published', self.videos)]:
                (root/name).write_text(json.dumps(data), encoding='utf-8')
            (root/'known').write_text(json.dumps(
                {'handled': {'test-post': 'APSC 対応済み'}}), encoding='utf-8')
            posts = deepcopy(self.posts)
            posts['twitter'][0]['text'] += '\n【応用情報】APSC'
            (root/'posts').write_text(json.dumps(posts), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(a.main(['--ledger',str(root/'ledger'),
                    '--published',str(root/'published'),'--fixture',
                    str(root/'posts'),'--now',NOW.isoformat(),
                    '--known',str(root/'known')]), 0)
            self.assertIn('対応済み 1件', output.getvalue())

class ReadDiagnosticsTests(unittest.TestCase):
    """Failures must say where they stopped without leaking secrets."""

    class Response:
        def __init__(self, body, status=200):
            self.body = body.encode() if isinstance(body, str) else body
            self.status = status
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    def read(self, body, token='secret-token', status=200, **kwargs):
        import buffer_api
        with patch.dict('os.environ', {'BUFFER_API_KEY': token}), \
             patch('urllib.request.urlopen', return_value=self.Response(body, status)):
            return a.fetch_posts(buffer_api.graphql, a.CHANNELS['twitter'],
                                 retries=1, **kwargs)

    def test_graphql_errors_are_recorded_and_token_hidden(self):
        token = 'supersecrettoken'
        body = json.dumps({'errors': [{'message': 'Invalid API key ' + token}],
                           'data': None})
        with self.assertRaises(a.Incomplete) as caught:
            self.read(body, token=token)
        text = str(caught.exception)
        self.assertIn('HTTP=200', text)
        self.assertIn('errors=Invalid API key [redacted]', text)
        self.assertIn('応答の項目=data,errors', text)
        self.assertIn('段階=項目の取り出し', text)
        self.assertNotIn(token, text)

    def test_http_status_is_recorded(self):
        import urllib.error
        error = urllib.error.HTTPError('https://api.buffer.com', 401, 'Unauthorized', {}, None)
        with patch.dict('os.environ', {'BUFFER_API_KEY': 'secret-token'}), \
             patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(a.Incomplete) as caught:
                import buffer_api
                a.fetch_posts(buffer_api.graphql, a.CHANNELS['twitter'],
                              retries=1, retry_delay=0)
        self.assertIn('段階=送信 HTTP=401', str(caught.exception))

    def test_non_json_response_is_recorded(self):
        with self.assertRaises(a.Incomplete) as caught:
            self.read('<html>gateway error</html>')
        text = str(caught.exception)
        self.assertIn('段階=JSONの読み込み', text)
        self.assertIn('HTTP=200', text)

    def test_missing_posts_key_names_response_fields(self):
        with self.assertRaises(a.Incomplete) as caught:
            self.read(json.dumps({'data': {}}))
        self.assertIn('段階=項目の取り出し', str(caught.exception))
        self.assertIn('応答の項目=なし', str(caught.exception))

    def test_draft_without_text_does_not_break_read(self):
        def query(q):
            return {'posts': {'edges': [{'node': {
                'id': 'draft-1', 'channelId': a.CHANNELS['twitter'],
                'status': 'draft', 'text': '', 'dueAt': None, 'sentAt': None}}],
                'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        rows = a.fetch_posts(query, a.CHANNELS['twitter'], retries=1)
        self.assertEqual(rows[0]['status'], 'draft')

    def test_transient_failure_is_retried_once(self):
        calls = []
        good = {'posts': {'edges': [{'node': deepcopy(self.post_node())}],
                          'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        def query(q):
            calls.append(q)
            if len(calls) == 1:
                raise RuntimeError('temporary')
            return good
        self.assertEqual(len(a.fetch_posts(query, a.CHANNELS['twitter'],
                                           retry_delay=0)), 1)
        self.assertEqual(len(calls), 2)

    def post_node(self):
        return {'id': 'p1', 'channelId': a.CHANNELS['twitter'], 'status': 'sent',
                'text': TEXT, 'sentAt': '2026-10-17T08:00:00Z', 'dueAt': None}


if __name__ == '__main__': unittest.main(argv=[sys.argv[0]])
