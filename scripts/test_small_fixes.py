"""日付またぎと保存済み投稿。固定材料だけで、外部通信・音声合成なし。"""
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ps_quotes as quotes
import ps_story
import ps_game_story
import soccer_slots_v4 as slots
import soccer_selected_preview as preview
import soccer_preview_angles as angles
from test_soccer_preview_angles import game, fixture


class PreviewDates(unittest.TestCase):
    def setUp(self):
        for guard in (patch('socket.socket.connect', side_effect=AssertionError('通信禁止')),
                      patch('requests.sessions.Session.request', side_effect=AssertionError('通信禁止')),
                      patch.dict(os.environ, COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_LOOK='v6',
                                 COLLESPO_SOCCER_FOCUS='on', COLLESPO_SOLO_HOST='metan')):
            guard.start()
            self.addCleanup(guard.stop)

    def test_clock_boundaries_and_jst_publication_day(self):
        for generated, start, expected in [
            ('2026-11-07T10:30:00Z', '2026-11-07T12:30:00Z', '日本時間21時30分'),
            ('2026-11-07T10:30:00Z', '2026-11-07T14:30:00Z', '日本時間23時30分'),
            ('2026-11-07T10:30:00Z', '2026-11-07T15:00:00Z', '日本時間11月8日0時'),
            ('2026-11-07T10:30:00Z', '2026-11-07T20:05:00Z', '日本時間11月8日5時5分'),
            ('2026-11-07T15:00:00Z', '2026-11-07T20:05:00Z', '日本時間5時5分'),
            ('2026-12-31T10:30:00Z', '2026-12-31T15:00:00Z', '日本時間1月1日0時'),
        ]:
            with self.subTest(generated=generated, start=start):
                g = dict(game(), start_time_utc=start)
                self.assertEqual(slots.preview_time(g, generated), expected)
                self.assertTrue(preview.opening(g, generated).startswith(expected+'、'))

    def test_saved_jst_only_midnight_and_year_boundary(self):
        for generated, start, expected in [
            ('2026-11-07T10:30:00Z', '11/08 00:00', '日本時間11月8日0時'),
            ('2026-12-31T10:30:00Z', '01/01 05:05', '日本時間1月1日5時5分'),
        ]:
            with self.subTest(start=start):
                self.assertEqual(slots.preview_time(dict(start_time_jst=start), generated), expected)

    def test_program_captions_narration_and_recomputed_guard(self):
        for start, clock in [('2026-11-07T12:30:00Z', '日本時間21時30分'),
                             ('2026-11-07T15:00:00Z', '日本時間11月8日0時'),
                             ('2026-11-07T20:05:00Z', '日本時間11月8日5時5分')]:
            with self.subTest(start=start):
                g = dict(game(), start_time_utc=start, home_has_jp=True)
                data = dict(fixture(g), generated_at='2026-11-07T10:30:00Z')
                before = copy.deepcopy(data)
                with patch.object(angles, 'read', return_value={}):
                    enriched = angles.attach(data, results={})
                doc = preview.program(enriched)['narration']
                self.assertEqual(data, before)
                self.assertTrue(doc['segments'][1]['text'].startswith(clock+'、'))
                self.assertEqual(angles.check(doc), [])
                if '11月8日' in clock:
                    self.assertEqual(doc['segments'][0]['meta']['unit'], '日本時間11月8日')
                    bad = copy.deepcopy(doc)
                    bad['segments'][1]['text'] = bad['segments'][1]['text'].replace('11月8日', '')
                    self.assertTrue(angles.check(bad))
                for plan in (preview.program(data), slots.preview_program(data)):
                    self.assertTrue(plan['narration']['segments'][1]['text'].startswith(clock+'、'))


class SavedQuotes(unittest.TestCase):
    def row(self, text='“Cubs season”', **extra):
        return dict(team='カブス', text=text, jp='「今季を振り返る」', likes=1,
                    at='2026-11-07T00:00:00Z', uri='at://test/app.bsky.feed.post/1',
                    handle='test', author='記者', **extra)

    def test_same_rule_for_images_links_and_word_boundary(self):
        for embed in ({'$type': 'app.bsky.embed.images', 'images': [{}]},
                      {'$type': 'app.bsky.embed.external', 'external': {'uri': 'https://example.com'}},
                      {'$type': 'app.bsky.embed.record', 'record': {}}):
            for count in (11, 12):
                with self.subTest(embed=embed['$type'], count=count):
                    row = self.row(text=' '.join(['word']*count), embed=embed)
                    self.assertEqual(quotes.usable_posts([row]), [] if count < 12 else [row])

    def test_missing_or_empty_embed_keeps_legacy_rows_and_does_not_mutate(self):
        rows = [self.row(), self.row(embed=None), self.row(embed={}), self.row(embed={'images': [{}]})]
        before = copy.deepcopy(rows)
        self.assertEqual(quotes.usable_posts(rows), rows[:3])
        self.assertEqual(rows, before)

    def test_reader_and_merge_filter_old_and_new_rows(self):
        old = self.row(embed={'images': [{}]})
        legacy = dict(self.row(), uri='legacy')
        long = dict(self.row(text=' '.join(['word']*12), embed={'external': {}}), uri='long')
        with patch('pathlib.Path.read_text', return_value=json.dumps({'posts': [old, legacy, long]})):
            self.assertEqual(quotes.load('saved.json'), [legacy, long])
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        self.assertEqual(quotes.merge([old, legacy, long], [], now), [legacy, long])
        self.assertEqual(quotes.merge([], [old, legacy, long], now), [legacy, long])
        expired = dict(legacy, at='2026-10-01T00:00:00Z')
        self.assertEqual(quotes.merge([expired], [], now), [])
        with patch('pathlib.Path.read_text', side_effect=OSError):
            self.assertEqual(quotes.load('missing.json'), [])

    def test_selectors_and_momentum_reuse_exclude_saved_embed(self):
        blocked = self.row(embed={'images': [{}]})
        legacy = self.row()
        self.assertIsNone(ps_story.pick_quote([blocked], 'カブス', {}, {}))
        self.assertTrue(ps_story.pick_quote([legacy], 'カブス', {}, {}))
        args = ('カブス', '2026-11-06', {}, {}, {}, [])
        self.assertIsNone(ps_game_story.pick_reporter([blocked], *args))
        self.assertTrue(ps_game_story.pick_reporter([legacy], *args))


if __name__ == '__main__':
    unittest.main()
