"""前回調査の重複・匿名化を保存材料で再現する回帰試験。外部APIは呼ばない。"""
import copy
from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fan_privacy as privacy
import player_publications as players
import soccer_publications as flashes
import soccer_now as now
import soccer_goal_short as goal

ROOT = Path(__file__).resolve().parents[1]


class SoccerTests(unittest.TestCase):
    def setUp(self):
        self.boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        self.summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        self.clock = now.results.utc('2026-09-20T17:15:00Z')
        self.data = now.build(self.boards, self.summaries, self.clock, {}, goal_short=None)[0][0]
        self.ident = self.data['games'][0]['id']

    def test_goal_priority_and_pending_across_both_builders(self):
        self.assertEqual(now.build(self.boards, self.summaries, self.clock, {})[0], [])
        self.assertEqual(len(goal.build(self.boards, self.summaries, self.clock, {})[0]), 1)
        for kind in flashes.KINDS:
            for status in ('pending', 'uploaded'):
                ledger = {self.ident: dict(kind=kind, status=status)}
                self.assertEqual(goal.build(self.boards, self.summaries, self.clock, ledger)[0], [])
                self.assertEqual(now.build(self.boards, self.summaries, self.clock, ledger, goal_short=False)[0], [])
        no_goal = copy.deepcopy(self.data)
        for p in no_goal['games'][0]['players']:
            p.update(goals=0, assists=0)
        self.assertTrue(flashes.eligible(no_goal, {}))
        self.assertFalse(flashes.eligible(no_goal, {}, goal_short=True))

    def test_legacy_ledgers_merge_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'data').mkdir()
            for kind in flashes.KINDS:
                (root/f'data/{kind}_receipts.json').write_text(json.dumps({kind: dict(status='pending')}), encoding='utf8')
            with patch.object(flashes, 'ROOT', root):
                self.assertEqual(set(flashes.load()), set(flashes.KINDS))

    def test_concurrent_receipt_claim_cannot_overwrite_another_owner(self):
        from merge_json_conflict import merge_three_way
        path = flashes.PATH
        first = {self.ident:dict(status='pending',kind='soccer_now',at='first')}
        second = {self.ident:dict(status='pending',kind='soccer_goal_short',at='second')}
        with self.assertRaisesRegex(ValueError,'別の速報予約'):
            merge_three_way({},first,second,path)
        uploaded = copy.deepcopy(first);uploaded[self.ident].update(status='uploaded',video_id='video')
        self.assertEqual(merge_three_way(first,first,uploaded,path),uploaded)
        self.assertEqual(set(merge_three_way({},first,{'other':second[self.ident]},path)),{self.ident,'other'})

    def test_publish_rechecks_after_sanity_before_pending_or_upload(self):
        with patch.dict(os.environ, {'COLLESPO_SOCCER_GOAL_SHORT':'on'}), \
                patch.object(now, 'datetime') as clock, \
                patch.object(flashes, 'load', side_effect=[{}, {self.ident:dict(status='pending')}]) as load, \
                patch.object(now.subprocess, 'run') as sanity, \
                patch.object(now, 'checkpoint_receipt') as checkpoint:
            clock.now.return_value = self.clock
            now.publish(self.data, 'unused', {}, goal_short=True)
            self.assertEqual(load.call_count, 2)
            self.assertTrue(all(c.kwargs['refresh'] for c in load.call_args_list))
            sanity.assert_called_once()
            checkpoint.assert_not_called()

    def test_goal_opening_is_one_scene_in_v5_and_v6(self):
        import soccer_results_render as render
        for look in ('v5', 'v6'):
            with patch.dict(os.environ, {'COLLESPO_SOCCER_LOOK':look, 'COLLESPO_HOST_SPLIT':''}):
                narr = render.production_narration(self.data, goal_short=True)
            self.assertEqual([s['kind'] for s in narr['segments'][:2]], ['intro', 'result'])
            self.assertEqual(sum(s['kind']=='intro' for s in narr['segments']), 1)

    def test_morning_retains_all_matches_but_only_one_line_for_flash(self):
        import soccer_results_render as story
        data = copy.deepcopy(self.data)
        second = copy.deepcopy(data['games'][0]); second['id'] = 'not-flashed'
        for p in second['players']: p['event_id'] = second['id']
        data['games'].append(second); data['players'] += second['players']
        # A preview followup subset must not remove other results.
        data['preview_followup'] = dict(games=[dict(event_id=self.ident)])
        with patch.object(flashes, 'load', return_value={self.ident:dict(status='pending')}), \
                patch.dict(os.environ, {'COLLESPO_SOCCER_LOOK':'v6'}):
            narr = story.production_narration(data)
        brief = [s for s in narr['segments'] if s['kind']=='flash-results']
        self.assertEqual(brief[0]['meta']['event_ids'], [self.ident])
        self.assertEqual(len(brief[0]['meta']['lines']), 1)
        with patch.dict(os.environ, {'COLLESPO_SOCCER_LOOK':'v6'}):
            im = story.frame(3, brief[0], data)
            self.assertFalse(story.validate_frame(im, data, story.resolve_clubs(data)))
        self.assertFalse(any(s['meta'].get('event_id')==self.ident for s in narr['segments']))
        self.assertTrue(any('not-flashed' in s['meta'].get('event_ids',[]) for s in narr['segments']))
        self.assertFalse(any(s['kind']=='followup-detail' for s in narr['segments']))

    def test_now_preserves_v6_and_uses_morning_stats(self):
        import short_saved_render as saved
        import soccer_stats
        with patch.dict(os.environ, {'COLLESPO_SOCCER_LOOK':'v6'}):
            saved.setup()
            self.assertEqual(os.environ['COLLESPO_SOCCER_LOOK'], 'v6')
            data = copy.deepcopy(self.data)
            data['games'][0]['players'][0].update(position='FW', minutes=90, shots=3, on_target=2)
            data['players'] = data['games'][0]['players']
            narr = now.narration(data)
            self.assertTrue(any(s['kind']=='player-stats' for s in narr['segments']))
            self.assertNotIn('得点は2点', str(narr))
            for s in narr['segments']:
                im = now.frame(data, 3, s)
                self.assertTrue(im.info.get('soccer_readable'))
            self.assertTrue(soccer_stats.attack_label(data['players'][0]).startswith('攻撃関与 '))


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 10, 26, tzinfo=timezone.utc)

    def test_both_directions_exact_boundary_reservation_and_other_player(self):
        for kind in ('player_story', 'season_player'):
            for days, expected in ((6, True), (7, True), (7.001, False), (-1, False)):
                record = dict(player_id='660271', published_at=(self.at-timedelta(days=days)).isoformat())
                ledgers = ({'player_story':{'day':record}}, {}) if kind=='season_player' else ({}, {'assets':{'season_player_660271':record}})
                self.assertEqual(players.recent('660271', kind, self.at, ledgers), expected)
                self.assertFalse(players.recent('808967', kind, self.at, ledgers))

    def test_scheduled_publication_uses_reserved_time(self):
        row = dict(published_at=(self.at-timedelta(days=8)).isoformat(), publish_at=(self.at+timedelta(days=1)).isoformat())
        self.assertTrue(players.recent('660271','player_story',self.at,({}, {'assets':{'season_player_660271':row}})))

    def test_selection_skips_conflicting_story(self):
        import player_story as story
        from test_player_story import AS_OF, FIX
        ledger = ({}, {'assets':{'season_player_660271':dict(published_at=AS_OF.isoformat())}})
        with patch.object(players, 'load', return_value=ledger):
            result = story.build(story.read(FIX/'recap_20261013.json'), story.read(FIX/'reporters_20261014.json'), {}, {}, {}, AS_OF)
        self.assertFalse(result['can_make'])

    def test_final_publication_refreshes_both_ledgers(self):
        for kind in ('player_story','season_player'):
            row = dict(player_id='660271', published_at=self.at.isoformat())
            ledger = ({'player_story':{'day':row}}, {}) if kind=='season_player' else ({}, {'assets':{'season_player_660271':row}})
            with patch.object(players, 'load', return_value=ledger) as load:
                self.assertIsNone(players.publication('660271', kind, self.at))
                load.assert_called_once_with(refresh=True)
            with patch.object(players, 'load', return_value=({}, {})):
                self.assertEqual(players.publication('660271', kind, self.at)['player_id'], '660271')

    def test_season_selection_skips_recent_story(self):
        import io
        import next_asset
        from types import SimpleNamespace
        import sys
        args = SimpleNamespace(published='unused', season=1)
        topics = {'season_player_660271':{}, 'season_player_808967':{}}
        row = dict(player_id='660271', published_at=datetime.now(timezone.utc).isoformat())
        with patch.dict(sys.modules, {'generate_asset_video':SimpleNamespace(LIST_TOPICS=topics)}), \
                patch.object(next_asset, 'published', return_value=set()), \
                patch.object(next_asset, 'posted_today', return_value=0), \
                patch.object(players, 'load', return_value=({'player_story':{'day':row}}, {})), \
                patch('ui_voice_stock.prioritize', side_effect=lambda x:x), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            next_asset.pick_season(args)
        self.assertEqual(output.getvalue().strip(), 'season_player_808967')

    def test_legacy_story_title_and_jst_week(self):
        ledger = ({'player_story':{'day':dict(title='大谷翔平のいまの流れ', published_at=self.at.isoformat())}}, {})
        self.assertTrue(players.recent('660271', 'season_player', self.at, ledger))
        self.assertEqual(players.record('660271', self.at)['player_week_start'], '2026-10-26')
        self.assertTrue(players.recent(None, 'player_story', self.at, ({}, {})))


class PrivacyTests(unittest.TestCase):
    def assert_private(self, value):
        visible = html.unescape(str(value))
        for marker in ('Reddit', 'reddit', 'r/baseball', 'NamedPoster', '@架空の投稿者'):
            self.assertNotIn(marker, visible)

    def test_comment_at_name_never_enters_public_summary(self):
        import correction_comments as cc
        from test_comment_seeds import fake_get, thread, NOW
        body = '@架空の投稿者さん 数字が間違っています'
        payload = cc.collect(get=fake_get([thread(text=body)]), now=NOW)
        summary = cc.render(payload)
        self.assert_private(summary)
        self.assertNotIn(body, summary)
        self.assertIn('誤り・訂正', summary)
        self.assertIn('動画ID', summary)
        self.assertIn('件数: 1', summary)

    def test_all_public_consumers_reject_identifying_quote_text(self):
        import reddit_reaction
        import player_story
        from test_player_story import AS_OF, FIX
        for text in ('Redditで応援', 'r/baseball最高', '@NamedPoster がんばれ！', 'u/NamedPoster 頑張れ'):
            self.assertFalse(reddit_reaction.short_translation('Great game', text))
            row = dict(ja=text, original='Great game', jp_players=['Shohei Ohtani'], url='https://www.reddit.com/r/baseball/comments/x/', at=AS_OF.isoformat())
            self.assertEqual(privacy.voices({'voices':[row]})['voices'], [])
            n = player_story.build(player_story.read(FIX/'recap_20261013.json'), player_story.read(FIX/'reporters_20261014.json'), {}, {'voices':[row]}, {}, AS_OF, publication_ledgers=({}, {}))
            self.assertTrue(n['can_make'])
            self.assertFalse(any(s['kind']=='fan' for s in n['segments']))

    def test_public_description_preserves_official_handles(self):
        self.assertEqual(privacy.description('https://www.youtube.com/@MLB'), 'https://www.youtube.com/@MLB')
        self.assert_private(privacy.description('Reddit r/baseball https://www.reddit.com/r/baseball/comments/x/'))

    def test_japan_reacts_translation_cannot_reintroduce_names(self):
        import japan_reacts
        player = dict(name_en='Shohei Ohtani', sport='MLB')
        row = dict(kind='reddit', source='r/baseball', original='いい試合', url='https://www.reddit.com/r/baseball/comments/x/')
        with patch.object(japan_reacts, 'translate', return_value=dict(english='Great game', review={})), patch.object(japan_reacts, 'log_report'):
            n = japan_reacts.from_rows(player,[row],None)
        self.assert_private([s['text']+s.get('caption_en','') for s in n['segments']])
        with patch.object(japan_reacts, 'translate', return_value=dict(english='Reddit @NamedPoster says great game', review={})), patch.object(japan_reacts, 'log_report'):
            self.assertIsNone(japan_reacts.from_rows(player,[row],None))

    def test_reddit_reaction_visible_source_and_player_story_frame(self):
        import reddit_reaction
        import player_story_render as render
        material = dict(updated_at='2026-10-14T06:00:00Z', voices=[dict(original='Great game', at='2026-10-14T06:00:00Z', url='https://www.reddit.com/r/baseball/comments/x/')])
        n = reddit_reaction.program(material, [dict(original='Great game', ja='いい試合だった', reviewed=True)], dict(source_title='Rays Guardians', board='baseball'))
        reddit_reaction.validate(n)
        seg = next(s for s in n['segments'] if s['kind']=='fan')
        self.assertEqual(seg['meta']['source'], privacy.LABEL)
        __import__('short_saved_render').setup()
        im = render.frame(3, seg, n)
        self.assert_private([r.get('text') for r in im.info['v3_layout']])

    def test_morning_renderer_and_loader_never_show_board_or_author(self):
        import local_voices
        import generate_morning_short as morning
        import short_saved_render
        from PIL import ImageDraw
        material = dict(updated_at=datetime.now(timezone.utc).isoformat(), source='r/baseball', source_url='https://www.reddit.com/r/baseball/',
                        voices=[dict(title='Great game', ja='いい試合', source='Reddit', url='https://www.reddit.com/r/baseball/comments/x/', author='NamedPoster')])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'voices.json';path.write_text(json.dumps(material),encoding='utf8')
            public=local_voices.load(str(path))
        self.assertEqual(public['source'],privacy.LABEL)
        drawn=[]; original=ImageDraw.ImageDraw.text
        def text(draw, xy, value, *args, **kwargs):
            drawn.append(str(value))
            return original(draw,xy,value,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',new=text), patch.object(morning,'font',side_effect=short_saved_render.bundled_font):
            morning.render_voices(1,material)
        self.assert_private(drawn)
        self.assertTrue(any(privacy.LABEL in text for text in drawn))

    def test_other_quote_consumers_use_anonymous_material(self):
        import comment_render
        import ps_game_story
        row = dict(title='Great game',ja='いい試合',url='https://www.reddit.com/r/baseball/comments/x/',
                   source='r/baseball',at='2026-10-26T00:00:00Z',matchup='AWAY HOME')
        material = dict(source='r/baseball',voices=[row])
        self.assert_private(comment_render.strip_for_voices(material))
        self.assertEqual(comment_render._voices_source(material)[0],privacy.LABEL)
        feed=dict(gameData=dict(teams=dict(away=dict(teamName='AWAY'),home=dict(teamName='HOME'))))
        picked=ps_game_story.pick_voice(material,feed,'2026-10-25',{}, {}, {}, [])
        self.assertEqual(picked['source'],privacy.LABEL)
        named=dict(row,ja='NamedPoster が応援',author='NamedPoster')
        self.assertIsNone(ps_game_story.pick_voice(dict(voices=[named]),feed,'2026-10-25',{}, {}, {}, []))
        self.assertEqual(privacy.material(dict(voices=[named]))['voices'],[])
        public=privacy.material(material)
        self.assertEqual(public['source'],privacy.LABEL)
        self.assertEqual(public['voices'][0]['url'],row['url'])
        self.assertEqual(material['source'],'r/baseball')

    def test_japan_reacts_and_morning_saved_material_source(self):
        import japan_reacts
        row = dict(kind='reddit', source='r/baseball / Reddit / NamedPoster', original='いい試合', url='https://www.reddit.com/r/baseball/comments/x/')
        data = dict(title='Reactions', date='2026-10-26', sources=[row], segments=[dict(speaker=2)], saved_preview=False)
        meta = japan_reacts.metadata(data)
        self.assert_private(meta)
        self.assertIn(privacy.LABEL, meta['description'])
        public = privacy.voices(dict(source='r/baseball', source_url=row['url'], voices=[dict(row, ja='いい試合')]))
        self.assert_private([public['source'],public['source_url'],public['voices'][0]['source'],public['voices'][0]['ja'],public['voices'][0]['url']])
        self.assertEqual(public['voices'][0]['source'], privacy.LABEL)
        self.assertEqual(row['url'], 'https://www.reddit.com/r/baseball/comments/x/')


if __name__ == '__main__':
    unittest.main(argv=[__file__])
