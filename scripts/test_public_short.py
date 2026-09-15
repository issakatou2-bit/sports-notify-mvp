from datetime import datetime, timezone
import unittest
from unittest.mock import patch, MagicMock
import io
import json
import public_short as resolver
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


class ReadinessTests(unittest.TestCase):
    def resolve(self, replies, *, delay=0, kind='daily'):
        row={'video_id':'abcdefghijk','published_at':'2026-09-14T09:57:00Z','publish_at':'2026-09-14T10:00:00Z'}
        now=datetime(2026,9,14,10,delay,tzinfo=timezone.utc)
        def response(reply):
            if isinstance(reply, Exception): return reply
            result=MagicMock()
            result.__enter__.return_value=io.StringIO(json.dumps({'items':reply}))
            return result
        with patch.dict(resolver.os.environ, {'YOUTUBE_API_KEY':'TEST_SECRET'}), \
             patch.object(resolver.Path,'read_text',return_value=json.dumps({'daily':{'2026-09-14':row}})), \
             patch.object(resolver.urllib.request,'urlopen',side_effect=[response(r) for r in replies]) as fetch, \
             patch.object(resolver.time,'sleep') as sleep, \
             patch('sys.stdout',new_callable=io.StringIO) as log:
            result=resolver.public_short(kind,now=now)
        self.assertNotIn('TEST_SECRET',log.getvalue())
        return result,fetch.call_count,sleep.call_count

    def video(self, privacy='public', embeddable=True, channel=resolver.CHANNEL):
        return [{'id':'abcdefghijk','status':{'privacyStatus':privacy,'embeddable':embeddable},
                 'snippet':{'channelId':channel,'title':'Current video'}}]

    def test_scheduled_transition_confirms_before_returning(self):
        result,calls,sleeps=self.resolve([self.video('private'),self.video()])
        self.assertEqual(result['video_id'],'abcdefghijk')
        self.assertEqual((calls,sleeps),(2,1))

    def test_retry_exhaustion_never_returns_unconfirmed_video(self):
        for replies in ([[],[],[]], [self.video('private')]*3, [self.video(embeddable=False)]*3,
                        [OSError('https://example.invalid/?key=TEST_SECRET')]*3):
            with self.subTest(replies=replies):
                self.assertEqual(self.resolve(replies),(None,3,2))

    def test_other_channel_never_retried(self):
        self.assertEqual(self.resolve([self.video(channel='other')]),(None,1,0))

    def test_no_wait_outside_release_window_or_without_candidate(self):
        self.assertEqual(self.resolve([self.video('private')],delay=3),(None,1,0))
        self.assertEqual(self.resolve([],kind='daily_soccer'),(None,0,0))


if __name__ == '__main__':
    unittest.main(argv=['test_public_short'])
