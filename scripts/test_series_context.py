"""シリーズの第何戦かを、日付ではなく試合IDで取る（10/28 第5戦が第4戦になった）。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notability_engine as ne


def game(pk, date, number, home, away, final=None):
    teams = {'home': {'team': {'id': home}}, 'away': {'team': {'id': away}}}
    if final:
        teams['home']['score'], teams['away']['score'] = final
    return {'gamePk': pk, 'gameDate': date, 'seriesGameNumber': number, 'gamesInSeries': 7,
            'teams': teams, 'status': {'abstractGameCode': 'F' if final else 'P'}}


class Response:
    def raise_for_status(self):
        pass

    def json(self):
        # 米国 10/27 夜の第4戦は UTC 10/28、10/28 夜の第5戦は UTC 10/29
        return {'dates': [{'games': [game(849803, '2026-10-28T00:00:00Z', 4, 139, 158, (4, 3))]},
                          {'games': [game(849799, '2026-10-29T00:00:00Z', 5, 139, 158)]}]}


class SeriesContext(unittest.TestCase):
    def test_game_number_comes_from_game_id_not_utc_date(self):
        with patch.object(ne.requests, 'get', return_value=Response()):
            context = ne.fetch_series_context('139', '158', '2026-10-28', '849799')
        self.assertEqual(context['series_game_number'], 5)
        self.assertEqual((context['home_wins_in_stretch'], context['away_wins_in_stretch']), (1, 0))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])  # run_checks は一時置場を引数で渡す
