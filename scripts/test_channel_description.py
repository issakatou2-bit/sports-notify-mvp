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


class ReplaceFull(unittest.TestCase):
    def test_full_text_replaces_current_description(self):
        self.assertEqual(cd.replace_full(cd.NEW_FIRST_LINE + "\n\n古い本文", "新しい全文\n続き\n"),
                         "新しい全文\n続き")

    def test_unexpected_description_is_left_alone(self):
        self.assertIsNone(cd.replace_full("別の紹介文\n続き", "新しい全文"))
        self.assertIsNone(cd.replace_full("", "新しい全文"))
        self.assertIsNone(cd.replace_full(cd.NEW_FIRST_LINE, ""))

    def test_already_applied_is_idempotent(self):
        self.assertEqual(cd.replace_full("新しい全文\n続き", "新しい全文\n続き\n"), "新しい全文\n続き")

    def test_saved_text_starts_with_the_new_lead(self):
        with open(cd.FULL_TEXT, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("MLB・欧州サッカーの日本人選手を、数字と図で短く。"))
        self.assertLessEqual(len(text), 1000)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
