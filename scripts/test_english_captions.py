"""API・実素材・フォント・古いGit履歴に依存しない英語字幕の検査。"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock

import captions as ja
import english_captions as en
import caption_names

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = json.loads((ROOT/'scripts/fixtures/captions/aligned.json').read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)


def environment(remaining=10000, observed=None, quota_day='2026-10-14'):
    return dict(COLLESPO_EN_CAPTIONS='on', YOUTUBE_SHARED_QUOTA_SNAPSHOT=json.dumps({
        'observed_at': (observed or NOW).isoformat(), 'quota_date': quota_day, 'remaining_units': remaining}))


def response(text):
    return SimpleNamespace(content=[SimpleNamespace(type='text',text=text)], stop_reason='end_turn', usage=None)


class CaptionsTest(unittest.TestCase):
    def setUp(self):
        self.cues = ja.build_cues(FIX['narration'], FIX['manifest'])
        self.state = {'events': []}

    def translated(self, texts=None):
        with patch.object(en.backstage_guard,'create',return_value=response(json.dumps(texts or FIX['english']))), patch.object(en.token_log,'allowed',return_value=True), patch.object(en.token_log,'record'):
            return en.translate(self.cues, Mock())

    def test_same_timestamps_and_all_measured_segments(self):
        translated = self.translated()
        self.assertEqual([(a,b) for a,b,_ in self.cues],[(a,b) for a,b,_ in translated])
        japanese = ja.build_srt(FIX['narration'],FIX['manifest'])
        self.assertEqual(japanese,(ROOT/'scripts/fixtures/captions/japanese.srt').read_text(encoding='utf-8'))
        english = ja.render_srt(translated,english=True)
        self.assertEqual([x for x in japanese.splitlines() if ' --> ' in x],[x for x in english.splitlines() if ' --> ' in x])
        self.assertEqual(len(translated),3)
        self.assertAlmostEqual(translated[-1][1],9.6)

    def test_translation_contract_rejects_count_names_numbers_and_backstage(self):
        for texts in [FIX['english'][:2], ['Ohtani had 2 hits.',*FIX['english'][1:]],
                      ['Shohei Ohtani had 9 hits.',*FIX['english'][1:]],
                      ['制作中の原稿です',*FIX['english'][1:]], [None,*FIX['english'][1:]]]:
            with self.assertRaises(ValueError):
                self.translated(texts)

    def test_guard_and_translate_role_are_used(self):
        with patch.object(en.backstage_guard,'create',return_value=response(json.dumps(FIX['english']))) as guard, patch.object(en.token_log,'allowed',return_value=True), patch.object(en.token_log,'record'):
            en.translate(self.cues,Mock())
        self.assertEqual(guard.call_args.kwargs['model'],en.llm_models.model('translate'))
        self.assertEqual(guard.call_args.kwargs['mode'],'whole')
        self.assertEqual(caption_names.required('大谷翔平とドジャース'), {'大谷翔平':'Shohei Ohtani','ドジャース':'Los Angeles Dodgers'})

    def test_budget_unknown_stale_future_date_and_units(self):
        # 窓口が無いときは1日の上限本数の範囲で付ける（10/14）。窓口があって読めないときは見送る。
        self.assertEqual(en.budget_reason(self.state,'v',{},NOW),'')
        self.assertEqual(en.budget_reason(self.state,'v',{'YOUTUBE_SHARED_QUOTA_SNAPSHOT':'{}'},NOW),'quota_unknown')
        self.assertEqual(en.budget_reason(self.state,'v',environment(1449),NOW),'quota_insufficient')
        self.assertEqual(en.budget_reason(self.state,'v',environment(1450),NOW),'')
        for offset in (-301,1):
            self.assertEqual(en.budget_reason(self.state,'v',environment(observed=NOW+timedelta(seconds=offset)),NOW),'quota_snapshot_stale')
        self.assertEqual(en.budget_reason(self.state,'v',environment(quota_day='2026-10-13'),NOW),'quota_day_mismatch')

    def test_api_day_is_pacific_and_daily_cap_is_jst(self):
        now=NOW.replace(hour=0)
        self.assertEqual(en.budget_reason(self.state,'v',environment(observed=now,quota_day='2026-10-13'),now),'')
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'state.json'
            en.save_event(path,self.state,'first','insert_reserved',units=400,now=now)
            self.assertEqual(en.budget_reason(self.state,'second',environment(observed=now,quota_day='2026-10-13'),now),'daily_limit')
            self.assertEqual(en.budget_reason(self.state,'first',environment(),now),'already_attempted')
            self.assertEqual(en.load_state(path),self.state)

    def test_live_quota_provider_fails_closed_and_fetches_each_time(self):
        env={'YOUTUBE_SHARED_QUOTA_URL':'https://quota.example.invalid/current'}
        snap=json.loads(environment()['YOUTUBE_SHARED_QUOTA_SNAPSHOT'])
        with patch('requests.get') as get:
            get.return_value.json.return_value=snap
            self.assertEqual(en.budget_reason(self.state,'v',env,NOW),'')
            self.assertEqual(en.budget_reason(self.state,'v',env,NOW),'')
            self.assertEqual(get.call_count,2)
            get.side_effect=RuntimeError('offline')
            self.assertEqual(en.budget_reason(self.state,'v',env,NOW),'quota_unknown')
        self.assertEqual(en.budget_reason(self.state,'v',{'YOUTUBE_SHARED_QUOTA_URL':'http://example.invalid'},NOW),'quota_unknown')

    def test_pacific_winter_and_summer_midnight(self):
        for month, hour, expected in [(1,7,'2026-01-13'),(1,8,'2026-01-14'),(7,6,'2026-07-13'),(7,7,'2026-07-14')]:
            self.assertEqual(en.quota_date(datetime(2026,month,14,hour,tzinfo=timezone.utc)),expected)

    def test_reservations_subtract_units_from_same_snapshot(self):
        self.state['events']=[dict(at=NOW.isoformat(),day='2026-10-14',video_id='v',status='list_reserved',units=50)]
        self.assertEqual(en.budget_reason(self.state,'v',environment(1450),NOW),'quota_insufficient')
        self.assertEqual(en.budget_reason(self.state,'v',environment(1500),NOW),'')

    def args(self, td):
        root=pathlib.Path(td); (root/'manifest.json').write_text(json.dumps({'segments':FIX['manifest']}),encoding='utf-8')
        (root/'narr.json').write_text(json.dumps(FIX['narration']),encoding='utf-8')
        (root/'record.json').write_text(json.dumps({'assets':{'season_game_123':{'video_id':'video'}}}),encoding='utf-8')
        return SimpleNamespace(kind='asset',asset_topic='season_game_123',record=str(root/'record.json'),date=None,
            state=str(root/'state.json'),narration=str(root/'narr.json'),audio_dir=str(root),out=None)

    def test_off_unknown_budget_and_duplicates_make_no_insert(self):
        with tempfile.TemporaryDirectory() as td, patch.object(en.captions,'client') as client:
            args=self.args(td)
            with patch.dict(os.environ,{'COLLESPO_EN_CAPTIONS':'off'},clear=True): en.main(args)
            self.assertFalse(pathlib.Path(args.state).exists())
            with patch.dict(os.environ,{'COLLESPO_EN_CAPTIONS':'on','YOUTUBE_SHARED_QUOTA_SNAPSHOT':'{}'},clear=True): en.main(args)
            self.assertEqual(en.load_state(args.state)['events'][-1]['status'],'quota_unknown')
            client.assert_not_called()

    def test_success_duplicate_and_list_failure(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,environment(),clear=True), patch.object(en,'utcnow',return_value=NOW), patch.object(en,'translate',return_value=self.translated()), patch('anthropic.Anthropic',return_value=Mock()), patch.object(en.captions,'client') as client:
            args=self.args(td); api=client.return_value.captions.return_value
            api.list.return_value.execute.return_value={'items':[]}
            en.main(args)
            state=en.load_state(args.state)
            self.assertEqual(state['events'][-1]['status'],'inserted')
            self.assertEqual(sum(e['units'] for e in state['events']),450)
            self.assertEqual(api.insert.call_args.kwargs['body']['snippet']['language'],'en')
            en.main(args); self.assertEqual(api.insert.call_count,1)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,environment(),clear=True), patch.object(en,'utcnow',return_value=NOW), patch.object(en.captions,'client') as client:
            args=self.args(td); api=client.return_value.captions.return_value
            api.list.return_value.execute.side_effect=RuntimeError('failure')
            en.main(args); api.insert.assert_not_called()
            self.assertEqual(en.load_state(args.state)['events'][-1]['status'],'failed_RuntimeError')

    def test_workflow_contracts_have_correct_paths_and_serial_lock(self):
        import yaml
        class UniqueLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node, deep=False):
            pairs=loader.construct_pairs(node,deep=deep)
            keys=[key for key,_ in pairs]
            if len(keys)!=len(set(keys)):
                raise ValueError('duplicate YAML key')
            return dict(pairs)
        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
        for name in ('daily_notify','ps_game_now'):
            text=(ROOT/f'.github/workflows/{name}.yml').read_text(encoding='utf-8')
            data=yaml.load(text,Loader=UniqueLoader)
            self.assertIn('collespo-en-captions',data['concurrency']['group'])
            self.assertIn('YOUTUBE_SHARED_QUOTA_SNAPSHOT',text)
            self.assertIn('data/en_caption_state.json',text)
            self.assertIn('--language en',text)
        ps=(ROOT/'.github/workflows/ps_game_now.yml').read_text(encoding='utf-8')
        self.assertIn('--asset-topic "$t" --record data/published_assets.json',ps)
        self.assertNotIn('--out data/local_reporters.json data/en_caption',ps)

class NumbersSurviveTest(unittest.TestCase):
    """10/14：19時の回で、正しい訳が数字の並び順と「10月→October」で落ちた。"""
    def test_order_and_months(self):
        self.assertTrue(en.numbers_survive('大谷は3打数1安打', 'Ohtani went 1-for-3'))
        self.assertTrue(en.numbers_survive('10月15日の試合', 'the October 15 game'))
        self.assertFalse(en.numbers_survive('3打数1安打', 'went 1-for-4'))
        self.assertFalse(en.numbers_survive('2本塁打', 'hit a home run'))


if __name__ == '__main__':
    result=unittest.main(argv=[sys.argv[0]],exit=False).result
    print('ALL OK' if result.wasSuccessful() else 'FAILED')
    raise SystemExit(0 if result.wasSuccessful() else 1)
