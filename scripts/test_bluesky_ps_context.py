from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import public_short
from post_bluesky import post_context, save_ps_delivery
import update_bluesky_ps as updater


NOW = datetime(2026, 9, 30, 10, 30, tzinfo=timezone.utc)
DID = 'did:plc:owner'
URI = f'at://{DID}/app.bsky.feed.post/abcdef123'
EDITION = dict(video_id='abcdefghijk', published_at='2026-09-30T09:55:00Z',
               publish_at='2026-09-30T10:00:00Z', program_version='ps-program',
               social_summary='村上宗隆が所属するホワイトソックスのWCS第2戦。全4試合を紹介します。')
SHORT = dict(EDITION, url='https://www.youtube.com/watch?v=abcdefghijk', title='PS第2戦')
OLD = {'$type': 'app.bsky.feed.post', 'createdAt': '2026-09-30T10:00:13Z',
       'text': '旧形式', 'langs': ['en'], 'reply': {'root': {'uri': 'keep', 'cid': 'keep'}}}


class BlueskyPSContextTests(unittest.TestCase):
    def test_publication_check_does_not_erase_due_ps_context(self):
        body, _, _ = post_context([], None, EDITION)
        self.assertEqual(body, EDITION['social_summary'])
        with patch.object(public_short.Path, 'read_text', return_value='{"daily":{"2026-09-30":' +
                          json.dumps(EDITION) + '}}'):
            self.assertEqual(public_short.edition_metadata('daily', now=NOW), EDITION)
            self.assertIsNone(public_short.edition_metadata('daily', now=datetime(2026, 9, 30, 9, tzinfo=timezone.utc)))
            self.assertIsNone(public_short.edition_metadata('daily_soccer', now=NOW))

    def test_pending_edition_keeps_exact_post_and_video_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'delivery.json'
            path.write_text(json.dumps({'editions': {'daily:2026-09-29': {'uri': 'keep'}}}), encoding='utf-8')
            save_ps_delivery(URI, 'daily', EDITION, False, path)
            payload = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(payload['editions']['daily:2026-09-29']['uri'], 'keep')
            self.assertEqual(payload['editions']['daily:2026-09-30'],
                             dict(uri=URI, video_id='abcdefghijk', state='pending_video'))
            save_ps_delivery(URI, 'daily', EDITION, True, path)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['editions']['daily:2026-09-30']['state'], 'linked')

    def test_facet_offsets_and_existing_metadata_are_preserved(self):
        record = updater.replacement(OLD, SHORT, EDITION)
        self.assertEqual(record['createdAt'], OLD['createdAt'])
        self.assertEqual(record['reply'], OLD['reply'])
        self.assertEqual(record['embed']['external']['uri'], SHORT['url'])
        raw = record['text'].encode()
        for facet in record['facets']:
            word = raw[facet['index']['byteStart']:facet['index']['byteEnd']].decode()
            feature = facet['features'][0]
            self.assertEqual(word, '#' + feature['tag'] if 'tag' in feature else
                             '今回のショート動画' if feature['uri'] == SHORT['url'] else feature['uri'])

    def run_repair(self, old=OLD, owner=DID, confirmed=SHORT):
        found = dict(uri=URI, cid='original-cid', value=old)
        calls = []
        def api(method, payload, token=None, write=False):
            calls.append((method, payload, write))
            if method.endswith('createSession'):
                return dict(did=owner, accessJwt='TEST_TOKEN')
            if method.endswith('putRecord'):
                found['value'] = payload['record']
                return dict(uri=URI, cid='updated-cid')
            return found.copy()
        with patch.object(updater, 'edition_metadata', return_value=EDITION), \
             patch.object(updater, 'public_short', return_value=confirmed), \
             patch.object(updater, 'api', side_effect=api), \
             patch.dict(updater.os.environ, BLUESKY_HANDLE='owner', BLUESKY_APP_PASSWORD='TEST_ONLY'):
            result = updater.repair(URI, 'abcdefghijk', now=NOW)
        return result, calls

    def test_update_uses_original_cid_and_never_creates_a_new_key(self):
        result, calls = self.run_repair()
        writes = [p for m, p, w in calls if m.endswith('putRecord')]
        self.assertEqual(result['uri'], URI)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['swapRecord'], 'original-cid')
        self.assertEqual(writes[0]['rkey'], 'abcdef123')
        self.assertTrue(writes[0]['validate'])

    def test_idempotence(self):
        _, calls = self.run_repair(old=updater.replacement(OLD, SHORT, EDITION))
        self.assertFalse(any(m.endswith('putRecord') for m, _, _ in calls))

    def test_wrong_owner_date_or_unconfirmed_video_stops(self):
        for options in (dict(owner='did:plc:other'), dict(confirmed=None),
                        dict(old={**OLD, 'createdAt': '2026-09-29T10:00:13Z'})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_repair(**options)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
