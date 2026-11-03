"""日本人資産の母数・同率・連続性・選択日・本番接続の回帰検査。外部通信なし。"""
import copy
from datetime import datetime
import unittest
from pathlib import Path
from unittest.mock import patch

import jp_stock as jp


class StockTests(unittest.TestCase):
    def setUp(self):
        # 在庫を消費しても試験の30本条件を壊さない。実台帳は別の引数試験で確認する。
        original = jp.stock.read
        def saved(path, default=None):
            if Path(path).name in ('published_assets.json', 'published_videos.json'):
                return {}
            return original(path, default)
        reader = patch.object(jp.stock, 'read', side_effect=saved)
        reader.start()
        self.addCleanup(reader.stop)

    def test_innings_are_outs(self):
        self.assertEqual(jp.outs('5.2')+jp.outs('0.1'), 18)
        self.assertEqual(jp.ip(17), '5回2/3')
        with self.assertRaises(ValueError):
            jp.outs('5.3')

    def test_denominators(self):
        self.assertFalse(jp.eligible(dict(plateAppearances=49, atBats=40), 'hitting', False))
        self.assertTrue(jp.eligible(dict(plateAppearances=50, atBats=40), 'hitting', False))
        self.assertFalse(jp.eligible(dict(outs=44), 'pitching', False))
        self.assertTrue(jp.eligible(dict(outs=45), 'pitching', False))
        self.assertFalse(jp.eligible(dict(appearances=2, outs=60), 'pitching', False, True))
        self.assertTrue(jp.eligible(dict(appearances=3, outs=27), 'pitching', False, True))
        self.assertFalse(jp.eligible(dict(appearances=6, atBats=19), 'hitting', False, True))

    def test_doubleheader_order(self):
        raw = {'1': {'jp': '選手', 'hitting_gameLog': [dict(season='2026', gameType='R', date='2026-07-01',
                game=dict(gamePk=pk, gameNumber=num), opponent={'id': 119}, stat={'hits': 1}) for pk, num in ((100, 2), (101, 1))]}}
        self.assertEqual([r['game_pk'] for r in jp.slim(raw)['players']['1']['hitting']], [101, 100])

    def test_authored_unicode_and_precise_headings(self):
        for name in ('jp_stock.py', 'test_jp_stock.py'):
            self.assertNotRegex((jp.ROOT/'scripts'/name).read_text(encoding='utf8'), r'\?{3,}|\ufffd')
        for t in jp.build()['topics']:
            self.assertRegex(t['title'], r'\d')
            self.assertNotIn('｜2026年', t['title'])

    def test_best_ties_are_counted(self):
        rows = [dict(date=f'2026-06-0{i}', game_pk=i, stat=dict(homeRuns=2, rbi=4, hits=2,
                 atBats=4, plateAppearances=4, totalBases=8, baseOnBalls=0)) for i in (1, 2)]
        spec, reason = jp.best('1', {'jp': '選手'}, 'hitting', rows, False)
        self.assertIsNone(reason)
        self.assertEqual(spec['tied_games'], 2)
        self.assertEqual(spec['game_ids'], ['1', '2'])
        self.assertIn('2試合', spec['intro'])
        self.assertNotIn('早い', spec['intro'])

    def test_streak_runs_not_earned_runs(self):
        rows = [dict(stat=dict(runs=x, earnedRuns=0)) for x in (0, 0, 1, 0, 0, 0)]
        self.assertEqual([len(r) for r in jp.runs(rows, 'pitching')], [2, 3])
        batting = [dict(stat=dict(hits=x, plateAppearances=4)) for x in (1, 1, 0, 1)]
        self.assertEqual([len(r) for r in jp.runs(batting, 'hitting')], [2, 1])
        batting[0]['stat']['plateAppearances'] = 0
        self.assertEqual(jp.runs(batting, 'hitting'), [])

    def test_expression_and_tampering(self):
        doc = jp.build()
        self.assertGreaterEqual(len(doc['topics']), 25)
        self.assertLessEqual(len(doc['topics']), 55)
        for t in doc['topics']:
            self.assertFalse(jp.expression_errors(t))
            self.assertGreaterEqual(len(t['items']), 3)
            self.assertFalse(any(h == '比較の条件' for h, _ in t['items']))
            self.assertTrue(jp.validate_spec(t))
        t = copy.deepcopy(doc['topics'][0])
        t['items'][0] = ('記録', '史上初の活躍')
        with self.assertRaises(ValueError):
            jp.validate_spec(t)

    def test_ohtani_two_way_dates_are_distinct(self):
        t = next(t for t in jp.build()['topics'] if t['key'] == 'season_best_2026_660271_pitching')
        self.assertTrue(t['two_way'])
        self.assertIn('別の試合', t['items'][-1][1])
        self.assertFalse(set(t['game_ids']) & set(t['batting_game_ids']))
        self.assertIn('8月5日と8月17日', t['items'][-1][1])
        self.assertNotIn('同じ試合', t['intro'])

    def test_editorial_strength_and_spoken_information(self):
        document = jp.build()
        self.assertEqual(sum(t['stock_kind'] not in ('home', 'win', 'daynight') for t in document['topics']), 29)
        for t in document['topics']:
            self.assertFalse(jp.expression_errors(t))
            self.assertNotIn('2026年', t['intro'].split('。')[0])
            self.assertRegex(t['intro'].split('。')[0], r'\d')
            self.assertIn('2026年', t['criteria_note'])
        keys = {t['key'] for t in document['topics']}
        self.assertNotIn('season_best_2026_663457_hitting', keys)
        self.assertNotIn('season_streak_2026_663457_hitting', keys)
        self.assertNotIn('season_streak_2026_808963_pitching', keys)
        self.assertIn('season_vs_2026_808959_hitting', keys)

    def test_schedule_has_no_consecutive_player_or_type(self):
        document = jp.build()
        topics = {t['key']:t for t in document['topics']}
        last_kind, previous_players, used = None, set(), []
        for day in document['schedule']:
            players, kinds = set(), set()
            for key in day:
                t = topics[key]
                self.assertNotEqual(last_kind, t['stock_kind'])
                self.assertNotIn(t['stock_kind'], kinds)
                self.assertFalse(set(t['player_ids']) & (players|previous_players))
                players.update(t['player_ids']); kinds.add(t['stock_kind'])
                last_kind = t['stock_kind']; used.append(key)
            previous_players = players
        self.assertEqual(set(used), set(topics))
        self.assertEqual(len(used), len(topics))

    def test_average_reading_preserves_display_and_other_episodes(self):
        import synthesize_narration as voice
        self.assertEqual(voice.baseball_average_reading('打率.306と.275'), '打率3割6厘と2割7分5厘')
        self.assertEqual(voice.baseball_average_reading('防御率0.306'), '防御率0.306')
        self.assertEqual(voice.baseball_average_reading('.300 .010 .000'), '3割 1分 0割')
        import generate_asset_video as generator
        topics = jp.build()['topics']
        for t in topics:
            generator.LIST_TOPICS[t['key']] = t
            narration = generator.build_narration(t['key'])
            self.assertEqual(narration.get('baseball_average_voice', False), t['comparison_group']=='hitting')

    def test_rotation_uses_reserved_jst_date(self):
        spec = {'player_ids': ['660271']}
        now = datetime.fromisoformat('2026-11-03T00:30:00+09:00')
        rows = ({'asset': {'season_best_2026_660271_hitting': dict(player_ids=['660271'],
                 published_at='2026-11-01T03:00:00Z', publish_at='2026-11-02T13:00:00Z')}}, {'assets': {}})
        self.assertFalse(jp.rotation_available('new', spec, rows, now))
        self.assertTrue(jp.rotation_available('new', {'player_ids': ['808967']}, rows, now))

    def test_published_subject_is_not_reissued(self):
        spec = jp.build()['topics'][0]
        self.assertTrue(jp.duplicate(spec, {spec['key']: {}}, {}))
        self.assertTrue(jp.duplicate(spec, {'old_key': {'title': spec['title']}}, {}))
        comparison = next(t for t in jp.build()['topics'] if t['stock_kind'] == 'compare')
        a, b = comparison['player_ids']
        self.assertTrue(jp.duplicate(comparison, {f'season_compare_2026_{b}_{a}': {}}, {}))

    def test_generated_topic_without_key_reaches_validation(self):
        # generated_topics は辞書の鍵へ移すので spec に key が無い。11/2 に全件が選ばれなかった。
        import generate_asset_video as gav
        spec = dict(jp.build()['topics'][0])
        topic = spec.pop('key')
        with patch.dict(gav.LIST_TOPICS, {topic: spec}):
            self.assertTrue(gav.build_narration(topic))

    def test_material_copy_workflow_keeps_mechanical_gate(self):
        import sanity_workflows
        workflow = (jp.ROOT/'.github/workflows/season_review.yml').read_text(encoding='utf8')
        call = next(line for line in workflow.splitlines() if 'python scripts/sanity.py ' in line)
        self.assertIn('--general', call)
        for flag in ('--strict', '--narration', '--out', '--hold-record', '--kind'):
            self.assertIn(flag, call)
        self.assertEqual(sanity_workflows.errors(jp.ROOT), [])

    def test_integration_and_sns(self):
        import asset_sns
        import asset_policy
        import generated_topics
        import next_asset
        import buffer_daily
        topics = jp.build()['topics']
        self.assertIn('build/jp_stock_topics.json', generated_topics.SOURCES)
        for t in topics:
            self.assertTrue(asset_sns.TOPIC.fullmatch(t['key']))
            self.assertTrue(asset_policy.selectable(t['key'], t, {t['jp']}))
            kind, _ = asset_sns.register(t['key'], 'season-review', {'path': '.github/workflows/season_review.yml'})
            self.assertEqual(buffer_daily.KIND_WORDS[kind]['short'], 'シーズンまとめ')
            record = dict(title=t['title'], video_id='xbfpDJqtQUk', description='VOICEVOX:四国めたん')
            for service in ('twitter', 'instagram', 'tiktok'):
                caption = buffer_daily.caption(service, '2026-11-02', record, kind)
                self.assertTrue(caption.startswith('11/02更新｜シーズンまとめ'))
                self.assertNotIn('PSの話題', caption)
            self.assertLess(next_asset.season_order(t['key'], t), next_asset.season_order('season_player_1', {'jp': '選手'}))
        self.assertEqual(asset_policy.PAUSED_KINDS, {'venue', 'season_team', 'team'})

    def test_new_types_rotate_after_two_days_and_keep_receipts(self):
        import jp_assets
        from datetime import timedelta
        import asset_sns
        import hashlib
        import io
        import zipfile
        import json
        now = datetime.fromisoformat('2026-11-03T12:00:00+09:00')
        for t in jp.build()['topics']:
            row = dict(player_ids=t['player_ids'], published_at=(now-timedelta(days=1)).isoformat())
            ledgers = ({'asset': {'season_other': row}}, {'assets': {}})
            self.assertFalse(jp_assets.publication_available(t['key'], t, ledgers, now))
            row['published_at'] = (now-timedelta(days=2)).isoformat()
            self.assertTrue(jp_assets.publication_available(t['key'], t, ledgers, now))
            digest = hashlib.sha256(b'local-fixture').hexdigest()
            archive = io.BytesIO()
            filename = 'collespo_asset_'+t['key']+'.mp4'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(filename.removesuffix('.mp4')+'.sns.json', json.dumps(dict(topic=t['key'], style='v3', sha256=digest)))
            self.assertTrue(asset_sns.verify_receipt(archive.getvalue(), filename, t['key'], digest))


    def test_all_stock_intro_numbers_are_not_split_between_lines(self):
        import re
        import review_render_v3 as r
        for spec in jp.build()['topics']:
            image = r.intro(2, spec, 'シーズンまとめ')
            big = [row['text'] for row in image.info['v3_layout']
                   if row['role'] == 'text' and 400 <= row['box'][1] < 1000]
            for number in re.findall(r'\d+(?:\.\d+)?|\.\d+', spec['hook']):
                self.assertTrue(any(number in line for line in big), (spec['key'], number, big))

    def test_leading_decimal_in_body_stays_with_its_dot_at_wrap_boundary(self):
        import review_render_v3 as r
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new('RGB', (8, 8)))
        for number in ('.306', '.169', '.455', '0.60', '11.57'):
            body = 'ヌートバーは'+number+'。'
            width = draw.textlength('ヌートバーは.', font=r.font(42))+1
            rows = r.rich_lines(r._runs(body), width, (80, 180, 160), size=42, badges=False)
            lines = [''.join(part[1] for part in line) for line in rows]
            self.assertTrue(any(number in line for line in lines), (number, lines))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
