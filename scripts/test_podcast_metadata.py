"""サイトだけの更新で、購読者に同じ回を再配信しないための回帰検査。"""

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_podcast import DESCRIPTION, LEGACY_DESCRIPTION, TITLE, build_feed, episode_description
from refresh_podcast_metadata import ITUNES, refresh_metadata


class PodcastMetadataTests(unittest.TestCase):
    def test_ps_all_cards_and_actual_speakers(self):
        for game_type in ("F", "D", "L", "W", "R"):
            with self.subTest(game_type=game_type), tempfile.TemporaryDirectory() as directory:
                games = Path(directory) / "games.json"
                narration = Path(directory) / "narration.json"
                rows = [dict(is_notable=True, game_type=game_type,
                             start_time_jst=f"09/30 {n:02d}:00",
                             away_team_name=f"Away{n}", home_team_name=f"Home{n}",
                             reasons=[dict(text="旧構成の見どころ")])
                        for n in (11, 6, 9, 3)]
                games.write_text(json.dumps({"games": rows}), encoding="utf-8")
                narration.write_text(json.dumps({"segments": [{"speaker": 3}, {"speaker": 2}]}), encoding="utf-8")
                description = episode_description(str(games), str(narration))
                if game_type == "R":
                    self.assertNotIn("Away3", description)
                    self.assertIn("旧構成の見どころ", description)
                else:
                    self.assertNotIn("旧構成の見どころ", description)
                    offsets = [description.index(f"Away{n}") for n in (3, 6, 9, 11)]
                    self.assertEqual(offsets, sorted(offsets))
                self.assertIn("VOICEVOX:ずんだもん / VOICEVOX:四国めたん", description)

    def test_default_and_unknown_speaker(self):
        with tempfile.TemporaryDirectory() as directory:
            games = Path(directory) / "games.json"
            narration = Path(directory) / "narration.json"
            games.write_text(json.dumps({"games": [dict(is_notable=True)]}), encoding="utf-8")
            narration.write_text(json.dumps({"segments": [{"text": "legacy"}]}), encoding="utf-8")
            self.assertIn("VOICEVOX:ずんだもん", episode_description(str(games), str(narration)))
            self.assertNotIn("四国めたん", episode_description(str(games), str(narration)))
            narration.write_text(json.dumps({"segments": [{"speaker": 999}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                episode_description(str(games), str(narration))

    def test_exact_episode_correction_preserves_delivery_identity(self):
        episodes = [dict(date=date(2026, 9, n), file=f"2026-09-{n}.mp3", title="daily",
                         description="old", duration=42, size=64000) for n in (29, 28)]
        before = ET.fromstring(build_feed(episodes))
        with tempfile.TemporaryDirectory() as directory:
            feed = Path(directory) / "feed.xml"
            catalog = Path(directory) / "corrections.json"
            feed.write_text(build_feed(episodes), encoding="utf-8")
            catalog.write_text(json.dumps([dict(guid="https://collespo.com/podcast/2026-09-29.mp3",
                                                description="four verified games")]), encoding="utf-8")
            refresh_metadata(feed, catalog)
            after = ET.parse(feed).getroot()
            first = feed.read_bytes()
            refresh_metadata(feed, catalog)
            self.assertEqual(first, feed.read_bytes())
            self.assertEqual(after.findtext("channel/item/description"), "four verified games")
            self.assertEqual(after.findall("channel/item")[1].findtext("description"), "old")
            for old, new in zip(before.findall("channel/item"), after.findall("channel/item")):
                for tag in ("title", "pubDate", "guid", "enclosure", f"{{{ITUNES}}}duration"):
                    self.assertEqual(ET.tostring(old.find(tag)), ET.tostring(new.find(tag)))
            # 対象が重複していたら、元のRSSを壊さず止める。
            duplicate = ET.parse(feed)
            import copy
            duplicate.find("channel").append(copy.deepcopy(duplicate.find("channel/item")))
            duplicate.write(feed, encoding="utf-8")
            original = feed.read_bytes()
            with self.assertRaises(ValueError):
                refresh_metadata(feed, catalog)
            self.assertEqual(original, feed.read_bytes())

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
