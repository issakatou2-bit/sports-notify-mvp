"""前半・後半の境界、母数、元の全候補と選手順の回帰。通信なし。"""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jp_stock as jp


def digest(spec):
    return hashlib.sha256(json.dumps({k: v for k, v in spec.items() if k != 'stock_order'},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HalfTests(unittest.TestCase):
    def test_official_date_boundary(self):
        for date, period in [('2026-03-01', 'first'), ('2026-06-30', 'first'),
                             ('2026-07-01', 'second'), ('2026-09-30', 'second'), ('2026-10-01', None)]:
            self.assertEqual(jp.half_period(dict(date=date)), period)

    def rows(self):
        return [dict(date=date, game_pk=i, stat=dict(plateAppearances=50, atBats=50,
                    hits=hits, homeRuns=2, rbi=3, outs=45, earnedRuns=er,
                    strikeOuts=10, runs=er, gamesStarted=1))
                for i, (date, hits, er) in enumerate((('2026-06-30', 20, 1), ('2026-07-01', 15, 6)))]

    def test_both_samples_and_exact_differences(self):
        rows = self.rows()
        for group in ('hitting', 'pitching'):
            self.assertIsNotNone(jp.half('1', {'jp': '選手'}, group, rows, False)[0])
        rows[0]['stat']['plateAppearances'] = 49
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'hitting', rows, False)[0])
        rows[0]['stat']['plateAppearances'] = 50
        rows[0]['stat']['hits'] = 19
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'hitting', rows, False)[0])
        rows[1]['stat']['earnedRuns'] = 5
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'pitching', rows, False)[0])
        rows[1]['stat']['earnedRuns'] = 6
        rows[0]['stat']['outs'] = 44
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'pitching', rows, False)[0])
        rows[0]['stat'].update(outs=15, earnedRuns=1)
        rows[1]['stat'].update(outs=15, earnedRuns=6)
        self.assertIsNotNone(jp.half('1', {'jp': '選手'}, 'pitching', rows, True)[0])
        rows[0]['stat']['outs'] = 14
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'pitching', rows, True)[0])
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'hitting', rows[:1], False)[0])
        rows[0]['date'] = '2026-10-01'
        self.assertIsNone(jp.half('1', {'jp': '選手'}, 'pitching', rows, True)[0])

    def test_short_cards_and_precise_period_note(self):
        for group in ('hitting', 'pitching'):
            rows = self.rows()
            player = dict(jp='選手', hitting=rows, pitching=rows)
            spec, _ = jp.half('1', player, group, rows, False)
            spec, reason = jp.editorial(spec, {'1': player})
            self.assertIsNone(reason)
            self.assertIn('前半3〜6月・後半7〜9月', spec['criteria_note'])
            self.assertTrue(spec['items'][0][1].startswith('打率' if group == 'hitting' else '防御率'))
            self.assertNotIn('失点', spec['items'][0][1])

    def test_all_legacy_candidates_unchanged(self):
        import jp_assets
        import generate_asset_video as g
        expected = jp.stock.read(jp.ROOT/'scripts/fixtures/jp_half_legacy_20261104.json')
        original = jp.stock.read
        def read(path, *args):
            return {} if Path(path).name in ('published_assets.json', 'published_videos.json') else original(path, *args)
        with patch.object(jp.stock, 'read', side_effect=read):
            source_specs = {t['key']: t for t in jp.build()['topics'] if t['stock_kind'] != 'half'}
            source_specs.update({t['key']: t for t in jp_assets.build()['topics']})
            actual = {k: digest(t) for k, t in source_specs.items() if k in expected['jp_stock']}
            self.assertEqual(actual, expected['jp_stock'])
            self.assertEqual({t['key']: digest(t) for t in jp_assets.build()['topics']}, expected['jp_assets'])
        for key, old in expected['generated'].items():
            # 更新前のbuildに残っていた公開済み回も、公開台帳を空にした元材料で照合する。
            # 球団・球場などの一覧の回は毎日の材料の更新で中身が変わる（11/6 team_sfn の主な選手）。
            # 前半/後半の型が触らないので、回が残っていることだけを見る。
            if key in g.LIST_TOPICS:
                continue
            self.assertEqual(digest(source_specs[key]), old, key)

    def test_older_player_prioritized_and_existing_gap_preserved(self):
        import jp_assets
        as_of = datetime.fromisoformat('2026-11-10T18:30:00+09:00')
        a = dict(jp_stock=True, player_ids=['1'])
        b = dict(jp_stock=True, player_ids=['2'])
        ledgers = ({'asset': {'old1': dict(player_ids=['1'], published_at='2026-11-06T18:30:00+09:00'),
                              'old2': dict(player_ids=['2'], published_at='2026-11-08T22:00:00+09:00')}}, {})
        self.assertLess(jp.rotation_priority('a', a, ledgers, as_of), jp.rotation_priority('b', b, ledgers, as_of))
        self.assertTrue(jp.rotation_available('b', b, ledgers, as_of))
        ledgers[0]['asset']['old2']['publish_at'] = '2026-11-09T22:00:00+09:00'
        self.assertFalse(jp.rotation_available('b', b, ledgers, as_of))
        self.assertFalse(jp_assets.available('b', b, ledgers, as_of))

    def test_half_validates_and_uses_existing_duplicate_guards(self):
        import asset_sns
        import next_asset
        for spec in jp.build()['topics']:
            if spec['stock_kind'] != 'half':
                continue
            self.assertTrue(jp.validate_spec(spec))
            self.assertTrue(asset_sns.TOPIC.fullmatch(spec['key']))
            self.assertEqual(next_asset.season_kind(spec['key']), 'season_half')
            self.assertTrue(jp.duplicate(spec, {spec['key']: {}}, {}))
            changed = copy.deepcopy(spec)
            changed['items'][0] = ('記録', '打率.999')
            with self.assertRaises(ValueError):
                jp.validate_spec(changed)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
