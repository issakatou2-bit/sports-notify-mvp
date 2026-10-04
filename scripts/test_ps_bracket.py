"""シードと確定勝者の関係を固定材料で検査。APIや当日のJSONに依存しない。"""
import copy
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ps_bracket as p

SEEDS = {103: [139, 114, 117, 147, 111, 145], 104: [158, 119, 144, 135, 112, 143]}


def series(rnd, a, b, aw, bw):
    winner = a if aw == p.NEED[rnd] else b if bw == p.NEED[rnd] else None
    return {"round": rnd, "played": aw+bw, "over": winner is not None, "winner": winner,
            "teams": [{"id": a, "wins": aw, "players": ["所属選手"]},
                      {"id": b, "wins": bw, "players": []}]}


def fixture():
    teams = {str(t): {"name": str(t), "league": league, "seed": seed, "clinched": True}
             for league, ids in SEEDS.items() for seed, t in enumerate(ids, 1)}
    return {"phase": "postseason", "season": "2026", "date": "2026-10-04",
            "updated_at": "2026-10-04T06:00:00Z", "teams": teams,
            "series": [series("F", 147, 111, 2, 0), series("F", 117, 145, 0, 2),
                       series("F", 135, 112, 2, 0), series("F", 144, 143, 2, 1)]}


class Bracket(unittest.TestCase):
    def test_ds_matchups_follow_seeds_and_wc_winners(self):
        m = p.build(fixture())
        self.assertEqual([[t["id"] for t in s["teams"]] for l in m["leagues"] for s in l["ds"]],
                         [[139, 147], [114, 145], [158, 135], [119, 144]])
        self.assertTrue(all(t["id"] is None for l in m["leagues"] for t in l["lcs"]["teams"]))

    def test_wc_lead_is_not_advancement(self):
        d = fixture()
        d["series"][0] = series("F", 147, 111, 1, 0)
        ds = p.build(d)["leagues"][0]["ds"][0]
        self.assertIsNone(ds["teams"][1]["id"])
        self.assertIsNone(ds["teams"][1]["wins"])

    def test_ds_leads_are_only_conditional_lcs(self):
        d = fixture()
        d["series"] += [series("D", 139, 147, 1, 0), series("D", 114, 145, 0, 1),
                        series("D", 158, 135, 1, 0), series("D", 119, 144, 1, 0)]
        m = p.build(d)
        self.assertFalse(m["conditional_lcs"][0]["confirmed"])
        self.assertEqual([t["id"] for t in m["conditional_lcs"][0]["teams"]], [139, 145])
        self.assertTrue(all(t["id"] is None for l in m["leagues"] for t in l["lcs"]["teams"]))

    def test_tie_has_no_conditional_leader(self):
        d = fixture()
        d["series"].append(series("D", 139, 147, 2, 2))
        self.assertIsNone(p.build(d)["conditional_lcs"][0]["teams"][0])

    def test_full_progression_through_ws_final(self):
        d = fixture()
        d["series"] += [series("D", 139, 147, 3, 0), series("D", 114, 145, 0, 3),
                        series("D", 158, 135, 3, 2), series("D", 119, 144, 3, 1),
                        series("L", 139, 145, 1, 4), series("L", 158, 119, 2, 4),
                        series("W", 145, 119, 4, 3)]
        m = p.build(d)
        self.assertEqual([t["id"] for t in m["ws"]["teams"]], [145, 119])
        self.assertTrue(m["ws"]["over"])
        self.assertEqual(m["ws"]["winner"], 145)

    def test_inconsistent_winner_wins_or_played_stops(self):
        d = fixture()
        for changes in ({"winner": 111}, {"over": False}, {"played": 3}):
            bad = copy.deepcopy(d)
            bad["series"][0].update(changes)
            with self.assertRaises(ValueError):
                p.build(bad)

    def test_wrong_ds_opponent_does_not_silently_disappear(self):
        d = fixture()
        d["series"].append(series("D", 139, 111, 1, 0))
        with self.assertRaises(ValueError):
            p.build(d)

    def test_duplicate_unclinched_or_missing_seed_stops(self):
        for update in ({"seed": 1}, {"clinched": False}, {"seed": None}):
            d = fixture()
            d["teams"]["147"].update(update)
            with self.assertRaises(ValueError):
                p.build(d)

    def test_outside_postseason_has_no_bracket(self):
        self.assertIsNone(p.build(dict(fixture(), phase="regular")))

    def test_render_text_stays_outside_sns_controls(self):
        import ps_bracket_render as render
        m = p.build(fixture())
        for i in (0, 1):
            prepared = render.prepare(m, i)
            for row in prepared["trace"]:
                x, y, right, bottom = row["box"]
                self.assertGreaterEqual(x, 72)
                self.assertGreaterEqual(y, 140)
                self.assertLessEqual(right, 940)
                self.assertLessEqual(bottom, 1574)
            self.assertEqual(render.frame(prepared, 1.2).size, (1080, 1920))


if __name__ == "__main__":
    unittest.main(argv=["test_ps_bracket"])
