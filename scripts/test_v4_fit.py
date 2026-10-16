"""v4 の札：長いシリーズ名は止める前に短い呼び方で収め直す（10/16 試合の回が出なかった件）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image

import short_v4_cards as v4


def canvas():
    im = Image.new('RGB', (1080, 1920), 'white')
    im.info['v3_layout'] = []
    return im


class FitTest(unittest.TestCase):
    def width_between(self, long_text, short_text):
        # 長い方は最小の大きさでも入らず、短い方は入る幅を作る
        f = v4.r3.font(18)
        return int((f.getlength(long_text) + f.getlength(short_text)) / 2)

    def test_long_round_name_is_shortened_instead_of_failing(self):
        long_text = 'リーグ優勝決定シリーズ　突破'
        width = self.width_between(long_text, '優勝決定S　突破')
        im = canvas()
        v4.text(im, 40, 100, long_text, size=40, width=width)
        drawn = ''.join(e.get('text', '') for e in im.info['v3_layout'])
        self.assertIn('優勝決定S', drawn)
        self.assertNotIn('リーグ優勝決定シリーズ', drawn)

    def test_still_fails_when_nothing_to_shorten(self):
        with self.assertRaises(ValueError):
            v4.text(canvas(), 40, 100, 'あ' * 80, size=40, width=200)

    def test_fitting_text_is_unchanged(self):
        im = canvas()
        v4.text(im, 40, 100, 'リーグ優勝決定シリーズ', size=40, width=2000)
        drawn = ''.join(e.get('text', '') for e in im.info['v3_layout'])
        self.assertIn('リーグ優勝決定シリーズ', drawn)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
