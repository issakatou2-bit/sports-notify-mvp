#!/usr/bin/env python3
"""得点王・アシスト王争いが、嘘にならないか。

保存した実応答（2026-11-25 取得）だけで検査する。ネットには出ない。
"""

import copy
import pathlib
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import soccer_leaders as sl  # noqa: E402

FIXTURES = HERE / "fixtures" / "leaders_1125"
TODAY = date(2026, 11, 25)


def entries(*pairs):
    return sl.rank([{"name": name, "value": value,
                     "name_jp": name, "team": "", "team_jp": "",
                     "matches": 10, "jp": False}
                    for name, value in pairs])


class LeadersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = sl.load_fixtures(str(FIXTURES))
        cls.parsed = sl.parse_all(cls.raw)
        cls.snapshots = {"%s:%s" % key: sl.snapshot(value)
                         for key, value in cls.parsed.items()}

    def test_saved_response_values(self):
        goals = self.parsed[("eng.1", "goals")]
        self.assertEqual(goals[0]["name"], "Erling Haaland")
        self.assertEqual(goals[0]["value"], 9)
        self.assertEqual(goals[0]["rank"], 1)
        self.assertEqual(goals[1]["name"], "Alexander Isak")
        self.assertEqual(goals[1]["value"], 7)
        self.assertEqual(self.parsed[("esp.1", "goals")][0]["value"], 15)

    def test_japanese_names_use_existing_table(self):
        assists = self.parsed[("eng.1", "assists")]
        kamada = [x for x in assists if x["name"] == "Daichi Kamada"]
        self.assertTrue(kamada)
        self.assertEqual(kamada[0]["name_jp"], "鎌田大地")
        self.assertTrue(kamada[0]["jp"])

        goals = self.parsed[("ger.1", "goals")]
        suzuki = [x for x in goals if x["name"] == "Yuito Suzuki"]
        self.assertTrue(suzuki)
        self.assertEqual(suzuki[0]["name_jp"], "鈴木唯人")

    def test_ties_share_rank(self):
        ranked = entries(("A", 9), ("B", 9), ("C", 7))
        self.assertEqual([x["rank"] for x in ranked], [1, 1, 3])

    def test_no_movement_when_same(self):
        now = sl.snapshot(entries(("A", 9), ("B", 7)))
        self.assertEqual(sl.detect_movements(now, now, "goals"), [])

    def test_leader_changed(self):
        before = sl.snapshot(entries(("A", 9), ("B", 7)))
        after = sl.snapshot(entries(("B", 9), ("A", 7)))
        moves = sl.detect_movements(before, after, "goals")
        kinds = [m["kind"] for m in moves]
        self.assertIn("leader_changed", kinds)
        # 抜いた相手と、前回からの増え方が言えるときだけ言う。
        text = moves[0]["text"]
        self.assertIn("Aを抜いた", text)
        self.assertIn("前回より2点", text)

    def test_tied_lead(self):
        before = sl.snapshot(entries(("A", 9), ("B", 7)))
        after = sl.snapshot(entries(("A", 9), ("B", 9)))
        kinds = [m["kind"] for m in sl.detect_movements(before, after, "goals")]
        self.assertIn("tied_lead", kinds)

    def test_gap_opened_and_closed(self):
        before = sl.snapshot(entries(("A", 9), ("B", 8)))
        after = sl.snapshot(entries(("A", 10), ("B", 7)))
        kinds = [m["kind"] for m in sl.detect_movements(before, after, "goals")]
        self.assertIn("gap_opened", kinds)

        before = sl.snapshot(entries(("A", 9), ("B", 6)))
        after = sl.snapshot(entries(("A", 10), ("B", 9)))
        kinds = [m["kind"] for m in sl.detect_movements(before, after, "goals")]
        self.assertIn("gap_closed", kinds)

    def test_japanese_entered_or_rose(self):
        before = sl.snapshot(entries(("A", 9), ("B", 8), ("C", 7)))
        after = sl.snapshot(entries(("A", 9), ("J", 8), ("B", 7)))
        after["jp"] = [{"name": "J", "name_jp": "日本人", "rank": 2,
                        "value": 8}]
        kinds = [m["kind"] for m in sl.detect_movements(before, after, "goals")]
        self.assertIn("jp_entered", kinds)

    def test_no_story_without_movement(self):
        state = {"sections": self.snapshots}
        data = sl.build(self.raw, state, TODAY)
        self.assertEqual(data["picked"], [])
        self.assertEqual(data["title"], "")
        self.assertEqual(data["movements"], {})
        self.assertEqual(data["narration"]["segments"], [])

    def test_story_and_narration(self):
        state = {"sections": copy.deepcopy(self.snapshots)}
        state["sections"]["eng.1:goals"]["leader"] = "Someone Else"
        data = sl.build(self.raw, state, TODAY)
        self.assertEqual(data["picked"], ["eng.1:goals"])
        self.assertIn("プレミアリーグ", data["title"])
        self.assertIn("得点王", data["title"])
        self.assertIn("ハーランド", data["title"])
        speakers = [s.get("speaker") for s in data["narration"]["segments"]]
        self.assertIn(3, speakers)
        self.assertIn(2, speakers)
        said = "".join(s["text"] for s in data["narration"]["segments"])
        self.assertIn("ハーランド", said)
        self.assertIn("9", said)
        self.assertEqual(data["race"]["picked"], ["PL"])
        self.assertEqual(data["race"]["frame_label"], "得点王争い")
        # 原稿の数字を共通の検査が照合できる材料が付いている。
        self.assertTrue(data["narration"].get("soccer_material"))
        lines = data["race"]["competitions"][0]["lines"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["at"], 2)
        self.assertEqual(lines[0]["label"], "首位と2位")
        self.assertEqual(lines[1]["at"], sl.TOP_N)
        race_lines = [s for s in data["narration"]["segments"]
                      if s["kind"] == "race_line"]
        self.assertEqual(len(race_lines), 2)
        self.assertTrue(race_lines[0]["meta"]["rows"])
        self.assertTrue(race_lines[1]["meta"]["rows"])

    def test_race_view_japanese_name_and_club(self):
        snapshots = copy.deepcopy(self.snapshots)
        snapshots["eng.1:assists"]["leader"] = "Someone Else"
        data = sl.build(self.raw, {"sections": snapshots}, TODAY)
        jp = data["race"]["competitions"][0]["jp"]
        self.assertTrue(jp)
        self.assertEqual(jp[0]["name"], "鎌田大地")
        self.assertEqual(jp[0]["club_jp"], "クリスタル・パレス")

    def test_japanese_movement_comes_first(self):
        movements = {
            "esp.1:goals": [{"kind": "leader_changed", "text": "首位交代"}],
            "eng.1:assists": [{"kind": "jp_rose", "text": "鎌田が上がった"}],
        }
        chosen = sl.choose(movements, {}, TODAY)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen[2], "eng.1:assists")

    def test_seven_day_window(self):
        six = (TODAY - timedelta(days=6)).isoformat()
        seven = (TODAY - timedelta(days=7)).isoformat()
        state = {"sections": {"eng.1:goals": {"last_published": six}}}
        self.assertFalse(sl.can_publish(state, "eng.1:goals", TODAY))
        state["sections"]["eng.1:goals"]["last_published"] = seven
        self.assertTrue(sl.can_publish(state, "eng.1:goals", TODAY))

    def test_one_per_day(self):
        state = {"last_published_date": TODAY.isoformat(), "sections": {}}
        self.assertFalse(sl.can_publish(state, "eng.1:goals", TODAY))

        snapshots = copy.deepcopy(self.snapshots)
        snapshots["eng.1:goals"]["leader"] = "Someone Else"
        data = sl.build(self.raw, {"sections": snapshots,
                                   "last_published_date": TODAY.isoformat()},
                        TODAY)
        self.assertEqual(data["picked"], [])

    def test_state_read_write(self):
        state = {"version": 1, "sections": {
            "eng.1:goals": {"last_published": TODAY.isoformat()}}}
        with tempfile.TemporaryDirectory() as folder:
            path = str(pathlib.Path(folder) / "state.json")
            sl.save_state(path, state)
            self.assertEqual(sl.load_state(path), state)
            updated = sl.next_state(sl.load_state(path),
                                    {"sections": self.snapshots}, TODAY,
                                    published_key="eng.1:goals")
            self.assertEqual(updated["last_published_date"],
                             TODAY.isoformat())
            self.assertEqual(updated["sections"]["eng.1:goals"]
                             ["last_published"], TODAY.isoformat())
            self.assertEqual(updated["sections"]["eng.1:goals"]["leader"],
                             "Erling Haaland")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
