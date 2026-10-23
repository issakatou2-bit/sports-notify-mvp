"""大会の形式の言い切り（総当たりなど）を、AIの要約から弾く（10/21 CLを総当たりと誤って書いた）。"""
import sys
import unittest
from unittest.mock import patch
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

    def test_repeated_format_claim_is_dropped_after_retry(self):
        game = dict(league='CL', matchup='試験カード', is_notable=True, reasons=['固定の材料'])
        output = dict(generated_at='2026-10-21T00:00:00Z', games=[game])
        with patch.object(ne, '_call_ai', return_value=('全クラブと対戦する総当たり戦。', 0, 0, 0, False)) as call, \
             patch.object(ne, '_build_ai_prompt', return_value='固定の試験'), \
             patch.object(ne, 'collect_log_notes', return_value=[]), \
             patch.object(ne, 'host_reversed', return_value=[]):
            ne.enhance_games_with_ai(output, {}, 'fixture')
        self.assertEqual(call.call_count, 2)
        self.assertNotIn('ai_summary', game)
        self.assertEqual(output['ai_status']['succeeded'], 0)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
