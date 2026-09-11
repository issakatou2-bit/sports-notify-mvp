from datetime import datetime, timezone
import unittest
from public_short import candidate


class CandidateTests(unittest.TestCase):
    def test_selects_same_kind_current_edition(self):
        now=datetime(2026,9,11,11,tzinfo=timezone.utc)
        row={'video_id':'abcdefghijk','published_at':'2026-09-11T09:55:00Z','publish_at':'2026-09-11T10:00:00Z'}
        records={'daily':{'2026-09-11':row},'daily_soccer':{'2026-09-10':row}}
        self.assertEqual(candidate(records,'daily',now),row)
        self.assertIsNone(candidate(records,'daily_soccer',now))
        self.assertIsNone(candidate(records,'morning',now))

    def test_rejects_future_missing_or_invalid_records(self):
        now=datetime(2026,9,11,11,tzinfo=timezone.utc)
        for row in ({}, {'video_id':'../secret'},
                    {'video_id':'abcdefghijk','published_at':'2026-09-10T09:55:00Z'},
                    {'video_id':'abcdefghijk','published_at':'2026-09-11T09:55:00'},
                    {'video_id':'abcdefghijk','published_at':'2026-09-11T09:55:00Z','publish_at':'2026-09-11T12:00:00Z'}):
            with self.subTest(row=row):
                self.assertIsNone(candidate({'daily':{'2026-09-11':row}},'daily',now))


if __name__ == '__main__':
    unittest.main(argv=['test_public_short'])
