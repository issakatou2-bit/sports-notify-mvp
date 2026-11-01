"""作り直した長編の導線と、説明欄の本文保護を検査する。"""
import sys
import unittest

from longform_links import HEADING, LEGACY_HEADING, replace_longform_link


class LinkTests(unittest.TestCase):
    def test_first_link_and_repeat_are_idempotent(self):
        expected = HEADING + "\nhttps://youtu.be/BCg3ebh7XlE\n\n本文\n音声クレジット"
        got = replace_longform_link("本文\n音声クレジット", "BCg3ebh7XlE")
        self.assertEqual(got, expected)
        self.assertEqual(replace_longform_link(got, "BCg3ebh7XlE"), got)

    def test_observed_three_candidates_become_one_correct_heading(self):
        body = "本文\n#MLB\n元動画: https://youtu.be/Vrjvltn_9HY\n音声: VOICEVOX"
        old = "".join(LEGACY_HEADING + "\nhttps://youtu.be/" + vid + "\n\n"
                      for vid in ("BCg3ebh7XlE", "hMIf4vlY91g", "zcwSx_PfHjQ"))
        got = replace_longform_link(old + body, "BCg3ebh7XlE")
        self.assertEqual(got, HEADING + "\nhttps://youtu.be/BCg3ebh7XlE\n\n" + body)

    def test_replacement_preserves_unmanaged_links_even_to_same_id(self):
        body = "本文中の参考: https://youtu.be/BCg3ebh7XlE\nクレジット"
        got = replace_longform_link(body, "BCg3ebh7XlE")
        self.assertTrue(got.endswith(body))
        self.assertTrue(got.startswith(HEADING))

    def test_changed_id_replaces_previous_managed_link(self):
        old = replace_longform_link("本文", "hMIf4vlY91g")
        got = replace_longform_link(old, "BCg3ebh7XlE")
        self.assertNotIn("hMIf4vlY91g", got)
        self.assertEqual(got.count(HEADING), 1)

    def test_crlf_and_empty_description(self):
        body = "本文\r\n音声クレジット"
        old = LEGACY_HEADING + "\r\nhttps://youtu.be/hMIf4vlY91g\r\n\r\n" + body
        self.assertTrue(replace_longform_link(old, "BCg3ebh7XlE").endswith(body))
        self.assertEqual(replace_longform_link("", "BCg3ebh7XlE"),
                         HEADING + "\nhttps://youtu.be/BCg3ebh7XlE")

    def test_overflow_does_not_silently_cut_credits(self):
        with self.assertRaises(ValueError):
            replace_longform_link("x" * 5000 + "VOICEVOX", "BCg3ebh7XlE")

    def test_invalid_id_is_not_posted(self):
        with self.assertRaises(ValueError):
            replace_longform_link("本文", "bad\nInjected")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
