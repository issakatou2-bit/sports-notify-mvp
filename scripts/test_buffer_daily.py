import io
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import buffer_daily as daily


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.run = {'path': '.github/workflows/daily_notify.yml', 'head_branch': 'main',
                    'conclusion': 'success', 'event': 'workflow_dispatch',
                    'repository': {'full_name': daily.REPO}, 'created_at': '2026-09-11T09:00:00Z',
                    'updated_at': '2026-09-11T10:10:00Z'}
        self.record = {'video_id': 'abcdefghijk', 'published_at': '2026-09-11T09:56:00Z',
                       'publish_at': '2026-09-11T10:00:00Z', 'title': '【MLB】今永昇太先発予定｜明日の注目試合'}
        self.records = {'daily': {'2026-09-11': self.record}}
        self.now = datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc)

    def test_source_edition(self):
        self.assertEqual(daily.select_record(self.run, self.records, self.now)[0], '2026-09-11')

    def test_untrusted_failed_and_stale_runs(self):
        for change in ({'head_branch': 'feature'}, {'conclusion': 'failure'}, {'event': 'pull_request'},
                       {'path': '.github/workflows/morning.yml'}, {'repository': {'full_name': 'x/y'}},
                       {'created_at': '2026-09-10T09:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                daily.select_record({**self.run, **change}, self.records, self.now)

    def test_wrong_run_record_and_future_publication(self):
        for change in ({'published_at': '2026-09-11T08:00:00Z'}, {'publish_at': '2026-09-12T10:00:00Z'},
                       {'video_id': '../secret'}, {'published_at': '2026-09-11T11:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                daily.select_record(self.run, {'daily': {'2026-09-11': {**self.record, **change}}}, self.now)

    def test_midnight_does_not_republish_yesterday(self):
        with self.assertRaises(ValueError):
            daily.select_record(self.run, self.records, datetime(2026,9,11,15,0,tzinfo=timezone.utc))

    def test_caption_and_platform_options(self):
        x = daily.caption('twitter', '2026-09-11', self.record)
        self.assertLessEqual(daily.x_weight(x), 280)
        self.assertIn('watch?v=abcdefghijk', x)
        for service in daily.CHANNELS:
            payload=daily.create_payload(service, x, 'https://example.test/a.mp4')
            self.assertEqual(payload['schedulingType'], 'automatic')
            self.assertEqual(payload['assets'][0]['video']['url'], 'https://example.test/a.mp4')
        self.assertEqual(daily.create_payload('instagram', x, '')['metadata']['instagram']['type'], 'reel')

    def test_overlong_x_fails_instead_of_bad_post(self):
        with self.assertRaises(ValueError):
            daily.caption('twitter', '2026-09-11', {**self.record,'title':'今'*200})

    def test_rollout_selects_only_verified_channels(self):
        self.assertEqual(daily.selected_services('twitter,instagram'), ('twitter','instagram'))
        self.assertNotIn('tiktok', daily.selected_services('twitter,instagram'))
        self.assertEqual(daily.selected_services(None), tuple(daily.CHANNELS))

    def test_invalid_channel_configuration_fails_closed(self):
        for value in ('twitter,other', 'twitter,', ' '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                daily.selected_services(value)

    def test_artifact_not_arbitrary_extraction(self):
        def archive(names):
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                for name in names:
                    z.writestr(name,b'x'*1200)
            return data.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'video.mp4'
            with self.assertRaises(ValueError):
                daily.extract_video(archive(['anything.txt']),target)
            with self.assertRaises(ValueError):
                daily.extract_video(archive(['collespo_short.mp4','extra.txt']),target)
            digest=daily.extract_video(archive(['../../collespo_short.mp4']),target)
            self.assertEqual(len(digest),64)
            self.assertEqual(target.stat().st_size,1200)

    def ledger(self, old=None, fail=False):
        class Ledger:
            def __init__(self):
                self.data={'deliveries': {'key':old} if old else {}}
                self.events=[]
            def set(self,key,value):
                if fail:
                    raise RuntimeError('Durable write failed')
                self.data['deliveries'][key]=json.loads(json.dumps(value))
                self.events.append(value['state'])
        return Ledger()

    def test_reservation_before_mutation(self):
        ledger=self.ledger()
        def create(*args):
            self.assertEqual(ledger.events,['reserved'])
            return {'createPost':{'__typename':'PostActionSuccess','post':{'id':'post1','status':'scheduled'}}}
        with patch.object(daily,'recent_posts',return_value=[]),patch.object(daily,'graphql',side_effect=create):
            daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
        self.assertEqual(ledger.events,['reserved','scheduled'])

    def test_no_post_if_durable_write_fails(self):
        with patch.object(daily,'recent_posts',return_value=[]),patch.object(daily,'graphql') as mutate:
            with self.assertRaises(RuntimeError):
                daily.submit_once(self.ledger(fail=True),'key',{'channelId':'x','text':'today'}, {})
            mutate.assert_not_called()

    def test_uncertain_response_never_blindly_retries(self):
        ledger=self.ledger()
        with patch.object(daily,'recent_posts',return_value=[]),patch.object(daily,'graphql',side_effect=TimeoutError) as mutate:
            with self.assertRaises(TimeoutError):
                daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
            with self.assertRaises(RuntimeError):
                daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
            self.assertEqual(mutate.call_count,1)

    def test_reconcile_lost_response(self):
        ledger=self.ledger({'state':'reserved'})
        with patch.object(daily,'recent_posts',return_value=[{'id':'p1','text':'today','status':'sent','externalLink':'https://x.com/a'}]),patch.object(daily,'graphql') as mutate:
            daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
            mutate.assert_not_called()
        self.assertEqual(ledger.data['deliveries']['key']['state'],'sent')

    def test_rejection_stays_rejected_without_operator_retry(self):
        ledger=self.ledger()
        with patch.object(daily,'recent_posts',return_value=[]),patch.object(daily,'graphql',return_value={'createPost':{'__typename':'PostInvalidInputError','message':'unsupported'}}) as mutate:
            with self.assertRaises(RuntimeError):
                daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
            self.assertEqual(ledger.data['deliveries']['key']['state'],'rejected')
            with self.assertRaises(RuntimeError):
                daily.submit_once(ledger,'key',{'channelId':'x','text':'today'}, {})
            self.assertEqual(mutate.call_count,1)


if __name__ == '__main__':
    unittest.main(argv=['test_buffer_daily'])
