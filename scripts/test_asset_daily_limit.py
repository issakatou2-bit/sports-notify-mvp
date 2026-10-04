"""投稿済み日の早期見送りと、未投稿/指定制作日の継続を検証する。"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import next_asset as na


class DailyLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "published.json"
        self.output = Path(self.tmp.name) / "output"
        self.now = datetime.now(timezone(timedelta(hours=9)))
        self.write({})

    def write(self, assets):
        self.ledger.write_text(json.dumps({"assets": assets}), encoding="utf-8")

    def row(self, stamp=None):
        return {"video_id": "fixture", "published_at": (stamp or self.now).isoformat()}

    def cli(self, *extra):
        args = ["next_asset.py", "--published", str(self.ledger), *extra]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.output)}), \
                patch.dict(sys.modules, {"generate_asset_video": None}), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            # 生成器を読み込んだら失敗する。事前確認には追加依存や在庫を要しない。
            self.assertEqual(na.main(), 0)
        return stdout.getvalue(), self.output.read_text(encoding="utf-8")

    def test_today_skips_before_generator_import(self):
        self.write({"team_fixture": self.row()})
        self.assertEqual(self.cli("--check-daily-limit"), ("build=false\n", "build=false\n"))

    def test_late_guard_is_kept_without_generator_import(self):
        self.write({"team_fixture": self.row()})
        self.assertEqual(self.cli(), ("\n", "topic=\nremaining=\n"))

    def test_missing_inventory_does_not_skip_unposted_day(self):
        self.assertEqual(self.cli("--check-daily-limit"), ("build=true\n", "build=true\n"))

    def test_yesterdays_video_does_not_skip_today(self):
        self.write({"team_fixture": self.row(self.now - timedelta(days=1))})
        self.assertFalse(na.daily_limit_reached(str(self.ledger)))

    def test_season_review_uses_separate_daily_budget(self):
        self.write({"season_fixture": self.row()})
        self.assertEqual(self.cli("--check-daily-limit"), ("build=true\n", "build=true\n"))

    def test_explicit_topics_and_all_still_build(self):
        self.write({"team_fixture": self.row()})
        for topic in ("team_fixture", "all", "team_a team_b"):
            with self.subTest(topic=topic):
                self.assertFalse(na.daily_limit_reached(str(self.ledger), topic))

    def test_empty_workflow_inputs_mean_next(self):
        self.write({"team_fixture": self.row()})
        self.assertTrue(na.daily_limit_reached(str(self.ledger), ""))

    def test_again_override_is_preserved(self):
        self.write({"team_fixture": self.row()})
        self.assertFalse(na.daily_limit_reached(str(self.ledger), again=True))

    def test_jst_date_boundary_uses_existing_policy(self):
        self.write({"team_fixture": {"published_at": "2026-10-03T15:00:00Z"}})
        self.assertTrue(na.posted_today(str(self.ledger), today=datetime(2026, 10, 4).date()))
        self.write({"team_fixture": {"published_at": "2026-10-03T14:59:59Z"}})
        self.assertFalse(na.posted_today(str(self.ledger), today=datetime(2026, 10, 4).date()))

    def test_missing_and_invalid_ledger_keep_existing_late_check_behavior(self):
        # 事前判定で新しい見送り条件を増やさず、従来の選択/投稿時照合へ渡す。
        self.ledger.unlink()
        self.assertFalse(na.daily_limit_reached(str(self.ledger)))
        self.ledger.write_text("broken", encoding="utf-8")
        self.assertFalse(na.daily_limit_reached(str(self.ledger)))


if __name__ == "__main__":
    # run_checks.py は共通の一時フォルダを引数に渡す。
    unittest.main(argv=[sys.argv[0]])
