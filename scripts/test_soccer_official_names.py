"""公式照合42人の表記ずれと、漢字→題・画面・読みの取り違えを検出する。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import notability_engine as ne
import name_reading_guard as readings
import soccer_results as results
import soccer_results_render as render
import soccer_voices as voices
import test_soccer_results as fixtures


class OfficialNames(unittest.TestCase):
    def test_entire_roster_matches_official_audit_and_dictionaries(self):
        audit=json.loads((ROOT/'data/soccer_player_names.json').read_text(encoding='utf8'))
        saved=json.loads((ROOT/'data/player_kana.json').read_text(encoding='utf8'))
        expected={p['name_en']:p for p in audit['players']}
        actual={p['name_en']:p for p in ne.JP_PLAYERS_SOCCER}
        self.assertEqual(set(expected),set(actual))
        self.assertEqual(len(expected),42)
        voice_names={p['name_en']:p['name_jp'] for p in voices.load_names()}
        for name,p in expected.items():
            with self.subTest(name=name):
                self.assertEqual(p['status'],'confirmed')
                self.assertTrue(p['source'].startswith('https://'))
                self.assertEqual(actual[name]['name_jp'],p['name_jp'])
                self.assertEqual(saved['reading_aliases'][name],p['name_jp'])
                self.assertEqual(voice_names[name],p['name_jp'])
                self.assertEqual(readings.player_reading(name),p['reading'])

    def test_zion_remains_zion_and_hirakawa_is_not_rei(self):
        self.assertEqual(readings.player_reading('鈴木彩艶'),'スズキザイオン')
        self.assertEqual(readings.player_reading('鈴木ザイオン'),'スズキザイオン')
        self.assertEqual(readings.player_reading('Yu Hirakawa'),'ヒラカワユウ')
        self.assertEqual(readings.player_reading('平川怜'),'ヒラカワレイ')
        zion=next(p for p in voices.load_names() if p['name_en']=='Zion Suzuki')
        self.assertEqual(voices.names_in('Zion saved us again',[zion]),['鈴木彩艶'])
        self.assertEqual(voices.names_in('鈴木ザイオンがセーブ',[zion]),['鈴木彩艶'])
        yu=next(p for p in voices.load_names() if p['name_en']=='Yu Hirakawa')
        self.assertFalse(voices.names_in('平川怜が出場',[yu]))

    def test_saved_api_to_official_title_description_narration_and_screen(self):
        data=fixtures.fixed('2026-09-19')
        person=next(p for p in data['players'] if p['name_en']=='Zion Suzuki')
        self.assertEqual(person['name'],'鈴木彩艶')
        # 本人を主役に選ぶ以外、出場区分・得点・試合結果は保存APIの実値。
        data=copy.deepcopy(data)
        data['players']=[person]
        data.pop('preview_followup',None)
        self.assertIn('鈴木彩艶',results.title(data))
        self.assertIn('鈴木彩艶','\n'.join(results.description_lines(data)))
        narr=render.narration(data)
        self.assertIn('鈴木彩艶',''.join(s['text'] for s in narr['segments']))
        for look in ('v4','v5','v6'):
            shown=[]
            with self.subTest(look=look),patch.object(render.r3,'LOOK','v4'),patch.dict(os.environ,COLLESPO_SOCCER_LOOK=look,COLLESPO_SHORT_LOOK='v4'):
                for seg in narr['segments']:
                    im=render.frame(3,seg,data)
                    shown.extend(str(r.get('text','')) for r in im.info.get('v3_layout',[]))
            self.assertIn('鈴木彩艶',''.join(shown))
            self.assertNotIn('鈴木ザイオン',''.join(shown))


if __name__=='__main__':unittest.main(argv=['test_soccer_official_names'])
