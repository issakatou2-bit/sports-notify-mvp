"""日付・ネット・Gitの履歴に依存しない選手の話題の回の検査。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import player_story as s

FIX = Path(__file__).resolve().parent/'fixtures/player_story'
AS_OF = s.stamp('2026-10-14T04:00:00+00:00')
PLAYER = s.JP_PLAYERS_MLB[0]


class StoryTests(unittest.TestCase):
    def build(self, **kwargs):
        values = dict(recap={}, reporters={}, buzz={}, voices={}, stats={}, as_of=AS_OF)
        values.update(kwargs)
        return s.build(**values)

    def fixture(self):
        return self.build(recap=s.read(FIX/'recap_20261013.json'),
                          reporters=s.read(FIX/'reporters_20261014.json'),
                          voices=s.read(FIX/'voices_20261014.json'))

    def stats(self, hits):
        return {'Shohei Ohtani': dict(updated_at=AS_OF.isoformat(), source='MLB固定試験材料',
                    season=dict(ab=400, hits=120),
                    games=[dict(date=f'2026-10-{day}', game_id=str(day), ab=4, hits=h)
                           for day, h in zip((10, 11, 12), hits)])}

    def test_empty_and_fan_only_skip(self):
        self.assertFalse(self.build()['can_make'])
        v = dict(voices=[dict(jp_players=['Shohei Ohtani'], ja='大谷翔平がんばれ！',
                             author='名前を出さない人', url='https://example.test/fan', at=AS_OF.isoformat())])
        self.assertFalse(self.build(voices=v)['can_make'])
        narr = self.fixture()
        narr = self.build(reporters=s.read(FIX/'reporters_20261014.json'), voices=v)
        self.assertTrue(any(seg['kind'] == 'fan' for seg in narr['segments']))
        self.assertNotIn('名前を出さない人', json.dumps(narr, ensure_ascii=False))
        v['voices'][0]['ja'] = '大谷翔平は怪我だから調子を取り戻せない'
        bad = self.build(reporters=s.read(FIX/'reporters_20261014.json'), voices=v)
        self.assertFalse(any(seg['kind'] == 'fan' for seg in bad['segments']))

    def test_single_hitless_game_is_not_a_flow(self):
        self.assertFalse(self.build(recap=s.read(FIX/'recap_20261013.json'))['can_make'])
        self.assertFalse(self.build(stats=self.stats([1, 2, 0]))['can_make'])

    def test_saved_report_is_not_a_decision_and_has_followup(self):
        narr = self.fixture(); s.validate(narr)
        reports = [seg for seg in narr['segments'] if seg['kind'] == 'report']
        self.assertEqual(len(reports), 2)
        self.assertIn('協議する見込みと報じられています', reports[0]['text'])
        self.assertIn('その後の報道によると', reports[1]['text'])
        self.assertIn('予定と報じられています', reports[1]['text'])
        self.assertTrue(all(seg['meta']['report']['source'] and seg['meta']['report']['at'] for seg in reports))
        self.assertTrue(reports[0]['meta']['report']['url'].startswith('https://bsky.app/'))
        self.assertEqual(narr['direction'], 'down')
        self.assertEqual(narr['segments'][-1]['text'], s.RULES['down']['closing'])
        self.assertEqual(sum(seg['kind'] == 'fan' for seg in narr['segments']), 1)
        self.assertNotRegex(''.join(x['text'] for x in narr['segments']), '怪我|けが|疲労|心理|原因')
        bad = deepcopy(narr); bad['segments'][1]['text'] = '第3戦を休みます。'
        with self.assertRaises(ValueError): s.validate(bad)

    def test_numeric_closings_and_pitcher_hits(self):
        down = self.build(stats=self.stats([0, 0, 0])); up = self.build(stats=self.stats([2, 2, 2]))
        self.assertEqual(down['segments'][-1]['text'], s.RULES['down']['closing'])
        self.assertEqual(up['segments'][-1]['text'], s.RULES['up']['closing'])
        self.assertIsNone(s.numeric_flow(dict(PLAYER, type='pitcher'), self.stats([0, 0, 0])['Shohei Ohtani']))
        neutral = self.build(reporters={'posts': s.read(FIX/'reporters_20261014.json')['posts']})
        self.assertEqual(neutral['direction'], 'neutral')

    def test_stale_future_missing_and_negative_reports(self):
        d = s.read(FIX/'reporters_20261014.json')
        for at in ('2026-10-10T00:00:00Z', '2026-10-15T00:00:00Z', None):
            row = dict(d['posts'][0], at=at)
            self.assertFalse(self.build(reporters={'posts': [row]})['can_make'])
        row = dict(d['posts'][0], text='The Dodgers will not discuss sitting Shohei Ohtani in Game 3.')
        self.assertFalse(self.build(reporters={'posts': [row]})['can_make'])
        old = self.stats([0, 0, 0])
        for g in old['Shohei Ohtani']['games']: g['date'] = '2026-09-01'
        self.assertFalse(self.build(stats=old)['can_make'])

    def test_buzz_count_is_not_reporting(self):
        self.assertFalse(self.build(buzz={'players': [{'name': 'Shohei Ohtani', 'mentions': 99}],
                                        'teams': [{'gist': '大谷が不調'}]})['can_make'])

    def test_pitching_flow_uses_earned_runs_and_integer_outs(self):
        p = dict(PLAYER, type='pitcher')
        stats = dict(source='MLB固定試験材料', season=dict(outs=300, er=30),
                     games=[dict(date=f'2026-10-{day}', game_id=str(day), outs=15, er=5)
                            for day in (10, 11, 12)])
        down = s.numeric_flow(p, stats)
        self.assertEqual(down['direction'], 'down')
        self.assertIn('自責15', down['text'])
        for game in stats['games']: game['er'] = 0
        self.assertEqual(s.numeric_flow(p, stats)['direction'], 'up')
        self.assertEqual(s.ip_outs('2.2'), 8)
        with self.assertRaises(ValueError): s.ip_outs('2.3')
        self.assertIsNone(s.numeric_flow(PLAYER, dict(stats, type='pitcher')))

    def test_off_switch_removes_old_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'narr.json'; path.write_text('{}')
            with patch.dict(os.environ, {'COLLESPO_PLAYER_STORY': 'off'}), patch('sys.argv', ['player_story', '--out', str(path)]):
                s.main()
            self.assertFalse(path.exists())

    def test_workflow_and_publish_guard(self):
        text = (s.ROOT/'.github/workflows/player_story.yml').read_text(encoding='utf8')
        self.assertIn("if: vars.COLLESPO_PLAYER_STORY == 'on'", text)
        self.assertIn("vars.PLAYER_STORY_PUBLISH == 'true'", text)
        self.assertNotIn('inputs.publish', text)
        import upload_youtube as u
        with patch.dict(os.environ, {'COLLESPO_PLAYER_STORY': 'on', 'PLAYER_STORY_PUBLISH': 'false'}), patch('sys.argv', ['upload', '--kind', 'player_story']), patch.object(u, 'get_youtube_service', create=True) as api:
            u.main(); api.assert_not_called()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'narr.json'; path.write_text(json.dumps(self.fixture(), ensure_ascii=False), encoding='utf8')
            meta = u.build_metadata(str(path), '2026-10-14', kind='player_story', narration_path=str(path))
            self.assertIn('大谷翔平', meta['snippet']['title'])

    def test_bundled_font_and_expression(self):
        os.environ['COLLESPO_EXPR'] = 'fan'
        import player_story_render as r
        import characters as c
        c.EXPR = 'fan'
        narr = self.fixture(); seg = narr['segments'][0]
        r.r3.set_caption(seg['text'], 5, 30, speaker=2, duo=False)
        r.fan_events.TRACK[:] = [dict(start=0, end=5, decision=dict(face=s.RULES['down']['face'],
              effect=s.RULES['down']['effect'], reason='固定材料', highlights=[]), text=seg['text'], speech=5)]
        r.r3.set_program_clock(1)
        for each in narr['segments']:
            im = r.frame(1, each, narr); r.verify_frame(im)
        self.assertEqual(im.info['fan_expr']['face'], 'jitome')
        self.assertTrue(all(Path(p).is_relative_to(s.ROOT/'assets/fonts') and Path(p).is_file()
                            for p in r.brand.FONT_CANDIDATES['jp']))
        r.fan_events.TRACK.clear(); r.r3.set_program_clock(None)


if __name__ == '__main__':
    unittest.main(argv=['test_player_story'])
