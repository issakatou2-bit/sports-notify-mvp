"""Protect archive discovery, original URLs, safe metadata and publish gating."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_archive_pages as page


def game(**extra):
    return dict(dict(is_notable=True, league='MLB', matchup='パイレーツ vs カブス',
                     start_time_jst='09/12 03:20', jp_players=['今永昇太', '鈴木誠也']), **extra)


class ArchiveDiscovery(unittest.TestCase):
    def test_related_players_do_not_become_appearance_claims(self):
        details = page.discovery_details([game(jp_starters=[{'name': '今永昇太'}]),
                                         game(matchup='ドジャース vs パドレス', jp_players=['大谷翔平'])])
        self.assertEqual(details['players'], ['今永昇太', '鈴木誠也', '大谷翔平'])
        output = page.render_index_page([('2026-09-11', None)], {},
                                       {'2026-09-11': '2026年9月12日'}, {'2026-09-11': details})
        self.assertIn('ドジャース vs パドレス', output)
        self.assertIn('関連する選手：今永昇太・鈴木誠也・大谷翔平', output)
        self.assertIn('href="2026-09-11.html"', output)
        self.assertNotIn('data-archive-entry hidden', output)
        self.assertIn('出場を保証するものではありません', output)

    @patch.object(page, 'load_published_videos', return_value={})
    def test_day_metadata_uses_game_date_keeps_original_url(self, _):
        output = page.render_day_page('2026-09-11', {'games': [game()]}, None, None)
        self.assertIn('<title>2026年9月12日の注目試合｜パイレーツ vs カブス | コレスポ</title>', output)
        self.assertIn('href="https://collespo.com/archive/2026-09-11.html"', output)
        self.assertNotIn('カブスほか', output)
        structured = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', output)]
        trail = next(x for x in structured if isinstance(x, dict))['itemListElement']
        self.assertEqual([x['position'] for x in trail], [1, 2, 3])
        self.assertEqual(trail[-1]['name'], '2026年9月12日')

    @patch.object(page, 'load_published_videos', return_value={})
    def test_external_text_cannot_close_title_or_json_script(self, _):
        name = '</title></script><script>alert("x")</script>'
        output = page.render_day_page('2026-09-11', {'games': [game(matchup=name)]}, None, None)
        self.assertNotIn(name, output)
        values = re.findall(r'<script type="application/ld\+json">(.*?)</script>', output)
        self.assertEqual(json.loads(values[0])[0]['name'], name)

    def test_only_calendar_dates_are_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['2026-09-11', '2026-02-30', 'index', '2024-02-29']:
                (root / (name + '.json')).write_text('{}')
            self.assertEqual([x[0] for x in page.parse_date_files(root)], ['2026-09-11', '2024-02-29'])

    def test_broken_record_does_not_replace_existing_output(self):
        for bad in ['{', '[]', '{"games": null}', '{"games": [1]}']:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target = root / 'source', root / 'out'
                source.mkdir(); target.mkdir()
                (source / '2026-09-11.json').write_text(bad)
                (target / 'index.html').write_text('existing')
                with patch.object(sys, 'argv', ['archive', '--archive-dir', str(source), '--out-dir', str(target)]):
                    with self.assertRaises(RuntimeError):
                        page.main()
                self.assertEqual((target / 'index.html').read_text(), 'existing')

    def test_sitemap_does_not_invent_last_modified_date(self):
        output = page.render_sitemap([('2026-09-11', None)])
        self.assertIn('https://collespo.com/archive/2026-09-11.html', output)
        self.assertNotIn('<lastmod>', output)

    def test_missing_and_empty_source_cannot_pass_publish_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for source in [Path(tmp) / 'absent', Path(tmp)]:
                with patch.object(sys, 'argv', ['archive', '--archive-dir', str(source)]):
                    with self.assertRaises((FileNotFoundError, RuntimeError)):
                        page.main()

    def test_failed_archive_blocks_site_but_not_daily_video_steps(self):
        root = Path(__file__).resolve().parents[1]
        daily = (root / '.github/workflows/daily_notify.yml').read_text(encoding='utf-8')
        gate = "steps.standings.outcome == 'success' && steps.archive.outcome == 'success'"
        self.assertEqual(daily.count(gate), 2)
        archive = daily.split('- name: Generate archive pages')[1].split('- name:')[0]
        self.assertIn('id: archive', archive)
        self.assertIn('continue-on-error: true', archive)
        deploy = (root / '.github/workflows/deploy_site.yml').read_text(encoding='utf-8')
        self.assertNotIn('continue-on-error', deploy.split('- name: Generate archive pages')[1].split('- name:')[0])


if __name__ == '__main__':
    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=0).result
    print('ALL OK' if result.wasSuccessful() else 'FAILURES')
    raise SystemExit(0 if result.wasSuccessful() else 1)
