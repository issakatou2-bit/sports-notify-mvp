import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_v3 as d
import press_v3 as p
import generate_morning_short as g


class PressV3(unittest.TestCase):
    def data(self):
        rd = json.loads((Path(__file__).parent / "fixtures/comment/local_reporters-preview.json").read_text(encoding="utf-8"))
        data = {"players": [], "reporters": rd, "date_jst": "2026-10-07"}
        return data, g.build_narration(data, "press")

    def test_defaults_keep_every_word_and_other_slot(self):
        data, nar = self.data(); old = copy.deepcopy(nar)
        with patch.dict(os.environ, {"COLLESPO_PRESS_DESIGN": "legacy"}):
            self.assertIsNone(d.prepare(data, nar, "press"))
        self.assertEqual(nar, old)

    def test_all_screens_quote_the_exact_selected_body(self):
        import review_render_v3 as r3
        data, nar = self.data(); words = [s["text"] for s in nar["segments"]]
        with patch.dict(os.environ, {"COLLESPO_PRESS_DESIGN": "v3"}):
            design = d.prepare(data, nar, "press")
        self.assertEqual([s["text"] for s in nar["segments"][:-1]], words[:-1])
        self.assertEqual(nar['segments'][-1]['text'],r3.OUTRO_TEXT)
        for seg in nar["segments"]:
            self.assertEqual(seg["speaker"], 2)
            self.assertEqual(d.frame(3, seg, design, 18).size, (1080, 1920))
            for row in p.bubbles(seg, data["reporters"]): self.assertIn(row["said"], seg["text"])

    def test_mismatched_caption_or_invalid_index_stops(self):
        data, nar = self.data()
        seg = next(s for s in nar["segments"] if s["kind"] == "headlines")
        seg["meta"]["picked"] = [-1]
        with self.assertRaises(ValueError): p.bubbles(seg, data["reporters"])
        seg["meta"]["picked"] = [0]; seg["text"] = "架空の違う記事"
        with self.assertRaises(ValueError): p.bubbles(seg, data["reporters"])

    def test_identity_and_club_color_are_material_bound(self):
        seg = {"kind": "headlines", "text": "ドジャースの記事", "meta": {"picked": [0]}}
        data = {"headlines": [{"jp": seg["text"], "source": "検査媒体"}]}
        self.assertEqual(p.team_id(seg, data), 119)
        self.assertEqual(p.bubbles(seg, data)[0]["who"], "検査媒体")
        data["headlines"][0]["jp"] = seg["text"] = "ドジャースとパドレスの記事"
        self.assertIsNone(p.team_id(seg, data))

    def test_background_keeps_moving_and_cues_fit_the_voice(self):
        data, nar = self.data(); seg = next(s for s in nar["segments"] if s["kind"] == "headlines")
        self.assertIsNotNone(ImageChops.difference(p.frame(4, seg, data["reporters"], 15), p.frame(5, seg, data["reporters"], 15)).getbbox())
        for at, *_ in p.cues(seg, data["reporters"], 15): self.assertLess(at, 15)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
