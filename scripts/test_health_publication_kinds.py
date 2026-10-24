#!/usr/bin/env python3
"""別枠の公開物で欠配を打ち消さない。外部接続なしの実例回帰。"""
import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import healthcheck as hc


class PublicationKindTests(unittest.TestCase):
    def run_health(self, missing=1, public_ids=None, stale=0, today=False):
        lines = ["| 17:00 | 成績 | 出た | players |"]
        if missing:
            lines.append("| 17:30 | コメント | **出ていない** | |")
        output = io.StringIO()
        mocks = dict(
            check_videos=(lines, missing, 0, {"players"}),
            published_ids=public_ids,
            check_data=(["材料"], stale),
            check_content=([], 0), check_assets=("資産", 0),
            check_history=("履歴", 0), check_playlists=("一覧", 0),
            check_analytics=("分析", 0), check_credit=("", 0))
        argv = ["healthcheck", "--today"] if today else ["healthcheck", "--date", "2026-10-16"]
        with contextlib.ExitStack() as stack:
            for name, value in mocks.items():
                stack.enter_context(patch.object(hc, name, return_value=value))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = hc.main()
        return result, output.getvalue()

    def test_real_missing_comment_not_offset_by_three_assets(self):
        result, out = self.run_health(public_ids={"players", "game-al", "game-nl", "season"})
        self.assertEqual(result, 1)
        self.assertIn("動画の欠け 1件", out)
        self.assertIn("記録なし・公開未確認", out)
        self.assertIn("種類は未照合", out)
        self.assertNotIn("記録が欠けているだけ", out)

    def test_extra_single_video_also_needs_kind_match(self):
        self.assertEqual(self.run_health(public_ids={"players", "other"})[0], 1)

    def test_unavailable_public_list_is_not_zero_or_success(self):
        result, out = self.run_health(public_ids=None)
        self.assertEqual(result, 1)
        self.assertNotIn("記録に無い動画", out)

    def test_complete_known_kinds_remain_successful(self):
        result, out = self.run_health(missing=0, public_ids={"players"})
        self.assertEqual(result, 0)
        self.assertIn("**問題なし**", out)

    def test_complete_records_and_extra_assets_remain_successful(self):
        result, out = self.run_health(missing=0, public_ids={"players", "asset"})
        self.assertEqual(result, 0)
        self.assertIn("種類は未照合", out)

    def test_extra_assets_do_not_hide_stale_material_for_missing_kind(self):
        result, out = self.run_health(public_ids={"players", "asset1", "asset2"}, stale=1)
        self.assertEqual(result, 1)
        self.assertIn("データの古さ 1件", out)

    def test_confirmed_complete_record_keeps_previous_stale_policy(self):
        result, out = self.run_health(missing=0, public_ids={"players"}, stale=1)
        self.assertEqual(result, 0)
        self.assertIn("**問題なし**", out)

    def test_intraday_extra_does_not_hide_missing(self):
        result, out = self.run_health(public_ids={"players", "asset1", "asset2"}, today=True)
        self.assertEqual(result, 1)
        self.assertIn("動画の欠け 1件", out)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
