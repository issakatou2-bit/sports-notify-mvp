"""前の晩の注目試合の記録を、翌朝の結果ショートの前提に足す部品。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import soccer_stake_followup as followup

START = '2026-11-21T15:00:00Z'
START_UTC = '2026-11-21T15:00:00+00:00'
BEFORE = '2026-11-20T15:00:00Z'


def row(position, team, points):
    return dict(position=position, team=team, points=points)


def doc(event_id='501', start=START, kind='残留争い', gap=2, home=None, away=None):
    return dict(event_id=event_id, title='残留争いの直接対決 #Shorts',
                stake=dict(kind=kind, gap=gap, home=home or row(17, 'Home FC', 9),
                           away=away or row(20, 'Away FC', 7)),
                game=dict(start_time_utc=start))


def game(gid='501', start=START_UTC, score=(1, 2), home_jp='ホーム', away_jp='アウェイ'):
    return dict(id=gid, home=dict(name_en='Home FC', name_jp=home_jp),
                away=dict(name_en='Away FC', name_jp=away_jp),
                score=dict(home=score[0], away=score[1]), start_utc=start)


def history(item):
    return {item['event_id']: item}


class StakeFollowupTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(followup.club_display_names, 'lookup', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lower_side_wins_and_overtakes(self):
        item = followup.record(doc(), 'v1', BEFORE)
        data = dict(games=[game()])
        attached = followup.attach(data, history(item))
        self.assertNotIn('stake_followup', data)
        entry = attached['stake_followup']['501']
        self.assertEqual(entry['record'], item)
        self.assertEqual(entry['premise'], dict(
            lead='残留争いの直接対決でした。',
            after='アウェイが勝点10で、ホームの9を上回りました。'))

    def test_equal_points_draw_stays_level(self):
        item = followup.record(doc(kind='境目', gap=0,
                                   home=row(15, 'Home FC', 9), away=row(16, 'Away FC', 9)),
                               'v1', BEFORE)
        attached = followup.attach(dict(games=[game(score=(1, 1))]), history(item))
        self.assertEqual(attached['stake_followup']['501']['premise'], dict(
            lead='順位の境目が懸かった試合でした。',
            after='勝点は10で並んだままです。'))

    def test_no_attach_for_mismatched_time_or_window(self):
        item = followup.record(doc(), 'v1', BEFORE)
        cases = (
            ('開始時刻が違う', game(start='2026-11-21T16:00:00+00:00'), item),
            ('記録が開始後', game(), dict(item, as_of='2026-11-21T16:00:00Z')),
            ('48時間より前', game(), followup.record(doc(), 'v1', '2026-11-19T14:00:00Z')),
        )
        for label, g, rec in cases:
            with self.subTest(label):
                self.assertNotIn('stake_followup', followup.attach(dict(games=[g]), history(rec)))

    def test_save_is_idempotent_and_rejects_other_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'soccer_stake_history.json'
            followup.save(doc(), 'v1', BEFORE, path=path)
            followup.save(doc(), 'v1', BEFORE, path=path)
            saved = followup.load(path)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved['501']['video_id'], 'v1')
            text = path.read_text(encoding='utf-8')
            self.assertTrue(text.endswith('\n'))
            self.assertIn('\n  "501": {', text)
            with self.assertRaises(ValueError):
                followup.save(doc(), 'v2', BEFORE, path=path)

    def test_validate_rejects_changed_premise(self):
        item = followup.record(doc(), 'v1', BEFORE)
        attached = followup.attach(dict(games=[game()]), history(item))
        followup.validate(attached)
        attached['stake_followup']['501']['premise']['after'] = '勝点は変わりません。'
        with self.assertRaises(ValueError):
            followup.validate(attached)

    def test_record_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            followup.record(doc(), '', BEFORE)
        with self.assertRaises(ValueError):
            followup.record(doc(), 'v1', START)
        bad = doc()
        bad['stake']['home']['points'] = '9'
        with self.assertRaises(ValueError):
            followup.record(bad, 'v1', BEFORE)
        bad = doc()
        bad['stake']['away']['position'] = True
        with self.assertRaises(ValueError):
            followup.record(bad, 'v1', BEFORE)

    def test_load_missing_or_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing.json'
            with patch('builtins.print') as output:
                self.assertEqual(followup.load(missing), {})
            output.assert_not_called()
            broken = Path(tmp) / 'broken.json'
            broken.write_text('{oops', encoding='utf-8')
            with patch('builtins.print') as output:
                self.assertEqual(followup.load(broken), {})
            output.assert_called_once_with(followup.BROKEN)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])

class WordingAndStoryTest(unittest.TestCase):
    def test_close_match_kind_is_not_doubled(self):
        item = followup.record(doc(kind='順位の近い直接対決'), 'v1', BEFORE)
        self.assertEqual(followup.premise(item, game())['lead'], '順位の近い直接対決でした。')

    def test_result_story_and_title_carry_the_premise(self):
        import json, os
        import soccer_title_v2 as v2
        data = json.loads((Path(__file__).resolve().parent/'fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf8'))
        env = dict(COLLESPO_SOCCER_TITLE_V2='on')
        with patch.dict(os.environ, env):
            plain = v2.result_focus(data)
        g = plain['game']
        item = dict(event_id=str(g['id']), video_id='v1', title='t', kind='残留争い', gap=2,
                    as_of='2026-10-24T10:00:00+00:00', start_utc=g['start_utc'].replace('Z', '+00:00'),
                    home=dict(team=g['home']['name_en'], position=17, points=9),
                    away=dict(team=g['away']['name_en'], position=20, points=7))
        staked = followup.attach(data, {item['event_id']: item})
        followup.validate(staked)
        with patch.dict(os.environ, env):
            title = v2.results_title(staked)
            narr = v2.result_narration(staked)
        self.assertIn('｜残留争い ', title)
        first = narr['segments'][0]['text']
        premise = staked['stake_followup'][item['event_id']]['premise']
        self.assertTrue(first.endswith(premise['lead'] + premise['after']), first)
        self.assertNotIn('stake_followup', data)
