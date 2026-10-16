"""API・実素材・フォント・古いGit履歴に依存しない英語字幕の検査。"""
import json
import io
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

# run 38663406702 / AaivcUiJ6qg / 0f6ab7b2:data/ps_game_topics.json。
# intro・items・japaneseの原文（字幕本文の材料）。英訳は再現用の固定例で、当日の応答ではない。
PS_GAME_EXAMPLES = (
    ('リーグ優勝決定シリーズ第3戦、ブリュワーズが敵地でドジャースに6対2で勝ちました。',
     'In Game 3 of the NLCS, the Milwaukee Brewers beat the Los Angeles Dodgers 6-2 on the road.'),
    ('ブリュワーズ 6対2 ドジャース　敵地で勝利　シリーズはブリュワーズの3勝0敗',
     'The Milwaukee Brewers beat the Los Angeles Dodgers 6-2 on the road for a 3-0 series lead.'),
    ('7回表　ジェイク・バウアーズの2点本塁打（飛距離126メートル、打球の速さ時速176キロ）',
     'In the top of the seventh, Jake Bauers hit a two-run homer (126 meters, 176 km/h).'),
    ('ブリュワーズ3本（チョーリオ、バウアーズ、ミッチェル）',
     'Three homers for the Milwaukee Brewers (Jackson Chourio, Jake Bauers, Garrett Mitchell).'),
    ('ブリュワーズ ガッサー 5回を無失点　ドジャース スネル 6回を4失点',
     'Robert Gasser of the Milwaukee Brewers pitched five scoreless innings; '
     'Blake Snell of the Los Angeles Dodgers allowed four runs in six innings.'),
    ('勝ち D.L.ホール（2回と3分の1を無失点）　セーブ トレバー・メギル',
     'Win: DL Hall (two and one third scoreless innings). Save: Trevor Megill.'),
    ('「勝負強い本塁打でブルワーズ、44年ぶりのワールドシリーズ進出まであと1勝」',
     '"Clutch homers leave the Brewers one win away from their first World Series appearance '
     'in forty-four years."'),
    ('大谷翔平が2打数1安打　1四球（ドジャース）',
     'Shohei Ohtani went one-for-two with one walk (Los Angeles Dodgers).'),
    ('佐々木朗希が3分の1回　1失点　0奪三振（ドジャース）',
     'Roki Sasaki: one third of an inning, one run allowed, zero strikeouts (Los Angeles Dodgers).'),
)


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

    def test_ps_game_script_with_spelled_out_numbers(self):
        for original, english in PS_GAME_EXAMPLES:
            with self.subTest(original=original):
                self.assertTrue(en.numbers_survive(original, english),
                                en.number_mismatches(original, english))
        # 実例に含まれる本物の変化は、他の数字が残っていても通さない。
        for index, before, after in ((0, '6-2', '6-3'), (1, '3-0', '3-1'),
                                     (2, 'two-run', 'three-run'), (2, '126', '125'),
                                     (6, 'forty-four', 'forty-three'),
                                     (5, 'one third', 'one fourth'), (8, 'zero', 'two')):
            original, english = PS_GAME_EXAMPLES[index]
            with self.subTest(index=index, change=after):
                self.assertFalse(en.numbers_survive(original, english.replace(before, after)))

    def test_ps_game_examples_pass_the_translation_contract(self):
        cues = [(i, i + 1, original) for i, (original, _) in enumerate(PS_GAME_EXAMPLES)]
        texts = [english for _, english in PS_GAME_EXAMPLES]
        with patch.object(en.backstage_guard, 'create', return_value=response(json.dumps(texts))), \
             patch.object(en.token_log, 'allowed', return_value=True), patch.object(en.token_log, 'record'):
            self.assertEqual(en.translate(cues, Mock()),
                             [(i, i + 1, text) for i, text in enumerate(texts)])

    def test_score_series_game_inning_and_runs_variants(self):
        examples = (
            ('6対2', '6-2'), ('6対2', 'six to two'),
            ('3勝0敗', 'a 3-0 series lead'), ('3勝0敗', 'a three-zero series lead'),
            ('第3戦', 'Game 3'), ('第3戦', 'the third game'),
            ('第3戦', 'the 3rd game'), ('1回', 'the first inning'),
            ('2点', 'two runs'), ('2点本塁打', 'a two-run homer'),
            ('2回と3分の1', '2 1/3 innings'), ('3分の1回', 'one-third of an inning'),
            ('2回と3分の1', 'two and a third innings'), ('3分の2回', 'two-thirds of an inning'),
            ('1四球', 'a walk'), ('0奪三振', 'no strikeouts'),
            ('5回を無失点', 'five innings with zero runs allowed'),
            ('21得点', 'twenty-one runs'), ('22回', 'the twenty-second inning'),
            ('126メートル', 'one hundred and twenty-six meters'),
            ('44年ぶりの進出まであと1勝', 'one win away from the 1st appearance in 44 years'),
            ('２点', 'TWO runs'),
        )
        for original, english in examples:
            with self.subTest(original=original, english=english):
                self.assertTrue(en.numbers_survive(original, english))

    def test_changed_missing_extra_and_repeated_numbers_fail(self):
        for original, english in (
            ('6対2', '6-3'), ('3勝0敗', 'a 3-1 series lead'),
            ('第3戦', 'Game 4'), ('1回', 'the second inning'),
            ('2点', 'three runs'), ('2点', 'runs'),
            ('2点', 'two runs in the first inning'), ('2安打2打点', 'two hits'),
            ('2四球', 'a walk'), ('1奪三振', 'no strikeouts'),
            ('5回を無失点', 'five innings with one run allowed'),
            ('打率0.250', 'batting .300'), ('10月15日', 'September 15'),
        ):
            with self.subTest(original=original, english=english):
                self.assertFalse(en.numbers_survive(original, english))

    def test_japanese_first_and_counted_articles(self):
        examples = (
            ('初ゴール', 'his first goal'), ('初めて得点した', 'scored for the first time'),
            ('最初の安打', 'the first hit'), ('史上初の快挙', 'a first in history'),
            ('1点を決めた', 'scored a goal'), ('1本打った', 'hit a homer'),
            ('1本塁打', 'a home run'), ('1安打', 'a hit'), ('1安打', 'one hit'),
            ('1回を投げた', 'pitched an inning'),
            ('初出場で1安打', 'a hit in his first appearance'),
            ('初めて1点を決めた', 'scored a goal for the first time'),
        )
        for original,english in examples:
            with self.subTest(original=original,english=english):
                self.assertEqual(en.number_mismatches(original,english),([],[]))
        cues=[(i,i+1,ja) for i,(ja,_) in enumerate(examples)]
        with patch.object(en.backstage_guard,'create',return_value=response(json.dumps([text for _,text in examples]))), \
             patch.object(en.token_log,'allowed',return_value=True), patch.object(en.token_log,'record'):
            self.assertEqual(len(en.translate(cues,Mock())),len(examples))

    def test_first_and_article_do_not_hide_changed_counts(self):
        for original,english in (
            ('初ゴール','his second goal'), ('初めて得点した','scored'),
            ('最初の安打','a hit'), ('2点を決めた','scored a goal'),
            ('2本塁打','a homer'), ('2安打','one hit'),
            ('1安打','a great performance'), ('1安打','an amazing performance'),
            ('1点','a goalkeeper'), ('1安打1四球','a hit'),
            ('初出場で2安打','a hit in his first appearance'),
            ('1点','a goal in his first game'),
        ):
            with self.subTest(original=original,english=english):
                self.assertTrue(any(en.number_mismatches(original,english)))

    def test_translation_logs_only_unmatched_numbers(self):
        with patch.object(en.backstage_guard, 'create', return_value=response('["6-3"]')), \
             patch.object(en.token_log, 'allowed', return_value=True), \
             patch.object(en.token_log, 'record'), patch('sys.stdout', new_callable=io.StringIO) as log:
            with self.assertRaisesRegex(ValueError, '^translation_numbers$'):
                en.translate([(0, 1, '試合は6対2でした。')], Mock())
        self.assertEqual(log.getvalue(),
                         "[warn] 英語字幕: translation_numbers Japanese=['2'] English=['3']\n")
        self.assertEqual(en.number_mismatches('2安打2打点', 'two hits'), (['2'], []))

    def test_synthetic_headline_number_forms(self):
        # 10/16の応答は未保存。見出し特有の同義表現と脱落を固定材料で区別する。
        examples=(
            ('大谷翔平1号','Shohei Ohtani hits his first homer'),
            ('大谷翔平1安打','Shohei Ohtani records a single'),
            ('大谷翔平1安打','Shohei Ohtani records one hit'),
            ('21日に第1戦','Game 1 on the twenty-first'),
            ('第1戦の1回','The first inning of Game 1'),
            ('初回に1安打','A hit in the opening inning'),
            ('第1戦に1安打','A single in the series opener'),
            ('1回に1号','His first home run in the first inning'),
            ('初回に1安打、21日に第1戦','A single in the opening inning; Game 1 on the 21st'),
            ('21日に出場する可能性','He may play on the 21st'),
        )
        for original,english in examples:
            with self.subTest(original=original,english=english):
                self.assertEqual(en.number_mismatches(original,english),([],[]))
        with patch.object(en.backstage_guard,'create',return_value=response(json.dumps([t for _,t in examples]))), \
             patch.object(en.token_log,'allowed',return_value=True),patch.object(en.token_log,'record'):
            en.translate([(i,i+1,original) for i,(original,_) in enumerate(examples)],Mock())

    def test_headline_omissions_and_changed_numbers_still_fail(self):
        for original,english in (
            ('大谷翔平1号','Shohei Ohtani hits his second homer'),
            ('大谷翔平1号','Shohei Ohtani goes deep'),
            ('大谷翔平1安打','Shohei Ohtani records two hits'),
            ('大谷翔平2安打','Shohei Ohtani records a single'),
            ('21日に第1戦','Game 1 on the 9th'),
            ('第1戦の1回','The first inning of Game 2'),
            ('1回に1安打','A hit in the second inning'),
            ('初回に1安打','A single in the second inning'),
            ('21日に1号','A homer in September'),
        ):
            with self.subTest(original=original,english=english):
                self.assertTrue(any(en.number_mismatches(original,english)))
        self.assertEqual(en.number_mismatches('大谷翔平は21日に1号','Shohei Ohtani goes deep in September'),(['1','21'],['9']))

    def test_translation_instruction_preserves_headline_details(self):
        with patch.object(en.backstage_guard,'create',return_value=response('["Game 1 on the 21st"]')) as create, \
             patch.object(en.token_log,'allowed',return_value=True),patch.object(en.token_log,'record'):
            en.translate([(0,1,'21日に第1戦')],Mock())
        prompt=create.call_args.kwargs['messages'][0]['content']
        for text in ('1号','1安打','第1戦','1回','21日','never infer a month'):
            self.assertIn(text,prompt)


if __name__ == '__main__':
    result=unittest.main(argv=[sys.argv[0]],exit=False).result
    print('ALL OK' if result.wasSuccessful() else 'FAILED')
    raise SystemExit(0 if result.wasSuccessful() else 1)
