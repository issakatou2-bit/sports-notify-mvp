"""保留IDと公開/予約/解除を台帳から照合。YouTube通信は偽物だけ。"""
import json
import pathlib
import sys
import tempfile
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

import generate_archive_pages as archive
import hold_video as hold
import video_visibility as visibility

NOW=datetime(2026,10,12,tzinfo=timezone.utc)
HELD_ID='zcwSx_PfHjQ'  # HANDOFFの過去の非公開保留例。今の実公開状態の再確認ではない。


def entry(**extra):
    return dict({'video_id':HELD_ID,'url':'https://youtu.be/'+HELD_ID,'title':'旧候補'},**extra)


class Visibility(unittest.TestCase):
    def test_held_private_unlisted_are_excluded(self):
        for e in [entry(held=True),entry(hold=True),entry(status='held'),entry(privacy='private'),
                  entry(privacy='unlisted'),entry(status='private'),entry(held=True,publish_at='2000-01-01T00:00:00Z')]:
            with self.subTest(e=e): self.assertFalse(visibility.is_public(e,NOW))

    def test_reservation_offsets_and_bad_timestamps(self):
        for at in ['2099-01-01T00:00:00Z','2099-01-01T09:00:00+09:00','broken','2099-01-01T00:00:00']:
            self.assertFalse(visibility.is_public(entry(publish_at=at),NOW))
        self.assertTrue(visibility.is_public(entry(publish_at='2000-01-01T00:00:00Z'),NOW))
        self.assertTrue(visibility.is_public(entry(privacy='public'),NOW))
        self.assertTrue(visibility.is_public(entry(),NOW))  # 古い台帳の互換

    def test_hold_clears_expired_schedule_and_preserves_other_records(self):
        original={'longform':{'day':entry(publish_at='2000-01-01T00:00:00Z',published_at='upload-time')},
                  'longform_reviewed':{'day':entry()}, 'morning':{'day':entry(video_id='other-id')}}
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'ledger.json'
            path.write_text(json.dumps(original),encoding='utf-8')
            self.assertEqual(visibility.record_status(path,HELD_ID,{'privacyStatus':'private'}),2)
            saved=json.loads(path.read_text(encoding='utf-8'))
            e=saved['longform']['day']
            self.assertTrue(e['held']); self.assertNotIn('publish_at',e)
            self.assertEqual(e['published_at'],'upload-time')
            self.assertEqual(saved['morning'],original['morning'])
            self.assertFalse(visibility.is_public(e,NOW))
            visibility.record_status(path,HELD_ID,{'privacyStatus':'public'})
            released=json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(released['longform']['day']['held'])
            self.assertTrue(visibility.is_public(released['longform']['day'],NOW))

    def test_new_reservation_clears_hold(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'ledger.json'
            path.write_text(json.dumps({'longform':{'day':entry(held=True,status='held')}}),encoding='utf-8')
            visibility.record_status(path,HELD_ID,{'privacyStatus':'private','publishAt':'2099-01-01T00:00:00Z'})
            e=json.loads(path.read_text(encoding='utf-8'))['longform']['day']
            self.assertFalse(e['held']); self.assertNotIn('status',e)
            self.assertTrue(visibility.is_scheduled(e,NOW))

    def test_unknown_status_or_id_does_not_rewrite_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'ledger.json'
            original=json.dumps({'longform':{'day':entry()}})
            path.write_text(original,encoding='utf-8')
            for saved in [{},{'privacyStatus':'unknown'},{'privacyStatus':'private','publishAt':'broken'}]:
                with self.assertRaises(ValueError): visibility.record_status(path,HELD_ID,saved)
                self.assertEqual(path.read_text(encoding='utf-8'),original)
            self.assertEqual(visibility.record_status(path,'missing',{'privacyStatus':'private'}),0)
            self.assertEqual(path.read_text(encoding='utf-8'),original)

    def test_html_does_not_embed_the_held_candidate(self):
        records={'longform':{'2026-10-01':entry(held=True)},
                 'morning':{'2026-10-01':entry(video_id='public-id',privacy='public')}}
        with patch.object(archive,'load_published_videos',return_value=records):
            page=archive.render_day_page('2026-10-01',{'games':[]},None,None)
        self.assertNotIn(HELD_ID,page)
        self.assertIn('public-id',page)

    def test_cli_dry_read_is_not_a_ledger_write(self):
        yt=Mock()
        yt.videos.return_value.list.return_value.execute.return_value={'items':[{'status':{'privacyStatus':'private'}}]}
        with patch.object(sys,'argv',['hold','--video',HELD_ID]),patch.object(hold,'client',return_value=yt),patch.object(hold,'sync_record') as sync:
            self.assertEqual(hold.main(),0)
        sync.assert_not_called()
        yt.videos.return_value.update.assert_not_called()

    def test_cli_already_held_syncs_only_when_write_requested(self):
        yt=Mock()
        saved={'privacyStatus':'private'}
        yt.videos.return_value.list.return_value.execute.return_value={'items':[{'status':saved}]}
        with patch.object(sys,'argv',['hold','--video',HELD_ID,'--write']),patch.object(hold,'client',return_value=yt),patch.object(hold,'sync_record') as sync:
            self.assertEqual(hold.main(),0)
        sync.assert_called_once_with(HELD_ID,saved)
        yt.videos.return_value.update.assert_not_called()

    def test_failed_readback_cannot_mark_ledger_as_held(self):
        yt=Mock()
        yt.videos.return_value.list.return_value.execute.return_value={'items':[{'status':{'privacyStatus':'public'}}]}
        with patch.object(sys,'argv',['hold','--video',HELD_ID,'--write']),patch.object(hold,'client',return_value=yt), \
             patch.object(hold,'verify_status',side_effect=ValueError('fixture:保存不一致')),patch.object(hold,'sync_record') as sync:
            with self.assertRaises(ValueError):hold.main()
        sync.assert_not_called()


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
