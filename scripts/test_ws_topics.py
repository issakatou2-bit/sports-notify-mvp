#!/usr/bin/env python3
"""ワールドシリーズの話題（ws_topics.py）。APIは使わず、小さな作り物で確かめる。"""
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ws_topics as wt  # noqa: E402

MIL, TB, LAD, NYY, SD, SEA, COL, STL, PHI = 158, 139, 119, 147, 135, 136, 115, 138, 143
NAMES = {MIL: "ブリュワーズ", TB: "レイズ", LAD: "ドジャース", NYY: "ヤンキース",
         SD: "パドレス", SEA: "マリナーズ", COL: "ロッキーズ",
         STL: "カージナルス", PHI: "フィリーズ"}
TEAMS = [(MIL, "ブリュワーズ"), (TB, "レイズ"), (SD, "パドレス"),
         (SEA, "マリナーズ"), (COL, "ロッキーズ"), (LAD, "ドジャース"),
         (NYY, "ヤンキース"), (STL, "カージナルス"), (PHI, "フィリーズ")]
FIRST = {MIL: 1968, TB: 1998, LAD: 1890, NYY: 1903}


def result(season, a, b, aw, bw):
    return {"season": season, "teams": [a, b], "wins": {a: aw, b: bw},
            "losses": {a: bw, b: aw}, "champion": a if aw > bw else b,
            "games": aw + bw, "complete": True}


HISTORY = [
    result(1982, MIL, STL, 3, 4),
    result(2008, PHI, TB, 4, 1),
    result(2020, LAD, TB, 4, 2),
    result(2025, LAD, NYY, 4, 1),
    result(1998, NYY, SD, 4, 0),
]


def game(pk, date, away, home, winner=None, n=1, tbd=False,
         state="Final"):
    return {"gamePk": pk, "gameDate": date, "seriesGameNumber": n,
            "status": {"abstractGameState": state, "startTimeTBD": tbd},
            "teams": {"away": {"team": {"id": away, "name": f"T{away}"},
                               "isWinner": winner == away},
                      "home": {"team": {"id": home, "name": f"T{home}"},
                               "isWinner": winner == home}}}


def schedule_game(n, date, away, home, tbd=False):
    return game(100 + n, date, away, home, None, n=n, tbd=tbd, state="Preview")


SCHEDULE = [
    schedule_game(1, "2026-10-24T00:00:00Z", TB, MIL),
    schedule_game(2, "2026-10-25T00:00:00Z", TB, MIL),
    schedule_game(3, "2026-10-27T00:00:00Z", MIL, TB),
    schedule_game(4, "2026-10-28T00:00:00Z", MIL, TB),
    schedule_game(5, "2026-10-29T00:00:00Z", MIL, TB),
    schedule_game(6, "2026-10-31T00:00:00Z", TB, MIL),
    schedule_game(7, "2026-11-01T00:00:00Z", TB, MIL),
]
RECORDS = {MIL: {"wins": 103, "losses": 59, "pct": ".636"},
           TB: {"wins": 98, "losses": 64, "pct": ".605"}}


class History(unittest.TestCase):
    def test_unfinished_series_is_not_a_championship(self):
        rows = [game(1, "2025-10-24T00:00:00Z", MIL, TB, MIL),
                schedule_game(2, "2025-10-25T00:00:00Z", MIL, TB)]
        got = wt.parse_series(2025, rows)
        self.assertIsNone(got["champion"])
        self.assertFalse(got["complete"])

    def test_postponed_duplicate_keeps_final_result(self):
        final = game(1, "2020-10-24T00:00:00Z", MIL, TB, TB)
        preview = schedule_game(1, "2020-10-23T00:00:00Z", MIL, TB)
        preview["gamePk"] = 1
        rows = [preview, final] + [
            game(n, "2020-10-25T00:00:00Z", MIL, TB, TB, n=n)
            for n in range(2, 5)]
        got = wt.parse_series(2020, rows)
        self.assertEqual(got["wins"][TB], 4)
        self.assertEqual(got["champion"], TB)
        self.assertTrue(got["complete"])

    def test_complete_history_is_reused_without_api_calls(self):
        with patch.object(wt, "_read_cache", return_value={1982: HISTORY[0]}):
            def unexpected(*args, **kwargs):
                self.fail("キャッシュ済みの年を再取得した")
            self.assertEqual(wt.load_history(1982, get=unexpected,
                                            first=1982), [HISTORY[0]])

    def test_appearances_are_old_to_new_with_opponent_and_record(self):
        apps = wt.appearances(HISTORY, TB)
        self.assertEqual([a["season"] for a in apps], [2008, 2020])
        self.assertEqual((apps[0]["wins"], apps[0]["losses"]), (1, 4))
        self.assertEqual((apps[1]["wins"], apps[1]["losses"]), (2, 4))
        self.assertFalse(any(a["won"] for a in apps))

    def test_title_state_and_years_since_last_appearance(self):
        mil = wt.appearances(HISTORY, MIL)
        lad = wt.appearances(HISTORY, LAD)
        self.assertFalse(wt.title_state(mil)["has_title"])
        self.assertTrue(wt.title_state(lad)["has_title"])
        self.assertEqual(wt.title_state(lad)["last_title"], 2025)
        self.assertEqual(wt._gap_text(mil, 2026), "44年ぶり2回目")
        self.assertEqual(wt._gap_text(wt.appearances(HISTORY, TB), 2026),
                         "6年ぶり3回目")

    def test_ties_and_resumed_rows_are_counted_once(self):
        # 1907年の引き分けと、2008年の再開された第5戦（同じ gamePk）を模す
        tie = game(1, "1907-10-08T00:00:00Z", 116, 112, None, n=1)
        wins = [game(i, f"1907-10-{8 + i:02d}T00:00:00Z", 116, 112, 112, n=i)
                for i in range(2, 6)]
        got = wt.parse_series(1907, [tie] + wins)
        self.assertEqual((got["wins"][112], got["wins"][116]), (4, 0))
        self.assertEqual(got["champion"], 112)

        row = [game(9, "2008-10-23T00:00:00Z", PHI, TB, PHI, n=1),
               game(13, "2008-10-28T00:00:00Z", TB, PHI, PHI, n=5),
               game(13, "2008-10-30T00:37:00Z", TB, PHI, PHI, n=5)]
        got = wt.parse_series(2008, row)
        self.assertEqual((got["wins"][PHI], got["wins"][TB]), (2, 0))

    def test_remaining_teams_without_a_title(self):
        no_title, others = wt.no_title_split(HISTORY, TEAMS, exclude=(MIL, TB))
        self.assertEqual(len(no_title), 5)
        self.assertEqual([name for _, name in others],
                         ["パドレス", "マリナーズ", "ロッキーズ"])


class TitleTopic(unittest.TestCase):
    def build(self, pair=(MIL, TB)):
        return wt.title_history_topic(2026, pair, HISTORY, NAMES, FIRST, TEAMS,
                                      home_id=158)

    def test_both_first_time_hook_and_records(self):
        t = self.build()
        self.assertEqual(t["hook"], "どっちが勝っても初優勝")
        items = dict(t["items"])
        self.assertEqual(items["ブリュワーズの過去のWS"],
                         "1982年　カージナルスに3勝4敗")
        self.assertEqual(items["レイズの過去のWS"],
                         "2008年　フィリーズに1勝4敗／2020年　ドジャースに2勝4敗")
        self.assertEqual(items["前回のWSから"],
                         "ブリュワーズは44年ぶり2回目、レイズは6年ぶり3回目")
        self.assertEqual(items["今回の2球団を除く"],
                         "残り3球団（パドレス、マリナーズ、ロッキーズ）")
        self.assertEqual(t["style"], "v3")
        self.assertIn("どっちが勝っても初優勝", t["title"])

    def test_does_not_say_first_title_when_one_team_has_won(self):
        t = self.build((MIL, LAD))
        text = json.dumps(t, ensure_ascii=False)
        self.assertNotIn("初優勝", text)
        self.assertIn("初の世界一", t["hook"])
        self.assertIn("連覇", t["hook"])

    def test_both_with_titles_use_years(self):
        t = self.build((LAD, NYY))
        self.assertNotIn("初優勝", json.dumps(t, ensure_ascii=False))
        self.assertIn("連覇", t["hook"])
        self.assertIn("28年ぶり優勝", t["hook"])

    def test_zero_teams_without_titles_is_also_shown(self):
        teams = [(LAD, NAMES[LAD]), (NYY, NAMES[NYY])]
        t = wt.title_history_topic(2026, (LAD, NYY), HISTORY, NAMES, FIRST, teams)
        self.assertIn("2球団中0球団（なし）", dict(t["items"])["WS優勝が無い球団"])


class ScheduleTopic(unittest.TestCase):
    def test_jst_conversion_and_undecided(self):
        self.assertEqual(wt.jst_label("2026-10-23T20:30:00Z"),
                         "10月24日（土）5時30分")
        self.assertEqual(wt.jst_label("2026-10-24T00:00:00Z"),
                         "10月24日（土）9時")
        self.assertEqual(wt.jst_label("2026-10-24T00:30:00Z"),
                         "10月24日（土）9時30分")
        self.assertEqual(wt.jst_label(""), "未定")
        self.assertEqual(wt.jst_label("2026-10-24T00:00:00Z", tbd=True), "未定")

    def test_2_3_2_home_order_and_each_game(self):
        self.assertEqual([tid for _, tid in wt.home_order(SCHEDULE)],
                         [MIL, MIL, TB, TB, TB, MIL, MIL])
        t = wt.schedule_topic(2026, SCHEDULE, NAMES, RECORDS)
        items = dict(t["items"])
        self.assertEqual(items["第1・2戦"], "10月24日（土）・25日（日）9時　ブリュワーズの本拠地")
        self.assertEqual(items["第3〜5戦"], "10月27日（火）〜29日（木）9時　レイズの本拠地（第5戦は必要な場合）")
        self.assertEqual(items["第6・7戦"], "10月31日（土）・11月1日（日）9時　ブリュワーズの本拠地（必要な場合）")
        self.assertEqual(wt.pattern_text(wt.home_order(SCHEDULE), NAMES),
                         "2-3-2　第1・2・6・7戦がブリュワーズ、第3〜5戦がレイズ")
        self.assertIn("4勝", items["優勝まで"])
        self.assertIn("第1戦はブリュワーズの本拠地", t["hook"])
        self.assertIn("勝率が上", items["本拠地の理由"])

    def test_home_reason_only_when_regular_season_backs_it(self):
        lower = {MIL: {"wins": 90, "losses": 72, "pct": ".556"},
                 TB: {"wins": 98, "losses": 64, "pct": ".605"}}
        t = wt.schedule_topic(2026, SCHEDULE, NAMES, lower)
        self.assertNotIn("本拠地の理由", dict(t["items"]))

    def test_undecided_date_is_written_as_undecided(self):
        games = [schedule_game(1, "", TB, MIL, tbd=True)] + SCHEDULE[1:]
        t = wt.schedule_topic(2026, games, NAMES)
        self.assertTrue(dict(t["items"])["第1・2戦"].startswith("未定"))


class Build(unittest.TestCase):
    def test_unconfirmed_teams_produce_no_topics(self):
        row = schedule_game(1, "", None, None)
        row["teams"]["home"]["team"].pop("id")
        def fake(*args, **kwargs):
            return {"dates": [{"games": [row]}]}
        self.assertEqual(wt.build_topics(2026, get=fake, cache_path=None), [])

    def test_empty_topics_without_a_world_series_schedule(self):
        def fake(path, **params):
            return {"dates": []} if path == "/schedule" else {}
        self.assertEqual(wt.build_topics(2026, get=fake, cache_path=None), [])

    def test_pair_comes_from_the_postseason_schedule(self):
        def fake(path, **params):
            if path == "/schedule":
                if int(params.get("season") or 0) == 2026:
                    return {"dates": [{"games": SCHEDULE}]}
                return {"dates": []}
            if path == "/teams":
                return {"teams": [{"id": tid, "name": f"T{tid}"}
                                  for tid, _ in TEAMS]}
            if path == "/standings":
                return {"records": [{"teamRecords": [
                    {"team": {"id": tid}, **row} for tid, row in RECORDS.items()]}]}
            tid = int(path.rsplit("/", 1)[-1])
            return {"teams": [{"id": tid, "firstYearOfPlay": str(FIRST.get(tid, 1900))}]}
        topics = wt.build_topics(2026, get=fake, cache_path=None)
        self.assertEqual([t["key"] for t in topics],
                         ["ws_title_history", "ws_schedule"])
        self.assertIn("ブリュワーズ", topics[0]["title"])
        self.assertIn("第1戦はブリュワーズの本拠地", topics[1]["hook"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
