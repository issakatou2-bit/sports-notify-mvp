"""Regression checks for team ownership, IL-safe selection and matching covers."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from daily_focus import affiliated_team_hook, cover_metadata
from render_shorts_cover import render_cover


def game(home='ドジャース', away='カブス', **overrides):
    return dict({'game_id': '1', 'league': 'MLB', 'is_notable': True,
                 'home_team_name': home, 'away_team_name': away,
                 'home_has_jp': True, 'away_has_jp': False,
                 'start_time_jst': '09/21 08:10', 'reasons': []}, **overrides)


class DailyFocusTests(unittest.TestCase):
    def test_narration_prefers_affiliated_team_without_bypassing_il_gate(self):
        import generate_narration as gn
        g = game(jp_players=['大谷翔平'], jp_starters=[{'name': '大谷翔平'}],
                 reasons=[{'tag': 'streak', 'text': 'ドジャースは6連勝中'}])
        with patch.object(gn, '_recent_returns', return_value={}):
            hook = gn.pick_hook([g], availability={})
        self.assertEqual(hook['sub'], 'ドジャース')
        self.assertEqual(hook['big'], '6連勝中')
        self.assertNotIn('大谷', str(hook))

    def test_affiliated_club_beats_other_club_magic_without_promoting_player(self):
        games = [game('アストロズ', 'ブレーブス', home_has_jp=False,
                      reasons=[{'tag': 'ps_magic', 'text': 'アストロズは地区優勝マジック4'}]),
                 game(jp_players=[], jp_starters=[])]
        hook = affiliated_team_hook(games)
        self.assertEqual((hook['at'], hook['sub'], hook['big']), (1, 'ドジャース', 'カブスと対戦'))
        self.assertNotIn('出場', str(hook))
        self.assertNotIn('復帰', str(hook))

    def test_opponent_magic_does_not_become_selected_teams_magic(self):
        hook = affiliated_team_hook([game(reasons=[{'tag': 'ps_magic', 'text': 'カブスは地区優勝マジック4'}])])
        self.assertNotIn('マジック', hook['big'])

    def test_actual_club_fact_wins_over_generic_affiliation(self):
        games = [game(), game('パドレス', 'メッツ', game_id='2',
                             reasons=[{'tag': 'streak', 'text': 'パドレスは6連勝中'}])]
        original = deepcopy(games)
        hook = affiliated_team_hook(games)
        self.assertEqual(hook['at'], 1)
        self.assertEqual(hook['big'], '6連勝中')
        self.assertEqual(games, original)

    def test_missing_affiliation_is_not_guessed_from_famous_team(self):
        self.assertIsNone(affiliated_team_hook([game(home_has_jp=None)]))
        self.assertIsNone(affiliated_team_hook([game(league='プレミアリーグ')]))

    def test_cover_uses_hook_index_and_actual_date(self):
        games = [game(), game('パドレス', 'メッツ', game_id='2', start_time_jst='09/22 11:10',
                             reasons=[{'tag': 'streak', 'text': 'パドレスは6連勝中'}])]
        meta = cover_metadata(games, affiliated_team_hook(games))
        self.assertEqual(meta['time'], '9/22 11:10 日本時間')
        self.assertEqual(meta['matchup'], 'vs メッツ')
        self.assertEqual(meta['title'], 'パドレス、6連勝中｜9/22の注目試合【MLB】')

    def test_invalid_and_stale_references_are_rejected(self):
        games = [game()]
        hook = affiliated_team_hook(games)
        for change in ({'at': -1}, {'at': True}, {'at': 3}, {'game_id': 'wrong'}, {'team': 'メッツ'}):
            with self.assertRaises(ValueError):
                cover_metadata(games, {**hook, **change})

    def test_upload_title_uses_same_second_game_as_cover(self):
        import upload_youtube as uy
        games = [game(), game('パドレス', 'メッツ', game_id='2', start_time_jst='09/22 11:10',
                             reasons=[{'tag': 'streak', 'text': 'パドレスは6連勝中'}])]
        hook = affiliated_team_hook(games)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g = root / 'games.json'
            n = root / 'narration.json'
            g.write_text(json.dumps({'games': games}), encoding='utf-8')
            n.write_text(json.dumps({'segments': [{'kind': 'intro', 'meta': {'hook': hook}}]}),
                         encoding='utf-8')
            body = uy.build_metadata(str(g), '09/21', narration_path=str(n))
        self.assertEqual(body['snippet']['title'], cover_metadata(games, hook)['title'])
        self.assertIn('パドレス 6連勝中', body['snippet']['description'])

    def test_render_magic_streak_and_matchup_are_vertical_and_readable(self):
        for fact in ('地区優勝マジック4', '地区優勝マジック12', '6連勝中', 'ホワイトソックスと対戦'):
            meta = cover_metadata([game()], {'at': 0, 'sub': 'ドジャース', 'big': fact})
            self.assertEqual(render_cover(meta).size, (1080, 1920))
        with self.assertRaises(ValueError):
            render_cover({**meta, 'subject': '長い選手名' * 20})

    def test_cli_rejects_previous_day_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g = game()
            (root / 'g.json').write_text(json.dumps({'games': [g]}), encoding='utf-8')
            (root / 'n.json').write_text(json.dumps({'date_label': '09/20', 'segments': [
                {'kind': 'intro', 'meta': {'hook': affiliated_team_hook([g])}}]}), encoding='utf-8')
            p = subprocess.run([sys.executable, str(Path(__file__).with_name('render_shorts_cover.py')),
                                '--games', str(root / 'g.json'), '--narration', str(root / 'n.json'),
                                '--out', str(root / 'out.png')], capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse((root / 'out.png').exists())
            (root / 'n.json').write_text(json.dumps({'date_label': '09/21', 'segments': [
                {'kind': 'intro', 'meta': {'hook': affiliated_team_hook([g])}}]}), encoding='utf-8')
            p = subprocess.run([sys.executable, str(Path(__file__).with_name('render_shorts_cover.py')),
                                '--games', str(root / 'g.json'), '--narration', str(root / 'n.json'),
                                '--out', str(root / 'out.png')], capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue((root / 'out.png').exists())
            self.assertIn('9/21', json.loads((root / 'out.json').read_text(encoding='utf-8'))['title'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
