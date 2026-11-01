"""長編の新デザイン（longform_render_v3）のつなぎ: 尺を変えない・札の決まり・字幕が立ち絵にかからない。"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import longform_render_v3 as lr3


class LongformV3(unittest.TestCase):
    def segs(self):
        return [{"kind": "intro", "speaker": 2, "text": "きょうの話です。"},
                {"kind": "talk", "speaker": 3, "text": "村上は2本塁打なのだ。", "panel": "stat"},
                {"kind": "talk", "speaker": 2, "text": "4打数3安打、3打点よ。", "panel": "nokey"},
                {"kind": "outro", "speaker": 2, "text": "また見てね。"}]

    def test_timeline_keeps_durations_and_drops_unknown_panels(self):
        cards = {"stat": {"kind": "stat"}}
        pages = [(s, 2.0) for s in self.segs()]
        rows = lr3.timeline(pages, cards, 30)
        self.assertEqual([r["frames"] for r in rows], [60, 60, 60, 60])
        self.assertIs(rows[2]["panel"], rows[1]["panel"])     # 知らない鍵は前の札のまま

    def test_paginate_shares_add_up(self):
        long = {"kind": "talk", "speaker": 2, "text": "あ" * 400}
        pages = lr3.paginate([long])
        self.assertAlmostEqual(sum(p["_share"] for p in pages), 1.0, places=6)

    def test_subtitle_stays_left_of_the_portraits(self):
        h, cx, _ = lr3.PORTRAIT_PLACE["ずんだもん"]
        art = lr3.standing("ずんだもん")
        self.assertLessEqual(lr3.SUB_X1, cx - art.width // 2 + 40)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
