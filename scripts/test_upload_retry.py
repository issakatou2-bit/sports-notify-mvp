"""アップロードの一時的な失敗（410・5xx）は3回までやり直し、それ以外はすぐ止める。"""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload_youtube as uy


class FakeErr(Exception):
    def __init__(self, status):
        self.resp = type("R", (), {"status": status})()


class Retry(unittest.TestCase):
    def run_with(self, statuses):
        calls = []

        def execute():
            calls.append(1)
            if statuses:
                raise FakeErr(statuses.pop(0))
            return {"id": "abc"}
        yt = mock.Mock()
        yt.videos.return_value.insert.return_value.execute.side_effect = execute
        with mock.patch("googleapiclient.errors.HttpError", FakeErr), \
             mock.patch.object(uy, "MediaFileUpload", mock.Mock()), mock.patch("time.sleep"):
            return uy.insert_with_retry(yt, {}, "v.mp4"), len(calls)

    def test_410_then_success(self):
        self.assertEqual(self.run_with([410]), ({"id": "abc"}, 2))

    def test_403_stops_at_once(self):
        with self.assertRaises(FakeErr):
            self.run_with([403])

    def test_gives_up_after_three(self):
        with self.assertRaises(FakeErr):
            self.run_with([503, 503, 503])


if __name__ == "__main__":
    unittest.main(argv=[__file__])
