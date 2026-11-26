"""日本時間の集計と自動補充の順序を、保存台帳だけで検査する。"""
from datetime import datetime
import sys
import unittest
from unittest.mock import Mock, patch

import daily_floor

NOW = datetime.fromisoformat('2026-11-26T16:30:00+09:00')


def row(video_id, at, **fields):
    return dict(video_id=video_id, published_at=at, **fields)


class DailyFloor(unittest.TestCase):
    def test_counts_jst_reservations_and_longform(self):
        records = {
            'asset': {
                'before': row('a','2026-11-25T14:59:59Z'),
                'first': row('b','2026-11-25T15:00:00Z'),
                'last': row('c','2026-11-26T14:59:59Z'),
                'after': row('d','2026-11-26T15:00:00Z'),
                'held': row('e','2026-11-26T00:00:00Z', held=True),
                'private': row('f','2026-11-26T00:00:00Z', privacy='private'),
            },
            'soccer_club_topic': {
                'previous_upload': row('g','2026-11-25T12:00:00Z', publish_at='2026-11-26T12:00:00Z', privacy='private'),
                'tomorrow': row('h','2026-11-26T00:00:00Z', publish_at='2026-11-26T15:00:00Z'),
            },
            'longform': {'first':row('i','2026-11-26T05:00:00Z')},
        }
        short, long = daily_floor.count_by_kind(records, NOW.date())
        self.assertEqual(short, {'asset':2, 'soccer_club_topic':1})
        self.assertEqual(long, {'longform':1})

    def test_off_and_publish_disabled_cannot_dispatch(self):
        for enabled, publishing in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, publishing=publishing):
                actions = Mock()
                snapshot = Mock(return_value=({}, {}, {}))
                with patch.object(daily_floor.club, 'candidates', return_value=[{'topic_key':'match:topic'}]):
                    day, shorts, long, available, notes = daily_floor.check_day(
                        snapshot, lambda: NOW, enabled, publishing, actions)
                self.assertEqual((day, shorts, long, available), (NOW.date(), {}, {}, 1))
                self.assertTrue(notes)
                self.assertFalse(actions.mock_calls)

    def test_waits_for_each_run_and_recounts_before_dispatch(self):
        events = []
        records = {'asset': {'existing':row('first',NOW.isoformat())}, 'soccer_club_topic':{}}
        actions = Mock()
        actions.dispatch.side_effect = lambda key, day: events.append(('dispatch',key)) or key

        def wait(run, _deadline):
            events.append(('wait',run))
            records['soccer_club_topic'][run] = row(run,NOW.isoformat())
            return 'success'

        actions.wait.side_effect = wait
        docs = [{'topic_key':'a:keeper'}, {'topic_key':'b:early-goals'}, {'topic_key':'c:rematch'}]
        with patch.object(daily_floor.club, 'candidates', return_value=docs), patch.object(
                daily_floor.club, 'reservation', return_value=NOW):
            _, count, _, _, notes = daily_floor.check_day(lambda **_: (records, {}, {}), lambda: NOW, True, True, actions)
        self.assertEqual(sum(count.values()), 3)
        self.assertEqual(events, [('dispatch','a:keeper'), ('wait','a:keeper'),
                                  ('dispatch','b:early-goals'), ('wait','b:early-goals')])
        self.assertEqual(notes, [])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
