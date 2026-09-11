"""Public player pages must not reverse scores or claim player appearances."""
import unittest

from generate_player_pages import render_game, render_index, render_player_page


class PlayerPageTest(unittest.TestCase):
    def game(self, away=6, home=8, winner="home"):
        return {
            "away_team_name": "カブス", "home_team_name": "ブリュワーズ",
            "matchup": "カブス vs ブリュワーズ", "away_has_jp": True,
            "final_score": {"away": away, "home": home, "winner": winner},
        }

    def test_scores_stay_with_their_teams_for_both_winners(self):
        for away, home, side, winner in ((6, 8, "home", "ブリュワーズ"), (8, 6, "away", "カブス")):
            with self.subTest(side=side):
                page = render_game("2026-09-09", self.game(away, home, side))
                self.assertIn(f"カブス {away} - {home} ブリュワーズ　{winner}勝利", page)

    def test_no_away_win_is_invented_for_ties_or_unknown_winners(self):
        page = render_game("2026-09-09", self.game(2, 2, None))
        self.assertIn("同点", page)
        self.assertNotIn("勝利", page)
        page = render_game("2026-09-09", self.game(6, 8, None))
        self.assertIn("カブス 6 - 8 ブリュワーズ", page)
        self.assertNotIn("勝利", page)

    def test_incomplete_scores_do_not_look_like_finished_results(self):
        page = render_game("2026-09-09", self.game(None, 8))
        self.assertNotIn('class="result"', page)
        self.assertNotIn("None", page)

    def test_team_watchlist_is_not_an_appearance_record(self):
        games = [("2026-09-09", self.game())]
        for page in (render_player_page("今永昇太", games), render_index({"今永昇太": games})):
            self.assertIn("所属チームの注目試合", page)
            self.assertIn("登板・出場実績の一覧ではありません", page)
            self.assertNotIn("出場した注目試合", page)
        self.assertIn("掲載日: 2026-09-09", render_player_page("今永昇太", games))


if __name__ == "__main__":
    unittest.main(argv=["test_player_pages"])
