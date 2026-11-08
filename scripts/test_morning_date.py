"""夕方枠の遅れ・手動指定・投稿日の整合を固定時計で確認する。"""
import unittest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import publication_clock as clock
import upload_youtube as upload


class FrozenDateTime(datetime):
    instant = datetime.fromisoformat('2026-11-08T02:25:00+09:00')

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


class MorningDateTest(unittest.TestCase):
    def test_delayed_evening_run_keeps_edition_across_midnight(self):
        for instant in ['2026-11-07T15:00:00+09:00', '2026-11-07T23:59:00+09:00',
                        '2026-11-08T00:01:00+09:00', '2026-11-08T02:25:00+09:00',
                        '2026-11-08T11:59:00+09:00']:
            with self.subTest(instant=instant):
                day = clock.edition_day(now=datetime.fromisoformat(instant))
                self.assertEqual('2026-11-07', day)
                self.assertEqual('2026-11-06', clock.game_day(day))

    def test_noon_starts_next_edition(self):
        self.assertEqual('2026-11-08', clock.edition_day(now=datetime.fromisoformat('2026-11-08T12:00:00+09:00')))

    def test_manual_date_overrides_clock(self):
        now = datetime.fromisoformat('2026-11-08T02:25:00+09:00')
        self.assertEqual('2026-11-08', clock.edition_day('2026-11-08', now))
        with self.assertRaises(ValueError):
            clock.edition_day('2026-11-31', now)

    def test_upload_uses_the_edition_not_current_utc_date(self):
        self.assertEqual('2026-11-08', upload.material_date_key('morning', 'mlb', {},
                         recap={'date_jst': '2026-11-08'}))
        self.assertEqual('2026-11-08', upload.material_date_key('morning', 'mlb', {},
                         recap={'date': '2026-11-07'}))
        self.assertEqual('2026-11-07', upload.material_date_key('morning', 'mlb', {}, '2026-11-07',
                         recap={'date_jst': '2026-11-08'}))

    def test_late_recovery_does_not_reserve_the_next_evening(self):
        spec = clock.edition_publish_at('2026-11-07', '17:30')
        with patch('datetime.datetime', FrozenDateTime):
            self.assertIsNone(upload.resolve_publish_at(spec))

    def test_explicit_future_edition_reserves_its_own_day(self):
        spec = clock.edition_publish_at('2026-11-08', '17:30')
        with patch('datetime.datetime', FrozenDateTime):
            self.assertEqual('2026-11-08T08:30:00Z', upload.resolve_publish_at(spec))

    def test_workflow_passes_same_day_to_every_stage_and_recovery(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/morning_recap.yml').read_text(encoding='utf-8')
        watchdog = (root / '.github/workflows/watchdog.yml').read_text(encoding='utf-8')
        self.assertIn('--video-date "${{ steps.edition.outputs.day }}"', workflow)
        self.assertEqual(2, workflow.count('--edition-date "${{ steps.edition.outputs.day }}" \\'))
        self.assertIn('--date "${{ steps.edition.outputs.game_day }}"', workflow)
        self.assertIn('INPUTS=(-f "date=${{ steps.edition.outputs.day }}")', watchdog)

    def test_metadata_uses_the_selected_video_instead_of_rejected_top_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'buzz.json'
            path.write_text(json.dumps({'videos': [
                {'video_id': 'repeated', 'topic_jp': '既出の題材', 'views': 200},
                {'video_id': 'selected', 'topic_jp': '新しい題材', 'views': 100}]}), encoding='utf-8')
            self.assertEqual('新しい題材', upload.buzz_top(str(path), 'selected')['topic_jp'])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
