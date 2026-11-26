#!/usr/bin/env python3
"""得点王・アシスト王争いが、嘘にならないか・今の見た目で出るか。

保存した実応答（2026-11-25 取得）だけで検査する。ネットには出ない。
動画は作らない（静止画を数枚描くだけ）。
"""

import copy
import json
import os
import pathlib
import re
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import soccer_leaders as sl  # noqa: E402

FIXTURES = HERE / "fixtures" / "leaders_1125"
TODAY = date(2026, 11, 25)
LATER = date(2026, 11, 28)
LOOK = dict(COLLESPO_SOCCER_LOOK="v6", COLLESPO_SOCCER_FOCUS="on",
            COLLESPO_STYLE="v2", COLLESPO_SHORT_LOOK="v4",
            COLLESPO_HOST_SPLIT="", COLLESPO_SOLO_HOST="metan")


def state_from(snapshots, when="2026-11-25"):
    return {"version": 1, "sections": {
        key: dict(copy.deepcopy(snap), snapshot_date=when)
        for key, snap in snapshots.items()}}


class LeadersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = sl.load_fixtures(str(FIXTURES))
        cls.parsed = sl.parse_all(cls.raw)
        cls.snapshots = {"%s:%s" % key: sl.snapshot(value)
                         for key, value in cls.parsed.items()}

    # ---- 実応答の読み ----------------------------------------------------
    def test_saved_response_values(self):
        goals = self.parsed[("eng.1", "goals")]
        self.assertEqual((goals[0]["name"], goals[0]["value"],
                          goals[0]["rank"]), ("Erling Haaland", 9, 1))
        self.assertEqual((goals[1]["name"], goals[1]["value"]),
                         ("Alexander Isak", 7))
        self.assertEqual(self.parsed[("esp.1", "goals")][0]["value"], 15)

    def test_ties_share_rank(self):
        goals = self.parsed[("eng.1", "goals")]
        self.assertEqual([x["rank"] for x in goals[2:5]], [3, 3, 3])
        self.assertEqual(goals[5]["rank"], 6)

    def test_japanese_players_use_existing_table(self):
        assists = self.parsed[("eng.1", "assists")]
        kamada = next(x for x in assists if x["name"] == "Daichi Kamada")
        self.assertEqual((kamada["name_jp"], kamada["jp"]), ("鎌田大地", True))

    # ---- 4. 選手名は日本語。表に無い人は出さない -------------------------
    def test_unregistered_player_has_no_japanese_name_and_is_never_shown(self):
        esp = self.parsed[("esp.1", "goals")]
        zabiri = next(x for x in esp if x["name"] == "Yassir Zabiri")
        self.assertIsNone(zabiri["name_jp"])          # 英字で代用しない
        self.assertFalse(sl.is_ready(self.snapshots["esp.1:goals"]))
        with self.assertRaises(ValueError):
            sl.build(self.raw, {}, TODAY, only="esp.1:goals")
        # 自動選択でも、名前の無い人がいる部門は選ばれない
        moves = {"esp.1:goals": [{"kind": "gap_opened", "gap": 2}]}
        self.assertIsNone(sl.choose(moves, {}, TODAY, {
            (k.split(":")[0], k.split(":")[1]): v
            for k, v in self.snapshots.items()}))

    def test_registered_names_are_katakana_with_reading(self):
        names = json.loads((ROOT / "data" / "soccer_leaders_names.json")
                           .read_text(encoding="utf-8"))["players"]
        for en, row in names.items():
            with self.subTest(player=en):
                self.assertRegex(row["name"], r"^[ァ-ヶー・]+$")
                self.assertRegex(row["reading"], r"^[ァ-ヶー]+$")
                self.assertLessEqual(len(row["name"]), sl.MAX_NAME)

    # ---- 3. 前回の記録が無い時は動きを言わない ---------------------------
    def test_first_run_has_no_movement_and_no_baseline(self):
        data = sl.build(self.raw, {}, TODAY)
        self.assertEqual(data["picked"], [])            # 動きなし→作らない
        data = sl.build(self.raw, {}, TODAY, only="eng.1:goals")
        story = data["story"]
        self.assertEqual(story["movements"], [])
        self.assertIsNone(story["baseline_date"])
        program = self.program(data)
        text = "".join(s["text"] for s in program["narration"]["segments"])
        for word in ("昨日", "前回", "首位に立", "替わ", "抜い", "上がった"):
            self.assertNotIn(word, text)

    def test_saved_state_is_a_dated_baseline_and_same_data_is_no_movement(self):
        # 本番の data/ は毎日書き換わるので、11/25 の保存を固定して使う（11/26 日付がずれて赤になった）。
        state = sl.load_state(str(HERE / "fixtures" / "leaders_state_1125.json"))
        self.assertEqual(state["sections"]["eng.1:goals"]["snapshot_date"],
                         "2026-11-25")
        data = sl.build(self.raw, state, LATER)
        self.assertEqual(data["picked"], [])
        data = sl.build(self.raw, state, LATER, only="eng.1:goals")
        self.assertEqual(data["story"]["baseline_date"], "2026-11-25")
        self.assertEqual(data["story"]["movements"], [])

    def changed(self):
        """前回は2位が首位だった、という記録（今回は首位が替わった形）。"""
        old = copy.deepcopy(self.snapshots)
        pl = old["eng.1:goals"]
        pl["leader"], pl["leader_jp"] = "Alexander Isak", "イサク"
        pl["leader_value"], pl["second_value"], pl["gap"] = 8, 8, 0
        return state_from(old)

    def test_movement_is_said_with_baseline_date_and_without_repeating_numbers(self):
        data = sl.build(self.raw, self.changed(), LATER)
        self.assertEqual(data["picked"], ["eng.1:goals"])
        kinds = [m["kind"] for m in data["story"]["movements"]]
        self.assertIn("leader_changed", kinds)
        self.assertEqual(data["story"]["baseline_date"], "2026-11-25")
        program = self.program(data)
        table = program["narration"]["segments"][1]
        self.assertIn("11月25日の前回から", table["text"])
        self.assertIn("首位が", table["text"])
        self.assertIn("前回は11月25日", table["meta"]["title"])  # 画面にも基準の日

    def test_japanese_movement_comes_first(self):
        old = copy.deepcopy(self.snapshots)
        old["eng.1:assists"]["jp"] = []                 # 前回は上位10人にいなかった
        data = sl.build(self.raw, state_from(old), LATER)
        self.assertEqual(data["picked"], ["eng.1:assists"])
        self.assertTrue(any(m["kind"] == "jp_entered"
                            for m in data["story"]["movements"]))

    def test_one_per_day_and_seven_days(self):
        state = self.changed()
        state["last_published_date"] = LATER.isoformat()
        self.assertEqual(sl.build(self.raw, state, LATER)["picked"], [])
        state = self.changed()
        state["sections"]["eng.1:goals"]["last_published"] = "2026-11-24"
        self.assertEqual(sl.build(self.raw, state, LATER)["picked"], [])
        state["sections"]["eng.1:goals"]["last_published"] = "2026-11-20"
        self.assertEqual(sl.build(self.raw, state, LATER)["picked"],
                         ["eng.1:goals"])

    def test_gap_and_tie_movements(self):
        prev = {"leader": "A", "second_value": 7, "leader_value": 9,
                "gap": 1, "jp": []}
        now = {"leader": "A", "leader_value": 9, "second_value": 7, "gap": 2,
               "top": [], "jp": []}
        self.assertEqual([m["kind"] for m in sl.detect_movements(prev, now, "goals")],
                         ["gap_opened"])
        prev = dict(prev, gap=3, second_value=6)
        now = dict(now, gap=1, second_value=8)
        self.assertEqual([m["kind"] for m in sl.detect_movements(prev, now, "goals")],
                         ["gap_closed"])
        self.assertEqual(sl.detect_movements({}, now, "goals"), [])

    # ---- 2. 題・言い方 ---------------------------------------------------
    def test_title_says_gap_with_unit_in_front_of_diff(self):
        data = sl.build(self.raw, {}, TODAY, only="eng.1:goals")
        self.assertEqual(
            data["title"],
            "プレミアリーグ 得点王争い｜ハーランドが9点で首位、2位と2点差")
        assists = sl.build(self.raw, {}, TODAY, only="eng.1:assists")
        self.assertEqual(
            assists["title"],
            "プレミアリーグ アシスト王争い｜デクラン・ライスが5アシストで首位、2位と1アシスト差")
        self.assertEqual(sl.gap_text(2, "点"), "2点差")
        for title in (data["title"], assists["title"]):
            self.assertNotIn("点2差", title)
            self.assertNotIn("点上位", title)
            self.assertNotRegex(title, r"[、，]\s*[^｜]*？")   # 語りかけ・宣伝文にしない

    # ---- 台本（掛け合い）と画面 ------------------------------------------
    def program(self, data):
        import soccer_slots_v4 as slots
        with patch.dict(os.environ, LOOK):
            import review_render_v3 as r3
            with patch.object(r3, "LOOK", "v4"):
                return slots.race_program(data["race"])

    def test_dialogue_zundamon_asks_metan_answers_without_repeating_numbers(self):
        data = sl.build(self.raw, {}, TODAY, only="eng.1:goals")
        segs = self.program(data)["narration"]["segments"]
        self.assertEqual([s["kind"] for s in segs],
                         ["cover", "standings", "outro"])
        self.assertEqual([s["speaker"] for s in segs], [3, 2, 2])
        ask, answer = segs[0], segs[1]
        self.assertTrue(ask["text"].rstrip().endswith("？"))
        self.assertIn("ハーランド", ask["text"])
        self.assertIn("9点", ask["text"])                # 冒頭で誰が何点か
        self.assertNotIn("9点", answer["text"])          # 同じ数字を2回言わない
        self.assertIn("2点", answer["text"])             # 差は答えのほうで
        self.assertEqual(ask["meta"]["presenter"], "zundamon")
        hook = ask["meta"]["opening_hook"]
        self.assertEqual(hook["context"], "プレミアリーグ　得点王争い")
        self.assertEqual((hook["subject"], hook["value"]), ("ハーランド", 9))
        self.assertTrue(self.program(data)["narration"]["opening_check"]["passed"])
        # 同じ数字を2回言わない（答えの中でも）
        numbers = re.findall(r"\d+点", answer["text"])
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_metan_uses_current_tone_and_zundamon_uses_noda(self):
        import metan_tone
        for key in ("eng.1:goals", "eng.1:assists", "ger.1:goals"):
            data = sl.build(self.raw, {}, TODAY, only=key)
            segs = self.program(data)["narration"]["segments"]
            self.assertNotRegex(segs[1]["text"], metan_tone.BAD, key)
            self.assertTrue(re.search(r"のだ", segs[0]["text"]), key)

    def test_table_rows_keep_ties_and_show_only_known_names(self):
        data = sl.build(self.raw, {}, TODAY, only="eng.1:goals")
        rows = self.program(data)["narration"]["segments"][1]["meta"]["rows"]
        self.assertEqual([r["position"] for r in rows], [1, 2, 3, 3])
        self.assertTrue(all(re.search(r"[ァ-ヶー・一-龯]", r["team"])
                            for r in rows))

    def test_same_new_look_as_standings_race(self):
        """順位争い（soccer_race）と同じ部品で描かれる。静止画を数枚だけ描く。"""
        import review_render_v3 as r3
        import soccer_slots_v4 as slots
        data = sl.build(self.raw, {}, TODAY, only="eng.1:assists")
        with patch.dict(os.environ, LOOK), patch.object(r3, "LOOK", "v4"):
            plan = slots.race_program(data["race"])
            segs = plan["narration"]["segments"]
            for index, when in ((0, 1.4), (1, 21.5)):
                seg = segs[index]
                r3.set_program_clock(0)
                r3.set_caption(seg["text"], 22, 24, speaker=2, duo=False,
                               **({"caption_units": seg["caption_units"]}
                                  if seg.get("caption_units") else {}))
                r3.set_program_clock(when)
                try:
                    image = slots.frame(when, seg, plan)
                    self.assertEqual(slots.check_frame(image, plan), [])
                finally:
                    r3.set_program_clock(None)
                # 新しい見た目の印：隅の立ち絵・読みやすい画面
                self.assertTrue(image.info.get("soccer_readable"))
                self.assertTrue(image.info.get("short_cast"))
                self.assertEqual(image.size, (1080, 1920))
            texts = [e["text"] for e in image.info["v3_layout"]]
            for word in ("鎌田大地", "クリスタル・パレス", "アシスト"):
                self.assertIn(word, texts)

    def test_race_without_leaders_is_untouched(self):
        import soccer_slots_v4 as slots
        src = (HERE / "soccer_slots_v4.py").read_text(encoding="utf-8")
        self.assertIn("if data.get('leaders'):", src)
        # 旧い順位争いの描き方（generate_morning_short の race_*）は書き換えない
        old = (HERE / "generate_morning_short.py").read_text(encoding="utf-8")
        self.assertNotIn("soccer_leaders", old)
        self.assertNotIn("race_unit", old)
        self.assertTrue(callable(slots.race_program))

    # ---- 見た目の指定はworkflowで固定 ------------------------------------
    def test_workflow_pins_the_new_look(self):
        text = (ROOT / ".github" / "workflows" / "soccer_leaders.yml"
                ).read_text(encoding="utf-8")
        for line in ("COLLESPO_SOCCER_LOOK: v6", "COLLESPO_SOCCER_FOCUS: 'on'",
                     "COLLESPO_STYLE: v2", "COLLESPO_SHORT_LOOK: v4"):
            self.assertIn(line, text)
        for name in ("COLLESPO_SOCCER_LOOK", "COLLESPO_SOCCER_FOCUS",
                     "COLLESPO_STYLE", "COLLESPO_SHORT_LOOK"):
            self.assertNotRegex(text, name + r":\s*\$\{\{\s*vars\.")

    # ---- 状態 ------------------------------------------------------------
    def test_state_records_publish_day(self):
        data = {"sections": self.snapshots}
        updated = sl.next_state({}, data, TODAY, published_key="eng.1:goals")
        self.assertEqual(updated["last_published_date"], TODAY.isoformat())
        self.assertEqual(updated["sections"]["eng.1:goals"]["leader"],
                         "Erling Haaland")
        self.assertEqual(updated["sections"]["eng.1:goals"]["snapshot_date"],
                         TODAY.isoformat())


if __name__ == "__main__":
    unittest.main(argv=[__file__])
