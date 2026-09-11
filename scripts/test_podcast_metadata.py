"""サイトだけの更新で、購読者に同じ回を再配信しないための回帰検査。"""

from datetime import date
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_podcast import DESCRIPTION, LEGACY_DESCRIPTION, TITLE, build_feed
from refresh_podcast_metadata import ITUNES, refresh_metadata


class PodcastMetadataTests(unittest.TestCase):
    def test_preserves_episode_identity_audio_and_specific_description(self):
        episodes = [
            {"date": date(2026, 9, 11), "file": "2026-09-11.mp3",
             "title": "9月12日の注目試合", "description": "8:10 A & B\n具体的な見どころ",
             "duration": 42, "size": 64000},
            {"date": date(2026, 9, 10), "file": "2026-09-10.mp3",
             "title": "9月11日の注目試合", "description": LEGACY_DESCRIPTION,
             "duration": 39, "size": 61000},
        ]
        old_feed = build_feed(episodes).replace(TITLE, "旧番組名").replace(
            DESCRIPTION, LEGACY_DESCRIPTION)
        before = ET.fromstring(old_feed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            path.write_text(old_feed, encoding="utf-8")
            refresh_metadata(path)
            after = ET.parse(path).getroot()
            first_update = path.read_bytes()
            refresh_metadata(path)
            self.assertEqual(first_update, path.read_bytes())
        channel = after.find("channel")
        self.assertEqual(channel.findtext("title"), TITLE)
        self.assertEqual(channel.findtext("description"), DESCRIPTION)
        self.assertEqual(channel.findtext(f"{{{ITUNES}}}summary"), DESCRIPTION)
        old_items, new_items = before.findall("channel/item"), channel.findall("item")
        self.assertEqual(len(old_items), len(new_items))
        self.assertEqual(new_items[0].findtext("description"), episodes[0]["description"])
        self.assertEqual(new_items[1].findtext("description"), DESCRIPTION)
        for old, new in zip(old_items, new_items):
            for tag in ("title", "pubDate", "guid", "enclosure", f"{{{ITUNES}}}duration"):
                self.assertEqual(ET.tostring(old.find(tag)), ET.tostring(new.find(tag)))
        for tag in ("link", "lastBuildDate", f"{{{ITUNES}}}image", f"{{{ITUNES}}}owner"):
            self.assertEqual(ET.tostring(before.find("channel/" + tag)),
                             ET.tostring(channel.find(tag)))

    def test_invalid_or_incomplete_feed_is_not_overwritten(self):
        for text in ("<html>error</html>", "<rss><channel/></rss>", "not xml"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "feed.xml"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises((ValueError, ET.ParseError)):
                    refresh_metadata(path)
                self.assertEqual(path.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    # run_checks.py は各検査へ作業用ディレクトリを渡す。
    unittest.main(argv=[__file__])
