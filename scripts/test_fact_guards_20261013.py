"""Saved failure patterns: numbered translations, benching, quotes, cached summaries and venues."""
import copy
from datetime import datetime, timezone
import io
from pathlib import Path
import sys
import unittest
from unittest import mock
import contextlib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import local_reporters as lr
import ps_quotes as pq
import notability_engine as ne

EN = 'After beating Tarik Skubal, the next challenge for Brewers hitters comes quick: Yoshinobu Yamamoto.'
JP = 'スクーバルを攻略した打線、次は山本由伸。'
NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
def post(jp=JP, text=EN, uri='at://fixture/post/a', at='2026-10-12T14:51:26Z'):
    return dict(uri=uri, text=text, jp=jp, at=at, author='fixture', likes=3)

class TranslationTests(unittest.TestCase):
    def test_batch_labels_are_not_a_translation(self):
        for text in ['1番', '８番', '3.', '2', '7番。']:
            with self.subTest(text=text):
                self.assertEqual(lr.guard_translation(EN, text), '')
    def test_real_short_number_and_rank_keep_their_meaning(self):
        self.assertEqual(lr.guard_translation('No. 1!', '1番'), '1番')
        self.assertEqual(lr.guard_translation(EN, '山本は先発3番手。'), '山本は先発3番手。')
    def test_benching_is_removal_not_inclusion(self):
        source = 'As Shohei Ohtani struggles, Dodgers will discuss benching superstar in Game 3'
        self.assertEqual(lr.guard_translation(source, '大谷の第3戦でのベンチ入りを協議へ'), '大谷の第3戦で先発から外すことを協議へ')
    def test_correct_benching_translation_stays_identical(self):
        self.assertEqual(lr.guard_translation('They discuss benching Ohtani.', '大谷を先発から外すことを検討'), '大谷を先発から外すことを検討')
    def translation_call(self, bodies, allowed=True):
        from types import SimpleNamespace
        import backstage_guard, token_log, llm_models
        messages = [SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=x)]) for x in bodies]
        fake = SimpleNamespace(Anthropic=lambda **kwargs: object())
        with mock.patch.dict(sys.modules, {'anthropic': fake}), \
                mock.patch.object(backstage_guard, 'create', side_effect=messages) as create, \
                mock.patch.object(token_log, 'allowed', side_effect=allowed if isinstance(allowed, list) else None, return_value=allowed), \
                mock.patch.object(token_log, 'record'), \
                mock.patch.object(llm_models, 'params', return_value={}):
            result = lr.translate([{'text': EN}], 'fixture')
        return result[0], create.call_count
    def test_placeholder_retries_only_once_and_recovers(self):
        row, calls = self.translation_call(['1. 1番', '1. '+JP])
        self.assertEqual(row['jp'], JP)
        self.assertFalse(row.get('_translation_failed'))
        self.assertEqual(calls, 2)
    def test_persistent_placeholder_is_flagged_without_unbounded_retry(self):
        row, calls = self.translation_call(['1. 1番', '1. 1番'])
        self.assertEqual(row['jp'], '')
        self.assertTrue(row['_translation_failed'])
        self.assertEqual(calls, 2)
    def test_good_translation_has_only_one_model_call(self):
        row, calls = self.translation_call(['1. '+JP])
        self.assertEqual(row['jp'], JP)
        self.assertEqual(calls, 1)
    def test_retry_does_not_exceed_budget(self):
        row, calls = self.translation_call(['1. 1番'], allowed=[True, False])
        self.assertEqual(row['jp'], '')
        self.assertTrue(row['_translation_failed'])
        self.assertEqual(calls, 1)
    def test_failed_retry_keeps_translation_ineligible(self):
        row, calls = self.translation_call(['1. 1番', ''])
        self.assertEqual(row['jp'], '')
        self.assertTrue(row['_translation_failed'])
        self.assertEqual(calls, 2)
    def test_bench_registration_without_benching_is_not_rewritten(self):
        self.assertEqual(lr.guard_translation('Ohtani returns to the active roster.', '大谷がベンチ入り'), '大谷がベンチ入り')
    def test_unstated_handedness_is_not_invented(self):
        source = 'They rely on their number 3 starter, a two-time Cy Young winner with a 1.90 ERA.'
        self.assertEqual(lr.guard_translation(source, 'サイ・ヤング賞2度の右腕に頼る'), 'サイ・ヤング賞2度の投手に頼る')
    def test_explicit_handedness_is_kept(self):
        for source, jp in [('The LHP starter returns.', '左腕が戻る'), ('Their starter throws left.', '左腕が戻る'), ('Their starting pitcher is a southpaw.', '左腕が戻る'), ('Their right-handed pitcher starts.', '右腕が先発')]:
            self.assertEqual(lr.guard_translation(source, jp), jp)

class HistoryTests(unittest.TestCase):
    def test_new_translation_repairs_same_uri(self):
        old, fresh = post('1番'), post()
        result = pq.merge([old], [fresh], NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['jp'], JP)
        self.assertEqual(old['jp'], '1番')
    def test_orphan_label_is_ineligible_but_raw_source_survives(self):
        result = pq.merge([post('1番')], [], NOW)
        self.assertEqual(result[0]['jp'], '')
        self.assertEqual(result[0]['text'], EN)
        self.assertEqual(result[0]['uri'], 'at://fixture/post/a')
    def test_invalid_new_translation_cannot_replace_good_history(self):
        result = pq.merge([post()], [post('1番')], NOW)
        self.assertEqual(result[0]['jp'], JP)
    def test_same_uri_different_source_cannot_replace_history(self):
        result = pq.merge([post()], [post('別の話', text='different source')], NOW)
        self.assertEqual(result[0]['jp'], JP)
        self.assertEqual(result[0]['text'], EN)
    def test_different_uris_are_preserved_and_old_records_expire(self):
        result = pq.merge([post(at='2026-09-01T00:00:00Z')], [post(uri='at://fixture/post/b')], NOW)
        self.assertEqual([x['uri'] for x in result], ['at://fixture/post/b'])
    def test_invalid_placeholder_in_new_record_is_not_eligible(self):
        result = pq.merge([], [post('4番')], NOW)
        self.assertEqual(result[0]['jp'], '')

CL = {'league': 'チャンピオンズリーグ', 'home_team_id': 'CL-78', 'away_team_id': 'CL-66',
      'home_team_name': 'アトレティコ・マドリード', 'away_team_name': 'マンチェスター・ユナイテッド',
      'matchup': 'マンチェスター・ユナイテッド vs アトレティコ・マドリード',
      'game_type': 'R', 'is_notable': True, 'reasons': [{'text': 'CLリーグフェーズ'}]}
BAD = 'グループステージの総当たり戦を勝ち抜く一戦である。'
GOOD = 'アトレティコ・マドリードがホームでマンチェスター・ユナイテッドを迎える。'

class CompetitionTests(unittest.TestCase):
    def test_explicit_home_at_opponent_venue_is_detected(self):
        import soccer_venue
        game = dict(CL, home_team_name='アーセナル', away_team_name='リール')
        self.assertTrue(soccer_venue.check('アーセナルが敵地リールを迎える。', game))
        self.assertEqual(soccer_venue.check('アーセナルがホームでリールを迎える。', game), [])
        self.assertEqual(soccer_venue.check('リールが敵地アーセナルに乗り込む。', game), [])
        self.assertEqual(soccer_venue.check('アーセナルが敵地のリールを迎える。', game), [])
    def test_both_teams_cannot_meet_at_an_away_venue(self):
        import soccer_venue
        self.assertTrue(soccer_venue.check('両強豪が敵地で激突する。', CL))
        self.assertEqual(soccer_venue.check('両チームの敵地での成績を比較する。', CL), [])
    def generation(self, responses, old_summary=None):
        game = copy.deepcopy(CL)
        if old_summary:
            game.update(ai_summary=old_summary, notification_hook='old hook')
        with mock.patch.object(ne, 'collect_log_notes', return_value=[]), \
                mock.patch.object(ne, '_build_ai_prompt', return_value='fixed preview'), \
                mock.patch.object(ne, '_call_ai', side_effect=[(x, 0, 0, 0, False) for x in responses]) as call:
            ne.enhance_games_with_ai({'games': [game], 'generated_at': '2026-10-13'}, {}, 'fixture')
        return game, call.call_count
    def test_wrong_output_is_rewritten_once(self):
        game, calls = self.generation([BAD, GOOD])
        self.assertEqual(game['ai_summary'], GOOD)
        self.assertEqual(calls, 2)
    def test_retry_failure_clears_cached_bad_summary_and_hook(self):
        game, calls = self.generation([BAD, BAD], BAD)
        self.assertNotIn('ai_summary', game)
        self.assertNotIn('notification_hook', game)
        self.assertEqual(calls, 2)
    def test_good_output_does_not_add_api_calls(self):
        game, calls = self.generation([GOOD])
        self.assertEqual(game['ai_summary'], GOOD)
        self.assertEqual(calls, 1)

if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main(argv=[sys.argv[0]])
