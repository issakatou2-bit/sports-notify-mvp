"""非公開固定、再送保留、所有者、文字・音声の欠落など公開事故の境界を検査。"""
import array
import copy
import io
import json
import pathlib
import tempfile
import unittest
import wave
from datetime import date
from unittest.mock import MagicMock, patch

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
    def test_unknown_speaker_and_invalid_pitch_stop_generation(self):
        data = episode()
        data['segments'][0]['speaker'] = 'unknown'
        with self.assertRaisesRegex(ValueError, '話者'):
            series.validate_episode(data, TODAY)
        for pitch in [float('nan'), float('inf'), True, .9, 'high']:
            data = episode()
            data['voices']['metan']['pitch'] = pitch
            with self.assertRaisesRegex(ValueError, '高さ'):
                series.validate_episode(data, TODAY)

    def test_legacy_single_voice_content_still_validates(self):
        data = episode()
        del data['voices']
        for segment in data['segments']:
            segment.pop('speaker')
        series.validate_episode(data, TODAY)
        self.assertEqual(series.voice_credits(data), 'VOICEVOX:四国めたん')

    def test_dialogue_routes_audio_and_pitch_to_the_named_presenter(self):
        data = episode()
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            audio.writeframes(array.array('h', [1000, -1000] * 84000).tobytes())
        raw = stream.getvalue()
        calls = []
        def response(base, endpoint, params=None, body=None):
            if endpoint == '/version':
                return b'"test"'
            if endpoint == '/speakers':
                return json.dumps([{'name': name, 'styles': [{'id': sid, 'name': 'ノーマル'}]}
                                   for name, sid in series.PRESENTERS.values()]).encode()
            if endpoint == '/audio_query':
                calls.append(('query', params['speaker']))
                return b'{"kana":"","pauseLengthScale":1}'
            calls.append(('audio', params['speaker'], body['pitchScale'], body['speedScale']))
            return raw
        with tempfile.TemporaryDirectory() as tmp, patch.object(series, 'voice_request', side_effect=response):
            timeline = series.synthesize(data, tmp)
        for source, rendered, query, audio in zip(data['segments'], timeline['segments'], calls[::2], calls[1::2]):
            voice = series.segment_voice(data, source)
            self.assertEqual(query[1], voice['speaker'])
            self.assertEqual(audio[1:], (voice['speaker'], voice.get('pitch', 0), voice['speed']))
            self.assertEqual(rendered['speaker_name'], voice['name'])
        self.assertEqual({a[1] for a in calls}, {2, 3})

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
        self.assertIn("VOICEVOX:ずんだもん", body["snippet"]["description"])
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

    def test_manually_released_confirmed_episode_is_skipped_without_privacy_change(self):
        data = episode()
        key = series.episode_key(data)
        item = private_video()
        item['status']['privacyStatus'] = 'public'
        state = {'entries': {key: {'status': 'confirmed', 'video_id': item['id']}}}
        self.assertEqual(upload.select_episode([data], state, {key: item}), (None, None))
        self.assertEqual(item['status']['privacyStatus'], 'public')
        with self.assertRaises(RuntimeError):
            upload.select_episode([data], {}, {key: item})
        item['snippet']['channelId'] = 'another-channel'
        with self.assertRaises(RuntimeError):
            upload.select_episode([data], state, {key: item})

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
