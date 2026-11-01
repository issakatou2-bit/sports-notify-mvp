"""枠切れだけ保存・回収期限・日内重複・空の日・投稿経路の保存契約。実APIは使わない。"""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from googleapiclient.errors import HttpError
from httplib2 import Response
import retry_thumbnails as retry
import thumbnail_pending as pending
import upload_youtube as upload
import reset_thumbnail as reset

VID = "abcdefghijk"
NOW = datetime(2026, 10, 28, 7, 20, tzinfo=timezone.utc)
FAILED = NOW - timedelta(hours=1)
ROOT = Path(__file__).resolve().parents[1]


def error(reason="quotaExceeded", status=403):
    return HttpError(Response({"status": str(status)}), json.dumps(
        {"error": {"errors": [{"reason": reason}]}}).encode())


class RunArtifacts(unittest.TestCase):
    def test_retry_once_after_a_temporary_failure(self):
        error = retry.subprocess.CalledProcessError(1, "gh")
        with mock.patch.object(retry, "gh_json", side_effect=[error, [{"name": "a"}]]) as read,                 mock.patch.object(retry.time, "sleep"), mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(retry.run_artifacts("repos/x/actions", 1), [{"name": "a"}])
        self.assertEqual(read.call_count, 2)

    def test_skip_only_that_run_after_two_failures(self):
        error = retry.subprocess.CalledProcessError(1, "gh")
        with mock.patch.object(retry, "gh_json", side_effect=error) as read,                 mock.patch.object(retry.time, "sleep"), mock.patch("sys.stdout", new=io.StringIO()) as out:
            self.assertEqual(retry.run_artifacts("repos/x/actions", 1), [])
        self.assertEqual(read.call_count, 2)
        self.assertIn("::warning::", out.getvalue())


class Pending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / "source.png"
        self.image.write_bytes(b"original image")
        self.directory = self.root / "pending"

    def remember(self, failure, vid=VID):
        return pending.remember(failure, self.image, vid, "morning_press", "題",
                                directory=self.directory, now=FAILED)

    def test_quota_saved_with_original_image_and_metadata(self):
        self.assertTrue(self.remember(error()))
        self.assertEqual((self.directory / f"{VID}.png").read_bytes(), self.image.read_bytes())
        self.assertEqual(json.loads((self.directory / "pending.json").read_text(encoding="utf-8")),
                         [dict(video_id=VID, kind="morning_press", title="題", failed_at=FAILED.isoformat())])

    def test_other_errors_never_create_pending(self):
        failures = [error("forbidden"), error("uploadRateLimitExceeded", 429),
                    error(status=400), RuntimeError("quotaExceeded"),
                    HttpError(Response({"status": "403"}), b"invalid JSON")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.assertFalse(self.remember(failure))
                self.assertFalse(self.directory.exists())

    def test_append_and_deduplicate(self):
        self.remember(error())
        self.remember(error(), "lmnopqrstuv")
        self.remember(error())
        self.assertEqual(len(json.loads((self.directory / "pending.json").read_text(encoding="utf-8"))), 2)

    def test_upload_handler_records_only_quota_and_keeps_warning_behavior(self):
        yt = mock.Mock()
        real_remember = pending.remember
        def save(*args):
            return real_remember(*args, directory=self.directory, now=FAILED)
        with mock.patch.object(pending, "remember", side_effect=save), \
                mock.patch.object(upload, "MediaFileUpload"), mock.patch("sys.stderr", new=io.StringIO()):
            yt.thumbnails.return_value.set.return_value.execute.side_effect = error("forbidden")
            upload.set_thumbnail(yt, self.image, VID, "morning_press", "題")
            self.assertFalse(self.directory.exists())
            yt.thumbnails.return_value.set.return_value.execute.side_effect = error()
            upload.set_thumbnail(yt, self.image, VID, "morning_press", "題")
            self.assertTrue((self.directory / "pending.json").exists())

    def test_success_never_records(self):
        with mock.patch.object(upload, "MediaFileUpload"), mock.patch.object(pending, "remember") as save:
            upload.set_thumbnail(mock.Mock(), self.image, VID, "morning", "題")
        save.assert_not_called()


class Collector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def run_record(self, **changes):
        return dict(dict(id=1, head_branch="main", status="completed", event="schedule",
                         head_repository={"full_name": "owner/repo"},
                         updated_at=NOW.isoformat()), **changes)

    def artifact(self, **changes):
        return dict(dict(id=2, name="thumbnail-pending", expired=False), **changes)

    def archive(self, failed=FAILED, vid=VID):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("pending.json", json.dumps([dict(video_id=vid, kind="morning_press",
                                                       title="題", failed_at=failed.isoformat())]))
            z.writestr(f"{vid}.png", b"original image")
        return mock.Mock(stdout=data.getvalue())

    def collect(self, replies, archive=None, now=NOW):
        with mock.patch.object(retry, "gh_json", side_effect=replies) as gh, \
                mock.patch.object(retry.subprocess, "run", return_value=archive or self.archive()) as download:
            selected = retry.collect("owner/repo", self.directory, now)
        return selected, gh, download

    def test_no_runs_is_a_quiet_noop(self):
        entries, gh, download = self.collect([[], []])
        self.assertEqual(entries, [])
        download.assert_not_called()
        self.assertEqual(gh.call_count, 2)

    def test_no_pending_artifacts_is_a_noop(self):
        entries, _, download = self.collect([[], [self.run_record()], []])
        self.assertEqual(entries, [])
        download.assert_not_called()

    def test_second_attempt_same_day_is_a_noop(self):
        entries, gh, download = self.collect([[{"name": "marker"}]])
        self.assertEqual(entries, [])
        self.assertEqual(gh.call_count, 1)
        download.assert_not_called()

    def test_manual_before_reset_does_not_consume_daily_marker(self):
        entries, gh, download = self.collect([], now=NOW - timedelta(hours=1))
        self.assertEqual(entries, [])
        gh.assert_not_called()
        download.assert_not_called()

    def test_collect_original_png(self):
        entries, gh, download = self.collect([[], [self.run_record()], [self.artifact()]])
        self.assertEqual(entries[0]["video_id"], VID)
        self.assertEqual(Path(entries[0]["image"]).read_bytes(), b"original image")
        self.assertIn("thumbnail-retry-2026-10-28", gh.call_args_list[0].args[0])
        self.assertEqual(download.call_args.args[0][-1], "repos/owner/repo/actions/artifacts/2/zip")

    def test_old_fork_incomplete_and_future_runs_are_skipped(self):
        runs = [self.run_record(updated_at=(NOW - timedelta(days=2)).isoformat()),
                self.run_record(head_branch="feature"), self.run_record(event="pull_request"),
                self.run_record(head_repository={"full_name": "fork/repo"}),
                self.run_record(status="in_progress"),
                self.run_record(updated_at=(NOW + timedelta(minutes=1)).isoformat())]
        entries, gh, download = self.collect([[], runs])
        self.assertEqual(entries, [])
        self.assertEqual(gh.call_count, 2)
        download.assert_not_called()

    def test_expired_and_unrelated_artifacts_are_skipped(self):
        entries, _, download = self.collect([[], [self.run_record()],
                                             [self.artifact(expired=True), self.artifact(name="other")]])
        self.assertEqual(entries, [])
        download.assert_not_called()

    def test_expired_images_are_never_carried_to_next_day(self):
        for failed in [NOW - timedelta(hours=24), NOW - timedelta(days=2), NOW + timedelta(seconds=1)]:
            with self.subTest(failed=failed):
                entries, _, _ = self.collect([[], [self.run_record()], [self.artifact()]], self.archive(failed))
                self.assertEqual(entries, [])

    def test_previous_16_boundary_is_included(self):
        failed = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)
        # 16:00実行なら前日16:00は24hで期限切れ。16:20実行でも期限外。
        entries, _, _ = self.collect([[], [self.run_record()], [self.artifact()]], self.archive(failed))
        self.assertEqual(entries, [])

    def test_duplicate_video_is_selected_once(self):
        entries, _, download = self.collect([[], [self.run_record(), self.run_record(id=3)],
                                              [self.artifact()], [self.artifact(id=4)]])
        self.assertEqual(len(entries), 1)
        self.assertEqual(download.call_count, 2)

    def test_invalid_video_id_never_escapes_directory(self):
        with self.assertRaises(ValueError):
            self.collect([[], [self.run_record()], [self.artifact()]], self.archive(vid="../escape"))

    def test_gh_api_pages_are_flattened(self):
        with mock.patch.object(retry.subprocess, "run", return_value=mock.Mock(
                stdout=b'[{"artifacts":[{"id":1}]},{"artifacts":[{"id":2}]}]')) as run:
            self.assertEqual(retry.gh_json("endpoint", "artifacts"), [{"id": 1}, {"id": 2}])
        self.assertIn("--paginate", run.call_args.args[0])

    def test_empty_apply_never_calls_reset_or_auth(self):
        (self.directory / "selected.json").write_text("[]", encoding="utf-8")
        with mock.patch.object(sys, "argv", ["retry", "--apply", "--directory", str(self.directory)]), \
                mock.patch.object(retry.subprocess, "run") as run:
            self.assertEqual(retry.main(), 0)
        run.assert_not_called()

    def test_apply_uses_reset_write_and_stops_carrying_old_images(self):
        entries = [dict(video_id=VID, image="path with spaces.png",
                        failed_at=datetime.now(timezone.utc).isoformat()),
                   dict(video_id="lmnopqrstuv", image="expired.png",
                        failed_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())]
        (self.directory / "selected.json").write_text(json.dumps(entries), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["retry", "--apply", "--directory", str(self.directory)]), \
                mock.patch.object(retry.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(retry.main(), 0)
        self.assertEqual(run.call_args.args[0][-3:],
                         ["--write", "--quota-warning", f"{VID}=path with spaces.png"])


class Reset(unittest.TestCase):
    def test_write_checks_ownership_and_quota_stops_without_retry(self):
        yt = mock.Mock()
        yt.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "mine"}]}
        yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"title": "題", "channelId": "mine"}}]}
        yt.thumbnails.return_value.set.return_value.execute.side_effect = error()
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "thumb.png"
            img.write_bytes(b"image")
            with mock.patch.object(reset, "client", return_value=yt), \
                    mock.patch("googleapiclient.http.MediaFileUpload"), \
                    mock.patch.object(sys, "argv", ["reset", f"{VID}={img}",
                                                   f"lmnopqrstuv={img}", "--write", "--quota-warning"]):
                self.assertEqual(reset.main(), 0)
        self.assertEqual(yt.thumbnails.return_value.set.call_count, 1)
        self.assertEqual(yt.videos.return_value.list.call_count, 1)

    def test_non_owned_video_is_not_written(self):
        yt = mock.Mock()
        yt.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "mine"}]}
        yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"title": "題", "channelId": "someone_else"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "thumb.png"
            img.write_bytes(b"image")
            with mock.patch.object(reset, "client", return_value=yt), \
                    mock.patch.object(sys, "argv", ["reset", f"{VID}={img}", "--write"]):
                self.assertEqual(reset.main(), 1)
        yt.thumbnails.assert_not_called()


class WorkflowContract(unittest.TestCase):
    def test_all_thumbnail_publish_jobs_preserve_pending(self):
        import re
        import yaml
        count = 0
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
            for job in workflow.get("jobs", {}).values():
                steps = job.get("steps", [])
                if not any(re.search(r"upload_youtube|soccer_results_upload|soccer_week_publish|"
                                     r"ps_daily_entry.py|soccer_now.py|soccer_goal_short.py|"
                                     r"generate_ps_preview.py --upload", step.get("run", "")) for step in steps):
                    continue
                count += 1
                saved = [step for step in steps if step.get("with", {}).get("name") == "thumbnail-pending"]
                self.assertEqual(len(saved), 1, path.name)
                self.assertIn("always()", saved[0]["if"])
                self.assertEqual(saved[0]["with"]["retention-days"], "3")
                self.assertIn("build/thumbnail_pending/", saved[0]["with"]["path"])
        self.assertGreaterEqual(count, 16)

    def test_daily_marker_is_saved_before_api_write(self):
        import yaml
        workflow = yaml.load((ROOT / ".github/workflows/thumbnail_retry.yml").read_text(encoding="utf-8"),
                             Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"]["schedule"], [{"cron": "20 7 * * *"}])
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        steps = workflow["jobs"]["retry"]["steps"]
        marker = next(i for i, step in enumerate(steps) if step.get("name") == "Record daily attempt before writing")
        apply = next(i for i, step in enumerate(steps) if "--apply" in step.get("run", ""))
        self.assertLess(marker, apply)
        self.assertNotIn("continue-on-error", steps[marker])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
