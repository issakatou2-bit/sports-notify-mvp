"""非公開固定、再送保留、所有者、文字・音声の欠落など公開事故の境界を検査。"""
import array
import copy
import pathlib
import tempfile
import unittest
import wave
from datetime import date
from unittest.mock import MagicMock

import pilot_render
import pilot_series as series
import pilot_upload as upload

TODAY = date(2026, 9, 12)


def episode():
    return series.load_episode(series.CATALOG / "football-two-tables.json", TODAY)


def private_video(video_id="private-video"):
    return {"id": video_id, "snippet": {"channelId": upload.CHANNEL_ID},
            "status": {"privacyStatus": "private", "uploadStatus": "processed"}}


class ContentTests(unittest.TestCase):
    def test_review_expiry_stops_generation(self):
        with self.assertRaisesRegex(ValueError, "期限"):
            series.validate_episode(episode(), date(2027, 1, 1))

    def test_unreviewed_future_content_stops_generation(self):
        for change in ({"status": "draft"}, {"reviewed_on": "2026-10-01"}):
            data = episode()
            data.update(change)
            with self.assertRaises(ValueError):
                series.validate_episode(data, TODAY)

    def test_unsupported_rules_do_not_render_old_diagram(self):
        data = episode()
        data["facts"]["clubs"] = 35
        with self.assertRaisesRegex(ValueError, "方式"):
            series.validate_episode(data, TODAY)

    def test_content_revision_changes_deduplication_key(self):
        data = episode()
        changed = copy.deepcopy(data)
        changed["segments"][0]["speech"] += "もう一度。"
        self.assertNotEqual(series.episode_key(data), series.episode_key(changed))

    def test_all_frames_render_and_captions_fit(self):
        data = episode()
        for segment in data["segments"]:
            lines = pilot_render.wrap(segment["text"], 46, 1712)
            self.assertLessEqual(len(lines), 2)
            self.assertFalse(any(line[0] in "、。！？）」』】" for line in lines))
            image = pilot_render.frame(data, segment)
            self.assertEqual(image.size, (1920, 1080))
        self.assertEqual(pilot_render.thumbnail().size, (1920, 1080))

    def test_excess_subtitle_text_is_rejected(self):
        data = episode()
        data["segments"][0]["text"] = "観戦" * 100
        with self.assertRaises(ValueError):
            series.validate_episode(data, TODAY)

    def test_motion_changes_the_actual_picture(self):
        data = episode()
        segment = data["segments"][11]
        self.assertNotEqual(pilot_render.frame(data, segment, 0).tobytes(),
                            pilot_render.frame(data, segment, 1).tobytes())

    def test_silent_audio_cannot_continue_to_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "silent.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x00" * 48000)
            with self.assertRaisesRegex(ValueError, "無音"):
                series.wave_info(path)

    def test_audio_length_is_measured_from_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "tone.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(array.array('h', [1000, -1000] * 24000).tobytes())
            self.assertEqual(series.wave_info(path)["duration"], 2)


class PublicationTests(unittest.TestCase):
    def test_metadata_cannot_schedule_or_publish(self):
        timeline = {"duration": 150, "segments": [{"start": 0, "chapter": "はじめ"}]}
        body = upload.metadata(episode(), timeline)
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertNotIn("publishAt", body["status"])
        self.assertIn("VOICEVOX:四国めたん", body["snippet"]["description"])
        self.assertIn("[COLLESPO-PILOT:", body["snippet"]["description"])

    def test_public_or_wrong_owner_is_rejected(self):
        for field, value in (("privacyStatus", "public"), ("privacyStatus", "unlisted"), ("channelId", "another-channel")):
            item = private_video()
            item["snippet" if field == "channelId" else "status"][field] = value
            with self.assertRaises(RuntimeError):
                upload.require_private(item)

    def test_confirmed_episode_does_not_generate_another_upload(self):
        data = episode()
        key = series.episode_key(data)
        state = {"entries": {key: {"status": "confirmed", "video_id": "private-video"}}}
        self.assertEqual(upload.select_episode([data], state, {key: private_video()}), (None, None))

    def test_missing_or_uncertain_upload_never_blindly_retries(self):
        data = episode()
        key = series.episode_key(data)
        for status in ("pending", "uploaded", "confirmed"):
            with self.assertRaises(RuntimeError):
                upload.select_episode([data], {"entries": {key: {"status": status, "video_id": "old"}}}, {})

    def test_recovered_upload_is_reused_for_thumbnail_and_verification(self):
        data = episode()
        key = series.episode_key(data)
        selected, existing_id = upload.select_episode([data], {"entries": {key: {"status": "pending"}}}, {key: private_video()})
        self.assertEqual(existing_id, "private-video")
        self.assertEqual(selected["id"], data["id"])

    def test_wrong_account_stops_before_listing_uploads(self):
        yt = MagicMock()
        yt.channels().list().execute.return_value = {"items": [{"id": "not-collespo"}]}
        with self.assertRaises(RuntimeError):
            upload.owned_videos(yt)
        yt.playlistItems.assert_not_called()

    def test_failed_processing_is_not_treated_as_success(self):
        item = private_video()
        item["status"]["uploadStatus"] = "failed"
        with self.assertRaises(RuntimeError):
            upload.require_private(item)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
