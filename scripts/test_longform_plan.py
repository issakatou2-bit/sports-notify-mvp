#!/usr/bin/env python3
"""長編の構成表（longform_plan.py）の形の検査。AIは呼ばない。

例は 10/5 の材料（松井 1.1回 ホールド・佐々木 2回 自責0・大谷 4打数1安打・
山本 WHIP 276人中4位・村上 アダム・ダン率 267人中1位・PSの勝敗）。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import longform_plan as lp  # noqa: E402

PANELS = {
    "jp1": {"type": "star", "name": "松井裕樹"},
    "jp2": {"type": "star", "name": "佐々木朗希"},
    "jp3": {"type": "star", "name": "大谷翔平"},
    "rare1": {"type": "stat", "name": "山本由伸", "stat": "WHIP"},
    "rare2": {"type": "stat", "name": "村上宗隆", "stat": "アダム・ダン率"},
    "race": {"type": "group", "head": "ポストシーズン"},
    "topic": {"type": "topic"},
}


def good():
    return {
        "headline": "松井裕樹が1.1回を自責0でホールド",
        "chapters": [
            {"id": "c1", "type": "lead", "title": "松井のホールド", "focus": "jp1",
             "screen": "headline_card", "points": ["1.1回 失点1 自責0", "ホールド"]},
            {"id": "c2", "type": "player", "title": "佐々木の2回", "focus": "jp2",
             "screen": "player_card", "points": ["被安打0", "四球2・死球1"]},
            {"id": "c3", "type": "player", "title": "大谷の1安打", "focus": "jp3",
             "screen": "player_card", "points": ["4打数1安打"]},
            {"id": "c4", "type": "ranking", "title": "山本のWHIP", "focus": "rare1",
             "screen": "ranking_table", "points": ["0.87", "276人中4位"]},
            {"id": "c5", "type": "series", "title": "地区シリーズの現在地", "focus": "race",
             "screen": "scoreboard", "points": ["ドジャース1勝1敗", "パドレス0勝2敗"]},
            {"id": "c6", "type": "close", "title": "きょうのまとめ", "focus": "topic",
             "screen": "summary", "points": ["松井・佐々木は自責0"]},
        ],
        "requests": [{"kind": "game_log", "player": "松井裕樹", "last": 5}],
    }


class Plan(unittest.TestCase):
    def test_good_plan_passes(self):
        self.assertEqual(lp.validate(good(), PANELS), [])

    def test_unknown_screen_and_focus_are_rejected(self):
        p = good()
        p["chapters"][1]["screen"] = "fireworks"
        p["chapters"][2]["focus"] = "jp9"
        bad = lp.validate(p, PANELS)
        self.assertTrue(any("screen「fireworks」" in b for b in bad))
        self.assertTrue(any("jp9" in b for b in bad))

    def test_order_lead_first_close_last(self):
        p = good()
        p["chapters"] = p["chapters"][1:] + p["chapters"][:1]
        bad = lp.validate(p, PANELS)
        self.assertIn("最初の章は lead にしてください", bad)
        self.assertIn("最後の章は close にしてください", bad)

    def test_every_japanese_player_is_covered(self):
        p = good()
        del p["chapters"][2]           # 大谷の章を外す
        self.assertTrue(any("jp3" in b for b in lp.validate(p, PANELS)))

    def test_latin_names_are_rejected(self):
        p = good()
        p["chapters"][3]["title"] = "Logan Hendersonとの差"
        self.assertTrue(any("英字の人名" in b for b in lp.validate(p, PANELS)))

    def test_only_fetchable_requests(self):
        p = good()
        p["requests"] = [{"kind": "web_search", "q": "x"}, {"kind": "leaderboard", "stat": "WHIP"}]
        bad = lp.validate(p, PANELS)
        self.assertTrue(any("web_search" in b for b in bad))
        self.assertTrue(any("around がありません" in b for b in bad))

    def test_parse_accepts_code_fence(self):
        self.assertEqual(lp.parse('```json\n{"headline": "x"}\n```'), {"headline": "x"})

    def test_prompt_and_outline(self):
        text = lp.build_prompt("F", "M")
        self.assertIn("ranking_table", text)
        self.assertIn('"headline"', text)
        out = lp.outline(good(), PANELS)
        self.assertIn("1. [jp1] 松井のホールド（松井裕樹）", out)


if __name__ == "__main__":
    unittest.main(argv=["test_longform_plan"])
