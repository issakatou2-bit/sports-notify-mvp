"""保存値の欠測・重複・公開範囲と、実際の取得経路を固定材料で確認。"""
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

import fetch_analytics as fa
import morning_report as mr


class MorningReportTests(unittest.TestCase):
    def test_daily_query_backfills_without_zero_or_extra_calls(self):
        yta = MagicMock()
        yta.reports().query().execute.return_value = {
            "columnHeaders": [{"name": name} for name in ("day", *mr.METRICS)],
            "rows": [["2026-10-21", 12, 4.5, 2, 1], ["2026-10-22", 0, 0, 0, 0]]}
        yta.reset_mock()
        rows = fa.channel_daily(yta, date(2026, 9, 26), date(2026, 10, 24), "now")
        self.assertEqual(yta.reports().query.call_count, 1)
        self.assertEqual(yta.reports().query.call_args.kwargs["dimensions"], "day")
        store = {"daily": {"2026-10-20": {"views": 9}}}
        fa.merge_daily(store, rows)
        fa.merge_daily(store, {})
        self.assertEqual(store["daily"]["2026-10-21"]["subscribersLost"], 1)
        self.assertEqual(store["daily"]["2026-10-22"]["views"], 0)
        self.assertEqual(store["daily"]["2026-10-20"]["views"], 9)
        self.assertNotIn("2026-10-23", store["daily"])

    def test_daily_failure_preserves_existing_values(self):
        yta = MagicMock()
        yta.reports().query().execute.side_effect = TimeoutError("secret")
        with patch.object(fa, "_report"):
            self.assertEqual(fa.channel_daily(yta, date(2026, 10, 1), date(2026, 10, 24), "now"), {})

    def test_daily_saved_even_when_video_query_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "analytics.json"
            yta = MagicMock()
            yta.reports().query().execute.side_effect = RuntimeError("video failed")
            with patch.object(fa, "client", return_value=yta), patch.object(fa, "channel_daily", return_value={"2026-10-21": {"views": 5}}), patch.object(sys, "argv", ["fetch", "--out", str(dest)]):
                with self.assertRaises(RuntimeError):
                    fa._run()
            self.assertEqual(json.loads(dest.read_text())["daily"]["2026-10-21"]["views"], 5)

    def test_short_query_still_revisits_28_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            yta = MagicMock()
            yta.reports().query().execute.return_value = {"rows": []}
            now = datetime(2026, 10, 24, 9, 0, tzinfo=mr.JST)
            with patch.object(fa, "datetime", wraps=datetime) as clock, patch.object(fa, "client", return_value=yta), patch.object(fa, "channel_daily", return_value={}) as daily, patch.object(sys, "argv", ["fetch", "--days", "1", "--out", str(Path(tmp) / "data.json")]):
                clock.now.return_value = now
                self.assertEqual(fa._run(), 0)
                self.assertEqual(daily.call_args.args[1:3], (date(2026, 9, 26), date(2026, 10, 24)))

    def test_latest_complete_comparison_keeps_requested_window_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            rows = {(date(2026, 10, 20) - timedelta(days=i)).isoformat(): dict(zip(mr.METRICS, [10 if i < 7 else 20, 5, 2, 1]), fetched_at="2026-10-23") for i in range(14)}
            (data / "analytics.json").write_text(json.dumps({"daily": rows}))
            text = mr.report(data, datetime(2026, 10, 24, tzinfo=mr.JST), lambda _: "200")
            self.assertIn("2026-10-17〜2026-10-23", text)
            self.assertIn("2026-10-07〜2026-10-13 / 2026-10-14〜2026-10-20", text)
            self.assertIn("-50.0%", text)
            self.assertIn("| 再生 | 140 | 70", text)

    def test_oembed_failures_are_not_public_or_zero(self):
        with patch.object(mr, "get_url", side_effect=OSError("secret")):
            self.assertIn("未確認", mr.oembed("a" * 11))
        with patch.object(mr, "get_url", return_value=b"{}") as request:
            self.assertEqual(mr.oembed("a" * 11), "200")
            self.assertIn("youtube.com/oembed", request.call_args.args[0])

    def test_sources_overlap_is_not_summed(self):
        obj = {"days": {"2026-10-22": {"sources": {"2026-10-20": {"A": 9}}},
                        "2026-10-23": {"sources": {"2026-10-20": {"A": 12}}}},
               "daily": {"2026-10-20": {"estimatedMinutesWatched": 6}}}
        values = mr.daily_values(obj)
        self.assertEqual(values["2026-10-20"]["views"], 12)
        self.assertEqual(values["2026-10-20"]["estimatedMinutesWatched"], 6)

    def test_complete_week_net_and_missing(self):
        end = date(2026, 10, 23)
        values = {(end - timedelta(days=i)).isoformat(): dict(zip(mr.METRICS, [10, 5.5, 2, 1])) for i in range(7)}
        _, result = mr.week(values, end)
        self.assertEqual(result["views"], 70)
        self.assertEqual(result["net"], 7)
        del values["2026-10-21"]["subscribersLost"]
        _, result = mr.week(values, end)
        self.assertIsNone(result["net"])
        self.assertEqual(result["views"], 70)

    def test_public_report_hides_titles_ids_names_and_counts_ab_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            rec = dict(video_id="a" * 11, title="UNRELEASED COMMENT_AUTHOR", privacy="private",
                       published_at="2026-10-23T00:00:00Z", publish_at="2026-10-23T09:00:00Z",
                       ab_enabled=True, ab_test="hook", ab_variant="B")
            (data / "published_assets.json").write_text(json.dumps({"assets": {"season_player_1": rec}}))
            (data / "published_videos.json").write_text(json.dumps({"asset": {"x": rec}}))
            text = mr.report(data, datetime(2026, 10, 24, 9, 30, tzinfo=mr.JST), lambda _: "200")
            self.assertNotIn("UNRELEASED", text)
            self.assertNotIn("a" * 11, text)
            self.assertEqual(text.count("| 10/23 18:00"), 1)
            self.assertIn("選手まとめ", text)
            self.assertIn("B 1本", text)
            self.assertIn("未収録", text)
            self.assertIn("限定公開", text)

    def test_no_ab_label_is_not_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = mr.report(Path(tmp), datetime(2026, 10, 24, tzinfo=mr.JST), lambda _: "200")
            self.assertIn("ラベル付き A 0本 / B 0本", text)

    def test_ab_future_and_held_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            base = dict(privacy="private", ab_enabled=True, ab_test="hook", ab_variant="A")
            rows = {"future": dict(base, video_id="a" * 11, publish_at="2026-10-24T10:00:00Z"),
                    "held": dict(base, video_id="b" * 11, publish_at="2026-10-23T10:00:00Z", held=True),
                    "disabled": dict(base, video_id="c" * 11, publish_at="2026-10-23T10:00:00Z", ab_enabled=False)}
            (data / "published_videos.json").write_text(json.dumps({"morning_press": rows}))
            text = mr.report(data, datetime(2026, 10, 24, 9, 30, tzinfo=mr.JST), lambda _: "401")
            self.assertIn("ラベル付き A 0本 / B 0本", text)
            self.assertIn("予約時刻前", text)
            self.assertIn("保留", text)

    def test_cli_summary_file_and_commit_path_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            dest, summary, output = (data / name for name in ("report.md", "summary.md", "output.txt"))
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output)}), patch.object(sys, "argv", ["report", "--offline", "--data", str(data), "--out", str(dest)]), patch.object(mr, "get_url") as network:
                mr.main()
            self.assertEqual(dest.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertEqual(output.read_text(encoding="utf-8"), f"report_path={dest.as_posix()}\n")
            network.assert_not_called()

    def test_first_error_only_and_private_payload_redacted(self):
        self.assertEqual(mr.public_error("date ##[error]Process completed with exit code 1.\n[error]secret"),
                         "[error] Process completed with exit code 1.")
        self.assertNotIn("private-token", mr.public_error("[error]private-token COMMENT_AUTHOR"))
        self.assertIn("未収録", mr.public_error("no errors"))

    def test_log_redirect_does_not_forward_token(self):
        req = urllib.request.Request("https://api.github.com/repos/a/b/actions/jobs/1/logs", headers={"Authorization": "Bearer secret"})
        redirected = mr.SafeRedirect().redirect_request(req, None, 302, "Found", {}, "https://logs.example/log")
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_actions_skipped_excluded_and_continue_on_error_found(self):
        api = MagicMock()
        api.base = "https://api.github.com/repos/a/b"
        api.token = "test"
        api.pages.side_effect = [
            [{"id": 1, "name": "daily", "run_attempt": 2, "conclusion": "success"}, {"id": 2, "conclusion": "skipped"}],
            [{"id": 3, "name": "job", "conclusion": "success", "steps": [{"name": "sanity", "conclusion": "failure"}, {"name": "off", "conclusion": "skipped"}]},
             {"id": 4, "conclusion": "skipped"}]]
        with patch.object(mr, "get_url", return_value=b"[error]Process completed with exit code 1."):
            text = "\n".join(mr.actions_report(api, date(2026, 10, 23)))
        self.assertIn("failure 1", text)
        self.assertIn("sanity", text)
        self.assertIn("[error] Process completed with exit code 1.", text)
        self.assertNotIn("off", text)
        self.assertIn("2026-10-22T15:00:00Z..2026-10-23T14:59:59Z", api.pages.call_args_list[0].args[0])
        self.assertIn("attempts/2/jobs", api.pages.call_args_list[1].args[0])

    def test_pagination_and_unavailable_are_visible(self):
        api = mr.GitHub("a/b", None)
        with patch.object(api, "get", side_effect=[{"jobs": [{}] * 100}, {"jobs": [{}]}]):
            self.assertEqual(len(api.pages("/jobs", "jobs")), 101)
        with patch.object(api, "pages", side_effect=OSError("token-secret")):
            text = "\n".join(mr.actions_report(api, date(2026, 10, 23)))
        self.assertIn("未収録", text)
        self.assertNotIn("token-secret", text)

    def test_workflow_default_schedule_permissions_and_report_only_write(self):
        import yaml
        obj = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/morning_report.yml").read_text(encoding="utf-8"))
        triggers = obj.get("on", obj.get(True))
        self.assertEqual(triggers["schedule"][0]["cron"], "30 0 * * *")
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(obj["permissions"], {"contents": "write", "actions": "read"})
        steps = obj["jobs"]["report"]["steps"]
        self.assertNotIn("vars.", str(obj))
        self.assertIn('git add -- "$FILE"', steps[-1]["run"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
