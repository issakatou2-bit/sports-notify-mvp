"""保存した実例と、未発生を明記した構造テスト。通信・本番書込なし。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ledger_adapter import DATE_RULES, FILES, convert, documents
from ledger_audit import audit
from publications import Reader, identity, publication_id, read

FIXTURE = Path(__file__).parent/'fixtures/ledger/saved_20261027.json'


class PublicationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))

    def test_saved_discrepancies(self):
        f = self.fixture
        actual = audit(f['documents'], f['analytics'], f['playlists'])
        self.assertEqual(actual, f['expected_audit'])
        self.assertIn('SODgEsGrKWM', [x['video_id'] for x in actual['video_in_multiple_editions']])
        self.assertEqual(len(actual['edition_with_multiple_videos']), 3)
        self.assertTrue(all(x['repair_documented'] for x in actual['edition_with_multiple_videos']))
        self.assertTrue(actual['saved_not_in_ledger'])

    def test_get_preserves_repair_and_conflicts(self):
        reader = Reader(convert(self.fixture['documents']))
        pid = publication_id('mlb', 'morning_postseason', '2026-09-24')
        got = reader.get(pid)
        self.assertEqual({x['video_id'] for x in got['observations']}, {'UAGTxHrNlwU', 'eOiTYQKRD64'})
        self.assertEqual(reader.state(pid), 'unknown')
        self.assertEqual(reader.state(pid, video_id='eOiTYQKRD64'), 'public_confirmed')
        got.clear()
        self.assertIsNotNone(reader.get(pid))
        self.assertIsNone(reader.get('absent'))
        self.assertIsNone(reader.state('absent'))

    def test_dates_are_not_interchangeable(self):
        docs = {'published_videos': {'soccer_results': {'2026-10-26': {
            'video_id': 'result', 'published_at': '2026-10-27T01:00:00Z'}},
            'daily_soccer': {'2026-10-27': {'video_id': 'preview'}}}}
        r = Reader(convert(docs))
        self.assertEqual(len(r.find('soccer', 'results', material_day='2026-10-26')), 1)
        self.assertEqual(r.find(edition_day='2026-10-26'), [])
        self.assertEqual(r.find(event_day='2026-10-26'), [])
        self.assertEqual(len(r.find('soccer', 'daily', material_day='2026-10-27')), 1)
        with self.assertRaises(ValueError):
            r.find(date='2026-10-26')

    def test_backfill_does_not_prove_material_day_or_run_at(self):
        o = convert({'published_videos': {'soccer_results': {'2026-10-26': {
            'backfilled': True, 'video_id': 'x', 'published_at': '2026-10-26T00:00:00Z'}}}})[0]
        self.assertIsNone(o['material_day'])
        self.assertIsNone(o['run_at'])
        self.assertEqual(o['key_parts'], {'legacy_key': '2026-10-26'})

    def test_same_asset_in_two_ledgers_is_one_publication(self):
        docs = {'published_videos': {'asset': {'mlb_venue': {'video_id': 'x'}}},
                'published_assets': {'assets': {'mlb_venue': {'video_id': 'x'}}}}
        r = Reader(convert(docs))
        row, = r.find('asset')
        self.assertEqual(row['key_parts'], {'topic': 'mlb_venue'})
        self.assertEqual(len(row['observations']), 2)
        self.assertEqual(r.state(row['publication_id']), 'uploaded')

    def test_time_does_not_promote_upload_to_public(self):
        for raw, expected in [({'video_id': 'x', 'privacy': 'public'}, 'uploaded'),
                              ({'video_id': 'x', 'publish_at': '2000-01-01T00:00:00Z'}, 'scheduled')]:
            o, = convert({'published_videos': {'morning': {'2026-10-27': raw}}})
            self.assertEqual(o['state'], expected)
            self.assertEqual(o['edition_day'], '2000-01-01' if raw.get('publish_at') else None)
            self.assertTrue(o['unknown_reasons'])

    def test_scheduled_edition_day_is_jst_and_does_not_replace_legacy_key(self):
        o, = convert({'published_videos': {'daily': {'2026-10-26': {
            'video_id': 'x', 'publish_at': '2026-10-26T16:00:00Z'}}}})
        self.assertEqual(o['edition_day'], '2026-10-27')
        self.assertEqual(o['key_parts'], {'legacy_key': '2026-10-26'})
        self.assertIsNone(o['event_day'])
        self.assertEqual(len(Reader([o]).find(edition_day='2026-10-27')), 1)
        o, = convert({'published_videos': {'daily': {'2026-10-26': {
            'video_id': 'x', 'publish_at': '2026-10-26T16:00:00'}}}})
        self.assertIsNone(o['edition_day'])

    def test_sns_does_not_turn_inbox_into_publication(self):
        docs = {'published_tiktok': {'morning': {'2026-10-27': {
            'publish_id': 'inbox', 'status': 'SEND_TO_USER_INBOX'}}}}
        o, = convert(docs)
        self.assertEqual(o['state'], 'unknown')
        self.assertEqual(o['service'], 'tiktok')
        self.assertIsNone(o['video_id'])
        self.assertIsNone(o['edition_day'])
        self.assertEqual(o['raw']['publish_id'], 'inbox')

    def test_bluesky_links_only_unique_video_identity(self):
        docs = {'published_videos': {'daily': {'2026-10-27': {'video_id': 'x'}}},
                'bluesky_delivery': {'editions': {'daily:2026-10-27': {'video_id': 'x', 'state': 'linked'}}}}
        r = Reader(convert(docs))
        row, = r.find('mlb', 'daily')
        self.assertEqual(r.state(row['publication_id'], 'bluesky'), 'distributed')
        self.assertEqual(r.state(row['publication_id']), 'uploaded')
        docs['published_videos']['daily']['2026-10-26'] = {'video_id': 'x'}
        self.assertEqual(len(Reader(convert(docs)).find('delivery')), 1)

    def test_flash_pending_is_never_retry_permission(self):
        docs = {'soccer_flash_receipts': {'espn-401917035': {'kind': 'soccer_goal_short',
                'status': 'pending', 'at': '2026-10-27T00:00:00Z'}}}
        o, = convert(docs)
        self.assertEqual(o['key_parts'], {'game_id': 'espn-401917035'})
        self.assertEqual(o['state'], 'upload_pending')
        self.assertIsNone(o['video_id'])

    def test_id_components_cannot_collide(self):
        self.assertNotEqual(publication_id('soccer', 'goal_short', 'a:b', 'c'),
                            publication_id('soccer', 'goal_short', 'a', 'b:c'))
        i = identity('soccer', 'race', {'competition': 'PL', 'season': '2026', 'round': '10'})
        self.assertEqual(i['publication_id'], 'soccer:race:PL:2026:10')
        with self.assertRaises(ValueError):
            publication_id('mlb', 'daily', '')

    def test_unknown_date_rules_cover_fifteen_saved_kinds(self):
        self.assertEqual(len(self.fixture['documents']['published_videos']), 15)
        self.assertFalse(set(self.fixture['documents']['published_videos']) - DATE_RULES.keys())

    def test_player_identity_is_preserved_without_title_guess(self):
        o, = convert({'published_assets': {'assets': {'season_player_123': {'video_id': 'x'}}}})
        self.assertEqual(o['player_id'], '123')
        self.assertEqual(o['raw'], {'video_id': 'x'})

    def test_synthetic_cross_kind_and_title_mismatch(self):
        # 現snapshotには0件。実例と混ぜず検出器の条件を確かめる。
        docs = {'published_videos': {'daily_soccer': {'2026-10-27': {
                'video_id': 'x', 'title': '【欧州サッカー】日本人選手の結果'}},
                'soccer_results': {'2026-10-26': {'video_id': 'x'}}}}
        a = audit(docs, {}, {})
        self.assertEqual(len(a['cross_kind_registration']), 1)
        self.assertEqual(len(a['title_kind_mismatch']), 1)

    def test_reader_is_readonly_and_missing_or_corrupt_inputs_fail(self):
        docs = deepcopy(self.fixture['documents'])
        before = deepcopy(docs)
        Reader(convert(docs)).find()
        self.assertEqual(docs, before)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'data').mkdir()
            for name in FILES:
                (root/'data'/f'{name}.json').write_text(json.dumps(docs.get(name, {})), encoding='utf8')
            hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'data').iterdir()}
            read(root).find()
            self.assertEqual(hashes, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes})
            (root/'data/published_assets.json').write_text('{', encoding='utf8')
            with self.assertRaises(json.JSONDecodeError):
                documents(root)
            with self.assertRaises(FileNotFoundError):
                documents(root/'absent')


if __name__ == '__main__':
    unittest.main(argv=[__file__])
