"""UTC翌日・日本翌日の境界で、別試合や別日の材料を選ばない。通信しない。"""
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from contextlib import chdir, redirect_stdout
import io
import os
import json
import tempfile
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notability_engine as ne
import next_line
import ps_series
import soccer_sanity_material
import sanity_sources
import numbers_material
import early_views
import healthcheck
import soccer_race
import soccer_slots_v4
import soccer_jp_week
import soccer_results
import buffer_daily
import mlb_availability
import game_hook_guard
from sports_dates import jst_day

JST = timezone(timedelta(hours=9))


def game(pk=849799, official='2026-10-28', utc='2026-10-29T00:00:00Z', n=5):
    row = dict(gamePk=pk, gameType='W', seriesGameNumber=n, gamesInSeries=7,
               gameDate=utc, status=dict(abstractGameState='Preview', abstractGameCode='P'),
               teams=dict(home=dict(team=dict(id=139)), away=dict(team=dict(id=158))))
    if official is not None:
        row['officialDate'] = official
    return row


def context(rows, pk=None, bucket=None):
    response = Mock()
    response.json.return_value = dict(dates=[dict(date=bucket, games=rows)])
    with patch.object(ne.requests, 'get', return_value=response):
        return ne.fetch_series_context('139', '158', '2026-10-28', pk)


class UtcGameDate(unittest.TestCase):
    def test_us_night_fallback_uses_official_day(self):
        previous = game(849803, '2026-10-27', '2026-10-28T00:00:00Z', 4)
        self.assertEqual(context([previous, game()])['series_game_number'], 5)

    def test_schedule_bucket_is_official_day_not_utc_day(self):
        self.assertEqual(context([game(official=None)], bucket='2026-10-28')['series_game_number'], 5)

    def test_doubleheader_date_alone_is_ambiguous(self):
        rows = [game(utc='2026-10-28T22:00:00Z'), game(pk=849800, utc='2026-10-28T23:00:00Z', n=6)]
        self.assertIsNone(context(rows))
        self.assertEqual(context(rows, '849800')['series_game_number'], 6)

    def test_wrong_id_does_not_fall_back_to_date(self):
        self.assertIsNone(context([game()], '999'))

    def test_missing_all_official_dates_does_not_guess_from_utc(self):
        self.assertIsNone(context([game(official=None, utc='2026-10-28T22:00:00Z')]))

    def test_series_missing_official_date_uses_actual_jst_start(self):
        row = ps_series.build([game(official=None)])[0]
        self.assertEqual(row['next'], dict(day='10月29日', game=5))  # JST 9:00

    def test_waiting_opponent_missing_official_date_uses_jst(self):
        g = game(official=None)
        g['teams']['away']['team'] = dict(id=4614, name='AL 3/6 Winner')
        self.assertEqual(ps_series.build([g])[0]['next']['day'], '10月29日')

    def test_tbd_does_not_label_utc_day_as_local(self):
        g = game(official=None)
        g['status']['startTimeTBD'] = True
        say, screen, facts = next_line.when_words(g, [g], datetime(2026, 10, 28, tzinfo=JST))
        self.assertNotIn('現地10月29日', say + screen)
        self.assertIsNone(facts.get('local_date'))

    def test_doubleheader_without_official_day_cannot_pair_different_days(self):
        first = game(1, None, '2026-10-28T23:00:00Z')
        second = game(2, None, '2026-10-30T00:00:00Z')
        first.update(doubleHeader='Y', gameNumber=1)
        second.update(doubleHeader='Y', gameNumber=2)
        second['status']['startTimeTBD'] = True
        self.assertEqual(next_line._effective_start(second, [first, second]), (None, False))


class JapaneseMaterialDate(unittest.TestCase):
    def test_engine_preserves_requested_schedule_date(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'build') as temp, chdir(temp):
            with patch.object(sys, 'argv', ['notability', '--source', 'mlb', '--date', '2026-10-28', '--out', 'games.json']), \
                    patch.object(ne, 'fetch_mlb_games_and_standings', return_value=([], {}, {})), \
                    patch.object(ne, 'load_manual_notes', return_value=[]), patch.dict(os.environ, {}, clear=True), \
                    patch.object(ne, 'build_output', return_value=dict(generated_at='2026-10-29T00:30:00Z', games=[])), redirect_stdout(io.StringIO()):
                ne.main()
            payload = json.loads(Path('games.json').read_text(encoding='utf-8'))
            self.assertEqual(payload.get('schedule_date'), '2026-10-28')
            self.assertEqual(json.loads(Path('archive/2026-10-28.json').read_text(encoding='utf-8')).get('schedule_date'), '2026-10-28')

    def test_availability_updates_requested_archive_not_collection_day(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'build') as temp:
            base = Path(temp)
            payload = dict(schedule_date='2026-10-28', generated_at='2026-10-29T00:30:00Z', games=[dict(game_id='849799')])
            (base/'games.json').write_text(json.dumps(payload), encoding='utf-8')
            for day in ('2026-10-28', '2026-10-29'):
                (base/(day+'.json')).write_text(json.dumps(dict(games=[dict(game_id='849799', keep=day)])), encoding='utf-8')
            with patch.object(sys, 'argv', ['availability', '--games', str(base/'games.json'), '--snapshot', str(base/'snapshot.json'), '--archive-dir', str(base)]), \
                    patch.object(mlb_availability, 'collect', return_value=dict(teams={})), \
                    patch.object(mlb_availability, 'prepare', return_value=[dict(game_id='849799', filtered=True)]), redirect_stdout(io.StringIO()):
                mlb_availability.main()
            self.assertTrue(json.loads((base/'2026-10-28.json').read_text(encoding='utf-8'))['games'][0].get('filtered'))
            self.assertEqual(json.loads((base/'2026-10-29.json').read_text(encoding='utf-8'))['games'][0]['keep'], '2026-10-29')

    def test_hook_guard_archive_day_is_not_collection_timestamp(self):
        self.assertEqual(game_hook_guard._generated_date(dict(schedule_date='2026-10-28', generated_at='2026-10-29T00:30:00Z')), '2026-10-28')

    def test_soccer_utc_evening_belongs_to_next_japanese_day(self):
        material = dict(generated_at='2026-10-28T23:30:00Z', games=[])
        self.assertEqual(soccer_sanity_material.compact(material)['date_jst'], '2026-10-29')
        document = sanity_sources.attach(dict(segments=[]), material, sport='soccer')
        self.assertEqual(document['sanity_date_jst'], '2026-10-29')

    def test_explicit_edition_day_wins_over_collection_day(self):
        material = dict(date_jst='2026-10-27', generated_at='2026-10-28T23:30:00Z')
        self.assertEqual(soccer_sanity_material.compact(material)['date_jst'], '2026-10-27')

    def test_current_numbers_not_rejected_at_japan_midnight(self):
        self.assertTrue(numbers_material.fresh(dict(updated_at='2026-10-28T23:30:00Z'), date(2026, 10, 29), 0))

    def test_asset_publication_grouped_with_japanese_day(self):
        assets = dict(assets=dict(sample=dict(video_id='example', published_at='2026-10-28T23:30:00Z')))
        with patch.object(early_views, 'load', side_effect=[{}, assets]):
            rows = early_views.collect(3650)
        self.assertEqual(rows[0][0], '2026-10-29')

    def test_asset_health_uses_same_japanese_day(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 29, 9, tzinfo=JST).astimezone(tz)
        assets = dict(assets=dict(sample=dict(video_id='example', published_at='2026-10-28T23:30:00Z')))
        with patch.object(healthcheck, 'load', return_value=assets), patch.object(healthcheck, 'datetime', Clock), \
                patch('asset_policy.topic_catalog', return_value=['unused']), patch('asset_policy.paused', return_value=False):
            text, errors = healthcheck.check_assets(max_gap_days=0)
        self.assertEqual(errors, 0, text)
        self.assertIn('0日前', text)

    def test_soccer_ticker_uses_japanese_collection_day(self):
        with patch('host_split.adapt', side_effect=lambda n, k: n):
            plan = soccer_slots_v4.package('preview', dict(generated_at='2026-10-28T23:30:00Z'), [], [], '予告')
        self.assertEqual(plan['narration']['label'], '10月29日（木）')

    def test_race_keeps_current_material_during_japan_morning(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 29, 9, tzinfo=JST).astimezone(tz)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'build') as temp:
            path = Path(temp) / 'preview.json'
            source = dict(generated_at='2026-10-28T23:30:00Z', competitions=[])
            path.write_text(json.dumps(source), encoding='utf-8')
            with patch.object(soccer_race, 'datetime', Clock), patch.object(sys, 'argv', ['soccer_race', '--preview', str(path), '--due']), \
                    patch.object(soccer_race, 'due', return_value=[]), patch.object(soccer_race, 'load_state', return_value={}):
                soccer_race.main()
            self.assertEqual(json.loads(path.with_name('preview_prev.json').read_text(encoding='utf-8')), source)

    def test_offset_is_converted_and_unknown_zone_not_guessed(self):
        self.assertEqual(jst_day('2026-10-28T20:30:00-04:00'), '2026-10-29')
        self.assertEqual(jst_day('2026-10-29'), '2026-10-29')
        self.assertEqual(jst_day('2026-10-28T23:30:00'), '')

    def test_football_data_counts_japanese_start_day(self):
        matches = dict(PL=[dict(utcDate='2026-10-28T20:00:00Z')])
        self.assertEqual(soccer_jp_week.today_count(matches, date(2026, 10, 29)), 1)
        self.assertEqual(soccer_jp_week.today_count(matches, date(2026, 10, 28)), 0)

    def test_football_and_espn_compare_instants_instead_of_calendar_dates(self):
        g = dict(league='PL', home=dict(name_en='Arsenal FC'), away=dict(name_en='Chelsea FC'),
                 start_utc='2026-10-29T05:00:00+09:00', score=dict(home=1, away=0))
        fd = dict(status='FINISHED', utcDate='2026-10-28T20:00:00Z', homeTeam=dict(name='Arsenal FC'),
                  awayTeam=dict(name='Chelsea FC'), score=dict(fullTime=g['score']))
        self.assertEqual(soccer_results.football_check(g, dict(PL=[fd])), 'matched')
        fd['utcDate'] = '2026-10-27T20:00:00Z'
        self.assertEqual(soccer_results.football_check(g, dict(PL=[fd])), 'not_found')

    def test_buffer_expiry_compares_japanese_edition_days(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 29, 8, tzinfo=JST).astimezone(tz)
        key = '2026-10-26:daily:tiktok'
        ledger = buffer_daily.Ledger.__new__(buffer_daily.Ledger)
        ledger.data = dict(deliveries={key: dict(state='error', post_id='example', text='example')})
        ledger.set = lambda k, v: ledger.data['deliveries'].__setitem__(k, v)
        with patch.object(buffer_daily, 'Ledger', return_value=ledger), patch.object(buffer_daily, 'datetime', Clock), \
                patch.object(buffer_daily, 'recent_posts', return_value=[]):
            buffer_daily.reconcile()
        self.assertEqual(ledger.data['deliveries'][key]['state'], 'gave_up')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
