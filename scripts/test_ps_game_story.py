#!/usr/bin/env python3
"""PSの試合ごとの話題（ps_game_story.py）。公式APIは使わず、固定の試合経過で確かめる。

材料は 10/3（米国）の地区シリーズ第1戦 CWS 3-0 CLE を縮めたもの。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ps_game_story as g  # noqa: E402

JP = {"Munetaka Murakami": "村上宗隆"}
KANA = {"Hagen Smith": "ヘイゲン・スミス", "Parker Messick": "パーカー・メシック",
        "Bryan Hudson": "ブライアン・ハドソン", "Colson Montgomery": "コルソン・モンゴメリー",
        "Grant Taylor": "", "X": "", "Unknownplayer": ""}


def play(half, inning, event, rbi, away, home, batter, hit=None):
    ev = [{"hitData": hit}] if hit else [{}]
    return {"about": {"halfInning": half, "inning": inning},
            "result": {"event": event, "rbi": rbi, "awayScore": away, "homeScore": home},
            "matchup": {"batter": {"fullName": batter}}, "playEvents": ev}


def person(pid, name, batting=None, pitching=None):
    return {"person": {"id": pid, "fullName": name},
            "stats": {"batting": batting or {}, "pitching": pitching or {}}}


def feed(home_runs_away=3, home_runs_home=0):
    plays = [play("top", 4, "Home Run", 2, 2, 0, "Munetaka Murakami",
                  {"launchSpeed": 112.2, "totalDistance": 440.0}),
             play("top", 7, "Double", 1, 3, 0, "Colson Montgomery",
                  {"launchSpeed": 64.0, "totalDistance": 7.0})]
    return {
        "gameData": {"teams": {
            "away": {"id": 145, "name": "Chicago White Sox", "teamName": "White Sox",
                     "locationName": "Chicago"},
            "home": {"id": 114, "name": "Cleveland Guardians", "teamName": "Guardians",
                     "locationName": "Cleveland"}}},
        "liveData": {
            "linescore": {"teams": {"away": {"runs": home_runs_away},
                                    "home": {"runs": home_runs_home}}},
            "plays": {"allPlays": plays, "scoringPlays": [0, 1]},
            "decisions": {"winner": {"id": 3, "fullName": "Bryan Hudson"},
                          "save": {"id": 4, "fullName": "Grant Taylor"}},
            "boxscore": {"teams": {
                "away": {"pitchers": [1, 3, 4, 5, 6], "players": {
                    "ID1": person(1, "Hagen Smith", pitching={"inningsPitched": "2.2", "runs": 0}),
                    "ID3": person(3, "Bryan Hudson", pitching={"inningsPitched": "0.1", "runs": 0}),
                    "ID9": person(9, "Munetaka Murakami",
                                  batting={"plateAppearances": 4, "atBats": 4, "hits": 2,
                                           "homeRuns": 1, "rbi": 2})}},
                "home": {"pitchers": [2], "players": {
                    "ID2": person(2, "Parker Messick",
                                  pitching={"inningsPitched": "4.1", "runs": 2})}}}}},
    }


GAME = {"gamePk": 849829, "gameType": "D", "gameDate": "2026-10-03T17:00:00Z",
        "seriesStatus": {"gameNumber": 1, "wins": 1, "losses": 0,
                         "winningTeam": {"id": 145}, "isOver": False}}


class GameStory(unittest.TestCase):
    def build(self, voices=None, quotes=None, f=None):
        return g.story(GAME, f or feed(), dict(KANA), JP, voices or {}, quotes or [])

    def test_decisive_first_run_by_japanese_player_leads_title_and_intro(self):
        t = self.build()
        self.assertTrue(t["title"].startswith(
            "【MLB】村上宗隆の先制2ランでホワイトソックスが敵地で地区シリーズ先勝｜ガーディアンズに3対0"))
        self.assertIn("村上宗隆の先制2ランで", t["intro"])
        items = dict(t["items"])
        self.assertEqual(items["先制で決勝の一打"],
                         "4回表　村上宗隆の2点本塁打（飛距離134メートル、打球の速さ時速181キロ）")
        self.assertEqual(items["投手"], "ホワイトソックスは5人の継投で完封")
        self.assertIn("シリーズはホワイトソックスの1勝0敗", items["試合の結果"])

    def test_pitching_lines_do_not_run_numbers_together(self):
        items = dict(self.build()["items"])
        self.assertIn("メシック 4回と3分の1を2失点", items["先発"])
        self.assertIn("スミス 2回と3分の2を無失点", items["先発"])
        # 勝ち投手は救援。セーブはカタカナが無いので出さない
        self.assertEqual(items["勝ち投手"], "ブライアン・ハドソン（3分の1回を無失点）")

    def test_japanese_player_line_with_team(self):
        t = self.build()
        self.assertEqual(t["japanese"], [{"name": "村上宗隆",
                                          "line": "4打数2安打　1本塁打　2打点（ホワイトソックス）"}])

    def test_go_ahead_is_not_the_first_run_when_lead_changed(self):
        f = feed(5, 3)
        f["liveData"]["plays"]["allPlays"] = [
            play("bottom", 1, "Single", 1, 0, 1, "X"),
            play("top", 3, "Home Run", 2, 2, 1, "Munetaka Murakami", {"totalDistance": 400.0}),
            play("bottom", 5, "Home Run", 2, 2, 3, "X"),
            play("top", 8, "Sac Fly", 1, 3, 3, "Colson Montgomery"),
            play("top", 9, "Single", 2, 5, 3, "Colson Montgomery")]
        f["liveData"]["plays"]["scoringPlays"] = [0, 1, 2, 3, 4]
        items = dict(self.build(f=f)["items"])
        # 相手の最終3点を初めて上回ったのは9回の2点（4点目）
        self.assertEqual(items["決勝点"], "9回表　コルソン・モンゴメリーのタイムリー")
        self.assertNotIn("先制で決勝の一打", items)

    def test_error_is_not_credited_to_batter_or_called_decisive_hit(self):
        for batter in ("Munetaka Murakami", "Colson Montgomery"):
            with self.subTest(batter=batter):
                f = feed(1, 0)
                f["liveData"]["plays"] = {"allPlays": [
                    play("top", 6, "Field Error", 0, 1, 0, batter)], "scoringPlays": [0]}
                t = self.build(f=f)
                self.assertIn("の打球で相手の失策", dict(t["items"])["決勝点"])
                self.assertNotIn("の失策", dict(t["items"])["決勝点"].split("打球で")[0])
                self.assertNotIn("先制で決勝の一打", dict(t["items"]))
                self.assertNotIn("決勝打", t["title"])
                self.assertNotIn("先制打", t["title"])
                self.assertNotIn("先制打", t["intro"])

    def test_non_hit_decisive_plays_keep_the_actual_event(self):
        for event in ("Walk", "Hit By Pitch", "Sac Fly", "Groundout", "Wild Pitch", "Passed Ball"):
            with self.subTest(event=event):
                f = feed(1, 0)
                f["liveData"]["plays"] = {"allPlays": [
                    play("top", 6, event, 1, 1, 0, "Munetaka Murakami")], "scoringPlays": [0]}
                t = self.build(f=f)
                self.assertIn(g.EVENT_JP[event], dict(t["items"])["決勝点"])
                self.assertNotIn("先制で決勝の一打", dict(t["items"]))
                self.assertNotIn("先制打", t["title"])
                self.assertNotIn("決勝打", t["title"])
                if event in ("Wild Pitch", "Passed Ball"):
                    self.assertIn("相手の", dict(t["items"])["決勝点"])
                    self.assertNotIn("村上宗隆の", dict(t["items"])["決勝点"])

    def test_voice_is_from_this_game_after_first_pitch_and_localized(self):
        voices = {"voices": [
            {"matchup": "WHITE SOX vs. GUARDIANS", "at": "2026-10-03T20:10:00Z", "likes": 50,
             "ja": "White Soxの新人が決めた！", "title": "orig", "url": "u1"},
            {"matchup": "WHITE SOX vs. GUARDIANS", "at": "2026-10-02T20:10:00Z", "likes": 900,
             "ja": "昨日のコメント", "title": "old", "url": "u0"},
            {"matchup": "DODGERS vs. BRAVES", "at": "2026-10-03T23:00:00Z", "likes": 999,
             "ja": "別の試合", "title": "x", "url": "u2"}]}
        t = self.build(voices=voices)
        self.assertEqual(dict(t["items"])["ハイライトのコメント欄から"],
                         "「ホワイトソックスの新人が決めた！」")
        self.assertEqual(t["voice"]["url"], "u1")

    def test_voice_with_unspeakable_latin_is_skipped(self):
        voices = {"voices": [{"matchup": "WHITE SOX vs. GUARDIANS", "at": "2026-10-03T20:10:00Z",
                              "ja": "Unknownplayer がすごい", "title": "t", "url": "u"}]}
        self.assertNotIn("ハイライトのコメント欄から", dict(self.build(voices=voices)["items"]))

    def test_reporter_post_before_the_game_is_not_used(self):
        quotes = [{"team": "ホワイトソックス", "jp": "試合前の練習", "at": "2026-10-03T15:00:00Z",
                   "author": "A", "text": "t"},
                  {"team": "ホワイトソックス", "jp": "村上宗隆の一発が流れを変えた", "at": "2026-10-03T21:00:00Z",
                   "author": "B", "outlet": "MLB.com", "text": "t2"}]
        t = self.build(quotes=quotes)
        self.assertEqual(dict(t["items"])["ホワイトソックスの番記者の投稿から"],
                         "「村上宗隆の一発が流れを変えた」")
        self.assertEqual(t["source"]["author"], "B")

    def test_japanese_games_come_first(self):
        a = {"jp_first": False, "game_date": "2026-10-03T17:00:00Z"}
        b = {"jp_first": True, "game_date": "2026-10-03T20:00:00Z"}
        rows = sorted([a, b], key=lambda t: (not t["jp_first"], t.get("game_date") or ""))
        self.assertIs(rows[0], b)


class Localize(unittest.TestCase):
    """10/6、ホワイトソックスの試合のコメント「60 yrs a Sox fan」が「ボストン・レッドソックス」に化けた。"""
    FEED = {"gameData": {"teams": {
        "away": {"id": 145, "name": "Chicago White Sox", "teamName": "White Sox", "locationName": "Chicago"},
        "home": {"id": 114, "name": "Cleveland Guardians", "teamName": "Guardians", "locationName": "Cleveland"}}}}

    def test_nickname_last_word_is_the_team_in_this_game(self):
        words = g.team_words(self.FEED)
        self.assertEqual(g.localize("60年間 Sox ファンをやってきた。", words, {}, JP),
                         "60年間 ホワイトソックス ファンをやってきた。")

    def test_unknown_single_word_is_not_looked_up(self):
        words = g.team_words(self.FEED)
        self.assertEqual(g.localize("Roof が主役だ", words, {}, JP), "")

    def test_japanese_surname_alone(self):
        self.assertEqual(g.localize("Murakami がすごい", {}, {}, JP), "村上宗隆 がすごい")

    def test_headline_number_is_dropped(self):
        self.assertEqual(g.localize("1. 執拗なレイズが5回に4点", {}, {}, JP), "執拗なレイズが5回に4点")


if __name__ == "__main__":
    unittest.main(argv=["test_ps_game_story"])
