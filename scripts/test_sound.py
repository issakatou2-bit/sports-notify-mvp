#!/usr/bin/env python3
"""効果音（sfx.py）・BGMの重ね合わせ（sound_mix.py）・新デザインの効果音の時刻（review_render_v3.cues）。"""
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import review_render_v3 as r3  # noqa: E402
import sfx  # noqa: E402
import sound_mix as sm  # noqa: E402

SPEC = {"team_id": 145, "abbr": "CWS", "v3": {
    "big": "4", "tag": "4試合すべて敵地",
    "chips": [{"label": "WCS第1戦", "score": "6-3", "win": True}, {"label": "WCS第2戦", "score": "7-3", "win": True}]}}


class Effects(unittest.TestCase):
    def test_every_effect_is_short_and_in_range(self):
        for kind in sfx.KINDS:
            for v in ("a", "b"):
                y = sfx.make(kind, v)
                self.assertTrue(np.all(np.isfinite(y)), kind)
                self.assertLessEqual(np.max(np.abs(y)), 1.0, kind)
                self.assertLess(len(y) / sfx.SR, 2.0, kind)
                self.assertGreater(np.max(np.abs(y)), 0.1, kind)


class Mixing(unittest.TestCase):
    def test_bgm_is_quieter_under_the_voice(self):
        sr = sm.SR
        voice = np.zeros(sr * 4)
        t = np.arange(sr) / sr
        voice[sr:2 * sr] = 0.3 * np.sin(2 * np.pi * 220 * t)       # 1〜2秒だけ声
        bgm = 0.5 * np.sin(2 * np.pi * 110 * np.arange(sr) / sr)     # 1秒のループ
        g = sm.duck_gain(voice)
        self.assertLess(g[int(1.6 * sr)], g[int(0.5 * sr)])          # 声の間は下がる
        y = sm.mix(voice, bgm=bgm, fade=0.1)
        self.assertEqual(y.shape, (len(voice), 2))
        self.assertLessEqual(np.max(np.abs(y)), 0.95 + 1e-9)
        # BGM は声よりずっと小さい（声の無い所で比べる）
        quiet = np.sqrt(np.mean(y[: int(0.8 * sr), 0] ** 2))
        loud = np.sqrt(np.mean(voice[sr:2 * sr] ** 2))
        self.assertLess(quiet, loud / 5)

    def test_cues_are_placed_and_cut_at_the_end(self):
        track = np.zeros(sfx.SR)
        sfx.place(track, np.ones(100), 0.5)
        sfx.place(track, np.ones(sfx.SR), 0.9)                       # はみ出たぶんは切る
        self.assertEqual(track[int(0.5 * sfx.SR)], 1)
        self.assertEqual(len(track), sfx.SR)


class Timing(unittest.TestCase):
    def test_intro_cues_follow_the_drawing(self):
        c = r3.cues("intro", SPEC)
        kinds = [k for _, k, _, _ in c]
        self.assertIn("roll", kinds)
        self.assertIn("stop", kinds)
        self.assertEqual(kinds.count("pop"), 2)                      # 勝った札ごとに○
        stop = next(t for t, k, _, _ in c if k == "stop")
        self.assertAlmostEqual(stop, r3.T_ROLL[1] - 0.04)

    def test_list_cues_one_per_card(self):
        items = [("A", "1"), ("ハイライトのコメント欄から", "「すごい」"), ("C", "3")]
        c = r3.cues("list", SPEC, items, 0, 2)
        self.assertEqual([k for _, k, _, _ in c], ["transition", "swish", "notify"])


class Drawing(unittest.TestCase):
    def test_frames_are_full_size(self):
        spec = {**SPEC, "label": "ホワイトソックスの4連勝", "heading": "ホワイトソックス",
                "items": [("このポストシーズン", "4勝0敗"), ("次の試合", "日本時間10月8日5時")]}
        spec["v3"] = {**spec["v3"], "ticker": "次の試合　日本時間10月8日5時"}
        self.assertEqual(r3.intro(2.0, spec, "PSの話題").size, (1080, 1920))
        self.assertEqual(r3.list_page(1.0, spec, spec["items"], 0, 2, 1, 1, "PSの話題").size, (1080, 1920))

    def test_dark_ground_for_every_team(self):
        import notability_engine as ne
        for tid in ne.MLB_TEAM_COLOR:
            base, second, _ = r3.colors(tid)
            self.assertLessEqual(r3._lum(base), 0.16, tid)


if __name__ == "__main__":
    unittest.main(argv=["test_sound"])
