import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_v3 as d
import generate_morning_short as g


class DailyV3(unittest.TestCase):
    def data(self):
        vd = json.loads((Path(__file__).parent / "fixtures/comment/local_voices-preview.json").read_text(encoding="utf-8"))
        data = {"players": [], "voices": vd, "date_jst": "2026-10-07"}
        return data, g.build_narration(data, "voices")

    def test_off_preserves_narration_and_other_slots(self):
        data, nar = self.data(); before = copy.deepcopy(nar)
        with patch.dict(os.environ, {"COLLESPO_COMMENTS_DESIGN": "legacy"}):
            self.assertIsNone(d.prepare(data, nar, "voices"))
        with patch.dict(os.environ, {"COLLESPO_COMMENTS_DESIGN": "comments"}):
            self.assertIsNone(d.prepare(data, nar, "press"))
        self.assertEqual(nar, before)

    def test_full_program_metan_without_changing_the_words(self):
        data, nar = self.data(); words = [s["text"] for s in nar["segments"]]
        with patch.dict(os.environ, {"COLLESPO_COMMENTS_DESIGN": "comments"}):
            design = d.prepare(data, nar, "voices")
        self.assertEqual([s["text"] for s in nar["segments"]], words)
        for seg in nar["segments"]:
            self.assertEqual((seg["speaker"], seg["meta"]["who"]), (2, "四国めたん"))
            im = d.frame(3.0, seg, design, 14.0)
            self.assertEqual(im.size, (1080, 1920))

    def test_missing_material_does_not_mutate_voices(self):
        nar = {"segments": [{"kind": "thread", "text": "テスト", "speaker": 3, "meta": {"index": 3}}]}
        before = copy.deepcopy(nar)
        with patch.dict(os.environ, {"COLLESPO_COMMENTS_DESIGN": "comments"}), self.assertRaises(ValueError):
            d.prepare({"voices": {}}, nar, "voices")
        self.assertEqual(nar, before)

    def test_wrong_or_stale_audio_stops(self):
        nar = {"segments": [{"kind": "intro", "text": "本文", "speaker": 2}]}
        for actual in [[], [{"kind": "intro", "text": "本文", "speaker": 3}], [{"kind": "intro", "text": "古い本文", "speaker": 2}]]:
            with self.assertRaises(ValueError): d.validate_audio(actual, nar)
        d.validate_audio(nar["segments"], nar)

    def test_invalid_indexes_cannot_show_a_different_comment(self):
        import comment_render as cr
        vd = {"voices": [{"ja": "別のコメント"}]}
        for seg in [{"kind": "voices", "meta": {"picked": [-1]}},
                    {"kind": "voices", "meta": {"picked": [1]}},
                    {"kind": "thread", "meta": {"index": -1}}]:
            with self.assertRaises(ValueError): cr.voices_for_segment(seg, vd)

    def test_existing_sound_mixer_and_offsets(self):
        import sound_mix
        design = {"mode": "voices", "voices": {}}
        segs = [{"kind": "intro", "speaker": 2}, {"kind": "outro", "speaker": 2}]
        with patch.object(sound_mix, "mix_file", return_value="mixed") as mix:
            self.assertEqual(d.mix("voice.wav", segs, [5, 6], design, Path("build")), "mixed")
        self.assertEqual([c[0] for c in mix.call_args.kwargs["cues"]], [0.0, 5.0])
        self.assertEqual(mix.call_args.kwargs["bgm_path"].name, sound_mix.DEFAULT_BGM + ".mp3")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
