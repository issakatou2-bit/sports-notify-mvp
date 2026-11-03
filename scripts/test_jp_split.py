"""ホーム・チーム勝敗と既存50候補の回帰。通信なし。"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jp_stock as jp


def digest(t):
    return hashlib.sha256(json.dumps({k: v for k, v in t.items() if k != 'stock_order'},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SplitTests(unittest.TestCase):
    def test_schedule_replaces_log_daynight_and_ignores_postponed_copy(self):
        raw = {'1': dict(jp='選手', hitting_gameLog=[dict(season='2026', gameType='R',
                         date='2026-07-07', game=dict(gamePk=1, gameNumber=1, dayNight='day'),
                         opponent=dict(id=121), stat=dict(hits=1))])}
        schedule = {'dates': [{'games': [dict(gamePk=1, dayNight='day', status=dict(codedGameState='D')),
                                       dict(gamePk=1, dayNight='night', status=dict(codedGameState='F'))]}]}
        doc = jp.slim(raw, schedule, schedule_sha256='test-file-hash')
        self.assertEqual(doc['players']['1']['hitting'][0]['dayNight'], 'night')
        self.assertEqual(doc['schedule_sha256'], 'test-file-hash')
        for games in ([], [dict(gamePk=1)], [dict(gamePk=1, dayNight='unknown')]):
            row = jp.slim(raw, {'dates': [{'games': games}]})['players']['1']['hitting'][0]
            self.assertNotIn('dayNight', row)

    def test_existing_forty_specs_unchanged_after_schedule_import(self):
        expected = jp.stock.read(jp.ROOT/'scripts/fixtures/jp_split_40_20261104.json')
        actual = {t['key']: digest(t) for t in jp.build()['topics'] if t['stock_kind'] != 'daynight'}
        self.assertEqual(actual, expected)

    def test_daynight_uses_exact_thresholds_and_rejects_missing(self):
        rows = [dict(dayNight=v, game_pk=i, stat=dict(plateAppearances=50, atBats=50,
                    hits=h, homeRuns=2, rbi=3, outs=45, earnedRuns=er, strikeOuts=10, runs=er))
                for i, (v, h, er) in enumerate((('day', 20, 1), ('night', 15, 6)))]
        player = dict(jp='選手', hitting=rows, pitching=rows)
        for group in ('hitting', 'pitching'):
            spec, reason = jp.daynight('1', player, group, rows, False)
            self.assertIsNone(reason)
            spec, _ = jp.editorial(spec, {'1': player})
            self.assertIn('デーゲーム', spec['title'])
            self.assertIn('ナイター', spec['title'])
            self.assertEqual(spec['stock_kind'], 'daynight')
            import asset_sns
            import next_asset
            self.assertTrue(asset_sns.TOPIC.fullmatch(spec['key']))
            self.assertEqual(next_asset.season_kind(spec['key']), 'season_daynight')
            self.assertTrue(jp.duplicate(spec, {spec['key']: {}}, {}))
            # 実材料の昼夜区分は全dayなので、型の描画は人工材料と明示して検査。
            import os
            import generate_asset_video as g
            import review_render_v3 as r
            import v3_rules
            with patch.dict(g.LIST_TOPICS, {spec['key']: spec}), patch.object(r, 'LOOK', 'v4'), patch.dict(os.environ, {'COLLESPO_MOTION': 'on'}):
                seg = dict(kind='list', text='デーゲームの記録。'+spec['items'][0][1],
                           meta=dict(topic=spec['key'], start=0, count=2))
                r.set_caption(seg['text'], 12, 40, speaker=2)
                im = g.render_v3(3, 'list', seg['meta'], spec, spec['key'], seg, 12)
                self.assertEqual(v3_rules.check_layout(im), [])
        rows[1]['stat']['hits'] = 16
        self.assertIsNone(jp.daynight('1', player, 'hitting', rows, False)[0])
        rows[1]['stat'].update(hits=15, plateAppearances=49)
        self.assertIsNone(jp.daynight('1', player, 'hitting', rows, False)[0])
        rows[1]['dayNight'] = 'unknown'
        self.assertIsNone(jp.daynight('1', player, 'pitching', rows, False)[0])

    def test_win_rate_first_and_zero_denominator(self):
        self.assertEqual(jp.concise_stats(dict(atBats=116, hits=52, homeRuns=30, rbi=48), 'hitting'),
                         '打率.448、30本塁打、48打点')
        self.assertEqual(jp.concise_stats(dict(outs=555, earnedRuns=52, strikeOuts=182), 'pitching'),
                         '防御率2.53、185回、182奪三振')
        self.assertEqual(jp.concise_stats({}, 'pitching'), '防御率算出なし、0回、0奪三振')
        import synthesize_narration as voice
        self.assertEqual(voice.baseball_average_reading('打率.448、30本塁打'), '打率4割4分8厘、30本塁打')

    def test_stat_units_at_tight_width_and_across_style_runs(self):
        import review_render_v3 as r
        for text in ('48打点', '19本塁打', '52安打', '116打数', '182奪三振', '30回1/3', '30回2/3', '.448', '打率.448', '防御率2.53', '自責点31'):
            for runs in (r._runs('前文'+text+'。'), [('前文', 'M', False), (text[:2], 'M', True), (text[2:]+'。', 'M', False)]):
                lines = r.rich_lines(runs, 220, (80, 180, 160), size=42, badges=False)
                self.assertTrue(any(text in ''.join(p[1] for p in line) for line in lines), (text, lines))

    def test_all_stock_kinds_use_unsplit_stat_units_in_production_cards(self):
        import os
        import re
        import generate_asset_video as g
        import review_render_v3 as r
        import v3_rules
        original = jp.stock.read
        def read(path, *args):
            return {} if Path(path).name in ('published_assets.json', 'published_videos.json') else original(path, *args)
        # 検査側は描画器の正規表現を流用せず、実際に描いた行の境界を調べる。
        tokens = re.compile(r'(?:\d+(?:\.\d+)?|\.\d+)(?:回(?:[12]/3)?|本塁打|奪三振|打点|安打|打数|打席|登板|試合|得点|塁打|四球|失点|勝|敗)')
        checked, kinds = 0, set()
        with patch.object(jp.stock, 'read', side_effect=read), patch.dict(os.environ, {'COLLESPO_MOTION': 'on'}), patch.object(r, 'LOOK', 'v4'):
            catalog = jp.build()['topics']
            for spec in catalog:
                with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
                    nar = g.build_narration(spec['key'])
                    for seg in nar['segments']:
                        if seg['kind'] != 'list':
                            continue
                        r.set_caption(seg['text'], 12, 50, speaker=2)
                        # 1ページの4秒周期で入場後に止まった位置を全ページ検査する。
                        import v3_slot_render as common
                        rows = g.list_items(spec['key'])[seg['meta'].get('start', 0):][:seg['meta'].get('count', 1)]
                        pages = common.paginate(spec, rows)
                        for page in range(len(pages)):
                            im = g.render_v3(3+page*4, 'list', seg['meta'], spec, spec['key'], seg, 12)
                            self.assertEqual(v3_rules.check_layout(im), [], spec['key'])
                            for card in im.info.get('v3_card_contents', []):
                                lines = card.get('body_lines')
                                self.assertIsNotNone(lines, spec['key'])
                                body = ''.join(lines)
                                boundaries, offset = set(), 0
                                for line in lines[:-1]:
                                    offset += len(line)
                                    boundaries.add(offset)
                                for m in tokens.finditer(body):
                                    self.assertFalse(boundaries & set(range(m.start()+1, m.end())), (spec['key'], m[0], lines))
                                checked += 1
                                kinds.add(spec['stock_kind'])
        self.assertGreaterEqual(checked, len(catalog)*3)
        self.assertEqual(kinds, {t['stock_kind'] for t in catalog})

    def test_slim_keeps_team_results_without_using_pitcher_record(self):
        raw = {'1': dict(jp='選手', hitting_gameLog=[dict(season='2026', gameType='R',
                         date='2026-07-01', game=dict(gamePk=1, gameNumber=1, dayNight='night'),
                         opponent=dict(id=121), team=dict(id=119), isHome=True, isWin=False,
                         stat=dict(hits=2, wins=1))])}
        schedule = {'dates': [{'games': [dict(gamePk=1, dayNight='day')]}]}
        doc = jp.slim(raw, schedule)
        row = doc['players']['1']['hitting'][0]
        self.assertEqual((row['isHome'], row['isWin'], row['team_id']), (True, False, 119))
        self.assertEqual(row['dayNight'], 'day')
        self.assertNotIn('dayNight', jp.slim(raw)['players']['1']['hitting'][0])
        self.assertNotIn('dayNight', jp.slim(raw, {'dates': []})['players']['1']['hitting'][0])
        self.assertIn('schedule_sha256', doc)
        self.assertNotIn('wins', row['stat'])
        self.assertEqual(doc['acquired'], '2026-11-04')

    def test_legacy_topics_and_all_candidates_unchanged(self):
        fixture = jp.stock.read(jp.ROOT/'scripts/fixtures/jp_stock_legacy_20261104.json')
        original_read, original_edit = jp.stock.read, jp.editorial
        captured = {}
        def read(path, *args):
            return {} if Path(path).name in ('published_assets.json', 'published_videos.json') else original_read(path, *args)
        def capture(spec, players):
            result = original_edit(spec, players)
            if spec['stock_kind'] not in ('home', 'win', 'daynight'):
                captured[spec['key']] = digest(spec)
            return result
        with patch.object(jp.stock, 'read', side_effect=read), patch.object(jp, 'editorial', side_effect=capture):
            doc = jp.build()
        self.assertEqual(captured, fixture['candidates'])
        self.assertEqual({t['key']: digest(t) for t in doc['topics'] if t['stock_kind'] not in ('home', 'win', 'daynight')}, fixture['topics'])

    def test_home_requires_both_samples_and_exact_spread(self):
        def row(home, hits):
            return dict(isHome=home, game_pk=int(home), stat=dict(plateAppearances=50, atBats=50, hits=hits))
        rows = [row(True, 20), row(False, 15)]
        self.assertIsNotNone(jp.home('1', {'jp': '選手'}, 'hitting', rows, False)[0])
        rows[0]['stat']['hits'] = 19
        self.assertIsNone(jp.home('1', {'jp': '選手'}, 'hitting', rows, False)[0])
        rows[0]['stat'].update(hits=20, plateAppearances=49)
        self.assertIsNone(jp.home('1', {'jp': '選手'}, 'hitting', rows, False)[0])
        rows[0].pop('isHome')
        self.assertIsNone(jp.home('1', {'jp': '選手'}, 'hitting', rows, False)[0])

    def test_win_counts_games_not_homers_or_pitcher_wins(self):
        rows = [dict(game_pk=i, team_id=119, isWin=i % 2 == 0,
                     stat=dict(homeRuns=2, gamesStarted=1, wins=0, losses=1)) for i in range(6)]
        p = {'jp': '選手', 'hitting': rows, 'pitching': rows}
        for group in ('hitting', 'pitching'):
            spec, reason = jp.win('1', p, group, rows, False)
            self.assertIsNone(reason)
            self.assertEqual(len(spec['game_ids']), 6)
            rows[0]['team_id'] = 121
            self.assertIsNone(jp.win('1', p, group, rows, False)[0])
            rows[0]['team_id'] = 119
        rows[0]['stat']['gamesStarted'] = 0
        self.assertIsNone(jp.win('1', p, 'pitching', rows, False)[0])
        rows[0]['isWin'] = None
        self.assertIsNone(jp.win('1', p, 'hitting', rows, False)[0])

    def test_new_specs_validate_and_duplicate(self):
        import asset_policy
        import jp_assets
        import next_asset
        from datetime import datetime
        for t in jp.build()['topics']:
            if t['stock_kind'] not in ('home', 'win', 'daynight'):
                continue
            self.assertTrue(jp.validate_spec(t))
            self.assertEqual(next_asset.season_kind(t['key']), 'season_'+t['stock_kind'])
            self.assertTrue(jp.duplicate(t, {t['key']: {}}, {}))
            self.assertTrue(jp.duplicate(t, {'old': {'title': t['title']}}, {}))
            self.assertTrue(asset_policy.selectable(t['key'], t, {t['jp']}))
            now = datetime.fromisoformat('2026-11-04T22:00:00+09:00')
            ledgers = ({'asset': {t['key']: dict(player_ids=t['player_ids'], published_at=now.isoformat())}}, {})
            self.assertFalse(jp_assets.available(t['key'], t, ledgers, now))
            edited = copy.deepcopy(t)
            edited['stock_kind'] = 'best'
            with self.assertRaises(ValueError):
                jp.validate_spec(edited)

    def test_focused_stock_cards_stay_inside_safe_area(self):
        import os
        import generate_asset_video as g
        import review_render_v3 as r3
        import v3_rules
        with patch.dict(os.environ, {'COLLESPO_MOTION': 'on'}), patch.object(r3, 'LOOK', 'v4'):
            for spec in jp.build()['topics']:
                if spec['stock_kind'] not in ('home', 'win', 'daynight'):
                    continue
                with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
                    narration = g.build_narration(spec['key'])
                    for seg in narration['segments']:
                        if seg['kind'] != 'list':
                            continue
                        r3.set_caption(seg['text'], 12, 40, speaker=2)
                        for t in (2, 4, 7):
                            image = g.render_v3(t, seg['kind'], seg['meta'], spec, spec['key'], seg, 12)
                            self.assertEqual(v3_rules.check_layout(image), [], (spec['key'], t))


if __name__ == '__main__':
    unittest.main()
