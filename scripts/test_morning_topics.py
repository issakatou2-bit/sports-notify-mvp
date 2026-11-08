"""公開した題材の再使用と、新情報の取り違えを固定材料で確認する。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import morning_topics as topics


class MorningTopicsTest(unittest.TestCase):
    def setUp(self):
        pairs = [('Jung Hoo Lee', 'イ・ジョンフー'), ('Shohei Ohtani', '大谷翔平'),
                 ('Seiya Suzuki', '鈴木誠也')]
        self.aliases = patch.object(topics, 'aliases', return_value=[
            (topics.normalize(a), topics.normalize(b)) for a, b in pairs] + [
            (topics.normalize(b), topics.normalize(b)) for _, b in pairs])
        self.aliases.start()
        self.addCleanup(self.aliases.stop)

    def ledger(self, row=None, day='2026-11-07', kind='morning_voices'):
        record = {'video_id': 'our-video', 'privacy': 'public',
                  'title': 'イ・ジョンフー、2年連続で長打40本超えに現地ファンの声 #Shorts'}
        if row:
            record['source_topics'] = [topics.evidence(row)]
        return {kind: {day: record}}

    def test_legacy_published_title_blocks_the_reported_repeat(self):
        candidate = {'title': '2026 Jung Hoo Lee Highlights',
                     'topic_jp': 'イ・ジョンフー、2年連続で長打40本超えのハイライト'}
        self.assertEqual([], topics.filter_rows([candidate], '2026-11-08', self.ledger()))

    def test_legacy_subject_without_name_dictionary(self):
        with patch.object(topics, 'aliases', return_value=[]):
            candidate = {'topic_jp': 'イ・ジョンフー、2年連続で長打40本超えのハイライト'}
            self.assertEqual([], topics.filter_rows([candidate], '2026-11-08', self.ledger()))

    def test_same_video_with_other_url_form_and_title(self):
        old = {'url': 'https://www.youtube.com/watch?v=abc123&utm_source=feed',
               'video_title': '元の動画'}
        new = {'url': 'https://youtu.be/abc123?t=13', 'video_title': '題を書き替えた動画'}
        self.assertEqual([], topics.filter_rows([new], '2026-11-08', self.ledger(old)))

    def test_same_article_ignores_tracking_and_fragment(self):
        old = {'url': 'https://www.mlb.com/news/player-award?utm_source=feed#top', 'title': '元記事'}
        new = {'url': 'https://mlb.com/news/player-award', 'title': '別の訳'}
        self.assertTrue(topics.same(topics.evidence(old), topics.evidence(new)))

    def test_same_player_and_event_across_sources_and_languages(self):
        old = {'title': 'Shohei Ohtani wins Silver Slugger award', 'url': 'https://a.test/story'}
        new = {'jp': '大谷翔平がシルバースラッガー賞を受賞', 'url': 'https://b.test/new'}
        ledger = self.ledger(old, kind='morning_press')
        self.assertEqual([], topics.filter_rows([new], '2026-11-08', ledger))

    def test_same_player_different_award_or_stage_is_new(self):
        old = topics.evidence({'title': '大谷翔平がシルバースラッガー賞のファイナリストに'})
        for title in ['大谷翔平がシルバースラッガー賞を受賞', '大谷翔平がMVPを受賞']:
            with self.subTest(title=title):
                self.assertFalse(topics.same(old, topics.evidence({'title': title})))

    def test_different_player_same_event_is_new(self):
        old = topics.evidence({'title': '大谷翔平がシルバースラッガー賞を受賞'})
        new = topics.evidence({'title': '鈴木誠也がシルバースラッガー賞を受賞'})
        self.assertFalse(topics.same(old, new))

    def test_changed_record_and_different_game_are_new(self):
        old = topics.evidence({'title': 'イ・ジョンフーの長打40本', 'game_date': '2026-11-06'})
        self.assertFalse(topics.same(old, topics.evidence({'title': 'イ・ジョンフーの長打41本'})))
        self.assertFalse(topics.same(old, topics.evidence({'title': 'イ・ジョンフーの長打40本',
                                                          'game_date': '2026-11-07'})))

    def test_seven_day_boundary_and_same_day_cross_slot(self):
        row = {'video_id': 'same'}
        ledger = self.ledger(row, day='2026-11-01', kind='morning_press')
        self.assertEqual([], topics.filter_rows([row], '2026-11-08', ledger))
        self.assertEqual([row], topics.filter_rows([row], '2026-11-09', ledger))
        self.assertEqual([], topics.filter_rows([row], '2026-11-01', ledger))

    def test_window_uses_publication_japan_date(self):
        row = {'video_id': 'same'}
        ledger = self.ledger(row, day='2026-11-01')
        ledger['morning_voices']['2026-11-01']['publish_at'] = '2026-11-01T23:30:00Z'
        self.assertEqual([], topics.filter_rows([row], '2026-11-09', ledger))

    def test_delayed_immediate_publication_uses_actual_day_not_edition_key(self):
        row = {'video_id': 'same'}
        ledger = self.ledger(row, day='2026-11-01')
        ledger['morning_voices']['2026-11-01']['published_at'] = '2026-11-01T17:25:00Z'
        self.assertEqual([], topics.filter_rows([row], '2026-11-09', ledger))
        self.assertEqual([row], topics.filter_rows([row], '2026-11-10', ledger))

    def test_private_or_unpublished_record_does_not_block(self):
        row = {'video_id': 'same'}
        ledger = self.ledger(row)
        ledger['morning_voices']['2026-11-07']['privacy'] = 'private'
        self.assertEqual([row], topics.filter_rows([row], '2026-11-08', ledger))

    def test_only_published_sources_block_not_other_candidates(self):
        old, new = {'video_id': 'used'}, {'video_id': 'not-used'}
        self.assertEqual([new], topics.filter_rows([old, new], '2026-11-08', self.ledger(old)))

    def test_filtered_video_pool_matches_the_retained_comments(self):
        data = {'voices': {'voices': [{'url': 'https://youtu.be/new', 'video_title': '新しい題材'}]},
                'buzz': [{'video_id': 'repeated'}, {'video_id': 'new'}]}
        with patch.object(topics, 'filter_rows', side_effect=lambda rows, day: rows):
            topics.filter_material(data, 'voices', '2026-11-08')
        self.assertEqual([{'video_id': 'new'}], data['buzz'])

    def test_voice_binding_records_selected_video_not_fan_identity(self):
        data = {'date_jst': '2026-11-08', 'voices': {'voices': [
            {'video_title': 'イ・ジョンフーの長打40本', 'url': 'https://youtu.be/used',
             'author': 'private fan', 'title': 'private comment'},
            {'video_title': '別の動画', 'url': 'https://youtu.be/not-used'}]}}
        doc = {'segments': [{'kind': 'voices', 'meta': {'picked': [0]}, 'text': '引用'}]}
        bound = topics.attach(doc, data, 'voices')
        self.assertEqual('2026-11-08', bound['edition_date'])
        self.assertEqual(['youtube:used'], bound['source_topics'][0]['urls'])
        self.assertNotIn('private', json.dumps(bound['source_topics']))
        self.assertEqual(1, len(bound['source_topics']))
        self.assertEqual('used', bound['topic_video_id'])

    def test_upload_recheck_blocks_other_day_but_allows_same_edition_correction(self):
        row = {'video_id': 'same'}
        ledger = self.ledger(row)
        snapshot = [topics.evidence(row)]
        self.assertTrue(topics.repeated_for_upload(snapshot, 'morning_voices', '2026-11-08', ledger))
        self.assertFalse(topics.repeated_for_upload(snapshot, 'morning_voices', '2026-11-07', ledger))
        self.assertIn('2026-11-07', ledger['morning_voices'])

    def test_press_binding_keeps_only_the_posts_actually_read(self):
        used = {'title': '今回読んだ投稿', 'url': 'https://a.test/used'}
        unused = {'title': '候補に残った投稿', 'url': 'https://a.test/unused'}
        doc = {'segments': [{'kind': 'reporters', 'text': '引用', 'meta': {'source_posts': [used]}}]}
        data = {'date_jst': '2026-11-08', 'reporters': {'posts': [used, unused]}}
        self.assertEqual([topics.evidence(used)], topics.attach(doc, data, 'press')['source_topics'])

    def test_seed_uses_only_cited_articles_before_the_upload(self):
        import seed_morning_topics as seed
        title = '大谷翔平がナ・リーグのシルバースラッガー賞のファイナリストに選出'
        row = {'title': title, 'url': 'https://a.test/used'}
        material = {'updated_at': '2026-11-07T06:00:00Z', 'headlines': [row,
            {'title': '鈴木誠也がナ・リーグのシルバースラッガー賞のファイナリストに選出',
             'url': 'https://a.test/not-used'}]}
        record = {'title': title, 'published_at': '2026-11-07T06:30:00Z'}
        self.assertEqual([topics.evidence(row)], seed.selected(record, material, 'morning_press'))
        material['updated_at'] = '2026-11-07T07:00:00Z'
        self.assertEqual([], seed.selected(record, material, 'morning_press'))

    def test_skip_is_respected_by_watchdog_and_healthcheck(self):
        import healthcheck as health
        import missing_kinds as missing
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'skips.json')
            ledger = Path(directory) / 'videos.json'
            ledger.write_text('{}', encoding='utf-8')
            topics.record_skip('morning_voices', '2026-11-08', '新しい題材が0件', path)
            original = topics.skip_reason
            with patch.object(topics, 'skip_reason', side_effect=lambda k, d: original(k, d, path)), \
                 patch.object(missing.post_common, 'DAILY_LINEUP', [('morning_voices', 'ファンの声', '', '17:30')]), \
                 patch.object(health, 'EXPECTED_DAILY', [('morning_voices', 'ファンの声', '17:30', '2026-01-01')]), \
                 patch.object(health, 'OPTIONAL_DAILY', []), patch.object(health, 'load', return_value={}), \
                 patch.object(health, '_mlb_games', side_effect=AssertionError('試合日程へ逃がさない')):
                self.assertEqual([], missing.missing('2026-11-08', str(ledger),
                    datetime.fromisoformat('2026-11-08T21:00:00+09:00')))
                lines, absent, skipped, _ = health.check_videos('2026-11-08')
                self.assertEqual((0, 1), (absent, skipped))
                self.assertIn('新しい題材が0件', lines[0])

    def test_no_candidates_records_reason_per_edition(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'skips.json')
            topics.record_skip('morning_voices', '2026-11-08', '新しい題材が0件', path)
            self.assertEqual('新しい題材が0件', topics.skip_reason('morning_voices', '2026-11-08', path))
            self.assertEqual('', topics.skip_reason('morning_voices', '2026-11-09', path))
            self.assertEqual('', topics.skip_reason('daily', '2026-11-08', path))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
