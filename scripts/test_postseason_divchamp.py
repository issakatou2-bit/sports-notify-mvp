#!/usr/bin/env python3
"""地区優勝の印（postseason.fetch の div_champ）は、地区1位のときだけ。APIは使わない。

2026年の公式の順位表は、地区2位・6ゲーム差のフィリーズ（ワイルドカード）にも
divisionChamp: true を付けていた。そのままだと「地区優勝」と言ってしまう。
"""
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import postseason as ps  # noqa: E402

API = {"records": [{"league": {"id": 104}, "division": {"id": 204}, "teamRecords": [
    {"team": {"id": 144, "name": "Atlanta Braves"}, "wins": 94, "losses": 68, "divisionRank": "1",
     "divisionChamp": True, "clinched": True, "leagueRecord": {"pct": ".580"}},
    {"team": {"id": 143, "name": "Philadelphia Phillies"}, "wins": 88, "losses": 74, "divisionRank": "2",
     "divisionChamp": True, "clinched": True, "gamesBack": "6.0", "leagueRecord": {"pct": ".543"}},
]}]}


class DivisionChampion(unittest.TestCase):
    def test_only_first_place_is_division_champion(self):
        with patch.object(ps, "_get", return_value=API):
            rows = {r["id"]: r for r in ps.fetch("2026")}
        self.assertTrue(rows[144]["div_champ"])
        self.assertFalse(rows[143]["div_champ"])
        self.assertTrue(rows[143]["clinched"])        # 進出は決まっている


if __name__ == "__main__":
    unittest.main(argv=["test_postseason_divchamp"])
