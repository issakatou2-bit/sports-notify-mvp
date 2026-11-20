"""欧州の注目試合（懸かっている物）の選び方と言い方。"""
import json
import os
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


def espn_fetch(rows, test=None):
    """ESPN の順位表 JSON を返す偽物。rows は (英語名, 順位, 勝点)。"""
    def fetch(url):
        if test:
            test.assertIn('eng.1', url)
        return {'children': [{'standings': {'entries': [
            dict(team=dict(displayName=name),
                 stats=[dict(name='rank', value=float(pos)), dict(name='points', value=float(pts))])
            for name, pos, pts in rows]}}]}
    return fetch


class CrosscheckTest(unittest.TestCase):
    def doc(self):
        return dict(game=dict(competition_code='PL'),
                    stake=dict(home=dict(team='Home FC', position=17, points=9),
                               away=dict(team='Away FC', position=20, points=7)))

    def lookup(self, name):
        # 実物の club_display_names は登録簿を読むので、名前から id を作る偽物にする。
        return dict(id=name.replace(' FC', ''))

    def test_matching_table_is_accepted(self):
        fetch = espn_fetch([('Home FC', 17, 9), ('Away FC', 20, 7)], self)
        with patch('club_display_names.lookup', side_effect=self.lookup):
            check = stake.crosscheck(self.doc(), fetch)
        self.assertEqual(check['source'], 'ESPN 順位表')
        self.assertEqual((check['clubs']['home']['position'], check['clubs']['home']['points']), (17, 9))
        self.assertEqual((check['clubs']['away']['position'], check['clubs']['away']['points']), (20, 7))

    def test_different_points_stop(self):
        fetch = espn_fetch([('Home FC', 17, 12), ('Away FC', 20, 7)], self)
        with patch('club_display_names.lookup', side_effect=self.lookup):
            with self.assertRaisesRegex(ValueError, '順位表が出どころで違います'):
                stake.crosscheck(self.doc(), fetch)

    def test_club_not_in_espn_table_stops(self):
        fetch = espn_fetch([('Other FC', 1, 30)], self)
        with patch('club_display_names.lookup', side_effect=self.lookup):
            with self.assertRaisesRegex(ValueError, '1つに決められません'):
                stake.crosscheck(self.doc(), fetch)


class PublishedTodayTest(unittest.TestCase):
    def test_same_day_and_other_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'soccer_stake_published.json'
            path.write_text(json.dumps({'1': {'date_jst': '2026-11-21'}}), encoding='utf-8')
            self.assertTrue(stake.published_today('2026-11-21', path))
            self.assertFalse(stake.published_today('2026-11-22', path))

    def test_missing_file_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(stake.published_today('2026-11-21', Path(tmp) / 'none.json'))


class ValidateUploadTest(unittest.TestCase):
    GAME = dict(start_time_utc='2026-11-21T15:00:00+00:00', competition_code='PL',
                game_id='x', espn_event_id='9', home_team_name='Home FC', away_team_name='Away FC')
    NOW = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    ON_TIME = '2026-11-21T10:30:00+00:00'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.narration = self.root / 'narration.json'
        self.games = self.root / 'material.json'
        self.video = self.root / 'video.mp4'
        self.ledger = self.root / 'soccer_stake_published.json'
        self.ledger.write_text('{}', encoding='utf-8')
        (self.root / 'audio').mkdir()
        (self.root / 'audio/voice_manifest.json').write_text('{}', encoding='utf-8')

    def doc(self, *, espn_home_points=9):
        return dict(program='soccer_stake', event_id='9', game=dict(self.GAME),
                    stake=dict(home=dict(position=17, points=9), away=dict(position=20, points=7)),
                    crosscheck=dict(source='ESPN 順位表',
                                    clubs=dict(home=dict(position=17, points=espn_home_points),
                                               away=dict(position=20, points=7))))

    def upload(self, doc, *, publish=True, publish_at=None, ledger=None):
        self.narration.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        self.games.write_text(json.dumps(dict(game=dict(self.GAME)), ensure_ascii=False), encoding='utf-8')
        if ledger is not None:
            self.ledger.write_text(json.dumps(ledger), encoding='utf-8')
        args = types.SimpleNamespace(narration=str(self.narration), games=str(self.games),
                                     publish_at=publish_at or self.ON_TIME, video=str(self.video))
        with patch.object(stake, 'LEDGER', self.ledger), \
                patch.dict(os.environ, {'COLLESPO_STAKE_PUBLISH': 'true'}), \
                patch('short_content.validate_upload', return_value=dict(actual_seconds=40)):
            if not publish:
                os.environ.pop('COLLESPO_STAKE_PUBLISH', None)
            return stake.validate_upload(args, now=self.NOW)

    def test_flag_missing_stops(self):
        with self.assertRaisesRegex(ValueError, 'COLLESPO_STAKE_PUBLISH'):
            self.upload(self.doc(), publish=False)

    def test_crosscheck_mismatch_stops(self):
        with self.assertRaisesRegex(ValueError, '2つ目の出どころ'):
            self.upload(self.doc(espn_home_points=12))

    def test_same_event_in_ledger_stops(self):
        with self.assertRaisesRegex(ValueError, '予約・投稿済み'):
            self.upload(self.doc(), ledger={'9': dict(date_jst='2026-11-21')})

    def test_reservation_after_45_minutes_before_kickoff_stops(self):
        with self.assertRaisesRegex(ValueError, '45分前'):
            self.upload(self.doc(), publish_at='2026-11-21T14:30:00+00:00')

    def test_on_time_reservation_passes(self):
        self.assertIsNone(self.upload(self.doc()))


class MetadataTest(unittest.TestCase):
    def test_description_has_metan_and_espn_source(self):
        doc = dict(title='残留争いは17位と20位で勝点2差 Home対Away #Shorts',
                   screen_title='プレミアリーグ',
                   credit='音声: VOICEVOX:ずんだもん・四国めたん　出典: football-data.org・ESPN 順位表',
                   source_url='https://www.espn.com/soccer/match/_/gameId/9',
                   segments=[dict(kind='list', text='順位は17位で、勝点は9です。', speaker=stake.METAN),
                             dict(kind='list', text='何が懸かっているのだ？', speaker='ずんだもん')])
        snippet = stake.metadata(doc)['snippet']
        self.assertEqual(snippet['title'], doc['title'])
        self.assertIn('順位は17位で、勝点は9です。', snippet['description'])
        self.assertIn('ESPN 順位表', snippet['description'])


if __name__ == '__main__':
    unittest.main()
