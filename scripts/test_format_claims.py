"""大会の形式の言い切り（総当たりなど）を、AIの要約から弾く（10/21 CLを総当たりと誤って書いた）。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import notability_engine as ne  # noqa: E402


class FormatClaims(unittest.TestCase):
    def test_format_claims_are_rejected_for_soccer(self):
        for text in ('チャンピオンズリーグは1部リーグの全チームが参加する総当たり戦であり、',
                     'リーグフェーズは8試合を戦う。',
                     '全クラブと対戦する方式。'):
            self.assertTrue(ne.forbidden_wording(text, True), text)

    def test_ordinary_preview_passes(self):
        self.assertEqual(ne.forbidden_wording('リバプールが敵地でブライトンと戦う一戦。', True), [])

    def test_saved_games_have_no_format_claims(self):
        games = json.loads((ROOT / 'data/soccer_games.json').read_text(encoding='utf-8'))['games']
        for game in games:
            if ne.is_soccer_league(game.get('league')):
                self.assertFalse(ne.FORMAT_CLAIM.search(game.get('ai_summary') or ''), game.get('matchup'))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
