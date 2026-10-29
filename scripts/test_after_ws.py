"""10/30・11/3を含むWS終了後の乾式試験。通信・音声・公開なし。"""
import copy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ps_offseason as off
import ps_editorial as editorial
import ps_game_now as watch
import ps_daily_entry as daily
import ps_program as program
import generate_ps_preview as preview
import next_asset
import recap_freshness
import numbers_material
import generated_topics
import ws_topics
import healthcheck
import send_onesignal
import postseason
import ps_series


# 球団・勝敗は保存済み10/29のpostseason.jsonと同じ形。
# gamePk・個々の時刻は判定を再現するための合成値（実日程の証明ではない）。
def fixture():
    games = []
    for n in range(1, 8):
        final = n <= 5
        games.append(dict(gamePk=9000+n, gameType='W', season='2026',
            officialDate=f'2026-10-{23+n:02d}', gameDate=f'2026-10-{23+n:02d}T23:00:00Z',
            seriesGameNumber=n, gamesInSeries=7,
            status=dict(abstractGameState='Final' if final else 'Preview', startTimeTBD=False),
            teams=dict(home=dict(team=dict(id=158, name='Milwaukee Brewers'), isWinner=final and n != 2),
                       away=dict(team=dict(id=139, name='Tampa Bay Rays'), isWinner=final and n == 2))))
    import ps_series
    rows = ps_series.build(games)
    snapshot = dict(date='2026-10-29', season='2026', phase='postseason', series=rows,
                    teams={}, japanese=[], ws_finished_on='2026-10-29')
    return snapshot, dict(dates=[dict(games=games)])


class AfterWS(unittest.TestCase):
    def test_whole_requested_interval_and_season_boundaries(self):
        snapshot, _ = fixture()
        for offset in range(11):
            self.assertTrue(off.completed_before(snapshot, date(2026, 10, 30)+timedelta(days=offset)))
        self.assertFalse(off.completed_before(snapshot, date(2026, 10, 29)))
        self.assertFalse(off.completed_before(snapshot, date(2027, 10, 30)))
        snapshot['series'][-1]['over'] = False
        self.assertFalse(off.completed_before(snapshot, date(2026, 10, 30)))

    def test_missing_or_unconfirmed_winner_is_not_offseason(self):
        snapshot, _ = fixture()
        for change in ({'winner': None}, {'need': 0}, {'played': 7}, {'best_of': 0}):
            other = copy.deepcopy(snapshot)
            other['series'][-1].update(change)
            self.assertFalse(off.completed_before(other, date(2026, 11, 3)))
        for wins, played in ((4, 8), (None, 5), (-1, 3)):
            other = copy.deepcopy(snapshot)
            other['series'][-1]['teams'][1]['wins'] = wins
            other['series'][-1]['played'] = played
            self.assertFalse(off.completed_before(other, date(2026, 11, 3)))
        self.assertFalse(off.completed_before({}, date(2026, 11, 3)))

    def test_official_shape_marks_editorial_and_both_programs_offseason(self):
        for day in ('2026-10-30', '2026-11-03'):
            now = datetime.fromisoformat(day+'T07:00:00+00:00')
            snapshot, schedule = fixture()
            snapshot['date'] = day  # 取得日だけ新しくても、最後の試合日は変わらない。
            self.assertEqual(off.finished_on(schedule['dates'][0]['games'], snapshot['series']), '2026-10-29')
            ctx = editorial.editorial(snapshot, schedule, now, 'fixture://statsapi')
            self.assertEqual(ctx['stage'], 'offseason')
            for slot in ('forecast', 'situation'):
                ev = dict(retrieved_at=now.isoformat(), source_url='fixture://statsapi', schedule=schedule)
                self.assertIsNone(program.prepare(snapshot, ev, slot, now))

    def test_refresh_keeps_decisive_game_day_in_saved_snapshot(self):
        for day in ('2026-10-30', '2026-11-03'):
            now = datetime.fromisoformat(day+'T07:00:00+00:00')
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now.astimezone(tz)
            _, schedule = fixture()
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/'postseason.json'
                with patch.object(postseason, 'datetime', Clock), patch.object(postseason, 'fetch', return_value=[{}]), patch.object(postseason, 'race', return_value={}), patch.object(postseason, 'japanese', return_value=[]), patch.object(postseason, 'flat', return_value={}), patch.object(ps_series, 'season_dates', return_value=dict(start='2026-09-28', end='2026-11-15')), patch.object(ps_series, 'fetch', return_value=schedule['dates'][0]['games']), patch.object(sys, 'argv', ['postseason', '--out', str(target)]):
                    self.assertEqual(postseason.main(), 0)
                saved = json.loads(target.read_text(encoding='utf-8'))
                self.assertEqual(saved['date'], day)
                self.assertEqual(saved['ws_finished_on'], '2026-10-29')
                self.assertTrue(off.completed_before(saved, day))
                self.assertEqual(saved['changes'], [])

    def test_entry_points_skip_green_without_network_or_rendering(self):
        for day in ('2026-10-30', '2026-11-03'):
            now = datetime.fromisoformat(day+'T07:00:00+00:00')
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now.astimezone(tz) if tz else now.replace(tzinfo=None)
            snapshot, _ = fixture()
            with tempfile.TemporaryDirectory() as folder:
                previous = Path.cwd()
                try:
                    os.chdir(folder)
                    Path('data').mkdir(); Path('build').mkdir(); Path('public').mkdir()
                    Path('data/postseason.json').write_text(json.dumps(snapshot), encoding='utf-8')
                    with patch.object(editorial, 'datetime', Clock), patch.object(editorial, 'fetch', side_effect=AssertionError('network')), patch.object(sys, 'argv', ['ps_editorial']):
                        self.assertIsNone(editorial.main())
                    for layout in ('v2', 'legacy'):
                        with patch.dict(os.environ, PS_PROGRAM_LAYOUT=layout), patch.object(daily, 'datetime', Clock), patch.object(sys, 'argv', ['daily', '--stage', 'narration']):
                            self.assertIsNone(daily.main())
                            self.assertEqual(json.loads(daily.STATUS.read_text())['state'], 'skipped')
                        for stage in ('video', 'thumbnail', 'cover', 'upload'):
                            with patch.object(sys, 'argv', ['daily', '--stage', stage]), patch.object(daily.subprocess, 'call', side_effect=AssertionError('production')):
                                self.assertIsNone(daily.main())
                        Path('build/old.json').write_text('{}')
                        with patch.object(preview, 'datetime', Clock), patch.object(sys, 'argv', ['preview', '--mode', 'postseason', '--narration-out', 'build/old.json']), patch.object(preview.subprocess, 'call', side_effect=AssertionError('production')):
                            self.assertIsNone(preview.main())
                            self.assertFalse(Path('build/old.json').exists())
                    for flag, code in (('--watch', 1), ('--due', 0)):
                        with patch.object(watch, 'datetime', Clock), patch.object(watch, 'schedule', side_effect=AssertionError('network')), patch.object(sys, 'argv', ['watch', flag]):
                            self.assertEqual(watch.main(), code)  # workflowはwatchの1を見送り・緑へ変換する。
                    with patch.object(next_asset, 'datetime', Clock):
                        self.assertTrue(next_asset.superseded(dict(game=True, game_pk=9005)))
                finally:
                    os.chdir(previous)

    def test_empty_schedule_cancelled_games_and_stale_or_future_topics(self):
        for day in ('2026-10-30', '2026-11-03'):
            now = datetime.fromisoformat(day+'T07:00:00+00:00')
            with patch('requests.get') as get:
                get.return_value.json.return_value = dict(totalGames=0, dates=[])
                self.assertEqual(watch.schedule(now), [])
            for status in (dict(abstractGameState='Final'), dict(codedGameState='C'), dict(codedGameState='D'), dict(detailedState='Cancelled')):
                self.assertFalse(watch.games_ahead([dict(gameType='W', gameDate=now.isoformat(), status=status)], now))
            old = dict(key='season_game_old', game=True, finished_at='2026-10-29T03:00:00Z')
            future = dict(old, finished_at=(now+timedelta(minutes=10)).isoformat())
            with patch.object(next_asset, 'superseded', return_value=False):
                self.assertEqual(watch.due([old, future], set(), now, 4), [])
            self.assertFalse(watch.waiting([old, future], set(), now))

    def test_old_results_and_empty_longform_do_not_become_today(self):
        old = dict(date='2026-10-28', date_jst='2026-10-29', players=[dict(name='古い選手')])
        for day in (date(2026, 10, 30), date(2026, 11, 3)):
            self.assertEqual(recap_freshness.read_for_edition(old, day), {})
            with patch.object(numbers_material, '_read', return_value={}):
                self.assertFalse(numbers_material.has_enough(numbers_material.load('fixture', today=day)))
            snapshot, _ = fixture()
            snapshot.update(date=day.isoformat(), changes=[dict(key='W:139-158', text='以前の優勝')])
            with patch.object(numbers_material, '_read', side_effect=lambda p: snapshot if Path(p).name == 'postseason.json' else {}):
                material = numbers_material.load('fixture', today=day)
                self.assertFalse(numbers_material.has_enough(material))
                self.assertEqual(material['race']['series'], [])

    def test_asset_material_drops_daily_ps_but_keeps_retrospectives(self):
        for day in ('2026-10-30', '2026-11-03'):
            now = datetime.fromisoformat(day+'T07:00:00+00:00')
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now.astimezone(tz)
            snapshot, schedule = fixture()
            previous = Path.cwd()
            with tempfile.TemporaryDirectory() as folder:
                try:
                    os.chdir(folder); Path('data').mkdir()
                    Path('data/postseason.json').write_text(json.dumps(snapshot), encoding='utf-8')
                    sources = [*generated_topics.DAILY_PS_SOURCES, 'ps_story_topics.json', 'season_topics.json']
                    for name in sources:
                        Path('data', name).write_text(json.dumps(dict(topics=[dict(key=name)])), encoding='utf-8')
                    with patch.object(generated_topics, '_CACHE', None), patch.object(generated_topics, 'datetime', Clock):
                        got = generated_topics.all_topics(['data/'+n for n in sources], refresh=True)
                        self.assertEqual(set(got), {'ps_story_topics.json', 'season_topics.json'})
                    # 終了の確認後に歴史・今後の日程を取りに行かない。
                    with patch.object(ws_topics, 'ws_games', return_value=schedule['dates'][0]['games']), patch.object(ws_topics, 'all_teams', side_effect=AssertionError('unnecessary fetch')):
                        self.assertEqual(ws_topics.build_topics(2026), [])
                finally:
                    os.chdir(previous)

    def test_no_games_are_not_missing_publications_or_failed_notifications(self):
        for day in ('2026-10-30', '2026-11-03'):
            with patch.object(healthcheck, '_mlb_games', return_value=0), patch.object(healthcheck, 'load', return_value={}), patch('soccer_preview_assessment.assessment', return_value=('skip', 0, '対象試合なし')):
                lines, missing, skipped, _ = healthcheck.check_videos(day)
                self.assertEqual(missing, 0)
                self.assertGreater(skipped, 0)
                self.assertTrue(all('見送り' in line for line in lines))
                _, stale = healthcheck.check_data(day)
                self.assertEqual(stale, 0)
            with patch.object(send_onesignal.requests, 'post', side_effect=AssertionError('notification')):
                self.assertTrue(send_onesignal.send_one('', '', 'mlb', [], 'MLB'))


if __name__ == '__main__':
    unittest.main(argv=['test_after_ws'])
