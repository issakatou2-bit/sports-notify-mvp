import unittest
from unittest.mock import patch
import buffer_daily as b


class ConfirmSentTests(unittest.TestCase):
    def setUp(self):
        self.key = '2026-10-29:morning_voices:twitter'
        self.entry = dict(state='error', post_id='failed', text='本文 https://youtu.be/fixture', youtube_id='fixture')
        self.failed = dict(id='failed', status='error', text=self.entry['text'], externalLink=None)
        self.sent = dict(id='actual', status='sent', text=self.entry['text'], externalLink='https://x.com/example/status/1')

    def ledger(self):
        obj = b.Ledger.__new__(b.Ledger)
        obj.data = {'deliveries': {self.key: self.entry}}
        obj.set = lambda key, value: obj.data['deliveries'].__setitem__(key, value)
        return obj

    def test_sent_beats_error_regardless_of_api_order(self):
        for rows in ([self.failed, self.sent], [self.sent, self.failed]):
            self.assertEqual(b.matched_post(rows, self.entry), self.sent)

    def test_reconcile_saves_actual_id_and_previous_id_without_mutation(self):
        ledger = self.ledger()
        with patch.object(b, 'Ledger', return_value=ledger), patch.object(b, 'recent_posts', return_value=[self.failed, self.sent]), \
                patch.object(b, 'graphql') as api:
            b.reconcile()
        row = ledger.data['deliveries'][self.key]
        self.assertEqual(row['state'], 'sent')
        self.assertEqual(row['post_id'], 'actual')
        self.assertEqual(row['previous_post_ids'], ['failed'])
        self.assertEqual(row['youtube_id'], 'fixture')
        api.assert_not_called()

    def test_ambiguous_actual_posts_stop_without_resend(self):
        with self.assertRaises(RuntimeError):
            b.matched_post([self.sent, dict(self.sent, id='second')], self.entry)

    def test_similar_text_is_not_enough(self):
        self.assertIsNone(b.matched_post([dict(self.sent, text=self.entry['text']+'別の動画')], self.entry))

    def test_gave_up_can_be_recovered(self):
        ledger = self.ledger()
        ledger.data['deliveries'][self.key] = dict(self.entry, state='gave_up')
        with patch.object(b, 'Ledger', return_value=ledger), patch.object(b, 'recent_posts', return_value=[self.sent]):
            b.reconcile()
        self.assertEqual(ledger.data['deliveries'][self.key]['state'], 'sent')

    def test_submit_existing_actual_post_never_creates_new_post(self):
        ledger = self.ledger()
        with patch.object(b, 'recent_posts', return_value=[self.failed, self.sent]), patch.object(b, 'graphql') as api:
            b.submit_once(ledger, self.key, dict(channelId='twitter', text=self.entry['text']), {})
        api.assert_not_called()
        self.assertEqual(ledger.data['deliveries'][self.key]['state'], 'sent')

    def test_actual_id_repair_removes_unledgered_audit_finding(self):
        import social_audit as audit
        text = '10/29更新｜ファンのコメント欄\nhttps://youtu.be/abcdefghijk\nhttps://collespo.com/'
        entry = dict(self.entry, text=text, youtube_id='abcdefghijk', checked_at='2026-10-29T01:00:00Z')
        post = dict(self.sent, text=text, channelId=audit.CHANNELS['twitter'], sentAt='2026-10-29T01:05:40Z', dueAt=None)
        posts = {s: [] for s in audit.CHANNELS}
        posts['twitter'] = [post]
        ledger = {'deliveries': {self.key: entry}}
        videos = {'morning_voices': {'2026-10-29': {'video_id': 'abcdefghijk'}}}
        now = audit.instant('2026-10-30T12:00:00Z')
        self.assertIn('台帳にない投稿・予約', audit.audit(posts, ledger, videos, now)['findings'][0]['reasons'])
        repaired = b.delivery_update(entry, b.matched_post([self.failed, post], entry))
        ledger['deliveries'][self.key] = dict(repaired, checked_at='2026-10-30T11:00:00Z')
        self.assertEqual(audit.audit(posts, ledger, videos, now)['findings'], [])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
