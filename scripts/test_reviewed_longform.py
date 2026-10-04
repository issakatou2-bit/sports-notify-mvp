"""原稿救済で生成APIや公開前検査を迂回しない。"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import generate_dialogue as gd
import hold_video
import numbers_material as nm


class RecoveryTests(unittest.TestCase):
    def test_readback_retries_reads_only_and_keeps_failure_visible(self):
        yt = Mock()
        old = {"privacyStatus": "private"}
        desired = dict(old, publishAt="2099-10-04T12:00:00+00:00")
        saved = dict(old, publishAt="2099-10-04T12:00:00Z")
        execute = yt.videos.return_value.list.return_value.execute
        execute.side_effect = [{"items": [{"status": old}]}, {"items": [{"status": saved}]}]
        with patch.object(hold_video.time, "sleep"):
            self.assertEqual(hold_video.verify_status(yt, "mine", desired), saved)
        self.assertEqual(execute.call_count, 2)
        yt.videos.return_value.update.assert_not_called()
        execute.side_effect = None
        execute.return_value = {"items": [{"status": old}]}
        execute.reset_mock()
        with patch.object(hold_video.time, "sleep"), self.assertRaisesRegex(ValueError, "publishAt=None"):
            hold_video.verify_status(yt, "mine", desired)
        self.assertEqual(execute.call_count, 4)

    def test_same_reservation_recovers_record_without_updating_youtube(self):
        st = {"privacyStatus": "private", "publishAt": "2099-10-04T12:00:00Z"}
        yt = Mock()
        yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"status": st, "snippet": {"title": "test"}}]}
        with patch("sys.argv", ["hold_video", "--video", "mine", "--write", "--publish-at",
                                "2099-10-04T21:00:00+09:00"]), patch.object(hold_video, "client", return_value=yt), \
                patch.object(hold_video, "record_schedule") as record, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hold_video.main(), 0)
        record.assert_called_once_with("data/published_videos.json", "mine", st)
        yt.videos.return_value.update.assert_not_called()

    def test_reservation_record_preserves_other_entries_and_upload_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"published.json"
            original = {"longform": {"today": {"video_id": "mine", "published_at": "upload-time"},
                                     "yesterday": {"video_id": "other", "title": "keep"}}}
            p.write_text(json.dumps(original), encoding="utf-8")
            hold_video.record_schedule(p, "mine", {"publishAt": "2099-10-04T12:00:00Z"})
            saved = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(saved["longform"]["today"]["published_at"], "upload-time")
            self.assertEqual(saved["longform"]["today"]["publish_at"], "2099-10-04T12:00:00Z")
            self.assertEqual(saved["longform"]["yesterday"], original["longform"]["yesterday"])
            with self.assertRaises(ValueError):
                hold_video.record_schedule(p, "missing", {"publishAt": "2099-10-04T12:00:00Z"})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), saved)

    def test_reviewed_lines_never_silently_disappear(self):
        for text in ("", "めたん：正しい行\n不明な形式", "めたん[unknown]：数字です"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                gd.reviewed_segments(text, {"jp1"})
        self.assertEqual(len(gd.reviewed_segments("めたん[jp1]：数字です", {"jp1"})), 1)

    def test_reviewed_path_uses_material_and_editorial_gate_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp)/"raw.txt", Path(tmp)/"out.json"
            raw.write_text("\n".join(["ずんだもん：数字なのだ。", "めたん：数字です。"]*4), encoding="utf-8")
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("sys.argv", ["generate_dialogue", "--mode", "numbers",
                    "--reviewed-text", str(raw), "--out", str(out)]))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(patch.object(nm, "load", return_value={"players": [], "rare": []}))
                for name, value in (("has_enough", True), ("outline", "test"), ("facts", "facts"),
                                    ("panels", {}), ("checkable", {"対象": {"安打": 2}}),
                                    ("meta", {"mode": "numbers", "title": "数字"})):
                    stack.enter_context(patch.object(nm, name, return_value=value))
                generation = stack.enter_context(patch.object(gd, "anthropic"))
                gate = stack.enter_context(patch("longform_editorial.check", return_value=["矛盾"]))
                self.assertEqual(gd.main(), 1)
                self.assertFalse(out.exists())
                generation.Anthropic.assert_not_called()
                gate.assert_called_once()
                self.assertEqual(gate.call_args[0][0]["facts"], {"対象": {"安打": 2}})

    def test_schedule_requires_private_unscheduled_video_and_future_timezone(self):
        st = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
        target = hold_video.target_status(st, publish_at="2099-10-04T21:00:00+09:00")
        self.assertEqual(target["publishAt"], "2099-10-04T12:00:00+00:00")
        self.assertFalse(target["selfDeclaredMadeForKids"])
        self.assertNotIn("publishAt", st)
        for source, release, at in (({"privacyStatus": "public"}, False, "2099-10-04T21:00:00+09:00"),
                                   (dict(st, publishAt="2099-01-01T00:00:00Z"), False, "2099-10-04T21:00:00+09:00"),
                                   (st, True, "2099-10-04T21:00:00+09:00"),
                                   (st, False, "2000-01-01T00:00:00Z"),
                                   (st, False, "2099-10-04T21:00:00")):
            with self.subTest(at=at, source=source), self.assertRaises(ValueError):
                hold_video.target_status(source, release, at)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
