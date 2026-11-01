"""単独ずんだもん音声の本文ページで、配置により別話者へ変わらない。"""
import pathlib
import unittest
from unittest.mock import patch
from PIL import Image
import review_render as rr


class Presenter(unittest.TestCase):
    def test_left_and_right_use_the_same_narrator(self):
        loaded, locations = [], []
        def open_portrait(path):
            loaded.append(str(path).replace('\\', '/'))
            return Image.new('RGBA', (1080, 1920), 'white')
        class Canvas:
            def paste(self, sprite, position, mask):
                locations.append(position)
        with patch.object(rr.Image, 'open', side_effect=open_portrait):
            for side in ('left', 'right'):
                rr._presenter(Canvas(), pathlib.Path('assets-root'), side)
        self.assertEqual(len(loaded), 2)
        self.assertTrue(all('zundamon/C-cheer/' in p for p in loaded))
        self.assertLess(locations[0][0], locations[1][0])
        self.assertEqual(locations[0][1], locations[1][1])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
