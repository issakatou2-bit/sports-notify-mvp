"""システム字体に頼らず、CI の欠落・通信失敗・復元を再現する。"""
import shutil
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_diagram_font import FONT
import install_ci_fonts as ci


class CIFontsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        # 実機の字体の代わりに空の探索先を使う。
        self.font_dir = Path(self.tmp) / 'system/noto'
        self.cache_dir = Path(self.tmp) / 'cache'
        self.enterContext(patch.object(ci.time, 'sleep'))

    def populate(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        for name in ci.NAMES:
            shutil.copyfile(FONT, directory / name)

    def test_empty_system_retries_then_installs_and_caches(self):
        calls = []

        def apt(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(cmd, kwargs['timeout'])
            if cmd[2] == 'install':
                self.populate(self.font_dir)

        with patch.object(ci.subprocess, 'run', side_effect=apt):
            ci.install(self.font_dir, self.cache_dir)
        self.assertEqual([cmd[2] for cmd in calls], ['update', 'update', 'install'])
        self.assertTrue(ci.readable(self.font_dir))
        self.assertTrue(ci.readable(self.cache_dir))

    def test_cache_restores_without_network(self):
        self.populate(self.cache_dir)

        def restore(cmd, **kwargs):
            self.assertEqual(cmd[:2], ['sudo', 'install'])
            if cmd[2] == '-d':
                Path(cmd[3]).mkdir(parents=True)
            else:
                shutil.copyfile(cmd[-2], cmd[-1])

        with patch.object(ci.subprocess, 'run', side_effect=restore):
            ci.install(self.font_dir, self.cache_dir)
        self.assertTrue(ci.readable(self.font_dir))

    def test_missing_corrupt_latin_or_partial_fonts_fail(self):
        for source in (None, b'broken', FONT.parents[1] / 'Oswald[wght].ttf', FONT):
            with self.subTest(source=source):
                root = Path(self.tmp) / str(len(list(Path(self.tmp).iterdir())))
                root.mkdir()
                for name in ci.NAMES:
                    if source is None:
                        continue
                    if isinstance(source, bytes):
                        (root / name).write_bytes(source)
                    else:
                        shutil.copyfile(source, root / name)
                    if source == FONT:
                        break  # Bold が無い状態も失敗させる。
                with patch.object(ci.subprocess, 'run') as apt:
                    with self.assertRaises((OSError, RuntimeError)):
                        ci.install(root, self.cache_dir)
                self.assertEqual(apt.call_count, 6)
                self.assertFalse(self.cache_dir.exists())

    def test_network_failure_without_cache_fails(self):
        with patch.object(ci.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'apt')) as apt:
            with self.assertRaises(OSError):
                ci.install(self.font_dir, self.cache_dir)
        self.assertEqual(apt.call_count, 3)

    def test_consumers_find_restored_fonts_without_host_fonts_or_env(self):
        import ps_brand_components as brand
        import pilot_render as pilot
        from PIL import ImageFont

        exists, is_file, truetype = Path.exists, Path.is_file, ImageFont.truetype

        def mapped(path):
            value = str(path).replace('\\', '/')
            if value.startswith('/usr/share/fonts/opentype/noto/'):
                return self.font_dir / path.name
            if value.startswith('C:/Windows/Fonts/') or '/.fonts/' in value:
                return Path(self.tmp) / 'hidden-host-font'
            return path

        def load(path, *args, **kwargs):
            if hasattr(path, 'read'):
                return truetype(path, *args, **kwargs)
            return truetype(str(mapped(Path(path))), *args, **kwargs)

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(Path, 'exists', lambda p: exists(mapped(p))), \
             patch.object(Path, 'is_file', lambda p: is_file(mapped(p))), \
             patch.object(ImageFont, 'truetype', side_effect=load):
            brand._cache.clear()
            pilot.font.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    brand.font(32)
                with self.assertRaises(RuntimeError):
                    pilot.font(32)
                self.populate(self.cache_dir)

                def restore(cmd, **kwargs):
                    if cmd[2] == '-d':
                        Path(cmd[3]).mkdir(parents=True)
                    else:
                        shutil.copyfile(cmd[-2], cmd[-1])

                with patch.object(ci.subprocess, 'run', side_effect=restore):
                    ci.install(self.font_dir, self.cache_dir)
                for font in (brand.font(32), pilot.font(32), pilot.font(32, False)):
                    self.assertTrue(font.getmask('日本語').getbbox())
            finally:
                brand._cache.clear()
                pilot.font.cache_clear()


if __name__ == '__main__':
    unittest.main(argv=[__file__])
