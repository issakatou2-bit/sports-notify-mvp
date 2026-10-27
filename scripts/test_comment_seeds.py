#!/usr/bin/env python3
"""公開範囲・匿名化・取得の境界を偽APIだけで検証する。"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comment_seeds as cs

NOW = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)


def thread(cid="c1", vid="public-video", text="大谷翔平の連続本塁打は初ですか？", **changes):
    item = dict(channelId=cs.CHANNEL_ID, publishedAt="2026-10-21T23:00:00Z",
                textOriginal=text, authorDisplayName="個人名SECRET", authorChannelUrl="https://example.com/private")
    item.update(changes.pop("comment", {}))
    sn = dict(channelId=cs.CHANNEL_ID, isPublic=True, videoId=vid,
              topLevelComment=dict(id=cid, snippet=item))
    sn.update(changes)
    return dict(id="thread-" + cid, snippet=sn)


def fake_get(rows, calls=None, video_status=None):
    def get(method, **params):
        if calls is not None:
            calls.append((method, params))
        if method == "commentThreads":
            return dict(items=rows)
        if method == "videos":
            return dict(items=[dict(id=vid, snippet=dict(channelId=cs.CHANNEL_ID),
                status=dict(privacyStatus=(video_status or {}).get(vid, "public")))
                for vid in params["id"].split(",")])
        raise AssertionError(method)
    return get


class Classify(unittest.TestCase):
    def test_fact_question_comparison_and_sources(self):
        for text, trigger, api in [
            ("初の本塁打？", "first", "hitting"),
            ("MLBで何年ぶりの優勝", "years", "/schedule"),
            ("連続安打", "streak", "gameLog"),
            ("どっちの打率が上", "compare", "hitting"),
            ("防御率が違う", "correction", "pitching"),
            ("三振数？", "question", "/people/search"),
        ]:
            with self.subTest(text=text):
                seed = cs.classify(text)
                self.assertIn(trigger, seed["triggers"])
                self.assertIn(api, json.dumps(seed["verification"]))
        self.assertIsNone(cs.classify("お疲れ様でした"))

    def test_why_is_not_claimed_to_be_proven_by_stats(self):
        seed = cs.classify("なぜ本塁打が多い？")
        self.assertEqual(seed["verification"]["outlook"], "要一次資料")
        self.assertIn("原因を断定できない", "".join(seed["verification"]["caveats"]))

    def test_soccer_and_unknown_sports_are_not_routed_to_mlb(self):
        seed = cs.classify("アーセナルは何年ぶりの優勝？")
        self.assertEqual(seed["sport"], "soccer")
        self.assertIn("football-data.org", json.dumps(seed["verification"]))
        self.assertNotIn("MLB", json.dumps(seed["verification"]))
        unknown = cs.classify("なぜ初なの？")
        self.assertEqual(unknown["sport"], "needs_identification")
        self.assertNotIn("MLB", json.dumps(unknown["verification"]))

    def test_malformed_response_is_a_failure(self):
        with self.assertRaises(ValueError):
            cs.collect(get=lambda *a, **k: {}, now=NOW)

    def test_personal_prose_and_numbers_never_enter_summary(self):
        seed = cs.classify("私は山田秘密です。電話09012345678 @private https://private.example なぜ初なの？")
        output = json.dumps(seed, ensure_ascii=False)
        for secret in ("山田秘密", "09012345678", "@private", "private.example", "私は"):
            self.assertNotIn(secret, output)


class Collect(unittest.TestCase):
    def test_channel_matches_existing_own_channel(self):
        from backfill_records import CHANNEL_ID
        self.assertEqual(cs.CHANNEL_ID, CHANNEL_ID)

    def test_own_public_comments_only_with_no_author_or_comment_id(self):
        rows = [thread(), thread("c2", isPublic=False), thread("c3", channelId="other"),
                thread("c4", comment=dict(channelId="other")),
                thread("c5", vid="unlisted"), thread("c6", vid="private"),
                thread("c7", comment=dict(publishedAt="2026-09-01T00:00:00Z")),
                thread("c8", comment=dict(publishedAt="2026-10-23T00:00:00Z"))]
        calls = []
        out = cs.collect(get=fake_get(rows, calls, dict(unlisted="unlisted", private="private")), now=NOW)
        self.assertEqual(len(out["seeds"]), 1)
        self.assertEqual(out["seeds"][0]["comment_count"], 1)
        self.assertEqual(out["seeds"][0]["source_video_id"], "public-video")
        self.assertEqual(calls[0][1]["allThreadsRelatedToChannelId"], cs.CHANNEL_ID)
        serialized = json.dumps(out, ensure_ascii=False)
        for private in ("個人名SECRET", "author", "thread-c1", '"c1"', "textOriginal"):
            self.assertNotIn(private, serialized)

    def test_wrong_video_owner_and_missing_privacy_are_excluded(self):
        def get(method, **params):
            if method == "commentThreads":
                return dict(items=[thread(vid="v1"), thread("c2", vid="v2")])
            return dict(items=[dict(id="v1", snippet=dict(channelId="other"), status=dict(privacyStatus="public")),
                               dict(id="v2", snippet=dict(channelId=cs.CHANNEL_ID))])
        self.assertEqual(cs.collect(get=get, now=NOW)["seeds"], [])

    def test_pagination_deduplication_and_coverage_limit(self):
        calls = []
        def get(method, **params):
            calls.append((method, params))
            if method == "commentThreads":
                if "pageToken" not in params:
                    return dict(items=[thread()], nextPageToken="next")
                return dict(items=[thread(), thread("c2")])
            return fake_get([])(method, **params)
        out = cs.collect(get=get, now=NOW)
        self.assertEqual(out["seeds"][0]["comment_count"], 2)
        self.assertEqual(out["coverage"]["pages"], 2)
        self.assertTrue(out["coverage"]["complete"])
        limited = cs.collect(get=get, now=NOW, max_pages=1)
        self.assertFalse(limited["coverage"]["complete"])

    def test_no_candidates_needs_no_video_calls_and_no_public_flag_is_excluded(self):
        calls = []
        rows = [thread(text="ありがとうございます"), thread("c2")]
        rows[1]["snippet"].pop("isPublic")
        out = cs.collect(get=fake_get(rows, calls), now=NOW)
        self.assertEqual(out["seeds"], [])
        self.assertEqual([m for m, _ in calls], ["commentThreads"])

    def test_old_page_stops_paging(self):
        calls = []
        def get(method, **params):
            calls.append(method)
            return dict(items=[thread(comment=dict(publishedAt="2020-01-01T00:00:00Z"))], nextPageToken="next")
        self.assertTrue(cs.collect(get=get, now=NOW)["coverage"]["complete"])
        self.assertEqual(calls, ["commentThreads"])

    def test_invalid_timestamp_is_reported_as_incomplete(self):
        out = cs.collect(get=fake_get([thread(comment=dict(publishedAt="invalid"))]), now=NOW)
        self.assertFalse(out["coverage"]["complete"])


def http_error(status, reason, body=None):
    return HTTPError("https://private.invalid/?key=SECRET_KEY", status,
                     "key=SECRET_MESSAGE", {}, io.BytesIO(body if body is not None else
                     json.dumps({"error": {"errors": [{"reason": reason}],
                               "message": "SECRET_BODY key=SECRET_KEY"}}).encode()))


class Failures(unittest.TestCase):
    def ledgers(self):
        root = Path(__file__).resolve().parent.parent / "build"
        root.mkdir(exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="seeds-ledger-", dir=root))
        paths = [directory / "published_videos.json", directory / "published_assets.json"]
        rows = [dict(video_id=vid, published_at=date, privacy=privacy) for vid, date, privacy in [
            ("aaaaaaaaaaa", "2026-10-21T00:00:00Z", "public"),
            ("bbbbbbbbbbb", "2026-10-20T00:00:00Z", "public"),
            ("oldoldold01", "2026-10-01T00:00:00Z", "public"),
            ("private0001", "2026-10-21T00:00:00Z", "private"),
            ("future00001", "2026-10-23T00:00:00Z", "public"),
            ("unknown0001", "unknown", "public")]]
        paths[0].write_text(json.dumps({"daily": {"date": rows[0]}, "other": rows[2:]}), encoding="utf-8")
        paths[1].write_text(json.dumps({"assets": [rows[0], rows[1]]}), encoding="utf-8")
        return paths

    def test_ledger_union_dates_privacy_order_and_dedup(self):
        self.assertEqual(cs.recent_video_ids(NOW, paths=self.ledgers()), ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_http_400_403_reason_and_no_key_url_body(self):
        for status, reason in [(400, "invalidParameter"), (403, "forbidden"),
                               (403, "quotaExceeded"), (403, "commentsDisabled")]:
            with self.subTest(reason=reason):
                out = cs.failure_reason(http_error(status, reason), "commentThreads", 2)
                self.assertEqual(out, dict(call="commentThreads", page=2, exception_type="HTTPError",
                                          http_status=status, api_reason=reason))
                for secret in ("key=", "SECRET", "https://", "message"):
                    self.assertNotIn(secret, json.dumps(out))

    def test_malformed_and_secret_reason_never_echoed(self):
        for body in [b"not JSON key=SECRET", b'{"error": {"errors": []}}',
                     b'{"error": {"errors": [{"reason":"forbidden key=SECRET"}]}}']:
            out = cs.failure_reason(http_error(403, "", body))
            self.assertEqual(out["api_reason"], "unknown")
            self.assertNotIn("key=", json.dumps(out))
            self.assertNotIn("SECRET", json.dumps(out))

    def test_channel_fallback_and_disabled_video_are_nonfatal(self):
        for status, reason in [(400, "invalidParameter"), (403, "forbidden"),
                               (400, "operationNotSupported")]:
            calls = []
            def get(method, **params):
                calls.append((method, params))
                if method == "videos":
                    return fake_get([])(method, **params)
                if "allThreadsRelatedToChannelId" in params:
                    raise http_error(status, reason)
                if params["videoId"] == "aaaaaaaaaaa":
                    raise http_error(403, "commentsDisabled")
                return dict(items=[thread(vid="bbbbbbbbbbb")])
            out = cs.collect(get=get, now=NOW, ledger_paths=self.ledgers())
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["reason"]["api_reason"], reason)
            self.assertEqual(out["scope"]["mode"], "videoId")
            self.assertFalse(out["coverage"]["complete"])
            self.assertEqual(out["coverage"]["skipped"][0]["api_reason"], "commentsDisabled")
            self.assertEqual(out["coverage"]["skipped"][0]["video_id"], "aaaaaaaaaaa")
            self.assertEqual(len(out["seeds"]), 1)
            self.assertEqual(out["seeds"][0]["source_video_id"], "bbbbbbbbbbb")
            self.assertEqual(out["coverage"]["api_calls"], dict(commentThreads=3, videos=2))

    def test_quota_and_disconnect_stop_without_fallback(self):
        for error in [http_error(403, "quotaExceeded"), URLError("key=SECRET"),
                      ConnectionResetError("https://private/?key=SECRET")]:
            calls = []
            def get(method, **params):
                calls.append(method)
                raise error
            with self.assertRaises(cs.FetchError) as caught:
                cs.collect(get=get, now=NOW)
            self.assertEqual(calls, ["commentThreads"])
            self.assertEqual(caught.exception.reason["exception_type"], type(error).__name__)
            self.assertNotIn("SECRET", str(caught.exception))

    def test_page_context_and_video_validation_context(self):
        for method in ["commentThreads", "videos"]:
            def get(call, **params):
                if call == "videos" or "pageToken" in params:
                    raise http_error(403, "quotaExceeded")
                return dict(items=[thread()], **({"nextPageToken": "next"} if method == "commentThreads" else {}))
            with self.assertRaises(cs.FetchError) as caught:
                cs.collect(get=get, now=NOW)
            self.assertEqual(caught.exception.reason["call"], method)
            self.assertEqual(caught.exception.reason["page"], 2 if method == "commentThreads" else 1)

    def test_video_and_page_caps_and_wrong_owner(self):
        calls = []
        def get(method, **params):
            calls.append((method, params))
            if method == "videos":
                return fake_get([])(method, **params)
            if "allThreadsRelatedToChannelId" in params:
                raise http_error(403, "forbidden")
            return dict(items=[thread(vid=params["videoId"])], nextPageToken="next")
        out = cs.collect(get=get, now=NOW, ledger_paths=self.ledgers(), max_videos=1, video_pages=1)
        self.assertEqual(out["coverage"]["videos_available"], 2)
        self.assertEqual(out["coverage"]["videos_selected"], 1)
        self.assertEqual(sum(m == "commentThreads" for m, _ in calls), 2)
        self.assertFalse(out["coverage"]["complete"])
        self.assertEqual(len(out["seeds"]), 1)
        def wrong_owner(method, **params):
            if method == "videos":
                return dict(items=[dict(id="aaaaaaaaaaa", snippet=dict(channelId="other"), status=dict(privacyStatus="public"))])
            raise http_error(403, "forbidden")
        self.assertEqual(cs.collect(get=wrong_owner, now=NOW, ledger_paths=self.ledgers())["seeds"], [])


class CLI(unittest.TestCase):
    def output_path(self):
        root = Path(__file__).resolve().parent.parent / "build"
        root.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="comment-seeds-test-", dir=root)) / "out.json"

    def test_default_off_without_key_or_network(self):
        out = self.output_path()
        with patch.dict(os.environ, {}, clear=True), patch.object(cs, "collect", side_effect=AssertionError), \
             patch.object(sys, "argv", ["seeds", "--out", str(out)]):
            self.assertEqual(cs.main(), 0)
        self.assertFalse(out.exists())

    def test_failure_replaces_stale_results_without_leaking_error(self):
        out = self.output_path()
        out.write_text('{"seeds":["stale"]}', encoding="utf-8")
        with patch.dict(os.environ, dict(COLLESPO_COMMENT_SEEDS="on", YOUTUBE_API_KEY="fake"), clear=True), \
             patch.object(cs, "collect", side_effect=RuntimeError("SECRET_URL")), \
             patch.object(sys, "argv", ["seeds", "--out", str(out)]):
            self.assertEqual(cs.main(), 1)
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "fetch_failed")
        self.assertEqual(saved["seeds"], [])
        self.assertNotIn("SECRET_URL", out.read_text(encoding="utf-8"))

    def test_reason_saved_and_printed_for_http_and_disconnect(self):
        for error in [http_error(403, "quotaExceeded"), http_error(400, "invalidParameter"),
                      URLError("key=SECRET")]:
            out, stdout = self.output_path(), io.StringIO()
            original_collect = cs.collect
            def collect(**kwargs):
                def get(*args, **params):
                    raise error
                return original_collect(get=get, now=NOW, ledger_paths=[])
            with patch.dict(os.environ, dict(COLLESPO_COMMENT_SEEDS="on", YOUTUBE_API_KEY="fake")), \
                 patch.object(cs, "collect", side_effect=collect), \
                 patch.object(sys, "argv", ["seeds", "--out", str(out)]), patch.object(sys, "stdout", stdout):
                self.assertEqual(cs.main(), 0 if isinstance(error, HTTPError) and error.code == 400 else 1)
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["reason"]["call"], "commentThreads")
            self.assertEqual(saved["reason"]["page"], 1)
            self.assertIn(json.dumps(saved["reason"], ensure_ascii=False), stdout.getvalue())
            for secret in ("key=", "SECRET", "private.invalid"):
                self.assertNotIn(secret, out.read_text(encoding="utf-8") + stdout.getvalue())

    def test_missing_key_is_visible(self):
        out = self.output_path()
        with patch.dict(os.environ, dict(COLLESPO_COMMENT_SEEDS="on"), clear=True), \
             patch.object(cs, "collect", side_effect=AssertionError), \
             patch.object(sys, "argv", ["seeds", "--out", str(out)]):
            self.assertEqual(cs.main(), 1)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "missing_key")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
