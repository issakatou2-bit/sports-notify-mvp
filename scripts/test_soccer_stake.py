"""欧州の注目試合（懸かっている物）の選び方と言い方。"""
import unittest

import soccer_stake as stake


def row(pos, team, pts, gf=10, ga=10):
    return dict(position=pos, team=team, points=pts, gf=gf, ga=ga, played=10, won=0, draw=0, lost=0)


def table(points):
    return [row(i + 1, f'Team {i + 1} FC', p) for i, p in enumerate(points)]


def game(home, away, code='PL', jp=None):
    return dict(game_id='x', espn_event_id='1', competition_code=code, league='プレミアリーグ',
                start_time_utc='2026-11-21T15:00:00+00:00', start_time_jst='11/22 00:00',
                home_team_name=home, away_team_name=away, jp_by_side=jp or dict(home=[], away=[]), season_players=[])


POINTS = [27, 22, 21, 18, 16, 16, 15, 14, 14, 13, 12, 12, 11, 11, 10, 9, 9, 8, 8, 7]


class StakeTest(unittest.TestCase):
    def comp(self):
        return dict(code='PL', name_jp='プレミアリーグ', table=table(POINTS))

    def test_bottom_pair_is_relegation_fight(self):
        s = stake.stake(game('Team 17 FC', 'Team 20 FC'), self.comp())
        self.assertEqual(s['kind'], '残留争い')
        self.assertEqual(s['gap'], 2)

    def test_far_apart_without_line_is_skipped(self):
        # 1位と11位：差15、どちらも境目から遠い。
        self.assertIsNone(stake.stake(game('Team 1 FC', 'Team 11 FC'), self.comp()))

    def test_line_relation_counts_points_to_the_line(self):
        t = table(POINTS)
        rel = stake.line_relation(t, 'PL', t[8])  # 9位 勝点14、EL圏（5位）は16
        self.assertEqual((rel['label'], rel['gap'], rel['inside']), ('EL圏内', 2, False))
        self.assertEqual(rel['short'], 'EL圏内まで勝点2')

    def test_relegation_line_inside_and_outside(self):
        t = table(POINTS)
        safe = stake.line_relation(t, 'PL', t[16])   # 17位 勝点9、18位は8
        down = stake.line_relation(t, 'PL', t[19])   # 20位 勝点7、17位は9
        self.assertEqual((safe['gap'], safe['inside']), (1, True))
        self.assertEqual((down['gap'], down['inside']), (2, False))

    def test_unavailable_players_are_not_named(self):
        g = game('Team 17 FC', 'Team 20 FC', jp=dict(home=['坂元達裕'], away=['鎌田大地', '冨安健洋']))
        g['season_players'] = [dict(name='冨安健洋', scope='season', out=True, goals=0, assists=0, minutes=189),
                               dict(name='鎌田大地', scope='season', out=False, goals=1, assists=3, minutes=877)]
        names = [p['name'] for p in stake.available_players(g, 'away')]
        self.assertEqual(names, ['鎌田大地'])

    def test_streak_words(self):
        rows = [dict(result=r) for r in 'WLLLL']
        self.assertEqual(stake.streak_words('パレス', rows), 'パレスは4連敗中です。')
        self.assertEqual(stake.streak_words('A', [dict(result=r) for r in 'WLWDW']), '')


if __name__ == '__main__':
    unittest.main()
