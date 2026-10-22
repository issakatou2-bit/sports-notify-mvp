"""10/20の古い記事・10/21の非公開配信と同姓別人を、通信なしで再現する。"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import article_freshness as af
import buffer_daily as buffer
import local_buzz
import local_reporters as reporters
import mlb_buzz
import sanity
import sanity_material
import soccer_jp_week as week

ROOT = Path(__file__).resolve().parents[1]
TARGET = '2026-10-20'
TITLE = 'Shohei Ohtani returns to Dodgers lineup after resting knee'


def article(at='', url='https://abc30.invalid/ohtani', source='ABC30', title=TITLE):
    return dict(title=title, at=at, url=url, source=source)


class ArticleDates(unittest.TestCase):
    def test_two_day_boundary_old_rss_and_unknown(self):
        rows = [article('Sun, 18 Oct 2026 00:00:00 GMT'),
                article('Sat, 17 Oct 2026 23:59:59 GMT'),
                article('Wed, 03 Jun 2026 12:00:00 GMT'), article(), article('not a date')]
        result = af.fresh_articles(rows, TARGET)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['published_date'], '2026-10-18')
        self.assertEqual(result[0]['publication_evidence'][0]['source'], 'at')

    def test_fresh_feed_does_not_hide_old_article_or_url(self):
        for html in ['<meta property="article:published_time" content="2026-06-03T08:00:00-07:00">',
                     '<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","datePublished":"2026-06-03"}]}</script>',
                     '<time datetime="2026-06-03T10:00:00Z">June 3</time>']:
            row = af.dated_article(article(TARGET), html)
            self.assertEqual(row['published_date'], '2026-06-03')
            self.assertFalse(af.fresh_articles([row], TARGET))
        for url in ['https://abc30.invalid/2026/06/03/story', 'https://abc30.invalid/story-2026-06-03']:
            self.assertFalse(af.fresh_articles([article(TARGET, url)], TARGET))
        row = af.dated_article(article(TARGET), '', 'https://abc30.invalid/2026/06/03/story')
        self.assertFalse(af.fresh_articles([row], TARGET))

    def test_modified_date_cannot_supply_missing_publication_date(self):
        row = af.dated_article(article(), '<meta property="article:modified_time" content="2026-10-20">'
                               '<time itemprop="dateModified" datetime="2026-10-20"></time>')
        self.assertFalse(af.fresh_articles([row], TARGET))

    def test_unknown_requires_same_report_from_another_dated_outlet(self):
        unknown = article()
        known = article(TARGET, 'https://espn.invalid/story', 'ESPN')
        kept = af.fresh_articles([unknown, known], TARGET)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0]['corroborated_by'][0]['date'], TARGET)
        self.assertEqual(len(af.fresh_articles([kept[0]], TARGET)), 1)
        self.assertFalse(af.fresh_articles([kept[0]], '2026-10-23'))
        for other in [article(TARGET), article('2026-06-03', source='ESPN'),
                      article(TARGET, source='ESPN', title='Ohtani hits a home run')]:
            self.assertFalse(af.fresh_articles([unknown], TARGET, corroborating=[other]))
        self.assertFalse(af.fresh_articles([article('2026-06-03')], TARGET, corroborating=[known]))
        self.assertFalse(af.fresh_articles([unknown], TARGET,
                         corroborating=[article(TARGET, source='ABC30 Sports')]))

    def test_collect_filters_before_deduplication(self):
        rows = [article('2026-06-03'), article(TARGET, source='ESPN')]
        with patch.object(reporters, 'JP_PLAYERS_MLB', [{'name_en': 'Shohei Ohtani'}]), \
             patch.object(reporters, 'LEAGUE_QUERIES', ()), \
             patch.object(reporters, 'fetch_headlines', return_value=rows), \
             patch('mlb_headlines.fetch', return_value=[]):
            result = reporters.collect_headlines(sleep=0, target_date=TARGET)
        self.assertEqual([r['source'] for r in result], ['ESPN'])

    def test_fetch_uses_article_date_even_if_rss_is_recent(self):
        rss = '<rss><channel><item><title>'+TITLE+'</title><pubDate>20 Oct 2026 12:00:00 GMT</pubDate><link>https://abc30.invalid/test-unique</link></item></channel></rss>'
        responses = [SimpleNamespace(text=rss, raise_for_status=lambda: None),
                     SimpleNamespace(text='<meta itemprop="datePublished" content="2026-06-03">',
                                     url='https://abc30.invalid/test-unique', raise_for_status=lambda: None)]
        with patch.object(reporters.requests, 'get', side_effect=responses):
            result = reporters.fetch_headlines('Ohtani')
        self.assertFalse(af.fresh_articles(result, TARGET))
        self.assertEqual(result[0]['published_date'], '2026-06-03')

    def test_saved_material_rechecked_against_edition_not_collection_time(self):
        material = dict(updated_at=TARGET, headlines=[article('2026-06-03'), article(TARGET)],
                        headline_pool=[article('2026-06-03')], posts=[dict(text='Ohtani news', at='2026-06-03')])
        result = af.fresh_material(material, TARGET)
        self.assertEqual(len(result['headlines']), 1)
        self.assertEqual(result['headline_pool'], [])
        self.assertEqual(result['posts'], [])

    def test_local_buzz_rss_and_atom_dates(self):
        now = datetime.now(timezone.utc).isoformat()
        for raw in [f'<rss><channel><title>Feed</title><item><title>Old</title><pubDate>2026-06-03</pubDate></item><item><title>Fresh</title><pubDate>{now}</pubDate></item><item><title>Unknown</title></item></channel></rss>',
                    f'<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title><entry><title>Old</title><published>2026-06-03</published></entry><entry><title>Fresh</title><published>{now}</published></entry><entry><title>Unknown</title><updated>{now}</updated></entry></feed>']:
            response = SimpleNamespace(content=raw.encode(), status_code=200, raise_for_status=lambda: None)
            with patch.object(local_buzz.requests, 'get', return_value=response):
                self.assertEqual(local_buzz.fetch_titles('fixture', 'https://feed.invalid'), ['Fresh'])

    def test_saved_buzz_checks_individual_video_dates(self):
        now = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'buzz.json'
            path.write_text(json.dumps(dict(updated_at=now, videos=[dict(title='old', published_at='2026-06-03'),
                           dict(title='new', published_at=now), dict(title='unknown')])), encoding='utf-8')
            self.assertEqual([r['title'] for r in mlb_buzz.load(str(path))], ['new'])

    def test_buzz_uses_original_publication_instead_of_playlist_addition(self):
        now = datetime.now(timezone.utc).isoformat()
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: dict(items=[
            dict(snippet=dict(title='Old Highlights', publishedAt=now, resourceId=dict(videoId='old')),
                 contentDetails=dict(videoPublishedAt='2026-06-03T00:00:00Z')),
            dict(snippet=dict(title='New Highlights', publishedAt=now, resourceId=dict(videoId='new')),
                 contentDetails=dict(videoPublishedAt=now)),
            dict(snippet=dict(title='Unknown Highlights', publishedAt=now, resourceId=dict(videoId='unknown')))]))
        with patch.object(mlb_buzz, '_official_channel_id', return_value='UCfixture'), \
             patch.object(mlb_buzz.requests, 'get', return_value=response):
            self.assertEqual([r['video_id'] for r in mlb_buzz.fetch_recent_highlights('TEST')], ['new'])


class PublicationGate(unittest.TestCase):
    def test_old_or_unknown_sources_in_saved_narration_stop_without_llm(self):
        for source in [article('2026-06-03'), article()]:
            doc = dict(date_jst=TARGET, segments=[dict(text='大谷翔平は復帰しました。',
                       meta=dict(source_headlines=[source]))])
            self.assertTrue(any('記事の公開日' in error for error in sanity_material.check(doc)))
        doc['segments'][0]['meta']['source_headlines'] = [article(TARGET)]
        self.assertFalse(sanity_material.check(doc))

    def test_high_stops_low_passes_and_results_are_saved(self):
        with tempfile.TemporaryDirectory() as td:
            narration, output, summary = [Path(td)/name for name in ('narr.json', 'sanity.json', 'summary.md')]
            narration.write_text(json.dumps(dict(date_jst=TARGET, segments=[dict(text='大谷翔平はスタメンに復帰しました。')])), encoding='utf-8')
            for severity, status in [('high', 1), ('low', 0)]:
                issue = dict(severity=severity, where='大谷翔平はスタメンに復帰しました。', why='6月の記事が10月の材料に混入')
                with patch.object(sys, 'argv', ['sanity.py', '--general', '--strict', '--narration', str(narration), '--out', str(output)]), \
                     patch.dict(os.environ, dict(ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=str(summary))), \
                     patch.object(sanity, 'general', return_value=[issue]), \
                     patch.object(sanity, 'check_scores', return_value=[]), \
                     patch.object(sanity, 'check_stat_files', return_value=[]):
                    self.assertEqual(sanity.main(), status)
                report = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(bool(report['blocking_issues']), severity == 'high')
            self.assertIn('予約停止', summary.read_text(encoding='utf-8'))

    def test_workflow_gate_fails_job_and_precedes_upload(self):
        import yaml
        workflow = yaml.safe_load((ROOT/'.github/workflows/morning_recap.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['recap']['steps'] if 'recap' in workflow['jobs'] else next(iter(workflow['jobs'].values()))['steps']
        shorts = next(s for s in steps if s.get('id') == 'shorts')
        script = shorts['run']
        gate = script[script.index('if ! python scripts/sanity.py'):script.index('python scripts/synthesize_narration.py')]
        self.assertIn('CLAIM_FAILED=1', gate)
        self.assertIn('continue', gate)
        self.assertLess(script.index('if ! python scripts/sanity.py'), script.index('--upload'))
        stop = next(s for s in steps if s.get('if') == "steps.shorts.outputs.claims_failed == '1'")
        self.assertEqual(stop['run'], 'exit 1')
        self.assertFalse(stop.get('continue-on-error', False))


class NonpublicVideo(unittest.TestCase):
    def verify(self, items=None, error=None):
        response = io.StringIO(json.dumps(dict(items=items or [])))
        with patch.dict(os.environ, dict(YOUTUBE_API_KEY='TEST')), \
             patch.object(buffer.urllib.request, 'urlopen', side_effect=error, return_value=response):
            return buffer.verify_youtube(dict(video_id='fixture'))

    def video(self, privacy, channel='UCpZ_j8X8uOex5VvKwwTJj3Q', **status):
        return dict(status=dict(privacyStatus=privacy, **status), snippet=dict(channelId=channel, title='fixture'))

    def test_nonpublic_is_skip_but_missing_wrong_channel_and_fetch_are_errors(self):
        for privacy, extra, reason in [('private', {}, '非公開'), ('unlisted', {}, '非公開'),
                                       ('private', dict(publishAt='2026-10-23T09:00:00Z'), '予約中')]:
            with self.assertRaises(buffer.VideoNotPublic) as caught:
                self.verify([self.video(privacy, **extra)])
            self.assertIn(reason, caught.exception.reason)
        for items in [[], [self.video('public', channel='other')], [self.video('private', channel='other')], [self.video('unknown')]]:
            with self.assertRaises(ValueError) as caught:
                self.verify(items)
            self.assertNotIsInstance(caught.exception, buffer.VideoNotPublic)
        with self.assertRaises(RuntimeError):
            self.verify(error=ConnectionError('offline'))
        self.assertEqual(self.verify([self.video('public')])['title'], 'fixture')

    def test_main_skips_before_any_sns_or_media_operations(self):
        with tempfile.TemporaryDirectory() as td:
            summary = Path(td)/'summary.md'
            for reason in ('非公開（private）', '予約中'):
                with patch.object(sys, 'argv', ['buffer_daily.py', '--source-run', '7', '--kind', 'morning_press', '--publish']), \
                     patch.object(buffer.os, 'environ', dict(BUFFER_CHANNELS='twitter', GITHUB_STEP_SUMMARY=str(summary))), \
                     patch.object(buffer, 'github', return_value=dict(id=7)), \
                     patch.object(Path, 'read_text', return_value='{}'), \
                     patch.object(buffer, 'select_record', return_value=(TARGET, dict(video_id='fixture'))), \
                     patch.object(buffer, 'verify_youtube', side_effect=buffer.VideoNotPublic(reason)), \
                     patch.object(buffer, 'graphql') as sns, patch.object(buffer, 'host_video') as host:
                    buffer.main()
                    sns.assert_not_called()
                    host.assert_not_called()
            text = summary.read_text(encoding='utf-8')
            self.assertIn('morning_press', text)
            self.assertIn('飛ばした（予約中）', text)
            self.assertIn('飛ばした（非公開', text)


class PlayerIdentity(unittest.TestCase):
    def row(self, first):
        return dict(id=1, first_name=first, second_name='Sano', web_name='Sano')

    def test_unique_surname_does_not_override_different_given_name(self):
        self.assertIsNone(week.resolve([self.row('Kodai')], 'Kaishu Sano'))
        self.assertIsNone(week.resolve([self.row('Kaishun')], 'Kaishu Sano'))
        self.assertEqual(week.resolve([self.row('Kaishu')], 'Kaishu Sano'), 1)
        self.assertIsNone(week.resolve([self.row('K.')], 'Kaishu Sano'))
        self.assertIsNone(week.resolve([self.row('')], 'Kaishu Sano'))
        self.assertIsNone(week.resolve([self.row('K.'), dict(self.row('Kodai'), id=2)], 'K. Sano'))
        self.assertIsNone(week.resolve([], ''))


if __name__ == '__main__':
    with patch('socket.socket.connect', side_effect=AssertionError('試験中の通信は禁止')):
        unittest.main(argv=[sys.argv[0]])
