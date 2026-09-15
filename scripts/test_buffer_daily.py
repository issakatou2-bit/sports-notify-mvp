import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import buffer_daily as daily


class BufferTests(unittest.TestCase):
    def test_reconcile_skips_buffer_when_every_delivery_is_confirmed(self):
        ledger = self.ledger()
        ledger.data['deliveries'] = {'2026-09-11:daily:twitter': {'state': 'sent'}}
        with patch.object(daily, 'Ledger', return_value=ledger), patch.object(daily, 'recent_posts') as read:
            daily.reconcile()
            read.assert_not_called()

    def test_reconcile_reads_only_pending_channel_and_never_creates_a_post(self):
        ledger = self.ledger()
        ledger.data['deliveries'] = {
            '2026-09-11:daily:twitter': {'state': 'sent'},
            '2026-09-11:daily:tiktok': {'state': 'sending', 'post_id': 'pending-id'}}
        with patch.object(daily, 'Ledger', return_value=ledger), patch.object(daily, 'recent_posts',
                return_value=[{'id':'pending-id','text':'caption','status':'sent','externalLink':'https://www.tiktok.com/@collespo/video/example'}]) as read, \
                patch.object(daily, 'graphql') as write:
            daily.reconcile()
            read.assert_called_once_with(daily.CHANNELS['tiktok'])
            write.assert_not_called()
        self.assertEqual(ledger.data['deliveries']['2026-09-11:daily:tiktok']['state'], 'sent')

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

    def test_caption_uses_one_published_game_reason_without_inventing_stakes(self):
        record={**self.record, 'title':'【MLB】菅野智之 先発予定｜明日の注目試合',
                'description':'紹介文\n\n1. 09/15 09:40 ロッキーズ vs パドレス\n   ・パドレスは7連勝中\n\n2. 09/15 10:00 A vs B\n   ・別の試合\n\nコレスポでは毎日配信'}
        for service in daily.CHANNELS:
            text=daily.caption(service,'2026-09-14',record)
            self.assertIn('菅野智之が先発予定です。',text)
            self.assertIn('パドレスは7連勝中。',text)
            self.assertNotIn('別の試合',text)
            self.assertNotIn('正念場',text)
            self.assertNotIn('プロフィールの',text)

    def test_caption_missing_description_and_long_reason_remain_safe(self):
        self.assertEqual(daily.first_game_reason('・別枠の宣伝'), '')
        self.assertEqual(daily.first_game_reason('1. 09/15 09:40 A vs B\n\n・宣伝'), '')
        self.assertEqual(daily.first_game_reason('1. 09/15 09:40 A vs B\n・https://example.test'), '')
        record={**self.record,'title':'【MLB】菅野智之 先発予定｜明日の注目試合',
                'description':'1. 09/15 09:40 A vs B\n・'+('あ'*70)}
        text=daily.caption('twitter','2026-09-14',record)
        self.assertLessEqual(daily.x_weight(text),280)
        self.assertIn('菅野智之が先発予定です。',text)
        self.assertTrue('あ' not in text or ('あ'*70+'。') in text)
        longer={**record, 'title':'【MLB】菅野智之 先発予定・パドレスは7連勝中｜明日の注目試合'}
        shortened=daily.caption('twitter','2026-09-14',longer)
        self.assertLessEqual(daily.x_weight(shortened),280)
        self.assertNotIn('あ',shortened)

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


class StillProcessingIsNotAFailure(unittest.TestCase):
    """9/14はXもInstagramも出ていたのに、実行は赤かった。

    TikTokだけが `sending` のまま6分の待ちを超えたため。**出ているのに
    出ていないと言うのは、出ていないのに出ていると言うのと同じくらい困る。**
    毎日1本赤が出れば、色を見なくなる。

    かといって、いつまでも待てば本当に詰まった日を見逃す。時間で切る。
    """

    def entry(self, state, hours_ago=0.5, field='reserved_at'):
        when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {'state': state, field: when.isoformat()}

    def test_a_post_handed_over_moments_ago_is_still_settling(self):
        self.assertTrue(daily.still_settling(self.entry('sending', 0.2)))

    def test_the_scheduled_reconciles_get_their_turn(self):
        # 19:00に投げて、照合は19:47と23:47。どちらもこの窓の内側。
        self.assertTrue(daily.still_settling(self.entry('sending', 0.8)))
        self.assertTrue(daily.still_settling(self.entry('sending', 4.8)))

    def test_a_post_stuck_past_the_window_is_a_real_problem(self):
        self.assertFalse(daily.still_settling(self.entry('sending', 13)))

    def test_a_refused_post_is_never_excused_by_the_clock(self):
        for state in daily.FAILED_STATES:
            self.assertFalse(daily.still_settling(self.entry(state, 0.1)), state)

    def test_a_delivered_post_needs_no_waiting(self):
        self.assertFalse(daily.still_settling(self.entry('sent', 0.1)))

    def test_checked_at_stands_in_when_there_is_no_reservation(self):
        self.assertTrue(daily.still_settling(self.entry('sending', 0.5, 'checked_at')))

    def test_a_ledger_that_cannot_say_when_is_not_given_the_benefit_of_the_doubt(self):
        self.assertFalse(daily.still_settling({'state': 'sending'}))
        self.assertFalse(daily.still_settling({'state': 'sending', 'reserved_at': 'broken'}))
        self.assertFalse(daily.still_settling({'state': 'sending', 'reserved_at': None}))
        self.assertFalse(daily.still_settling({}))

    def test_reconcile_stays_green_while_buffer_is_still_working(self):
        ledger = daily.Ledger.__new__(daily.Ledger)
        ledger.sha, ledger.data = None, {'version': 1, 'deliveries': {
            '2026-09-14:daily:tiktok': self.entry('sending', 0.5)}}
        ledger.set = lambda key, value: ledger.data['deliveries'].__setitem__(key, value)
        with patch.object(daily, 'Ledger', return_value=ledger), \
                patch.object(daily, 'recent_posts', return_value=[]):
            daily.reconcile()  # 例外が出なければ緑

    def test_reconcile_still_goes_red_once_the_window_has_passed(self):
        ledger = daily.Ledger.__new__(daily.Ledger)
        ledger.sha, ledger.data = None, {'version': 1, 'deliveries': {
            '2026-09-14:daily:tiktok': self.entry('sending', 30)}}
        ledger.set = lambda key, value: ledger.data['deliveries'].__setitem__(key, value)
        with patch.object(daily, 'Ledger', return_value=ledger), \
                patch.object(daily, 'recent_posts', return_value=[]):
            with self.assertRaises(SystemExit):
                daily.reconcile()

    def test_the_window_is_a_named_constant(self):
        self.assertIsInstance(daily.STUCK_AFTER_HOURS, (int, float))
        self.assertEqual(daily.STUCK_AFTER_HOURS, 12)


if __name__ == '__main__':
    unittest.main(argv=['test_buffer_daily'])
