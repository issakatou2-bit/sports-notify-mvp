"""停止中の種類が高成績・未計測・音声在庫ありでも選ばれないこと。"""
import contextlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import asset_policy
import next_asset as na
import ui_voice_stock
import healthcheck

PAUSED = ('venue_a', 'mlb_venue', 'team_a', 'season_team_1')
TOPICS = {k: {'style': 'v3'} for k in (*PAUSED, 'legend_1', 'season_player_1')}
TOPICS['season_player_1'].update(title='大谷翔平の成績', source='MLB Stats API', game_type='R')


class PauseTests(unittest.TestCase):
    def select(self, topics, season=0, avg=None):
        output = io.StringIO()
        generator = types.SimpleNamespace(LIST_TOPICS=topics)
        with patch.dict(sys.modules, {'generate_asset_video': generator}), \
                patch.object(na, 'published', return_value=set()), \
                patch.object(na, 'posted_today', return_value=0), \
                patch.object(na, 'measured', return_value=avg or {}), \
                patch.object(ui_voice_stock, 'prioritize', side_effect=lambda x: x), \
                patch.object(na, 'superseded', return_value=False), \
                patch.object(sys, 'argv', ['next_asset', *(['--season', str(season)] if season else [])]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(na.main(), 0)
        return output.getvalue().strip().split()

    def test_topic_and_kind_aliases(self):
        for topic in (*PAUSED, 'asset:venue', 'asset:team', 'asset:season_team'):
            self.assertTrue(asset_policy.paused(topic), topic)
        for topic in ('legend_1', 'season_story_a', 'season_game_1', 'season_league_1', 'ws_history'):
            self.assertFalse(asset_policy.paused(topic), topic)

    def test_unmeasured_and_high_views_cannot_restart(self):
        for avg in ({}, {'team': 99999, 'venue': 99999}):
            self.assertEqual(self.select(TOPICS, avg=avg), [])

    def test_no_replacement_when_only_paused_remain(self):
        self.assertEqual(self.select({k: TOPICS[k] for k in PAUSED}), [])
        self.assertEqual(self.select({'season_team_1': {}}, season=4), [])

    def test_season_budget_stays_an_upper_limit(self):
        self.assertEqual(self.select(TOPICS, season=4), ['season_player_1'])

    def test_stock_does_not_select_paused_topics(self):
        for topic in PAUSED:
            self.assertFalse(ui_voice_stock.eligible(topic, {'style': 'v3'}))
        self.assertTrue(ui_voice_stock.eligible('legend_1', {'style': 'v3'}))

    def test_health_skips_empty_active_inventory_but_keeps_real_alarm(self):
        for topics, expected in (({k: TOPICS[k] for k in PAUSED}, 0), (TOPICS, 1)):
            with patch.object(asset_policy, 'topic_catalog', return_value=topics), \
                    patch.object(healthcheck, 'load', return_value={'assets': {}}):
                self.assertEqual(healthcheck.check_assets()[1], expected)

    def test_monitor_catalog_matches_generator_without_importing_it(self):
        import generate_asset_video as gav
        with patch.dict(sys.modules, {'generate_asset_video': None}):
            self.assertEqual(set(asset_policy.topic_catalog()), set(gav.LIST_TOPICS))

    def test_watchdog_has_no_paused_required_slot(self):
        import missing_kinds
        import post_common
        for key in missing_kinds.OWNER:
            self.assertFalse(asset_policy.paused(key))
        for key, *_ in post_common.DAILY_LINEUP:
            self.assertFalse(asset_policy.paused(key))

    def test_workflow_filters_explicit_topics(self):
        source = (Path(__file__).resolve().parent.parent / '.github/workflows/asset_video.yml').read_text(encoding='utf8')
        self.assertLess(source.index('python scripts/asset_policy.py'), source.index('for t in $TOPICS'))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
