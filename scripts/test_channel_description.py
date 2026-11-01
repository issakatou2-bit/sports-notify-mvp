"""チャンネル紹介文の先頭1行の置き換えの検査。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_description as cd


class ReplaceFirstLine(unittest.TestCase):
    def test_only_first_line_changes(self):
        rest = "\n\nコレスポは、MLB・欧州サッカーの注目試合を届けます。\nhttps://collespo.com/"
        self.assertEqual(cd.replace_first_line(cd.OLD_FIRST_LINE + rest),
                         cd.NEW_FIRST_LINE + rest)

    def test_other_first_line_is_left_alone(self):
        self.assertIsNone(cd.replace_first_line("別の紹介文\n続き"))
        self.assertIsNone(cd.replace_first_line(cd.NEW_FIRST_LINE + "\n続き"))
        self.assertIsNone(cd.replace_first_line(""))
        self.assertIsNone(cd.replace_first_line(None))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
