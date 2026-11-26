"""朝の保存試合で、話題選定・上限・公開台帳を検査する。"""
from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import metan_tone
import soccer_club_topics as club
import short_content
from test_soccer_results import fixture
import upload_youtube
from duo import METAN

NOW = datetime.fromisoformat('2026-09-20T12:00:00+09:00')


class ClubTopics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boards, summaries = fixture()
        cls.pool = club.collect(club.results.build(boards, summaries, '2026-09-19'), summaries)

    def test_saved_games_produce_verified_dialogue(self):
        docs = club.candidates(self.pool, {}, NOW)
        self.assertEqual([d['topic_key'] for d in docs], [
            '401884786:late-goal', '401884787:equalizer', '401884786:late-winner'])
        for doc in docs:
            self.assertEqual(club.check(doc), [])
            self.assertGreaterEqual(len(short_content.information(doc)), 3)
            self.assertTrue(all(not metan_tone.problems(s['text']) for s in doc['segments'] if s['speaker'] == METAN))
            self.assertNotIn('、', doc['title'])
        forged = deepcopy(docs[0])
        forged['title'] = '未照合の題'
        self.assertTrue(club.check(forged))
        self.assertFalse(club.candidates(self.pool, {}, NOW + timedelta(days=1)))

    def test_skips_games_without_appearance_and_unsupported_leagues(self):
        boards, summaries = fixture()
        data = club.results.build(boards, summaries, '2026-09-19')
        game = next(g for g in data['games'] if g['id'] == '401884786')
        for competition in ('CL', 'EL', 'UECL', 'FAC'):
            with self.subTest(competition=competition):
                selected = club.collect(dict(data, games=[dict(game, league=competition)]), summaries)
                self.assertEqual(bool(selected['matches']), competition != 'FAC')
        players = [dict(p, status='none') for p in game['players']]
        self.assertFalse(club.collect(dict(data, games=[dict(game, players=players)]), summaries)['matches'])

    def test_limits_and_replacement(self):
        docs = club.candidates(self.pool, {}, NOW)
        first = docs[0]['topic_key']
        second_same_match = docs[2]['topic_key']
        posted = dict(video_id='old', publish_at=NOW.isoformat())
        ledger = {first: posted}
        self.assertNotIn(first, [d['topic_key'] for d in club.candidates(self.pool, ledger, NOW)])
        self.assertEqual([d['topic_key'] for d in club.candidates(self.pool, ledger, NOW, 'old')], [first])
        self.assertEqual([d['topic_key'] for d in club.candidates(
            self.pool, dict(ledger, **{second_same_match: posted}), NOW)], [docs[1]['topic_key']])
        self.assertEqual(club.candidates(self.pool, {f'{i}:theme': posted for i in range(4)}, NOW), [])
        with tempfile.TemporaryDirectory() as tmp, patch.object(club, 'LEDGER', Path(tmp)/'ledger.json'):
            club.national.save(club.LEDGER, ledger)
            club.record_published(docs[0], 'new', NOW.isoformat())
            self.assertEqual(club.national.read(club.LEDGER)[first]['replaced'], ['old'])

    def test_reservation_spacing_and_end_of_day(self):
        booked = NOW + timedelta(minutes=35)
        ledger = {'event:topic': {'publish_at': booked.isoformat()}}
        self.assertEqual(club.reservation(NOW, ledger, {}), booked + timedelta(minutes=90))
        self.assertIsNone(club.reservation(NOW.replace(hour=23, minute=45), {}, {}))

    def test_upload_validates_material_gate_and_sample_flag(self):
        doc = club.candidates(self.pool, {}, NOW)[0]
        self.assertIn(club.PROGRAM, upload_youtube.TOPIC_KINDS)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            narration, material = folder/'narration.json', folder/'material.json'
            club.national.save(narration, doc)
            club.national.save(material, doc['topic_summary'])
            club.national.save(folder/'audio/voice_manifest.json', {})
            at = club.reservation(NOW, {}, {})
            args = SimpleNamespace(narration=narration, games=material, sport='soccer', privacy='public',
                                   publish_at=at.isoformat(), video=folder/'test.mp4')
            with (patch.dict(os.environ, {'COLLESPO_CLUB_TOPICS_PUBLISH':'true', 'COLLESPO_SAMPLE_ONLY':'false',
                                          'COLLESPO_TOPIC_REPLACES':''}),
                  patch.object(club, 'read_pool', return_value=self.pool),
                  patch.object(club, 'LEDGER', folder/'ledger.json'),
                  patch.object(club, 'PUBLICATIONS', folder/'published.json'),
                  patch.object(short_content, 'validate_upload', return_value={'actual_seconds':24}) as content_gate,
                  patch.object(upload_youtube.upload_gate, 'check', return_value=(0, [])) as gate):
                club.national.save(club.LEDGER, {})
                club.national.save(club.PUBLICATIONS, {})
                club.validate_upload(args, NOW)
                content_gate.assert_called_once_with(args.video)
                description = club.metadata(doc)['snippet']['description']
                upload_youtube.require_upload_gate(args.video, narration, description, club.PROGRAM)
                gate.assert_called_once_with(args.video, narration, description, club.PROGRAM)
                with patch.dict(os.environ, {'COLLESPO_SAMPLE_ONLY':'true'}), self.assertRaises(ValueError):
                    club.validate_upload(args, NOW)
                club.national.save(material, {})
                with self.assertRaisesRegex(ValueError, '原稿と材料'):
                    club.validate_upload(args, NOW)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
