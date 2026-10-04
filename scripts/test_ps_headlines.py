"""PS見出しの誤接続・古い試合・取得失敗による古いJSON利用を固定材料で検査。"""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mlb_headlines as mh
import ps_game_story as ps
from test_ps_game_story import GAME, JP, KANA, feed

NOW = datetime(2026, 10, 4, 6, tzinfo=timezone.utc)
URL = "https://www.mlb.com/news/white-sox-win-alds-game-1-2026"
H = {"source": "MLB.com", "url": URL, "title": "White Sox win Game 1",
     "at": "Sat, 03 Oct 2026 22:22:00 GMT", "jp": "ホワイトソックスが敵地で地区シリーズ先勝"}


def material():
    f = feed()
    f["gameData"]["teams"]["away"]["league"] = {"id": 103}
    f["liveData"]["plays"]["allPlays"][-1]["about"]["endTime"] = "2026-10-03T20:00:00Z"
    return f


class Headlines(unittest.TestCase):
    def pick(self, h=None, f=None, game=None):
        f = f or material()
        return ps.pick_headline([h or H], game or GAME, f, ps.team_words(f), KANA, JP)

    def test_saved_not_trailing_headline_does_not_become_unbeaten(self):
        original = "Yet to trail this postseason, White Sox march into Cleveland and claim ALDS Game 1"
        h = dict(H, title=original, jp="ポストシーズン無敗のホワイトソックス、敵地で地区シリーズ先勝")
        got = self.pick(h)
        self.assertIn("まだリードを許していない", got["said"])
        self.assertNotIn("無敗", got["said"])
        self.assertEqual(got["text"], original)

    def test_unresolved_not_trailing_translation_is_not_quoted(self):
        h = dict(H, title="Yet to trail this postseason", jp="負けなしで勝利した")
        self.assertIsNone(self.pick(h))

    def test_exact_completed_game_matches_rss_timestamp(self):
        self.assertEqual(self.pick()["url"], URL)
        t = ps.story(GAME, material(), KANA, JP, {}, [], [H])
        self.assertIn("MLB.comの見出しから", dict(t["items"]))

    def test_schedule_without_series_hydration_uses_explicit_series_game_number(self):
        game = dict(GAME, seriesGameNumber=1)
        game.pop("seriesStatus")
        self.assertIsNotNone(self.pick(game=game))
        game.pop("seriesGameNumber")
        self.assertIsNone(self.pick(game=game))

    def test_other_winner_year_game_round_host_and_preview_rejected(self):
        for url in (URL.replace("white-sox", "guardians"), URL.replace("2026", "2025"),
                    URL.replace("game-1", "game-2"), URL.replace("alds", "alcs"),
                    URL.replace("www.mlb.com", "www.mlb.com.example.org"),
                    URL.replace("-win-", "-preview-")):
            with self.subTest(url=url):
                self.assertIsNone(self.pick(dict(H, url=url)))

    def test_source_unknown_league_missing_translation_unspeakable_rejected(self):
        for h in (dict(H, source="ESPN"), dict(H, jp=""), dict(H, jp="Unknownplayer の勝利")):
            self.assertIsNone(self.pick(h))
        f = material()
        f["gameData"]["teams"]["away"].pop("league")
        self.assertIsNone(self.pick(f=f))

    def test_before_finish_and_late_republication_rejected(self):
        for at in ("2026-10-03T19:59:59Z", "2026-10-05T22:22:00Z"):
            self.assertIsNone(self.pick(dict(H, at=at)))
        self.assertIsNotNone(self.pick(dict(H, at="2026-10-04T05:22:00+07:00")))

    def test_end_time_is_last_play_not_first_scoring_play(self):
        f = material()
        f["liveData"]["plays"]["allPlays"][0]["about"]["endTime"] = "2026-10-03T18:00:00Z"
        self.assertEqual(ps.finished_at(f), datetime(2026, 10, 3, 20, tzinfo=timezone.utc))

    def test_freshness_boundary_and_missing_future_end(self):
        f = material()
        end = ps.finished_at(f)
        for age, count in ((timedelta(hours=30), 1), (timedelta(hours=30, seconds=1), 0),
                           (timedelta(seconds=-1), 0)):
            with self.subTest(age=age):
                self.assertEqual(len(ps.build([GAME], {GAME["gamePk"]: f}, {}, [], now=end+age)), count)
        f["liveData"]["plays"]["allPlays"][-1]["about"].pop("endTime")
        self.assertEqual(ps.build([GAME], {GAME["gamePk"]: f}, {}, [], now=NOW), [])

    def test_failure_replaces_old_topics_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)/"topics.json"
            out.write_text(json.dumps({"topics": [{"key": "old"}]}))
            with patch.object(sys, "argv", ["ps_game_story", "--out", str(out)]), \
                 patch.object(ps, "finished_games", side_effect=RuntimeError("offline")):
                self.assertEqual(ps.main(), 1)
            actual = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(actual["topics"], [])
            self.assertEqual(actual["status"], "error")

    def test_description_preserves_source_url_and_original(self):
        import upload_youtube
        t = ps.story(GAME, material(), KANA, JP, {}, [], [H])
        meta = upload_youtube.asset_meta_from_spec(t)
        self.assertIn(URL, meta["lead"])
        self.assertIn("原文: " + H["title"], meta["lead"])

    def test_screen_source_matches_quote_and_does_not_claim_stats_api(self):
        import review_render
        for head, source in (("MLB.comの見出しから", "MLB.com"),
                             ("ハイライトのコメント欄から", "MLB公式コメント"),
                             ("ホワイトソックスの番記者の投稿から", "番記者の投稿")):
            label = review_render.page_source([(head, "「引用」")])
            self.assertIn(source, label)
            self.assertNotIn("Stats API", label)
        self.assertIn("Stats API", review_render.page_source([("先発", "数字")]))


class RSS(unittest.TestCase):
    def xml(self, at="Sat, 03 Oct 2026 22:22:00 GMT", url=URL):
        return f"<rss><channel><item><title>White Sox win Game 1</title><link>{url}</link><pubDate>{at}</pubDate></item></channel></rss>"

    def test_only_recent_verified_recaps_with_origin_url(self):
        rows = mh.parse(self.xml(), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], URL)
        self.assertTrue(rows[0]["at"].endswith("+00:00"))
        for at in ("bad", "2026-10-04T04:00:00", "Fri, 02 Oct 2026 00:00:00 GMT", "Mon, 05 Oct 2026 06:00:00 GMT"):
            self.assertEqual(mh.parse(self.xml(at), NOW), [])
        self.assertEqual(mh.parse(self.xml(url=URL.replace("-win-", "-preview-")), NOW), [])

    def test_duplicate_url_and_limit(self):
        xml = self.xml().replace("</channel>", self.xml().split("<channel>")[1].split("</channel>")[0]+"</channel>")
        self.assertEqual(len(mh.parse(xml, NOW)), 1)
        self.assertEqual(mh.parse(xml, NOW, limit=0), [])


if __name__ == "__main__":
    unittest.main(argv=["test_ps_headlines"])
