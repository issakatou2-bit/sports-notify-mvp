"""Rest day, stale input and request failure must not become today's results."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import morning_recap as mr
import numbers_material as nm
import recap_freshness as gate


class RecapFreshnessTests(unittest.TestCase):
    def test_no_game_day_blocks_results_but_keeps_independent_comments(self):
        import generate_morning_short as ms
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recap, out, missing = root/'recap.json', root/'narration.json', str(root/'missing.json')
            recap.write_text(json.dumps(dict(date='2026-09-28',date_jst='2026-09-29',players=[],collection_state='no_games')))
            base=['generate_morning_short.py','--recap',str(recap),'--narration-out',str(out)]
            for flag in ('--buzz','--reporters','--postseason','--race','--week','--talk','--voices'):
                base += [flag,missing]
            with mock.patch.object(gate,'current_day',return_value=date(2026,9,29)), contextlib.redirect_stdout(io.StringIO()):
                out.write_text('old narration')
                with mock.patch('sys.argv',base+['--mode','players']):
                    ms.main()
                self.assertFalse(out.exists())
                voices={'voices':[dict(ja='すばらしい活躍だった',likes=i) for i in range(ms.MIN_VOICE_ITEMS)]}
                with mock.patch('sys.argv',base+['--mode','voices']), \
                     mock.patch.object(ms.local_voices,'load',return_value=voices):
                    ms.main()
                self.assertTrue(out.exists())
                narration=json.loads(out.read_text(encoding='utf-8'))
                self.assertTrue(any(s['kind'] not in ('intro','outro') for s in narration['segments']))

    def test_result_date_and_edition_must_match(self):
        data = dict(date='2026-09-28', date_jst='2026-09-29', players=[1])
        self.assertEqual(gate.rejection(data, date(2026, 9, 29)), '')
        self.assertTrue(gate.rejection(data, date(2026, 9, 30)))
        self.assertTrue(gate.rejection({**data, 'date': '2026-09-27'}, date(2026, 9, 29)))
        self.assertTrue(gate.rejection({}, date(2026, 9, 29)))
        for state in ('failed', 'partial_failure'):
            self.assertTrue(gate.rejection({**data, 'collection_state': state}, date(2026, 9, 29)))
        # Explicit edition preserves a legitimate delayed or reviewed backfill.
        self.assertEqual(gate.rejection(data, '2026-09-29'), '')

    def test_off_day_uses_one_request_and_writes_current_empty_material(self):
        response = mock.Mock()
        response.json.return_value = {'totalGames': 0, 'dates': []}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'recap.json'
            out.write_text(json.dumps({'date': '2026-09-27', 'players': ['old']}))
            with mock.patch.object(mr.requests, 'get', return_value=response) as get, \
                 mock.patch('sys.argv', ['morning_recap.py', '--date', '2026-09-28', '--out', str(out)]), \
                 mock.patch.object(mr, 'save_history'), contextlib.redirect_stdout(io.StringIO()):
                mr.main()
            current = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(current['date_jst'], '2026-09-29')
            self.assertEqual(current['players'], [])
            self.assertEqual(current['collection_state'], 'no_games')

    def test_failure_is_written_before_error_without_reusing_old_players(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'recap.json'
            out.write_text(json.dumps({'players': ['old']}))
            with mock.patch.object(mr.requests, 'get', side_effect=RuntimeError('offline')), \
                 mock.patch('sys.argv', ['morning_recap.py', '--date', '2026-09-28', '--out', str(out)]), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    mr.main()
            current = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(current['players'], [])
            self.assertEqual(current['collection_state'], 'failed')

    def test_partial_request_failure_is_distinct_from_no_appearances(self):
        schedule, roster = mock.Mock(), mock.Mock()
        schedule.json.return_value = {'totalGames': 1}
        roster.json.return_value = {'people': [{'fullName': 'Sample', 'id': 1}]}
        with mock.patch.object(mr, 'JP_PLAYERS_MLB', [{'name_en': 'Sample', 'name_jp': '検証選手'}]), \
             mock.patch.object(mr.requests, 'get', side_effect=[schedule, roster]), \
             mock.patch.object(mr, 'fetch_day_pitching', side_effect=RuntimeError('offline')), \
             mock.patch.object(mr, 'fetch_day_hitting', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = mr.build(day='2026-09-28', season='2026')
        self.assertEqual(result['collection_state'], 'partial_failure')
        self.assertEqual(result['collection_errors'], [{'player_id': '1', 'group': 'pitching'}])

    def test_longform_keeps_fresh_results_and_blocks_yesterday_and_wrong_tracking(self):
        row = dict(name='検証選手', type='pitcher', ip='7.0', so=12, er=0, gs=1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recap = dict(date='2026-09-28', date_jst='2026-09-29', players=[row])
            (root/'morning_recap.json').write_text(json.dumps(recap), encoding='utf-8')
            (root/'statcast.json').write_text(json.dumps({'date': '2026-09-27', 'japanese': {'wrong': [1]}}), encoding='utf-8')
            with mock.patch.object(nm.mr, 'score_label', return_value='150'), contextlib.redirect_stdout(io.StringIO()):
                fresh = nm.load(tmp, today=date(2026,9,29))
                stale = nm.load(tmp, today=date(2026,9,30))
            self.assertTrue(nm.has_enough(fresh))
            self.assertEqual(fresh['shots'], [])
            self.assertFalse(nm.has_enough(stale))
            self.assertEqual(stale['players'], [])


if __name__ == '__main__':
    unittest.main()
