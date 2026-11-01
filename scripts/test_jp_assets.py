"""実材料の数・比較の範囲・複数選手の重複・日次選択を確認する。"""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import asset_policy
import jp_assets as jp
import next_asset as na
import player_publications as pp


class JapaneseAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topics = jp.build()['topics']
        cls.now = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)

    def test_nine_and_only_requested(self):
        self.assertEqual(len(self.topics), 9)
        self.assertEqual(sum(t['stock_kind'] == 'compare' for t in self.topics), 5)
        self.assertEqual({t['key'] for t in self.topics if t['stock_kind'] == 'momentum'}, jp.RUN_KEYS)
        for t in self.topics:
            self.assertTrue(asset_policy.selectable(t['key'], t))
            self.assertEqual(t['game_type'], 'R')
            self.assertEqual(len(t['items']), 3)
            self.assertFalse(any(x in str(t['items']) for x in ('Savant', 'Statcast', '球団の結末')))

    def test_actual_pairs_and_values(self):
        comparisons = jp.comparisons()
        self.assertEqual({tuple(t['player_ids']) for t in comparisons}, {(str(a), str(b)) for a, b, _ in jp.PAIRS})
        batter = next(t for t in comparisons if '660271' in t['player_ids'])
        self.assertEqual(batter['comparison_values']['本塁打'], ['30', '26'])
        self.assertEqual(batter['comparison_values']['打点'], ['81', '86'])
        for t in comparisons:
            self.assertNotIn('2026年比較', t['title'])
            self.assertTrue(all(line in t['intro'] for line in t['heading'].splitlines()))

    def test_non_rs_and_mixed_roles_fail_closed(self):
        data = jp.stock.read(jp.ROOT/'data/season_topics.json')
        for mutate in ('source', 'game_type', 'role', 'missing', 'year'):
            changed = copy.deepcopy(data)
            row = next(t for t in changed['topics'] if t.get('player_id') == 808967)
            if mutate == 'source':
                changed['source'] = '報道'
            elif mutate == 'game_type':
                row['game_type'] = 'P'
            elif mutate == 'role':
                row['items'] = [('今季の成績', '30本塁打 81打点 OPS.889')]
            elif mutate == 'year':
                row['title'] = row['title'].replace('2026', '2025')
            else:
                row['items'] = []
            with patch.object(jp.stock, 'read', return_value=changed):
                self.assertFalse(any('808967' in t['player_ids'] for t in jp.comparisons()))

    def test_clubs_are_affiliation_only(self):
        for t in jp.club_topics():
            self.assertTrue(t['affiliation_only'])
            self.assertIn('が所属する', t['title'])
            self.assertFalse(any(word in t['intro'] for word in ('出場', '登板', '貢献', '活躍')))
        dodgers = next(t for t in jp.club_topics() if str(t.get('team_id')) == '119')
        self.assertEqual(jp.ids(dodgers['key'], dodgers), {'808963', '660271', '808967'})

    def test_either_comparison_player_in_either_ledger_blocks(self):
        t = jp.comparisons()[0]
        for pid in t['player_ids']:
            for source in ('video', 'asset'):
                row = dict(player_id=pid, published_at=(self.now-timedelta(days=2)).isoformat())
                ledgers = ({'player_story': {'v': row}}, {}) if source == 'video' else ({}, {'assets': {'season_player_'+pid: row}})
                self.assertFalse(jp.available(t['key'], t, ledgers, self.now))

    def test_all_affiliated_players_block(self):
        t = next(t for t in jp.club_topics() if str(t.get('team_id')) == '119')
        for pid in t['player_ids']:
            ledgers = ({'player_story': {'v': dict(player_id=pid, published_at=self.now.isoformat())}}, {})
            self.assertFalse(jp.available(t['key'], t, ledgers, self.now))

    def test_new_publication_blocks_player_story_and_assets(self):
        for t in self.topics:
            row = dict(player_ids=t['player_ids'], title=t['title'], published_at=self.now.isoformat())
            for pid in t['player_ids']:
                for kind in ('player_story', 'season_player'):
                    self.assertTrue(pp.recent(pid, kind, self.now, ({}, {'assets': {t['key']: row}})))
                    self.assertTrue(pp.recent(pid, kind, self.now, ({'asset': {t['key']: row}}, {})))

    def test_seven_day_boundary_and_future_reservation(self):
        t = jp.comparisons()[0]
        for days, expected in ((7, False), (8, True), (-2, False)):
            row = dict(player_ids=[t['player_ids'][1]], publish_at=(self.now-timedelta(days=days)).isoformat())
            self.assertEqual(jp.available(t['key'], t, ({}, {'assets': {'season_compare_2026_1_2': row}}), self.now), expected)

    def test_done_and_extended_run_not_reissued(self):
        for t in self.topics:
            self.assertFalse(jp.available(t['key'], t, ({}, {'assets': {t['key']: {}}}), self.now))
        t = next(t for t in self.topics if t['stock_kind'] == 'momentum')
        key = f"season_momentum_rs2026_{t['team_id']}_1_{t['game_ids'][0]}"
        self.assertFalse(jp.available(t['key'], t, ({}, {'assets': {key: {}}}), self.now))

    def select(self, records=None, count=3):
        import generate_asset_video as generator
        catalog = {t['key']: t for t in self.topics}
        with tempfile.TemporaryDirectory(dir='build') as tmp:
            path = Path(tmp)/'assets.json'
            path.write_text(json.dumps({'assets': records or {}}), encoding='utf8')
            out = io.StringIO()
            with patch.object(generator, 'LIST_TOPICS', catalog), patch.object(pp, 'load', return_value=({}, {'assets': records or {}})), contextlib.redirect_stdout(out):
                na.pick_season(types.SimpleNamespace(published=str(path), season=count))
            return out.getvalue().strip().split()

    def test_no_same_kind_or_player_in_batch(self):
        keys = self.select()
        self.assertEqual(len(keys), 3)
        self.assertEqual(len({na.season_kind(k) for k in keys}), 3)
        specs = {t['key']: t for t in self.topics}
        all_ids = [pid for k in keys for pid in jp.ids(k, specs[k])]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_same_day_kind_and_total_limit(self):
        now = datetime.now(timezone.utc).isoformat()
        records = {'season_compare_2026_1_2': dict(published_at=now)}
        keys = self.select(records)
        self.assertLessEqual(len(keys), 2)
        self.assertFalse(any(na.season_kind(k) == 'season_compare' for k in keys))
        for i in range(2):
            records[f'season_other_{i}'] = dict(published_at=now)
        self.assertEqual(self.select(records), [])

    def test_reserved_publication_day_counts_toward_limit(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory(dir='build') as tmp:
            path = Path(tmp)/'assets.json'
            path.write_text(json.dumps({'assets': {'season_compare_1_2': dict(
                published_at=(now-timedelta(days=1)).isoformat(), publish_at=now.isoformat())}}), encoding='utf8')
            self.assertEqual(na.posted_today(str(path), kinds={'season'}, count=True), 1)
            # 旧assets側に予約日がなくても、videos側に保存された予約日を残す。
            path.write_text(json.dumps({'assets': {'season_compare_1_2': dict(
                published_at=(now-timedelta(days=1)).isoformat())}}), encoding='utf8')
            extra = {'season_compare_1_2': dict(publish_at=now.isoformat())}
            self.assertEqual(na.posted_today(str(path), kinds={'season'}, count=True, extra=extra), 1)
            self.assertIn('season_compare', na.season_kinds_today(str(path), extra=extra))

    def test_authored_japanese_has_no_replacement_runs(self):
        # Windowsのパイプで日本語を失った実例を再発検査へ戻す。
        import re
        for name in ('jp_assets.py', 'render_jp_asset_samples.py', 'generated_topics.py',
                     'player_publications.py', 'upload_youtube.py', 'test_trial_readiness.py'):
            text = (jp.ROOT/'scripts'/name).read_text(encoding='utf8')
            self.assertFalse(re.search(r'\?{3,}|\ufffd', text), name)

    def test_comparison_opening_keeps_each_whole_name(self):
        from PIL import Image, ImageDraw
        import review_render_v3 as r3
        names = {str(t['player_id']): t['jp'] for t in jp.stock.read(jp.ROOT/'data/season_topics.json')['topics'] if t.get('jp')}
        d = ImageDraw.Draw(Image.new('RGB', (8, 8)))
        for spec in jp.comparisons():
            lines, _ = r3._lines(d, spec['hook'], 96, r3.SAFE_RIGHT-r3.LEFT, 2)
            self.assertEqual(len(lines), 2)
            for pid in spec['player_ids']:
                self.assertTrue(any(names[pid] in line for line in lines))

    def test_upload_checks_actual_future_publication_day(self):
        spec = jp.comparisons()[0]
        tomorrow = self.now+timedelta(days=1)
        row = dict(published_at=self.now.isoformat(), publish_at=tomorrow.isoformat())
        ledgers = ({'asset': {'season_compare_2026_1_2': row}}, {})
        self.assertTrue(jp.publication_available(spec['key'], spec, ledgers, self.now))
        self.assertFalse(jp.publication_available(spec['key'], spec, ledgers, tomorrow))
        ledgers = ({}, {'assets': {f'season_other_{i}': row for i in range(3)}})
        self.assertFalse(jp.publication_available(spec['key'], spec, ledgers, tomorrow))

    def test_comparison_body_heading_has_no_orphan_metric(self):
        from PIL import Image, ImageDraw
        import review_render_v3 as r3
        names = {str(t['player_id']): t['jp'] for t in jp.stock.read(jp.ROOT/'data/season_topics.json')['topics'] if t.get('jp')}
        d = ImageDraw.Draw(Image.new('RGB', (8, 8)))
        for spec in jp.comparisons():
            lines, _ = r3._lines(d, spec['heading'], 52, r3.SAFE_RIGHT-r3.LEFT, 2)
            for line in lines:
                self.assertTrue(any(names[pid] in line for pid in spec['player_ids']), (spec['key'], line))
            for pid in spec['player_ids']:
                self.assertTrue(any(names[pid] in line for line in lines))

    def test_unpushed_success_in_same_run_counts_toward_budget(self):
        stamp = self.now.isoformat()
        fresh = ({}, {'assets': {f'season_player_{i}': dict(publish_at=stamp) for i in (1, 2)}})
        local = ({}, {'assets': {'season_game_3': dict(publish_at=stamp)}})
        with patch.object(pp, 'load', side_effect=[fresh, local]) as load:
            ledgers = jp.publication_ledgers()
        self.assertEqual(load.call_args_list, [unittest.mock.call(refresh=True), unittest.mock.call()])
        spec = jp.comparisons()[0]
        self.assertFalse(jp.publication_available(spec['key'], spec, ledgers, self.now))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
