"""字体の欠落・破損・日本語グリフ欠落を成功扱いしない。"""
import tempfile
import unittest
import os
import shutil
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PIL import ImageFont

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

    def test_system_font_cannot_replace_missing_or_corrupt_file(self):
        # CI の Linux 既定探索先を再現。環境変数による字体指定は使わない。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            host.mkdir()
            shutil.copyfile(FONT, host / "NotoSansCJK-Regular.ttc")
            walk = os.walk
            font_os = SimpleNamespace(**vars(os))
            font_os.walk = lambda directory: (
                walk(host) if str(directory).replace("\\", "/") == "/usr/share/fonts"
                else iter(())
            )
            path = root / "NotoSansCJK-Regular.ttc"
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(ImageFont, "sys", SimpleNamespace(platform="linux")), \
                 patch.object(ImageFont, "os", font_os):
                for corrupt in (False, True):
                    with self.subTest(corrupt=corrupt):
                        if corrupt:
                            path.write_bytes(b"broken")
                        # 修正前はこの代用を指定ファイルの検証と誤認していた。
                        self.assertTrue(ImageFont.truetype(str(path), 32)
                                        .getmask("日本語").getbbox())
                        with self.assertRaises(OSError):
                            check(path)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
