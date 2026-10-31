"""雨衣のみの口調・部品選択と、既定の画素が変わらないことを検査。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import sys
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image
import characters as c
import lipsync
import ui_puppet as puppet
import ui_tone as tone

EXAMPLES = (
    ('大谷翔平が4打数1安打なのよ。', '大谷翔平が4打数1安打です。'),
    ('松井裕樹は1回3分の1だったわ。', '松井裕樹は1回3分の1でした。'),
    ('佐々木朗希は2回1奪三振だわ。', '佐々木朗希は2回1奪三振です。'),
    ('山本由伸が先発だよ。', '山本由伸が先発です。'),
    ('鈴木誠也は2安打だね。', '鈴木誠也は2安打ですね。'),
    ('試合は9時ですよ。', '試合は9時です。'),
    ('明日の予定を見てみよう。', '明日の予定を見てみましょう。'),
    ('今日の勝利貢献順位です。', '今日の勝利貢献順位を見ていきましょう。'),
    ('3勝2敗だったわね。', '3勝2敗でしたね。'),
    ('決勝打に注目してね。', '決勝打に注目しましょう。'),
)


class UiSoloTest(unittest.TestCase):
    def test_outro_delivery_is_polite_only_for_ui(self):
        from review_render_v3 import INSEASON_OUTRO_TEXT as OUTRO_TEXT
        source = dict(segments=[dict(speaker=2, kind='outro', text=OUTRO_TEXT)])
        for host in ('ui', 'metan', ''):
            with self.subTest(host=host), patch.dict(os.environ, COLLESPO_SOLO_HOST=host):
                result = tone.narration(source)
                if host == 'ui':
                    text = result['segments'][0]['text']
                    self.assertIn('明日の試合の見どころをお届けしています', text)
                    self.assertEqual(tone.narration(result), result)
                else:
                    self.assertIs(result, source)
                self.assertEqual(source['segments'][0]['text'], OUTRO_TEXT)

    def test_tone_preserves_facts_quotes_and_is_idempotent(self):
        for before, after in EXAMPLES:
            self.assertEqual(tone.text(before), after)
            self.assertEqual(tone.text(after), after)
        quote = '記者は「3勝なのよ」と伝えた。'
        self.assertEqual(tone.text(quote), quote)
        source = dict(segments=[dict(speaker=2, kind='hero', text='1位、松井裕樹、1回3分の1、ホールド。',
                                    meta=dict(who='四国めたん', count=3, name='松井裕樹'))])
        original = copy.deepcopy(source)
        with patch.dict(os.environ, COLLESPO_SOLO_HOST='ui'):
            adapted = tone.narration(source)
            self.assertEqual(adapted['segments'][0]['text'], source['segments'][0]['text'][:-1]+'です。')
            self.assertEqual(tone.narration(adapted), adapted)
            self.assertEqual(adapted['segments'][0]['meta']['name'], '松井裕樹')
            self.assertEqual(adapted['segments'][0]['meta']['count'], 3)
            self.assertEqual(source, original)
            duo = dict(segments=source['segments']+[dict(speaker=3, text='なのだ。')])
            self.assertIs(tone.narration(duo), duo)
        for selected in ('', 'metan'):
            with patch.dict(os.environ, COLLESPO_SOLO_HOST=selected):
                self.assertIs(tone.narration(source), source)

    def test_amplitude_mouths_silence_laughter_blink_and_gestures(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'signal.wav'
            sr = 24000
            values = np.concatenate([np.sin(np.arange(sr)*.2)*amp for amp in (0, .035, .3, 0)])
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1,2,sr,0,'NONE','not compressed'))
                wav.writeframes((values*32767).astype(np.int16).tobytes())
            levels, origin = lipsync.audio_frames(path)
            self.assertEqual(origin, 'audio-envelope')
            self.assertEqual(set(levels), {0,1,2})
            for level in (0,1,2):
                state = puppet.state('base','札です。',1,1,5,level)
                self.assertIn(f':mouth{level}:', state)
                self.assertIn(':arm指:', state)
            self.assertIn(':arm考え:', puppet.state('question','どうでしょうか？',1,1,5,1))
            self.assertIn(':arm上げ:', puppet.state('pose-smile','大谷が本塁打です。',1,1,5,1,('pose-smile','sparkle','本塁打')))
            self.assertIn(':mouth笑:', puppet.state('smile','ふふ。',1,1,5,1))
            self.assertIn(':mouth0:', puppet.state('smile','ふふ。',1,1,5,1,silent=True))
            self.assertIn(':mouth0:', puppet.state('surprise','',5,5,5,2))
            self.assertIn(':blink1', puppet.state('base','',4.2,4.2,5,0))
            self.assertIn(':blink0', puppet.state('base','',4.5,4.5,5,0))
            self.assertIn(':arm基本:', puppet.state('base','札です。',3.8,3.8,5,1))

    def test_off_and_metan_pixels_match_parent_commit(self):
        root = Path(__file__).resolve().parents[1]
        code = subprocess.check_output(['git','show','55f4e5b1:scripts/characters.py'],cwd=root).decode('utf8')
        old = types.ModuleType('characters_before_ui_solo')
        exec(compile(code,'characters_before_ui_solo','exec'), old.__dict__)
        for host in ('', 'metan'):
            for mode in ('', 'voice'):
                with patch.dict(os.environ,COLLESPO_SOLO_HOST=host,COLLESPO_LIPSYNC=mode), \
                     patch.object(c,'EXPR','fan'),patch.object(old,'EXPR','fan'):
                    for line in ('山本由伸が先発します。','大谷翔平が本塁打。','大谷翔平は無安打。','今日の成績です。'):
                        for elapsed in (0,.2,.8,1.5,3.9):
                            a=Image.new('RGB',(1080,1920)); b=a.copy()
                            old.place_busts(a,'metan',line,elapsed,4,('metan',))
                            c.place_busts(b,'metan',line,elapsed,4,('metan',))
                            self.assertEqual(a.tobytes(),b.tobytes())
                            self.assertEqual(a.info,b.info)

    def test_pending_manifest_and_source_remain_separate(self):
        from prepare_ui_solo import prepare
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,COLLESPO_SOLO_HOST='ui'):
            source=Path(folder)/'source'; out=Path(folder)/'ui'; source.mkdir()
            value=dict(segments=[dict(speaker=2,kind='cover',text='3人なのよ。',meta={})])
            (source/'narration.json').write_text(json.dumps(value),encoding='utf8')
            raw=(source/'narration.json').read_bytes()
            adapted=prepare(source,out)
            self.assertEqual(adapted['segments'][0]['text'],'3人です。')
            self.assertEqual((source/'narration.json').read_bytes(),raw)
            pending=json.loads((out/'audio/manifest.json').read_text(encoding='utf8'))['segments'][0]
            self.assertEqual(pending['voice_host'],'ui')
            self.assertIsNone(pending['file'])
            with self.assertRaises(ValueError): prepare(source,source)

    def test_real_presenter_routes_voice_levels_and_restores_effect_after_cards(self):
        for level in (0,1,2):
            with patch.object(c,'bust',return_value=Image.new('RGBA',(329,250))) as bust, \
                 patch.dict(os.environ,COLLESPO_SOLO_HOST='ui',COLLESPO_LIPSYNC='voice'), \
                 patch.object(lipsync,'at',return_value=level),patch.object(c,'EXPR','fan'):
                im=Image.new('RGB',(1080,1920))
                c.place_busts(im,'ui','山本由伸が先発です。',1.5,6,('ui',))
                self.assertIn(f':mouth{level}:',bust.call_args.args[1])
                # 一覧の描き直しが記号を消した場合にも、雨衣の頭へ復元する。
                clean=Image.new('RGB',im.size)
                with patch.object(c,'fan_effect') as effect:
                    c.redraw(clean,im.info['duo_layer'])
                    effect.assert_called_once()
                    self.assertEqual(effect.call_args.args[1],'sparkle')
                    box=effect.call_args.args[2]
                    self.assertGreater(box[0],im.info['duo_portraits'][0]['box'][0])
                    self.assertLess(box[2],im.info['duo_portraits'][0]['box'][2])

    def test_ps_tone_edition_matches_modified_script(self):
        import ps_program as ps
        from test_ps_program import fixture
        snap, evidence, now=fixture(29)
        # 検証用にソロの定型文を旧語尾にし、変更後の指紋も更新する。
        original=tone.narration
        def adapt(program):
            value=copy.deepcopy(program)
            value['segments'][0]['text']+='先発に注目してね。'
            return original(value)
        with patch.dict(os.environ,COLLESPO_SOLO_HOST='ui',COLLESPO_PS_DESIGN='v3'), \
             patch.object(tone,'narration',side_effect=adapt):
            program=ps.prepare(snap,evidence,'forecast',now)
            self.assertEqual(program['edition_key'],ps.content_key(program))
            self.assertIn('先発に注目しましょう。',program['segments'][0]['text'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
