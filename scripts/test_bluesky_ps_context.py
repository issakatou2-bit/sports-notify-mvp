from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import public_short
import post_bluesky as sender

NOW = datetime(2026, 9, 30, 10, 30, tzinfo=timezone.utc)
URI = 'at://did:plc:owner/app.bsky.feed.post/abcdef123'
EDITION = dict(video_id='abcdefghijk', published_at='2026-09-30T09:55:00Z',
               publish_at='2026-09-30T10:00:00Z', program_version='ps-program',
               social_summary='村上宗隆が所属するホワイトソックスのWCS第2戦。全4試合を紹介します。')


class BlueskyPSContextTests(unittest.TestCase):
    def test_due_context_and_hashtags_survive_publication_delay(self):
        body, tags, _ = sender.post_context([], None, EDITION)
        self.assertEqual(body, EDITION['social_summary'])
        self.assertIn('MLB', tags)
        self.assertIn('村上宗隆', tags)
        self.assertLessEqual(len(tags), 3)

    def test_future_wrong_kind_and_previous_day_are_not_current_context(self):
        with patch.object(public_short.Path, 'read_text', return_value=json.dumps({'daily': {'2026-09-30': EDITION}})):
            self.assertEqual(public_short.edition_metadata('daily', now=NOW), EDITION)
            for kind, now in [('daily', datetime(2026, 9, 30, 9, tzinfo=timezone.utc)),
                              ('daily_soccer', NOW), ('daily', datetime(2026, 10, 1, 10, tzinfo=timezone.utc))]:
                self.assertIsNone(public_short.edition_metadata(kind, now=now))

    def test_receipt_preserves_previous_editions_and_exact_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'delivery.json'
            path.write_text(json.dumps({'editions': {'daily:2026-09-29': {'uri': 'keep'}}}), encoding='utf-8')
            sender.save_ps_delivery(URI, 'daily', EDITION, True, path)
            result = json.loads(path.read_text(encoding='utf-8'))['editions']
            self.assertEqual(result['daily:2026-09-29']['uri'], 'keep')
            self.assertEqual(result['daily:2026-09-30'], dict(uri=URI, video_id='abcdefghijk', state='linked'))

    def main_without_publish(self, flag, edition, row=None):
        with patch.object(sender.sys, 'argv', ['post_bluesky.py', flag]), \
             patch.object(sender.post_common, 'load_notable_games', return_value=[]), \
             patch.object(sender, 'edition_metadata', return_value=edition), \
             patch.object(sender, 'datetime') as clock, \
             patch.object(sender.Path, 'read_text', return_value=json.dumps({'editions': {'daily:2026-09-30': row or {}}})), \
             patch.object(sender, 'public_short', return_value=None) as verify:
            clock.now.return_value = NOW
            sender.main()
            return verify.call_count

    def test_original_ps_step_defers_before_public_lookup(self):
        self.assertEqual(self.main_without_publish('--defer-ps', EDITION), 0)

    def test_post_completion_worker_skips_non_ps_and_existing_receipts(self):
        self.assertEqual(self.main_without_publish('--ps-only', None), 0)
        self.assertEqual(self.main_without_publish('--ps-only', EDITION, {'uri': URI, 'state': 'public_view_unconfirmed'}), 0)

    def test_unconfirmed_public_video_stops_instead_of_sending_fallback(self):
        with self.assertRaises(SystemExit):
            self.main_without_publish('--ps-only', EDITION)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
