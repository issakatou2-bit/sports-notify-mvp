"""訂正の材料の直し方（直す前の文が一致しなければ止まる）と、置いてある直し方の形。"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import correct_video as cv

ROOT = Path(__file__).resolve().parents[1]


class Correct(unittest.TestCase):
    def test_edit_needs_the_old_text(self):
        t = {"items": [["決勝点", "誤り"]], "title": "題"}
        cv.apply_edits(t, [{"where": ["items", 0, 1], "from": "誤り", "to": "正しい"}])
        self.assertEqual(t["items"][0][1], "正しい")
        with self.assertRaises(ValueError):
            cv.apply_edits(t, [{"where": ["title"], "from": "別の題", "to": "x"}])

    def test_every_fix_file_has_what_the_workflow_needs(self):
        for path in (ROOT / "data" / "corrections").glob("*.json"):
            fix = json.loads(path.read_text(encoding="utf-8"))
            for key in ("kind", "topic", "old_video", "material", "edits", "reason"):
                self.assertIn(key, fix, path.name)
            for e in fix["edits"]:
                self.assertNotEqual(e["from"], e["to"], path.name)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
