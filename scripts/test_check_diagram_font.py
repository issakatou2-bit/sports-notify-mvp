"""字体の欠落・破損・日本語グリフ欠落を成功扱いしない。"""
import tempfile
import unittest
from pathlib import Path

from check_diagram_font import FONT, check


class DiagramFontTest(unittest.TestCase):
    def test_bundled_japanese_font(self):
        check()

    def test_missing_and_corrupt_font(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.ttf"
            with self.assertRaises(OSError):
                check(path)
            path.write_bytes(b"invalid font")
            with self.assertRaises(OSError):
                check(path)

    def test_latin_only_font_is_rejected(self):
        with self.assertRaises(RuntimeError):
            check(FONT.parents[1] / "Oswald[wght].ttf")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
