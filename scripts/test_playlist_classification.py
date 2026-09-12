"""実際に誤分類された題と、記録・題の不一致をAPIなしで確認する。"""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from playlist_classification import classify, kind_for_video, recorded_kinds

# Google SDKの有無や認証情報に依存せず、公開操作の境界を検査する。
sdk = {name: MagicMock() for name in (
    "google", "google.oauth2", "google.oauth2.credentials", "googleapiclient",
    "googleapiclient.discovery", "googleapiclient.errors")}
sdk["googleapiclient.errors"].HttpError = type("FakeHttpError", (Exception,), {})
with patch.dict(sys.modules, sdk):
    spec = importlib.util.spec_from_file_location("playlist_cli_under_test",
                                                pathlib.Path(__file__).with_name("playlists.py"))
    playlist_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(playlist_cli)


class PlaylistClassificationTests(unittest.TestCase):
    def test_current_soccer_title_does_not_enter_mlb(self):
        self.assertEqual(classify("【欧州サッカー】田中聡 シャルケの試合｜今夜の注目試合 #Shorts"),
                         "daily_soccer")

    def test_postseason_old_and_new_titles(self):
        for title in ("【MLB】パドレスが進出圏内に入った｜9月11日 ポストシーズン進出争い #Shorts",
                      "【9/11時点】MLBポストシーズン争い｜パドレスが進出圏内へ #Shorts"):
            self.assertEqual(classify(title), "postseason")

    def test_comment_short_and_long_are_separate(self):
        self.assertEqual(classify("山本由伸｜現地のファンは何と言ったか #Shorts"), "morning_voices")
        self.assertEqual(classify("【海外の反応】山本由伸への現地の声｜レッズ 対 ドジャース"), "longform")

    def test_unknown_titles_are_not_assumed_to_be_glossary(self):
        for title in ("", "決勝の注目試合", "新番組のお知らせ", "山本由伸7回10奪三振"):
            self.assertIsNone(classify(title))

    def test_recorded_id_survives_both_live_ab_titles(self):
        known = recorded_kinds({"longform": {"2026-09-11": {"video_id": "w19dHvo9XXQ"}}}, {}, {"longform"})
        for title in ("山本由伸7回10奪三振、援護を喜ぶファンの声｜レッズ戦【MLB】",
                      "ドジャース14得点、山本由伸への援護にファンは何を語った？【MLB】"):
            self.assertEqual(kind_for_video("w19dHvo9XXQ", title, known), "longform")

    def test_recorded_kinds_use_actual_upload_names(self):
        known = recorded_kinds({
            "morning_postseason": {"d": {"video_id": "postseason-video"}},
            "verdict": {"d": {"video_id": "verdict-video"}},
        }, {}, {"postseason", "weekly"})
        self.assertEqual(known, {"postseason-video": "postseason", "verdict-video": "weekly"})

    def test_asset_uses_separate_publication_record(self):
        known = recorded_kinds({}, {"assets": {"mlb_terms": {"video_id": "asset-video"}}}, {"asset"})
        self.assertEqual(kind_for_video("asset-video", "題を刷新", known), "asset")

    def test_conflicting_records_do_not_guess_from_title(self):
        entries = {"d": {"video_id": "ambiguous"}}
        known = recorded_kinds({"daily": entries, "longform": entries}, {}, {"daily", "longform"})
        self.assertIsNone(kind_for_video("ambiguous", "明日の注目試合【MLB】", known))

    def test_invalid_entries_and_unsupported_kinds_are_ignored(self):
        known = recorded_kinds({"daily": {"a": None, "b": {}, "c": {"video_id": 123}},
                                "unreleased": {"a": {"video_id": "unreleased"}}}, {}, {"daily"})
        self.assertEqual(known, {})


class PlaylistOperationTests(unittest.TestCase):
    def test_dry_run_never_adds_or_saves_for_any_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = pathlib.Path(tmp) / "videos.json"
            record.write_text(json.dumps({"daily": {"d": {"video_id": "daily-video"}}}))
            for options in (["--add", "daily-video", "--kind", "daily"],
                            ["--sync"], ["--backfill"]):
                with self.subTest(mode=options), contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(sys, "argv", ["playlists.py", *options, "--dry-run"]))
                    stack.enter_context(patch.object(playlist_cli, "client", return_value=MagicMock()))
                    stack.enter_context(patch.object(playlist_cli, "VIDEOS_PATH", str(record)))
                    stack.enter_context(patch.object(playlist_cli, "load_store", return_value={}))
                    stack.enter_context(patch.object(playlist_cli, "publication_kinds", return_value={}))
                    stack.enter_context(patch.object(playlist_cli, "all_uploads", return_value=[
                        {"id": "daily-video", "title": "明日の注目試合【MLB】"}]))
                    add = stack.enter_context(patch.object(playlist_cli, "add_video"))
                    save = stack.enter_context(patch.object(playlist_cli, "save_store"))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    self.assertEqual(playlist_cli.main(), 0)
                    add.assert_not_called()
                    save.assert_not_called()

    def test_existing_ui_playlist_and_video_do_not_create_duplicates(self):
        yt = MagicMock()
        store = {"longform": {"id": "existing-playlist", "videos": ["existing-video"]}}
        self.assertFalse(playlist_cli.add_video(yt, store, "longform", "existing-video"))
        self.assertEqual(yt.mock_calls, [])

    def test_backfill_routes_recorded_id_and_skips_unknown(self):
        yt, store = MagicMock(), {}
        with patch.object(sys, "argv", ["playlists.py", "--backfill"]), \
                patch.object(playlist_cli, "client", return_value=yt), \
                patch.object(playlist_cli, "load_store", return_value=store), \
                patch.object(playlist_cli, "publication_kinds", return_value={"w19dHvo9XXQ": "longform"}), \
                patch.object(playlist_cli, "all_uploads", return_value=[
                    {"id": "w19dHvo9XXQ", "title": "題が変わった長編"},
                    {"id": "unknown", "title": "新番組"}]), \
                patch.object(playlist_cli, "add_video", return_value=False) as add, \
                patch.object(playlist_cli, "save_store"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(playlist_cli.main(), 0)
            add.assert_called_once_with(yt, store, "longform", "w19dHvo9XXQ")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
