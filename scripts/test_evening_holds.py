"""10/25の保存見出し・実停止指摘・誤補完台帳の回帰。通信・生成APIなし。"""
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import backfill_records as backfill
import sanity
import sanity_material
import soccer_preview_history as history
import upload_youtube as upload
import verify_published as verify

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'scripts/fixtures/fact-guards/evening_holds_20261025.json').read_text(encoding='utf-8'))


class EveningHoldsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.old)
        self.document = copy.deepcopy(FIXTURE['document'])
        self.issue = copy.deepcopy(FIXTURE['issue'])
        self.materials = copy.deepcopy(FIXTURE['materials'])
        self.records = copy.deepcopy(FIXTURE['records'])
        self.games = dict(generated_at='2026-10-25T15:45:00+00:00', games=[])
        self.narration = dict(segments=[dict(text='今夜の予告です。')])

    def write(self, name, value):
        Path(name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def assessed(self):
        reviewed, errors = sanity_material.assess([self.issue], [self.document], self.materials)
        return reviewed[0], errors

    def test_saved_game_comeback_and_series_lead_are_supported(self):
        issue, errors = self.assessed()
        self.assertEqual(errors, [])
        self.assertTrue(issue['supported'])
        self.assertFalse(sanity_material.blocking(issue))
        self.assertEqual(issue['severity'], 'high')

    def test_missing_original_or_wrong_game_or_translation_still_holds(self):
        original = copy.deepcopy(self.document)
        for change in ('missing', 'game', 'date', 'source', 'original', 'translation', 'extra'):
            with self.subTest(change=change):
                self.document = copy.deepcopy(original)
                head = self.document['segments'][0]['meta']['source_headlines'][0]
                if change == 'missing':
                    self.document['segments'][0]['meta']['source_headlines'] = []
                elif change == 'game':
                    head['url'] = head['url'].replace('game-2', 'game-1')
                elif change == 'date':
                    head['at'] = '2026-09-01T00:00:00Z'
                    head['published_date'] = '2026-09-01'
                    head['publication_evidence'] = [dict(source='at', date='2026-09-01')]
                elif change == 'source':
                    head['url'] = head['url'].replace('www.mlb.com', 'example.com')
                elif change == 'original':
                    head['title'] = head['title'].replace('rally', 'fail')
                elif change == 'translation':
                    head['jp'] = head['jp'].replace('2勝0敗', '3勝0敗')
                    self.document['segments'][0]['text'] = head['jp'] + '。'
                else:
                    head['jp'] += '。架空太郎が5本塁打'
                    self.document['segments'][0]['text'] = head['jp'] + '。'
                self.issue['where'] = (head['jp'] if change in ('translation', 'extra') else
                                       FIXTURE['issue']['where'].rstrip('。')) + '。'
                self.assertTrue(sanity_material.blocking(self.assessed()[0]))

    def test_wrong_series_and_unrelated_factual_high_still_hold(self):
        self.materials[0]['series'][0]['teams'][0]['wins'] = 1
        self.assertTrue(sanity_material.blocking(self.assessed()[0]))
        self.materials = copy.deepcopy(FIXTURE['materials'])
        self.document['segments'].append(dict(text='架空太郎はレイズ所属です。'))
        self.materials.append(dict(source='fixture.roster', date_jst='2026-10-25',
                                   players=[dict(name='架空太郎', team_name='ブリュワーズ')]))
        self.issue.update(where='架空太郎はレイズ所属です。', why='所属が材料と違う')
        self.assertTrue(sanity_material.blocking(self.assessed()[0]))

    def test_headline_fragment_in_denial_or_another_sentence_does_not_release(self):
        claim = self.issue['where'].rstrip('。')
        for text in (f'昨年の{claim}。', f'「{claim}」は誤りです。', '別の原稿です。'):
            with self.subTest(text=text):
                self.document['segments'][0]['text'] = text
                self.assertTrue(sanity_material.blocking(self.assessed()[0]))

    def test_real_sanity_entry_passes_and_keeps_original_evidence(self):
        self.write('narration.json', self.document)
        with patch.object(sys, 'argv', ['sanity.py', '--general', '--strict', '--narration',
                                       'narration.json', '--out', 'review.json',
                                       '--hold-record', 'hold.json', '--kind', 'morning_press']), \
             patch.object(sanity, 'general', return_value=[self.issue]), \
             patch.object(sanity_material, 'grounding', return_value=self.materials), \
             patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'TEST'}), \
             patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(sanity.main(), 0)
        self.assertFalse(json.loads(Path('review.json').read_text(encoding='utf-8'))['upload_held'])
        self.assertEqual(json.loads(Path('hold.json').read_text(encoding='utf-8'))['status'], 'passed')

    def test_ai_prompt_includes_original_translation_and_article_game(self):
        self.write('narration.json', self.document)
        response = SimpleNamespace(content=[SimpleNamespace(type='text', text='[]')])
        with patch.dict(sys.modules, {'anthropic': SimpleNamespace(Anthropic=Mock())}), \
             patch('backstage_guard.create', return_value=response) as create, \
             patch.object(sanity.token_log, 'record'):
            self.assertEqual(sanity.general(['narration.json'], 'TEST', self.materials), [])
        prompt = create.call_args.kwargs['messages'][0]['content']
        head = self.document['segments'][0]['meta']['source_headlines'][0]
        for field in ('title', 'jp', 'url', 'at'):
            self.assertIn(head[field], prompt)

    def test_backfill_distinguishes_results_followup_preview_and_race(self):
        for title in (FIXTURE['records']['daily_soccer']['2026-10-25']['title'],
                      '【欧州サッカー】昨夜の注目試合 マインツ 2-3 ブレーメン #Shorts'):
            self.assertEqual(backfill.kind_of(title), 'soccer_results')
        self.assertEqual(backfill.kind_of('今夜の注目試合【サッカー】｜A vs B #Shorts'), 'daily_soccer')
        self.assertEqual(backfill.kind_of('チャンピオンズリーグ 順位争い｜CL圏内【欧州サッカー】#Shorts'), 'soccer_race')

    def test_repair_keeps_authoritative_result_material_day_and_is_idempotent(self):
        before = copy.deepcopy(self.records['soccer_results'])
        removed = backfill.repair_backfilled_aliases(self.records)
        self.assertEqual(len(removed), 1)
        self.assertEqual(self.records['soccer_results'], before)
        self.assertEqual(self.records['daily_soccer'], {})
        self.assertEqual(backfill.repair_backfilled_aliases(self.records), [])
        entry = before['2026-10-24']
        rss = [(datetime(2026, 10, 25, 0, 46, tzinfo=timezone.utc), entry['video_id'], entry['title'])]
        self.assertEqual(backfill.add_entries(self.records, rss), [])
        self.assertEqual(self.records['soccer_results'], before)

    def test_repair_does_not_guess_missing_material_day_or_change_real_previews(self):
        self.records['soccer_results'] = {}
        self.assertEqual(backfill.repair_backfilled_aliases(self.records), [])
        original = copy.deepcopy(self.records)
        entry = original['daily_soccer']['2026-10-25']
        with patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(backfill.add_entries({}, [(datetime.now(timezone.utc), 'missing', entry['title'])]), [])
        self.assertEqual(self.records, original)
        self.records['daily_soccer']['2026-10-25']['backfilled'] = False
        self.records['soccer_results'] = copy.deepcopy(FIXTURE['records']['soccer_results'])
        self.assertEqual(backfill.repair_backfilled_aliases(self.records), [])

    def test_upload_lookup_does_not_skip_preview_for_misfiled_result(self):
        self.write('records.json', self.records)
        self.assertEqual(upload.published_video('daily_soccer', '2026-10-25', path='records.json'), {})
        self.assertEqual(upload.published_video('soccer_results', '2026-10-24', path='records.json')['video_id'], '1Iy8UsDuSl8')

    def test_material_day_is_jst_for_preview_and_night_start_for_result(self):
        self.assertEqual(upload.material_date_key('daily', 'soccer', self.games), '2026-10-26')
        self.assertEqual(upload.material_date_key('soccer_results', 'soccer',
                                                  {'date_jst': '2026-10-24'}), '2026-10-24')
        with self.assertRaises(ValueError):
            upload.material_date_key('daily', 'soccer', self.games, '2026-10-25')
        with self.assertRaises(ValueError):
            upload.material_date_key('soccer_results', 'soccer', {'date_jst': '2026-10-24'}, '2026-10-25')

    def test_upload_entry_uses_distinct_kinds_and_material_dates(self):
        self.write('records.json', self.records)
        self.write('games.json', dict(generated_at='2026-10-25T10:00:00Z', games=[]))
        self.write('result.json', dict(date_jst='2026-10-24'))
        Path('video.mp4').write_bytes(b'test-only')
        lookup = upload.published_video
        for kind, path, posted in (('daily', 'games.json', False), ('soccer_results', 'result.json', True)):
            with self.subTest(kind=kind), patch.object(sys, 'argv', [
                    'upload_youtube.py', '--kind', kind, '--sport', 'soccer',
                    '--video', 'video.mp4', '--games', path]), \
                 patch.object(upload, 'published_video', side_effect=lambda k, d: lookup(k, d, 'records.json')) as called, \
                 patch.dict(os.environ, {'YOUTUBE_CLIENT_ID': '', 'YOUTUBE_CLIENT_SECRET': '', 'YOUTUBE_REFRESH_TOKEN': ''}), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                upload.main()
                expected = ('daily_soccer', '2026-10-25') if kind == 'daily' else ('soccer_results', '2026-10-24')
                called.assert_called_once_with(*expected)
                self.assertEqual('投稿済みのため' in output.getvalue(), posted)
                if not posted:
                    self.assertIn('YouTube認証情報が未設定', output.getvalue())

    def verify(self, kind='daily_soccer', material=True):
        self.write('records.json', self.records)
        self.write('games.json', self.games)
        self.write('narration.json', self.narration)
        args = ['verify_published.py', '--kind', kind, '--record', 'records.json']
        if material:
            args += ['--games', 'games.json']
            if kind == 'daily_soccer':
                args += ['--narration', 'narration.json']
        else:
            args += ['--video-date', '2026-10-25']
        with patch.object(sys, 'argv', args), patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''}), \
             patch('sys.stdout', new_callable=io.StringIO):
            return verify.main()

    def test_misfiled_result_cannot_report_preview_success(self):
        self.games['generated_at'] = '2026-10-25T10:00:00Z'
        self.assertEqual(self.verify(), 1)
        self.assertEqual(self.verify(material=False), 1)

    def test_exact_material_and_narration_pass_but_mismatches_hold(self):
        self.records['daily_soccer'] = {'2026-10-26': dict(
            video_id='preview', title='今夜の注目試合【サッカー】｜A vs B #Shorts',
            preview_binding=history.binding(self.games, self.narration))}
        self.assertEqual(self.verify(), 0)
        self.narration['segments'][0]['text'] = '別原稿'
        self.assertEqual(self.verify(), 1)
        self.narration['segments'][0]['text'] = '今夜の予告です。'
        self.games['games'] = ['別材料']
        self.assertEqual(self.verify(), 1)

    def test_result_confirmation_uses_material_day_not_publication_day(self):
        self.games = {'date_jst': '2026-10-24'}
        self.assertEqual(self.verify(kind='soccer_results'), 0)
        self.games['date_jst'] = '2026-10-25'
        self.assertEqual(self.verify(kind='soccer_results'), 1)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
