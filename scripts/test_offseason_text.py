"""保存済みの試合日・試合ゼロ日で定型文と通常期の完全一致を確認。通信なし。"""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import offseason_text as ot
import post_common as pc

ROOT = Path(__file__).resolve().parents[1]
SAVED = json.loads((ROOT / 'scripts/fixtures/offseason-outro/saved.json').read_text(encoding='utf-8'))


def original(name):
    return subprocess.check_output(['git', 'show', '465fcf1b:scripts/' + name], cwd=ROOT).decode('utf-8-sig')


def old_module(name):
    module = types.ModuleType('old_' + name)
    module.__file__ = str(ROOT / 'scripts' / (name + '.py'))
    exec(compile(original(name + '.py'), module.__file__, 'exec'), module.__dict__)
    return module


class OffseasonText(unittest.TestCase):
    def test_saved_days_and_failed_decisions(self):
        self.assertEqual(SAVED['no_games']['game_count'], 0)
        self.assertGreater(SAVED['game_day']['game_count'], 0)
        raw = '\n'.join(ot.REPLACEMENTS)
        self.assertNotEqual(ot.seasonal(raw, SAVED['offseason'], '2026-10-30'), raw)
        for ps, day in ((SAVED['active'], '2026-10-07'),
                        (SAVED['offseason'], SAVED['game_day']['date_jst']),
                        ({}, '2026-10-30'), ([], '2026-10-30'),
                        ({'series': [None]}, '2026-10-30'),
                        (SAVED['offseason'], '2027-03-01'),
                        (SAVED['offseason'], 'invalid')):
            self.assertEqual(ot.seasonal(raw, ps, day), raw)
        with patch.object(pc, '_postseason_now', side_effect=OSError):
            self.assertEqual(ot.seasonal(raw), raw)

    def test_site_inseason_and_missing_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('index.html', 'terms.html', 'football-competitions.html'):
                data = (ROOT / 'web' / name).read_bytes()
                (Path(tmp) / name).write_bytes(data)
            before = {p.name: p.read_bytes() for p in Path(tmp).iterdir()}
            for ps in (SAVED['active'], {}):
                self.assertEqual(ot.render_site(tmp, ps, '2026-10-07'), [])
                self.assertEqual({p.name: p.read_bytes() for p in Path(tmp).iterdir()}, before)
            self.assertEqual(set(ot.render_site(tmp, SAVED['offseason'], '2026-10-30')), set(before))
            home = (Path(tmp) / 'index.html').read_text(encoding='utf-8')
            self.assertNotIn('ポストシーズンへの距離', home)
            self.assertIn('MLBのシーズン成績', home)
            self.assertIn('試合のある日に', home)
            self.assertEqual(ot.render_site(tmp, SAVED['offseason'], '2026-10-30'), [])

    def test_guide_copy_and_politeness(self):
        # 原画面定義を読んで比較し、import時点に依存させない。
        tree = ast.parse(original('generate_asset_video.py'))
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'LIST_TOPICS' for t in n.targets))
        guide_node = next(v for k, v in zip(node.value.keys, node.value.values)
                          if isinstance(k, ast.Constant) and k.value == 'collespo_guide')
        spec = ast.literal_eval(guide_node)
        self.assertIs(ot.guide(spec, SAVED['active'], '2026-10-07'), spec)
        off = ot.guide(spec, SAVED['offseason'], '2026-10-30')
        self.assertEqual(spec['hook'], '毎日19時に届きます')
        self.assertEqual(off['hook'], '試合のある日に届きます')
        self.assertIn('試合のある日に19時にお届けする', off['intro'])
        self.assertEqual(off['items'][1:], spec['items'][1:])
        import ui_tone
        for text in (off['intro'], ot.seasonal('毎日午後七時に、その日の注目試合をお届けしています。', SAVED['offseason'], '2026-10-30')):
            self.assertEqual(ui_tone.text(ui_tone.text(text)), ui_tone.text(text))

    def test_inseason_metadata_all_static_topics_and_playlists_match_origin(self):
        # 元コミットを同じ保存材料・同じ設定で実行。文字列だけでなく返り値全体を比較。
        with patch.object(pc, '_postseason_now', return_value=SAVED['active']), patch.object(pc, 'mlb_offseason', return_value=False):
            import upload_youtube as yt
            import playlists
            import generate_asset_video as av
            old_yt = old_module('upload_youtube')
            old_yt.DAILY_LINEUP_LINES = yt.DAILY_LINEUP_LINES
            old_av = old_module('generate_asset_video')
            for topic in old_yt.ASSET_META:
                self.assertEqual(yt.build_asset_metadata(topic), old_yt.build_asset_metadata(topic), topic)
            self.assertEqual(av._outro_segment(), old_av._outro_segment())
            for kind, text in playlists.PLAYLISTS.items():
                self.assertEqual(playlists.playlist_text(kind), text, kind)

    def test_offseason_metadata_and_remaining_slots(self):
        with patch.object(pc, '_postseason_now', return_value=SAVED['offseason']):
            import upload_youtube as yt
            import playlists
            meta = yt.build_asset_metadata('collespo_guide')['snippet']
            self.assertNotIn('毎日19時', meta['title'] + meta['description'])
            self.assertNotIn('・明日の注目試合', meta['description'])
            self.assertNotIn('・日本人選手の成績', meta['description'])
            for name in ('ファンのコメント欄', '現地の報道', '欧州サッカー'):
                self.assertIn(name, meta['description'])
            for kind in ('morning', 'daily', 'morning_local'):
                title, desc = playlists.playlist_text(kind)
                self.assertNotIn('毎日', title + desc)
            for kind in ('morning_press', 'morning_voices', 'daily_soccer'):
                self.assertEqual(playlists.playlist_text(kind), playlists.PLAYLISTS[kind])

    def test_standings_switch_preserves_rows_and_uses_archive(self):
        from test_standings_page import fixture
        import generate_standings_page as standings
        from datetime import datetime
        # 既存の表の検査材料を使い、順位の数値を一切変更しない。
        page = standings.render_page(fixture(), 2026, datetime.fromisoformat('2026-10-30T19:00:00+09:00'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'standings.html'
            path.write_text(page, encoding='utf-8')
            ot.render_site(tmp, SAVED['offseason'], '2026-10-30')
            off = path.read_text(encoding='utf-8')
        import re
        self.assertEqual(re.findall(r'<table.*?</table>', page, re.S), re.findall(r'<table.*?</table>', off, re.S))
        self.assertIn('href="archive/">過去の注目試合', off)
        self.assertNotIn('ワイルドカード争い', off)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
