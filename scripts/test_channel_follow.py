"""説明欄の登録の導線（channel_follow）の試験。"""
import sys
import unittest

import channel_follow as cf


class WithSubscribe(unittest.TestCase):
    def test_after_first_paragraph(self):
        text = "久保建英のソシエダはEL圏内\n落ちるまで勝点3\n\n#サッカー\n\nサイト: https://collespo.com/"
        out = cf.with_subscribe(text)
        self.assertEqual(out.split("\n")[:4],
                         ["久保建英のソシエダはEL圏内", "落ちるまで勝点3", "", cf.SUBSCRIBE_LINE])
        self.assertTrue(out.endswith("サイト: https://collespo.com/"))

    def test_once_only(self):
        out = cf.with_subscribe(cf.with_subscribe("題\n\n本文"))
        self.assertEqual(out.count("sub_confirmation=1"), 1)

    def test_no_blank_line_appends(self):
        self.assertEqual(cf.with_subscribe("名簿だけ"), "名簿だけ\n\n" + cf.SUBSCRIBE_LINE)

    def test_does_not_overflow_limit(self):
        long = "あ" * 4990
        self.assertEqual(cf.with_subscribe(long), long)

    def test_upload_applies_it(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent / "upload_youtube.py").read_text(encoding="utf-8")
        self.assertIn("__import__('channel_follow').with_subscribe(", src)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
