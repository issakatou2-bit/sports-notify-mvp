"""配色を失う生成headと、締めの実描画で体が浮く失敗の回帰。"""
import json
from pathlib import Path
import sys
import unittest

from visual_capture import layout_issues, renderer_layout


class VisualFixes(unittest.TestCase):
    def test_review_text_survives_windows_shell_encoding(self):
        root = Path(__file__).parents[1]
        table = root/'build_reports/visual_fixes_20261027/baseline-replacements.md'
        text = table.read_text(encoding='utf-8')
        self.assertIn('配色基準', text)
        self.assertNotIn('???', text)
        data = json.loads((root/'docs/audit-evidence/visual-baseline/inventory.json').read_text(encoding='utf-8'))
        rows = [row for row in data['images'] if row.get('replacement_source')]
        self.assertTrue(rows)
        for row in rows:
            self.assertIn('合格', row['review'])
            self.assertNotIn('???', row['review'])

    def test_formula_and_connection_fields_use_shared_surfaces(self):
        import generate_score_page as score
        self.assertIn('.formula { background: var(--surface-raised)', score.render())
        root = Path(__file__).parents[1]
        for family in ('threads', 'tiktok'):
            for name in ('index.html', 'callback.html'):
                page = (root/'web'/family/name).read_text(encoding='utf-8')
                self.assertNotIn('background: #0E121A', page)

    def test_static_pages_share_palette_except_search_verification(self):
        for path in (Path(__file__).parents[1]/'web').rglob('*.html'):
            page = path.read_text(encoding='utf-8')
            if '</head>' not in page:
                continue  # 検索サービス所有確認用の一行ファイルは表示ページではない。
            head = page.split('</head>')[0]
            self.assertEqual(head.count('src="/site-theme.js"'), 1, str(path))
            self.assertEqual(head.count('href="/site-theme.css"'), 1, str(path))

    def test_all_generated_heads_share_palette_after_local_styles(self):
        import generate_archive_pages as archive
        import generate_player_pages as players
        import generate_score_page as score
        import generate_soccer_page as soccer
        import generate_standings_page as standings
        from datetime import datetime, timezone
        fixture = Path(__file__).parent/'fixtures/visual/standings-data.json'
        data = {int(k): v for k, v in json.loads(fixture.read_text(encoding='utf-8')).items()}
        pages = [archive.HEAD_TMPL, players.HEAD, score.render(), soccer.render({}),
                 standings.render_page(data, 2026, datetime(2026,10,27,tzinfo=timezone.utc))]
        for page in pages:
            head = page.split('</head>')[0]
            self.assertEqual(head.count('src="/site-theme.js"'), 1)
            self.assertEqual(head.count('href="/site-theme.css"'), 1)
            self.assertLess(head.index('</style>'), head.index('href="/site-theme.css"'))
            self.assertNotIn('defer src="/site-theme.js"', head)

    def test_saved_failure_and_actual_fixed_outros(self):
        fixture = Path(__file__).parent/'fixtures/visual/failures.json'
        case = next(c for c in json.loads(fixture.read_text(encoding='utf-8'))
                    if c['name'] == 'body-cut-inside-screen')
        self.assertIn('body-cut', [r['kind'] for r in layout_issues(case['layout'])])
        from preview_visual_fixes import frames
        for look in ('v6', 'v4'):
            for kind, image, errors in frames(look):
                self.assertFalse(errors, (look, kind, errors))
                if kind != 'outro':
                    if look == 'v6':
                        import characters
                        caption_top = image.info['duo_caption']['box'][1]
                        for item in image.info['duo_layer']:
                            art = characters.bust(item['who'], item['face'], item['height'], item['dim'])
                            self.assertGreater(item['at'][1] + art.height, caption_top)
                            self.assertEqual(item['at'][1] + item['cut'], caption_top)
                    continue
                geometry = renderer_layout(image.info)
                self.assertFalse(layout_issues(geometry))
                portraits = [b for b in geometry['boxes'] if b['role'] == 'character']
                self.assertTrue(portraits)
                self.assertTrue(all(b['body_cut_y'] == image.height for b in portraits))
                # 実描画の記録を旧位置へ戻した時だけ不合格になる。
                image.info['duo_portraits'][0]['box'][1] -= 300
                image.info['duo_portraits'][0]['box'][3] -= 300
                self.assertIn('body-cut', [r['kind'] for r in layout_issues(renderer_layout(image.info))])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
