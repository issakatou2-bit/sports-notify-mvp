"""取得は偽API。実コメントの再発・公開範囲・安全な要約・既定オフを確認。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import correction_comments as cc
from test_comment_seeds import NOW, fake_get, thread

FIXED = "タイガースは阪神。デトロイトはタイガーズです。"


class Corrections(unittest.TestCase):
    def test_oct23_comment_verbatim(self):
        result = cc.classify(FIXED)
        self.assertEqual(result["text"], FIXED)
        self.assertIn("名称の区別", result["kinds"])

    def test_kinds_and_ordinary_comments(self):
        for text, kind in [
            ("打点が間違っています", "誤り・訂正"),
            ("それは違います", "誤り・訂正"),
            ("数字が違うと思います", "数値・日付"),
            ("その呼び方は紛らわしい", "紛らわしさ・区別"),
            ("読み方が違います", "表記・読み"),
            ("There is a typo", "表記・読み"),
            ("This is incorrect", "誤り・訂正"),
        ]:
            with self.subTest(text=text):
                self.assertIn(kind, cc.classify(text)["kinds"])
        for text in ("いつも楽しみです", "今日はどちらが勝ちますか？", "打率を教えて", "wronglyric"):
            self.assertIsNone(cc.classify(text))

    def test_public_own_only_title_and_no_author(self):
        rows = [thread(text=FIXED), thread("c2", text=FIXED, isPublic=False),
                thread("c3", text=FIXED, channelId="other"),
                thread("c4", text=FIXED, comment=dict(channelId="other")),
                thread("c5", vid="private", text=FIXED),
                thread("c6", vid="unlisted", text=FIXED),
                thread("c7", text=FIXED, comment=dict(publishedAt="2020-01-01T00:00:00Z")),
                thread("c8", text=FIXED, comment=dict(publishedAt="2027-01-01T00:00:00Z")),
                thread("c9", vid="other-owner", text=FIXED)]
        calls = []
        base = fake_get(rows, calls, dict(private="private", unlisted="unlisted"))
        def get(method, **params):
            result = base(method, **params)
            if method == "videos":
                for item in result["items"]:
                    item["snippet"]["title"] = "動画の題"
                    if item["id"] == "other-owner":
                        item["snippet"]["channelId"] = "other"
            return result
        payload = cc.collect(get=get, now=NOW)
        self.assertEqual(len(payload["corrections"]), 1)
        row = payload["corrections"][0]
        self.assertEqual(row["source_video_title"], "動画の題")
        self.assertEqual(row["source_video_id"], "public-video")
        output = json.dumps(payload, ensure_ascii=False) + cc.render(payload)
        for secret in ("個人名SECRET", "author", "thread-c1", '"c1"'):
            self.assertNotIn(secret, output)
        self.assertNotIn(FIXED, cc.render(payload))
        self.assertEqual([m for m, _ in calls], ["commentThreads", "videos"])

    def test_summary_treats_viewer_input_as_text(self):
        payload = cc.collect(get=fake_get([thread(text="誤字 <script>x</script> @someone ::error::oops")]), now=NOW)
        summary = cc.render(payload)
        self.assertNotIn("<script>", summary)
        self.assertNotIn("@someone", summary)
        self.assertNotIn("&lt;script&gt;", summary)

    def test_missing_video_verification_is_not_no_candidates(self):
        def get(method, **params):
            return dict(items=[thread(text=FIXED)]) if method == "commentThreads" else {}
        with self.assertRaises(ValueError):
            cc.collect(get=get, now=NOW)

    def test_page_limit_and_no_candidates(self):
        def get(method, **params):
            if method == "commentThreads":
                return dict(items=[thread(text=FIXED)], nextPageToken="more")
            return fake_get([])(method, **params)
        payload = cc.collect(get=get, now=NOW, max_pages=1)
        self.assertFalse(payload["coverage"]["complete"])
        self.assertIn("不完全", cc.render(payload))
        empty = cc.collect(get=fake_get([thread(text="ありがとう")]), now=NOW)
        self.assertEqual(empty["corrections"], [])
        self.assertIn("候補なし", cc.render(empty))

    def test_default_off_and_wrong_value_do_not_fetch(self):
        for value in (None, "off", "true"):
            env = {} if value is None else dict(COLLESPO_CORRECTION_WATCH=value)
            with patch.dict(os.environ, env, clear=True), patch.object(cc, "collect", side_effect=AssertionError), \
                 patch.object(sys, "argv", ["corrections"]):
                self.assertEqual(cc.main(), 0)

    def test_enabled_summary_and_fixed_failure_no_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            summary = Path(temp) / "summary.md"
            env = dict(COLLESPO_CORRECTION_WATCH="on", YOUTUBE_API_KEY="test", GITHUB_STEP_SUMMARY=str(summary))
            payload = cc.collect(get=fake_get([thread(text=FIXED)]), now=NOW)
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["corrections"]):
                with patch.object(cc, "collect", return_value=payload), patch("builtins.print") as log:
                    self.assertEqual(cc.main(), 0)
                    self.assertIn("::warning::", str(log.call_args_list))
                    self.assertNotIn(FIXED, str(log.call_args_list))
                self.assertNotIn(FIXED, summary.read_text(encoding="utf-8"))
                with patch.object(cc, "collect", side_effect=RuntimeError("SECRET_URL")), patch("builtins.print") as log:
                    self.assertEqual(cc.main(), 1)
                    self.assertNotIn("SECRET_URL", str(log.call_args_list))
                self.assertIn("取得失敗", summary.read_text(encoding="utf-8"))
                quota = cc.cs.FetchError(dict(call="videos", page=1, http_status=403, api_reason="quotaExceeded"))
                with patch.object(cc, "collect", side_effect=quota), patch("builtins.print") as log:
                    self.assertEqual(cc.main(), 0)  # 枠切れは失敗メールにしない
                    self.assertIn("使用枠切れ", str(log.call_args_list))

    def test_workflow_gate_daily_and_read_only(self):
        workflow = (Path(__file__).resolve().parent.parent / ".github/workflows/correction_comments.yml").read_text(encoding="utf-8")
        self.assertIn("vars.COLLESPO_CORRECTION_WATCH == 'on'", workflow)
        self.assertEqual(workflow.count("cron:"), 1)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("commit_data", workflow)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
