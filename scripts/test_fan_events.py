import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import characters as c
import fan_events as f
import review_render_v3 as r3
import sound_mix


class FanTest(unittest.TestCase):
    def tearDown(self):
        f.TRACK.clear();r3.set_program_clock(None);c.EXPR=''

    def test_facts_override_words_and_pitcher_hits(self):
        with patch.dict(os.environ,COLLESPO_EXPR='fan'):
            p=dict(name='山本由伸',type='pitcher',hits=0,ip='7.0',er=1,wins=1,losses=0,so=10)
            self.assertEqual(f.decision('山本由伸は無安打だった。',dict(players=[p]))['face'],'pose-smile')
            p.update(wins=0,losses=1)
            self.assertEqual(f.decision('山本由伸が好投した。',dict(players=[p]))['face'],'sad')
            p=dict(name='大谷翔平',type='batter',ab=4,hits=0,hr=0)
            self.assertEqual(f.decision('大谷は勝ちました。',dict(players=[p]))['face'],'sad')

    def test_fallback_and_cue_and_number_window(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,COLLESPO_EXPR='fan'):
            c.EXPR='fan'
            f.prepare({},[dict(text='山本由伸が先発します。')],[4],td)
            r3.set_program_clock(.5)
            self.assertEqual(c.fan_mood('山本由伸が先発します。')[:2],('smile','sparkle'))
            f.prepare(dict(players=[dict(name='大谷翔平',type='batter',hr=2)]),
                      [dict(text='大谷翔平が2本塁打。',duration=4)],[4.7],td)
            self.assertEqual(len(f.event_cues()),1)
            r3.set_program_clock(2.1)
            self.assertTrue(f.number_focus('2'))
            r3.set_program_clock(.1)
            self.assertFalse(f.number_focus('2'))
            self.assertIn('evidence',json.loads(Path(td,'fan-confirmation.json').read_text(encoding='utf-8'))['segments'][0]['decision'])

    def test_sound_below_voice(self):
        sr=sound_mix.SR
        voice=np.sin(np.arange(sr)*2*np.pi*220/sr)*.15
        out=sound_mix.mix(voice,cues=[(.2,'impact','a',-24)])
        effect=out[:,0]-voice
        ratio=np.sqrt(np.mean(effect**2))/np.sqrt(np.mean(voice**2))
        self.assertLess(20*np.log10(max(ratio,1e-12)),-18)
        window=sr//20
        local=[20*np.log10(max(np.sqrt(np.mean(effect[i:i+window]**2)),1e-12)/
                          np.sqrt(np.mean(voice[i:i+window]**2))) for i in range(0,sr-window,window)]
        self.assertLess(max(local),-12)
        self.assertLess(np.max(np.abs(out)),.95)

    def test_ps_probable_fact_and_thirty_fps(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,COLLESPO_EXPR='fan'):
            c.EXPR='fan'
            program=dict(segments=[dict(meta=dict(card=dict(home_pitcher=dict(id=808967,display='山本由伸'))))])
            f.prepare(program,[dict(text='山本の一戦です。')],[3.37],td,fps=30)
            r3.set_program_clock(.5)
            self.assertEqual(c.fan_mood('山本の一戦です。')[:2],('smile','sparkle'))
            self.assertAlmostEqual(f.TRACK[0]['end'],101/30)

    def test_disabled_pixels(self):
        root=Path(__file__).resolve().parents[1]
        original=subprocess.check_output(['git','show','11035100:scripts/characters.py'],cwd=root).decode('utf-8')
        old=types.ModuleType('original');exec(compile(original,'original','exec'),old.__dict__)
        with patch.dict(os.environ,COLLESPO_EXPR=''):
            c.EXPR='';old.EXPR=''
            for text in ('山本由伸が10奪三振。','大谷翔平が2本塁打。','今日の成績です。'):
                for t in (.1,.5,1.7):
                    a=Image.new('RGB',(1080,1920));b=a.copy()
                    old.place_busts(a,'metan',text,t,4);old.bubble(a,'metan',text)
                    c.place_busts(b,'metan',text,t,4);c.bubble(b,'metan',text)
                    self.assertEqual(a.tobytes(),b.tobytes())


if __name__=='__main__':unittest.main(argv=[__file__])
