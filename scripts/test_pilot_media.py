"""写真の確認状態・取り違え・出典表示・保管の境界を検査する。"""
import copy
import io
import json
import os
import pathlib
import tempfile
import unittest
import zipfile
from datetime import date
from unittest.mock import patch

from PIL import Image

import pilot_archive
import pilot_baseball
import pilot_media
import pilot_media_sampler
import pilot_render
import pilot_series
import pilot_upload


def episode():
    return pilot_series.load_episode(pilot_series.CATALOG / "baseball-two-hits.json", date(2026, 9, 12))


class MediaTests(unittest.TestCase):
    def test_unapproved_or_restricted_asset_is_rejected(self):
        source = pilot_media.catalog()["ohtani-bat-2024"]
        for changes in ({"status": "pending"}, {"license": "CC BY-NC 4.0"}, {"author": ""},
                        {"captured_at": ""}, {"captured_at": "Taken on 5 January 2024"}, {"changes": ""}, {"sha256": "unverified"}):
            asset = {**source, **changes}
            with self.assertRaises(ValueError):
                pilot_media.validate_asset(asset)

    def test_download_cannot_use_an_arbitrary_host_or_credentials(self):
        for url in ["https://example.com/a.jpg", "http://upload.wikimedia.org/wikipedia/commons/a.jpg",
                    "https://password@upload.wikimedia.org/wikipedia/commons/a.jpg", "https://upload.wikimedia.org:443/wikipedia/commons/a.jpg"]:
            with self.assertRaises(ValueError):
                pilot_media.valid_download_url(url)

    def test_wrong_cached_content_stops_instead_of_being_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = pilot_media.catalog()["ohtani-bat-2024"]
            path = pathlib.Path(tmp) / "wrong.jpg"
            path.write_bytes(b"wrong picture")
            with self.assertRaises(ValueError):
                pilot_media.verify_file(path, asset)

    def test_source_clip_must_be_bounded_and_muted(self):
        source = pilot_media.catalog()["courtois-presentation-2018"]
        for clip in ({"start": -1, "duration": 6, "audio": "muted"}, {"start": 120, "duration": 180, "audio": "muted"},
                     {"start": 120, "duration": 6, "audio": "original"}):
            with self.assertRaises(ValueError):
                pilot_media.validate_asset({**source, "clip": clip})

    def test_sampler_dates_and_labels_fit(self):
        assets = pilot_media.catalog()
        source = Image.new("RGB", (1280, 720), "gray")
        for number, (asset_id, competition, notes) in enumerate(pilot_media_sampler.ITEMS, 1):
            self.assertEqual(pilot_media_sampler.frame(assets[asset_id], competition, notes, source, 0.5, number).size, (1920, 1080))
        self.assertEqual(pilot_media_sampler.ending().size, (1920, 1080))

    def test_missing_or_duplicate_media_id_stops(self):
        for ids in [["not-reviewed"], ["ohtani-bat-2024", "ohtani-bat-2024"]]:
            with self.assertRaises(ValueError):
                pilot_media.assets_for({"media_ids": ids})

    def test_dialogue_revision_is_distinct_from_old_upload_and_stable_on_retry(self):
        data = pilot_series.load_episode(pilot_series.CATALOG / "football-two-tables.json", date(2026, 9, 12))
        key = pilot_series.episode_key(data)
        self.assertNotEqual(key, "football-two-tables-14d638c44eb39b29")
        self.assertEqual(key, pilot_series.episode_key(copy.deepcopy(data)))
        data["voices"]["metan"]["pitch"] += .01
        self.assertNotEqual(key, pilot_series.episode_key(data))

    def test_source_revision_changes_the_new_pilot_key(self):
        data = episode()
        key = pilot_series.episode_key(data)
        assets = copy.deepcopy(pilot_media.assets_for(data))
        assets[0]["sha256"] = "0" * 64
        with patch.object(pilot_media, "assets_for", return_value=assets):
            self.assertNotEqual(pilot_series.episode_key(data), key)

    def test_photo_reference_and_diagram_facts_must_agree(self):
        data = episode()
        data["segments"][0]["media_id"] = "not-used"
        with self.assertRaises(ValueError):
            pilot_series.validate_episode(data, date(2026, 9, 12))
        data = episode()
        data["facts"]["a_runs"] = 1
        with self.assertRaises(ValueError):
            pilot_series.validate_episode(data, date(2026, 9, 12))

    def test_all_new_frames_and_thumbnail_fit_with_a_photo(self):
        data = episode()
        # 色と線を持つ写真の代用品で枠・ズームを検証。CIは外部素材を取りに行かない。
        source = Image.new("RGB", (1920, 1400), "#fabc29")
        source.paste(Image.new("RGB", (400, 1400), "#174635"), (760, 0))
        with patch.object(pilot_baseball, "photo_image", return_value=source):
            for segment in data["segments"]:
                self.assertEqual(pilot_render.frame(data, segment).size, (1920, 1080))
                lines = pilot_render.wrap(segment["text"], 46, 1712)
                self.assertLessEqual(len(lines), 2)
                self.assertTrue(all(line[0] not in "、。！？）」』】" for line in lines))
            self.assertEqual(pilot_render.thumbnail(data).size, (1920, 1080))
            first = data["segments"][0]
            self.assertNotEqual(pilot_render.frame(data, first, 0).tobytes(), pilot_render.frame(data, first, 1).tobytes())

    def test_upload_has_exact_photo_sources_and_baseball_tags(self):
        data = episode()
        body = pilot_upload.metadata(data, {"duration": 150, "segments": [{"start": 0, "chapter": "はじめ"}]})
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertNotIn("publishAt", body["status"])
        self.assertIn("MLB", body["snippet"]["tags"])
        self.assertNotIn("チャンピオンズリーグ", body["snippet"]["tags"])
        for asset in pilot_media.assets_for(data):
            for key in ("title", "author", "source_page", "license_url"):
                self.assertIn(asset[key], body["snippet"]["description"])
        self.assertIn("2024", body["snippet"]["description"])
        self.assertIn("架空", body["snippet"]["description"])


class ArchiveTests(unittest.TestCase):
    def test_encrypted_roundtrip_keeps_contents_and_uses_fresh_nonce(self):
        key = os.urandom(32)
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "source"
            source.mkdir()
            (source / "example.json").write_text(json.dumps({"example": "private"}), encoding="utf-8")
            raw = pilot_archive.pack(source)
            encrypted = pilot_archive.seal(raw, key)
            self.assertNotIn(b"example.json", encrypted)
            self.assertNotEqual(encrypted, pilot_archive.seal(raw, key))
            target = pathlib.Path(tmp) / "restored"
            pilot_archive.unpack(pilot_archive.unseal(encrypted, key), target)
            self.assertEqual((source / "example.json").read_bytes(), (target / "example.json").read_bytes())

    def test_wrong_key_and_tampering_cannot_be_opened(self):
        from cryptography.exceptions import InvalidTag
        key = os.urandom(32)
        encrypted = pilot_archive.seal(b"private archive payload", key)
        with self.assertRaises(InvalidTag):
            pilot_archive.unseal(encrypted, os.urandom(32))
        changed = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
        with self.assertRaises(InvalidTag):
            pilot_archive.unseal(changed, key)

    def test_archive_paths_and_existing_files_are_protected(self):
        for name in ("../escape.txt", "C:/escape.txt", "nested\\escape.txt", "/escape.txt"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                entry = zipfile.ZipInfo("placeholder")
                entry.filename = name  # WindowsのZipInfo初期化による区切り文字の修正を避ける。
                archive.writestr(entry, b"invalid")
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    pilot_archive.unpack(buffer.getvalue(), tmp)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            (path / "keep.txt").write_text("keep", encoding="utf-8")
            raw = pilot_archive.pack(path)
            with self.assertRaises(ValueError):
                pilot_archive.unpack(raw, path)
            self.assertEqual((path / "keep.txt").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
