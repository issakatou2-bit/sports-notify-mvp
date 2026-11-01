"""10/11保存ログの誤判定と、独立した枠・見送り・公開一覧の回帰検査。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock

import sanity
import sanity_material
import healthcheck as hc
import channel_feeds as cf
import ps_program

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / 'scripts/fixtures/fact-guards/evening_20261011.json').read_text(encoding='utf-8'))


class EveningFixTests(unittest.TestCase):
    def setUp(self):
        offline = patch('sanity_refresh.fetch', side_effect=RuntimeError('offline fixture'))
        offline.start()
        self.addCleanup(offline.stop)
        retry = patch('sanity_recheck.ai_review', return_value=([], dict(status='offline fixture', calls=0)))
        retry.start()
        self.addCleanup(retry.stop)

    def test_today_high_is_unconfirmed_and_game_mismatch_is_confirmed(self):
        document = json.loads((ROOT / 'scripts/fixtures/fact-guards/evening_20261012.json').read_text(encoding='utf-8'))
        reviewed, errors = sanity_material.assess(document['llm_issues'], [document])
        self.assertEqual(len(reviewed), 3)
        self.assertEqual(errors, [])
        self.assertFalse(any(i['confirmed'] for i in reviewed))
        document['segments'][2]['text'] = document['segments'][2]['text'].replace('第2戦', '第3戦')
        self.assertIn('試合番号', ' '.join(sanity_material.check(document)))

    def test_ps_render_narration_argument_does_not_rewrite_script(self):
        import generate_ps_preview as entry
        with patch.object(sys, 'argv', ['generate_ps_preview.py', '--mode', 'postseason', '--narration', 'saved.json', '--audio-dir', 'audio']), \
             patch.object(entry.Path, 'exists', return_value=False), \
             patch.object(ps_program, 'desired', return_value=True), \
             patch.object(ps_program, 'layout', return_value='v2'), \
             patch.object(ps_program, 'read', return_value={'saved': True}), \
             patch.object(ps_program, 'movie') as movie, \
             patch.object(ps_program, 'prepare', side_effect=AssertionError('原稿を再生成しない')):
            entry.main()
        movie.assert_called_once_with({'saved': True}, 'audio', 'build/morning')

    def test_workflow_checks_movie_before_reporting_upload(self):
        workflow = (ROOT / '.github/workflows/morning_recap.yml').read_text(encoding='utf-8')
        self.assertLess(workflow.index('if [ ! -s "$VIDEO" ]'), workflow.index('echo "$mode: 投稿しました'))

    def test_saved_high_false_positives_remain_unconfirmed(self):
        reviewed, errors = sanity_material.assess(FIXTURE['llm_issues'], [FIXTURE])
        self.assertEqual(errors, [])
        self.assertEqual([item['confirmed'] for item in reviewed], [False, False])
        self.assertEqual([item['severity'] for item in reviewed], ['high', 'high'])

    def test_real_series_contradiction_stops(self):
        document = copy.deepcopy(FIXTURE)
        document['segments'][0]['text'] = document['segments'][0]['text'].replace('2勝3敗', '3勝2敗')
        self.assertIn('シリーズ勝敗', ' '.join(sanity_material.check(document)))

    def test_actual_date_and_hour_contradictions(self):
        for old, new, index in [('明日9時', '明日10時', 2), ('明日9時', '今日9時', 2),
                                ('10月12日9時', '10月13日9時', 1)]:
            document = copy.deepcopy(FIXTURE)
            document['segments'][index]['text'] = document['segments'][index]['text'].replace(old, new)
            self.assertIn('日本時間', ' '.join(sanity_material.check(document)))

    def test_strict_cli_stops_only_with_material_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            narration, result = Path(folder) / 'narration.json', Path(folder) / 'sanity.json'
            for mismatched, expected in [(False, 0), (True, 1)]:
                document = copy.deepcopy(FIXTURE)
                if mismatched:
                    document['segments'][0]['text'] = document['segments'][0]['text'].replace('2勝3敗', '3勝2敗')
                narration.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
                args = ['sanity.py', '--general', '--strict', '--narration', str(narration), '--out', str(result)]
                issues = copy.deepcopy(FIXTURE['llm_issues'])
                if mismatched:
                    issues[0]['where'] = issues[0]['where'].replace('2勝3敗', '3勝2敗')
                with patch.object(sys, 'argv', args), patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'TEST'}), \
                     patch.object(sanity, 'general', return_value=issues), \
                     patch.object(sanity, 'check_scores', return_value=[]), \
                     patch.object(sanity, 'check_stat_files', return_value=[]):
                    self.assertEqual(sanity.main(), expected)
                report = json.loads(result.read_text(encoding='utf-8'))
                self.assertEqual(bool(report['contradictions']), mismatched)
                self.assertEqual(bool(report['blocking_issues']), mismatched)
                self.assertFalse(any(i['supported'] for i in report['blocking_issues']))

    def test_no_movie_skips_before_upload_and_records_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'no-movie.mp4'
            with patch.object(ps_program, 'check_program', side_effect=AssertionError('制作なしでは呼ばない')):
                ps_program.upload(dict(kind='morning_postseason', date_jst='2026-10-11'), ['--video', str(video)])
            record = json.loads((video.parent / 'ps_program_upload_skip.json').read_text(encoding='utf-8'))
            self.assertEqual(record['status'], 'skipped')
            self.assertTrue(record['reason'])

    def test_missing_movie_records_current_sanity_stop_reason(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                Path('data').mkdir()
                Path('data/sanity_postseason.json').write_text(json.dumps({
                    'date_jst': '2026-10-11', 'contradictions': ['勝敗が材料と不一致']}), encoding='utf-8')
                ps_program.upload(dict(kind='morning_postseason', date_jst='2026-10-11'), ['--video', 'build/missing.mp4'])
                record = json.loads(Path('build/ps_program_upload_skip.json').read_text(encoding='utf-8'))
                self.assertIn('勝敗が材料と不一致', record['reason'])
            finally:
                os.chdir(previous)

    def _soccer_check(self, games, stamp='2026-10-11T09:54:03+00:00'):
        games=[dict(g,game_id=str(i)) for i,g in enumerate(games)] if isinstance(games,list) else games
        def load(path):
            return {'games': games, 'generated_at': stamp, 'preview_selection':dict(day='2026-10-11', count=len(games or []), selected_ids=[str(i) for i in range(len(games or []))], reason='注目度がしきい値以上の試合なし')} if path == 'data/soccer_games.json' else {}
        with patch.object(hc, 'load', side_effect=load), patch.object(hc, 'EXPECTED_DAILY', []):
            return hc.check_videos('2026-10-11')

    def test_soccer_non_japanese_selected_fixtures_are_required(self):
        lines, missing, skipped, _ = self._soccer_check([{'is_notable': True, 'home_has_jp': False}]*17)
        self.assertEqual((missing, skipped), (1, 0))
        self.assertIn('出ていない', ' '.join(lines))
        self.assertIn('注目試合', ' '.join(lines))

    def test_soccer_eligible_game_missing_is_still_failure(self):
        _, missing, skipped, _ = self._soccer_check([{'is_notable': True, 'away_has_jp': True}])
        self.assertEqual((missing, skipped), (1, 0))

    def test_old_or_missing_soccer_material_is_not_skip(self):
        for games, stamp in [(None, ''), ([], '2026-10-10T09:00:00+00:00')]:
            _, missing, skipped, _ = self._soccer_check(games, stamp)
            self.assertEqual((missing, skipped), (1, 0))

    def test_no_mlb_games_does_not_count_unchanged_material(self):
        with patch.object(hc, '_mlb_games', return_value=0), patch.object(hc, 'load', return_value={}):
            lines, stale = hc.check_data('2026-10-11')
        self.assertEqual(stale, 0)
        self.assertTrue(all('見送り' in line for line in lines))
        with patch.object(hc, '_mlb_games', return_value=None), patch.object(hc, 'load', return_value=None):
            _, stale = hc.check_data('2026-10-11')
        self.assertEqual(stale, len(hc.DATA_FILES))

    def test_publication_ids_use_api_and_jst_without_rss(self):
        with patch.dict(os.environ, {'YOUTUBE_API_KEY': 'TEST'}), \
             patch.object(cf, 'fetch_uploads', return_value=[{'video_id': 'same-day', 'published_at': '2026-10-10T15:01:00Z'},
                                                          {'video_id': 'previous', 'published_at': '2026-10-10T14:59:00Z'}]) as fetch, \
             patch('urllib.request.urlopen', side_effect=AssertionError('RSSは呼ばない')):
            self.assertEqual(hc.published_ids('2026-10-11'), {'same-day'})
            self.assertTrue(fetch.call_args.kwargs['strict'])

    def test_api_failure_is_unknown_not_zero(self):
        with patch.dict(os.environ, {'YOUTUBE_API_KEY': 'TEST'}), \
             patch.object(cf, 'fetch_uploads', side_effect=RuntimeError('failed')):
            self.assertIsNone(hc.published_ids('2026-10-11'))

    def test_review_board_uses_same_skip_and_record_key(self):
        import review_board
        with patch.object(review_board, '_load', return_value={
                'morning_postseason': {'2026-10-11': {'title': 'PSの題'}}}), \
             patch.object(hc, 'check_videos', return_value=(['| 19:30 | サッカー | 見送り | 日本人の注目試合なし |'], 0, 1, set())) as check:
            result = review_board.gather('2026-10-11')
        check.assert_called_once_with('2026-10-11')
        self.assertIn('見送り', result)
        self.assertIn('PSの題', result)
        self.assertNotIn('出ていない', result)

    def test_api_reads_next_page_and_video_publication_time(self):
        now = datetime.now(timezone.utc)
        def item(vid, at):
            return {'snippet': {'title': vid, 'publishedAt': '2000-01-01T00:00:00Z', 'resourceId': {'videoId': vid}},
                    'contentDetails': {'videoPublishedAt': at.isoformat()}}
        pages = [{'items': [item('first', now)], 'nextPageToken': 'NEXT'},
                 {'items': [item('second', now - timedelta(days=1))]}]
        responses = []
        for page in pages:
            response = Mock()
            response.json.return_value = page
            responses.append(response)
        with patch.object(cf.requests, 'get', side_effect=responses) as get:
            result = cf.fetch_uploads('TEST', 'UCabc', 72, strict=True)
        self.assertEqual([row['video_id'] for row in result], ['first', 'second'])
        self.assertEqual(get.call_count, 2)

    def test_longform_failure_is_independent_and_main_only(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/longform.yml').read_text(encoding='utf-8'))
        condition = workflow['jobs']['build']['if']
        self.assertNotIn("conclusion == 'success'", condition)
        self.assertIn("conclusion != 'cancelled'", condition)
        self.assertIn("head_branch == 'main'", condition)
        self.assertIn('head_repository.full_name == github.repository', condition)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
