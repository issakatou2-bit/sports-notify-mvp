import hashlib
import json
import os
from pathlib import Path
import tempfile
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

    def test_portrait_stays_in_place_and_uses_audio_only_for_speaker(self):
        with patch.object(ls, 'at', return_value=2):
            a = Image.new('RGB', (1080, 1920))
            b = a.copy()
            before = c.place_busts(a, 'metan', '自己最多よ。', .7, 4)
            after = c.place_busts(b, 'metan', '自己最多よ。', 1.5, 4)
        self.assertEqual(before[1], after[1])
        self.assertEqual(before[0]['box'][0::2], after[0]['box'][0::2])
        self.assertTrue(0 < abs(before[0]['box'][1] - after[0]['box'][1]) <= 6)
        a_faces = {r['who']: r['face'] for r in a.info['duo_layer']}
        b_faces = {r['who']: r['face'] for r in b.info['duo_layer']}
        self.assertEqual(a_faces, {'zundamon': 'listen:mouth0', 'metan': 'surprise:mouth2'})
        self.assertEqual(b_faces['zundamon'], 'base:mouth0')
        self.assertEqual(c.expression('metan', 'zundamon', '', 0, 3.41), 'base:mouth0:blink')

    def test_original_parts_and_both_directions(self):
        for who in c.PORTRAIT_CAST:
            parts=c.vc._parts(c.NAMES[who], c.PORTRAIT_DIR)
            self.assertTrue(all(k in parts['口'] for k in ('閉','開','大')))
            self.assertEqual(c.source_facing(c.figure(who, side='left')), 'right')
            self.assertEqual(c.source_facing(c.figure(who, side='right')), 'left')
            self.assertEqual(c.bust(who, 'base', 192).tobytes(),
                             c.bust(who, 'base', 192, dim=True).tobytes())
        self.assertEqual(c.vc.FACES['v4_surprise:mouth0'][:2], c.FACE_PARTS['surprise'][:2])

    def test_swapped_cast_uses_actual_side(self):
        im = Image.new('RGB', (1080, 1920))
        c.place_busts(im, 'metan', '', 0, 1, ('metan', 'zundamon'))
        self.assertEqual({r['who']: r['side'] for r in im.info['duo_layer']},
                         {'metan': 'left', 'zundamon': 'right'})


if __name__ == '__main__':unittest.main(argv=[__file__])
