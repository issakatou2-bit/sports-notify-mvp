"""固定台帳で公開除外・SEO・解析の入れ外しを検査（外部通信なし）。"""
import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import generate_archive_pages as archive
import generate_player_pages as players
import site_analytics as analytics
import site_videos as videos


def entry(video_id="public-one", **extra):
    return dict(video_id=video_id, title="大谷翔平の試合", privacy="public",
                published_at="2000-01-01T00:00:00+00:00", **extra)


def objects(page):
    result = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        data = json.loads(raw)
        result.extend(data if isinstance(data, list) else [data])
    return [x for x in result if x.get("@type") == "VideoObject"]


class SiteVideoSEO(unittest.TestCase):
    def test_each_public_video_is_embedded_and_described_on_both_pages(self):
        ledger = {"daily": {"2000-01-01": entry()},
                  "new-slot": {"2000-01-01": entry("public-two", description="説明</script>",
                      thumbnail_url="https://example.com/thumb.jpg", content_url="https://example.com/video.mp4")},
                  "alias": {"2000-01-01": entry()}}
        pages = [archive.render_day_page("2000-01-01", {"games": []}, None, None, ledger),
                 players.render_player_page("大谷翔平", [], ledger)]
        for page in pages:
            self.assertEqual(page.count('<iframe '), 2)
            self.assertEqual(page.count('loading="lazy"'), 2)
            self.assertEqual(page.count('src="https://www.youtube-nocookie.com/embed/'), 2)
            data = objects(page)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['uploadDate'], '2000-01-01T00:00:00+00:00')
            full = next(x for x in data if 'description' in x)
            self.assertEqual(full['description'], '説明</script>')
            self.assertEqual(full['thumbnailUrl'], 'https://example.com/thumb.jpg')
            self.assertEqual(full['contentUrl'], 'https://example.com/video.mp4')
            self.assertIn('YouTubeで見る', page)

    def test_exclusions_apply_to_embed_and_jsonld_for_both_pages(self):
        excluded = [{'held': True}, {'hold': True}, {'status': 'deleted'},
                    {'status': 'failed'}, {'status': 'private'}, {'privacy': 'private'},
                    {'privacy': 'unlisted'}, {'publish_at': '2099-01-01T00:00:00Z'},
                    {'publish_at': 'broken'}, {'video_id': 'bad"<script>'}]
        for overrides in excluded:
            record = entry(); record.update(overrides)
            ledger = {'morning': {'2000-01-01': record}}
            for page in [archive.render_day_page('2000-01-01', {'games': []}, None, None, ledger),
                         players.render_player_page('大谷翔平', [], ledger)]:
                self.assertNotIn('<iframe ', page)
                self.assertEqual(objects(page), [])

    def test_absent_metadata_is_not_invented_or_confused_with_watch_url(self):
        data = json.loads(re.search(r'>(.*?)</script>', videos.video_jsonld([
            {'video_id': 'id', 'url': 'https://youtu.be/id'}])).group(1))[0]
        self.assertEqual(set(data), {'@context', '@type', 'embedUrl'})

    def test_player_link_requires_explicit_name_not_team_membership(self):
        ledger = {'daily': {'2000-01-01': entry()}}
        ledger['daily']['2000-01-01']['title'] = 'ドジャースの試合'
        self.assertEqual(videos.player_videos('大谷翔平', ledger), [])
        ledger['daily']['2000-01-01']['players'] = ['大谷翔平']
        self.assertEqual(len(videos.player_videos('大谷翔平', ledger)), 1)

    def test_same_video_on_two_dates_does_not_erase_the_older_day(self):
        ledger = {'daily': {'2000-01-01': entry(), '2000-01-02': entry()}}
        for date in ['2000-01-01', '2000-01-02']:
            page = archive.render_day_page(date, {'games': []}, None, None, ledger)
            self.assertEqual(len(objects(page)), 1)
        self.assertEqual(len(videos.player_videos('大谷翔平', ledger)), 1)

    def test_analytics_empty_enabled_idempotent_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'analytics.json'
            page = '<html><head></head><body></body></html>'
            config.write_text('{"goatcounter": ""}', encoding='utf-8')
            self.assertEqual(analytics.apply_analytics(page, analytics.analytics_script(config)), page)
            config.write_text('{"goatcounter": "collespo-test"}', encoding='utf-8')
            script = analytics.analytics_script(config)
            enabled = analytics.apply_analytics(page, script)
            self.assertIn('https://collespo-test.goatcounter.com/count', enabled)
            self.assertIn('async src="https://gc.zgo.at/count.js"', enabled)
            self.assertEqual(analytics.apply_analytics(enabled, script), enabled)
            self.assertEqual(analytics.apply_analytics(enabled, ''), page)
            config.write_text('{"goatcounter": "https://bad.example/"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                analytics.analytics_script(config)

    def test_whole_site_injection_and_disabled_generated_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'analytics.json'
            config.write_text('{"goatcounter": "test-site"}', encoding='utf-8')
            (root / 'players').mkdir()
            for path in [root / 'index.html', root / 'players/ohtani.html']:
                path.write_text('<head></head>', encoding='utf-8')
            argv = ['analytics', '--site', str(root), '--config', str(config)]
            with patch.object(sys, 'argv', argv):
                analytics.main()
            self.assertTrue(all('gc.zgo.at/count.js' in p.read_text() for p in root.rglob('*.html')))
            config.write_text('{"goatcounter": ""}', encoding='utf-8')
            with patch.object(sys, 'argv', argv):
                analytics.main()
            self.assertTrue(all('gc.zgo.at/count.js' not in p.read_text() for p in root.rglob('*.html')))
        for page in [archive.render_day_page('2000-01-01', {'games': []}, None, None, {}),
                     players.render_player_page('大谷翔平', [], {})]:
            self.assertNotIn('gc.zgo.at/count.js', page)

    def test_sitemap_includes_every_day_and_player_and_metadata_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'players').mkdir()
            for slug in ['shohei-ohtani', 'seiya-suzuki', 'index']:
                (root / 'players' / (slug + '.html')).touch()
            dates = [('2000-01-01', None), ('2000-01-02', None)]
            tree = ET.fromstring(archive.render_sitemap(dates, root))
            urls = {el.text for el in tree.findall('.//{*}loc')}
            self.assertTrue({'https://collespo.com/archive/' + d + '.html' for d, _ in dates} <= urls)
            self.assertIn('https://collespo.com/players/shohei-ohtani.html', urls)
            self.assertIn('https://collespo.com/players/seiya-suzuki.html', urls)
            self.assertNotIn('https://collespo.com/players/index.html', urls)
        for page in [archive.render_day_page('2000-01-01', {'games': []}, None, None, {}),
                     players.render_player_page('大谷翔平', [], {})]:
            title = re.search(r'<title>(.*?)</title>', page).group(1)
            description = re.search(r'<meta name="description" content="(.*?)"', page).group(1)
            canonical = re.search(r'<link rel="canonical" href="(.*?)"', page).group(1)
            self.assertIn('property="og:title" content="' + title + '"', page)
            self.assertIn('property="og:description" content="' + description + '"', page)
            self.assertIn('property="og:url" content="' + canonical + '"', page)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
