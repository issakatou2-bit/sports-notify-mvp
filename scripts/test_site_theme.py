"""Generated pages must keep the common appearance assets and content order."""
import unittest
from inject_video_links import add_channel_block, add_site_theme


class ThemeInjectionTest(unittest.TestCase):
    def test_theme_is_once_and_uses_root_paths(self):
        page = '<html><head></head><body><h1>Player</h1></body></html>'
        result = add_site_theme(page)
        self.assertEqual(add_site_theme(result), result)
        self.assertIn('src="/site-theme.js"', result)
        self.assertIn('href="/site-theme.css"', result)

    def test_top_back_link_does_not_push_content_below_promotions(self):
        page = '<head></head><body><a class="back">Back</a><h1>Game</h1></body>'
        result = add_channel_block(page, '<div>CHANNELS</div>')
        self.assertGreater(result.index('CHANNELS'), result.index('<h1>'))


if __name__ == '__main__':
    unittest.main(argv=['test_site_theme'])
