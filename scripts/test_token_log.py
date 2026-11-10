#!/usr/bin/env python3
"""使用量のまとめ：月の枠の数え方（11/10、8/28 の残高から引く計算がずれていた）。"""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import token_log  # noqa: E402


class MonthlyCredit(unittest.TestCase):
    def run_summary(self, days, credit):
        with tempfile.TemporaryDirectory() as tmp:
            u = pathlib.Path(tmp) / 'u.json'
            c = pathlib.Path(tmp) / 'c.json'
            u.write_text(json.dumps({'days': days}), encoding='utf-8')
            c.write_text(json.dumps(credit), encoding='utf-8')
            return token_log.summary(str(u), str(c))

    def test_counts_only_the_current_cycle(self):
        today = datetime.now(token_log.JST).date()
        old = (today - timedelta(days=40)).isoformat()
        days = {old: {'usd': 50.0, 'calls': 1}, today.isoformat(): {'usd': 1.5, 'calls': 1}}
        s = self.run_summary(days, {'monthly_usd': 100, 'cycle_start_day': today.day})
        self.assertEqual(s['cycle_start'], today.isoformat())
        self.assertEqual(s['cycle_spent'], 1.5)
        self.assertNotIn('days_left', s)

    def test_cycle_before_start_day_goes_to_last_month(self):
        today = datetime.now(token_log.JST).date()
        if today.day == 28:
            self.skipTest('28日は前の月へ戻れない')
        s = self.run_summary({today.isoformat(): {'usd': 1.0, 'calls': 1}},
                             {'monthly_usd': 100, 'cycle_start_day': 28 if today.day < 28 else 1})
        self.assertLessEqual(s['cycle_start'], today.isoformat())
        self.assertEqual(s['cycle_spent'], 1.0)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
