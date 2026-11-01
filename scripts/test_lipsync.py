import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image
import characters as c
import lipsync as ls


class LipsyncTest(unittest.TestCase):
    def test_hold_and_silence(self):
        result = ls.smooth([2]*6+[0]*6)
        self.assertEqual(result[-2:], [0,0])
        changes = [i for i in range(1,len(result)) if result[i] != result[i-1]]
        self.assertTrue(all(b-a >= 2 for a,b in zip(changes, changes[1:])))
        self.assertEqual(ls.envelope(np.zeros(800), 800, fps=30), [0]*30)

    def test_query_vowels_and_pause(self):
        q = dict(speedScale=2, prePhonemeLength=.2, postPhonemeLength=.2,
                 accent_phrases=[dict(moras=[dict(vowel='a',vowel_length=.4),
                     dict(vowel='i',vowel_length=.4), dict(vowel='U',vowel_length=.4)],
                     pause_mora=dict(vowel_length=.4))])
        frames = ls.query_frames(q, 1, fps=30)
        self.assertEqual(frames[0],0)
        self.assertEqual(frames[5],2)
        self.assertEqual(frames[12],1)
        self.assertEqual(frames[-1],0)

    def test_audio_sidecar_hash_and_track_tail(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, COLLESPO_LIPSYNC='voice'):
            p = Path(td,'voice.wav')
            x = np.r_[np.zeros(2400), np.sin(np.arange(4800)*.2)*.3, np.zeros(2400)]
            with wave.open(str(p),'wb') as w:
                w.setparams((1,2,24000,0,'NONE','not compressed'))
                w.writeframes((x*32767).astype(np.int16).tobytes())
            ls.prepare([dict(file=str(p),speaker=2)], [1], td)
            self.assertEqual(ls.at(.8,2),0)
            self.assertEqual(ls.at(.2,3),0)
            self.assertGreater(ls.at(.2,2),0)
            p.with_suffix('.lipsync.json').write_text(json.dumps(dict(wav_sha256='bad',query={})))
            with self.assertRaises(ValueError):ls.audio_frames(p)
            p.with_suffix('.lipsync.json').write_text(json.dumps(dict(
                wav_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                query=dict(accent_phrases=[dict(moras=[dict(vowel='a',vowel_length=.4)])]))))
            self.assertEqual(ls.audio_frames(p)[1],'voicevox-query')

    def test_unset_pixels_and_existing_parts(self):
        root = Path(__file__).resolve().parents[1]
        original = subprocess.check_output(['git','show','11035100:scripts/characters.py'],cwd=root).decode('utf-8')
        old = types.ModuleType('characters_baseline')
        exec(compile(original,'characters_baseline','exec'), old.__dict__)
        with patch.dict(os.environ, COLLESPO_LIPSYNC=''):
            for line in ('山本由伸が先発します。','村上が本塁打。','大谷は無安打。','今日の成績です。'):
                for t in (0,.2,.5,1.3,3.9):
                    a=Image.new('RGB',(1080,1920));b=a.copy()
                    old.place_busts(a,'metan',line,t,4)
                    c.place_busts(b,'metan',line,t,4)
                    self.assertEqual(a.tobytes(),b.tobytes())
        for who in c.PORTRAIT_CAST:
            parts=c.vc._parts(c.NAMES[who], c.PORTRAIT_DIR)
            self.assertTrue(all(k in parts['口'] for k in ('閉','開','大')))
        self.assertEqual(c.vc.FACES['v4_surprise:mouth0'][:2], c.FACE_PARTS['surprise'][:2])


if __name__ == '__main__':unittest.main(argv=[__file__])
