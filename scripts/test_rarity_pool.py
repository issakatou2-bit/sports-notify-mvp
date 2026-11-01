"""母集団の既定値や取得打ち切りで順位を変えない。"""
import unittest
from unittest.mock import Mock, patch
import rarity


def row(pid, stat, team=None):
    result = {"player": {"id": pid, "fullName": f"Player {pid}"}, "stat": stat}
    if team:
        result["team"] = {"id": team}
    return result


def response(rows, total):
    r = Mock()
    r.json.return_value = {"stats": [{"splits": rows, "totalSplits": total}]}
    return r


class PoolTests(unittest.TestCase):
    def test_all_players_requested_and_pages_joined_before_filtering(self):
        pages = [response([row(1, {"plateAppearances": 299}), row(2, {"plateAppearances": 300})], 3),
                 response([row(3, {"plateAppearances": 400})], 3)]
        with patch.object(rarity.requests, "get", side_effect=pages) as get:
            result = rarity.league("2026", "hitting")
        self.assertEqual([r["player_id"] for r in result], ["2", "3"])
        self.assertEqual([c.kwargs["params"]["offset"] for c in get.call_args_list], [0, 2])
        self.assertTrue(all(c.kwargs["params"]["playerPool"] == "ALL" for c in get.call_args_list))

    def test_transfer_total_selected_after_joining_pages(self):
        total = dict(row(1, {"plateAppearances": 550}), numTeams=2)
        pages = [response([row(1, {"plateAppearances": 310}, 10)], 3),
                 response([total, row(2, {"plateAppearances": 400}, 20)], 3)]
        with patch.object(rarity.requests, "get", side_effect=pages):
            result = rarity.league("2026", "hitting")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["stat"]["plateAppearances"], 550)

    def test_ambiguous_multiple_team_rows_do_not_double_count(self):
        with patch.object(rarity.requests, "get", return_value=response([
                row(1, {"plateAppearances": 350}, 10), row(1, {"plateAppearances": 400}, 20)], 2)):
            self.assertEqual(rarity.league("2026", "hitting"), [])

    def test_partial_or_repeated_pages_do_not_publish_partial_rank(self):
        first = response([row(1, {"inningsPitched": "60.0"})], 2)
        for second in (response([], 2), first):
            with patch.object(rarity.requests, "get", side_effect=[first, second]):
                self.assertEqual(rarity.league("2026", "pitching"), [])

    def test_pitching_threshold_is_outs_not_decimal_float(self):
        rows = [row(1, {"inningsPitched": "59.2"}), row(2, {"inningsPitched": "60.0"})]
        with patch.object(rarity.requests, "get", return_value=response(rows, 2)):
            self.assertEqual([r["player_id"] for r in rarity.league("2026", "pitching")], ["2"])


if __name__ == "__main__":
    unittest.main(argv=[__file__])
