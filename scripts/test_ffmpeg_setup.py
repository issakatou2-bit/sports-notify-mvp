"""10/16のLinux実行権限エラー: コピー権限・絶対PATH・音声結合と同じ呼出しを検査。"""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import soccer_results_render as render


class FfmpegSetup(unittest.TestCase):
    def test_existing_binary_is_used(self):
        with patch.object(render.shutil,'which',return_value='/installed/ffmpeg'):
            self.assertEqual(render.ensure_ffmpeg(Path('unused')),'/installed/ffmpeg')

    def test_posix_copy_is_executable_and_path_is_absolute(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'bundled';source.write_bytes(b'fake ffmpeg')
            fake_os=NS(name='posix',environ={'PATH':'old-path'},pathsep=os.pathsep)
            with patch.object(render,'os',fake_os),patch.object(render.shutil,'which',return_value=None), \
                 patch.dict('sys.modules',{'imageio_ffmpeg':NS(get_ffmpeg_exe=lambda:str(source))}), \
                 patch.object(Path,'chmod') as chmod:
                target=Path(render.ensure_ffmpeg(Path(td)/'nested'/'output'))
            self.assertTrue(target.is_absolute())
            self.assertEqual(target.read_bytes(),source.read_bytes())
            self.assertEqual(chmod.call_args.args[0] & (stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH),0o111)
            self.assertEqual(fake_os.environ['PATH'].split(os.pathsep)[0],str(target.parent))

    def test_real_bundled_fallback_runs_by_path_and_by_name(self):
        try:import imageio_ffmpeg
        except ImportError:self.skipTest('任意のimageio_ffmpegが未導入')
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ):
            with patch.object(render.shutil,'which',return_value=None):
                target=render.ensure_ffmpeg(Path(td))
            self.assertEqual(Path(shutil.which('ffmpeg')).resolve(),Path(target).resolve())
            for command in (target,'ffmpeg'):
                result=subprocess.run([command,'-version'],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn(b'ffmpeg version',result.stdout)
            self.assertTrue(Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file())


if __name__=='__main__':unittest.main(argv=['test_ffmpeg_setup'])
