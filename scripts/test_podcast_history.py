"""翌日生成/失敗時の既存回の説明と配信IDを検証。ffmpeg/配信APIは呼ばない。"""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_podcast as gp


class PodcastHistory(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=pathlib.Path(self.tmp.name)
        self.audio=self.root/'audio';self.audio.mkdir()
        self.store=self.root/'podcast';self.store.mkdir()
        self.public=self.root/'public'
        self.games=self.root/'games.json';self.narration=self.root/'narration.json'

    def tearDown(self):
        self.tmp.cleanup()

    def run_day(self,day,match,speakers,created=True):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls.fromisoformat(day+'T19:00:00+09:00')
        self.games.write_text(json.dumps({'games':[dict(is_notable=True,game_type='R',
            start_time_jst='08:10',away_team_name=match,home_team_name='Home',reasons=[])]}),encoding='utf-8')
        self.narration.write_text(json.dumps({'segments':[{'speaker':n} for n in speakers]}),encoding='utf-8')
        def concat(_,output):
            if created:output.write_bytes((day+'-audio').encode())
            return created
        with patch.object(gp,'datetime',Clock), \
                patch.object(gp,'concat_to_mp3',side_effect=concat), \
                patch.object(gp,'audio_meta',side_effect=lambda p:(42,p.stat().st_size)), \
                patch.object(sys,'argv',['generate_podcast.py','--audio-dir',str(self.audio),
                    '--store',str(self.store),'--public',str(self.public),'--games',str(self.games),
                    '--narration',str(self.narration)]),contextlib.redirect_stdout(io.StringIO()):
            gp.main()
        return {item.findtext('guid'):item for item in ET.parse(self.public/'feed.xml').findall('channel/item')}

    def test_next_day_preserves_description_speakers_and_delivery_identity(self):
        before=self.run_day('2026-10-10','Away1',[3,2])
        guid=gp.PODCAST_BASE+'2026-10-10.mp3';old=before[guid]
        original=(self.store/'2026-10-10.mp3').read_bytes()
        after=self.run_day('2026-10-11','Away2',[3])
        self.assertIn('Away1',after[guid].findtext('description'))
        self.assertIn('四国めたん',after[guid].findtext('description'))
        self.assertNotIn('Away2',after[guid].findtext('description'))
        for tag in ['title','description','pubDate','guid','enclosure']:
            self.assertEqual(ET.tostring(old.find(tag)),ET.tostring(after[guid].find(tag)))
        self.assertEqual(original,(self.store/'2026-10-10.mp3').read_bytes())

    def test_failed_same_day_regeneration_does_not_relabel_existing_audio(self):
        before=self.run_day('2026-10-10','Original',[3,2])
        after=self.run_day('2026-10-10','UnspokenReplacement',[3],created=False)
        guid=next(iter(before))
        self.assertEqual(before[guid].findtext('description'),after[guid].findtext('description'))

    def test_failed_converter_keeps_original_audio_and_bound_description(self):
        output=self.store/'2026-10-10.mp3';output.write_bytes(b'original')
        gp.save_episode_metadata(output,'title','original description')
        (self.audio/'seg_001.wav').write_bytes(b'input')
        def failed(cmd,**kw):
            pathlib.Path(cmd[-1]).write_bytes(b'incomplete conversion')
            raise subprocess.CalledProcessError(1,cmd)
        with patch.object(gp.subprocess,'run',side_effect=failed),contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(gp.concat_to_mp3(self.audio,output))
        self.assertEqual(output.read_bytes(),b'original')
        self.assertEqual(gp.load_episode_metadata(output)['description'],'original description')
        self.assertFalse(output.with_suffix('.tmp.mp3').exists())

    def test_successful_converter_replaces_audio_only_after_completion(self):
        output=self.store/'2026-10-10.mp3';output.write_bytes(b'original')
        (self.audio/'seg_001.wav').write_bytes(b'input')
        def converted(cmd,**kw):
            self.assertEqual(output.read_bytes(),b'original')
            pathlib.Path(cmd[-1]).write_bytes(b'complete conversion')
        with patch.object(gp.subprocess,'run',side_effect=converted):
            self.assertTrue(gp.concat_to_mp3(self.audio,output))
        self.assertEqual(output.read_bytes(),b'complete conversion')
        self.assertFalse(output.with_suffix('.tmp.mp3').exists())

    def test_replaced_audio_and_corrupt_metadata_are_not_trusted(self):
        audio=self.store/'2026-10-10.mp3';audio.write_bytes(b'old')
        gp.save_episode_metadata(audio,'title','old description')
        audio.write_bytes(b'repair')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(gp.load_episode_metadata(audio),{})
        audio.with_suffix('.json').write_text('not json',encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(gp.load_episode_metadata(audio),{})

    def test_legacy_audio_keeps_generic_description_without_invented_speakers(self):
        (self.store/'2026-10-09.mp3').write_bytes(b'legacy')
        items=self.run_day('2026-10-10','Today',[3,2])
        self.assertEqual(items[gp.PODCAST_BASE+'2026-10-09.mp3'].findtext('description'),gp.DESCRIPTION)

    def test_metadata_cannot_change_file_identity(self):
        audio=self.store/'2026-10-10.mp3';audio.write_bytes(b'audio')
        gp.save_episode_metadata(audio,'title','description')
        path=audio.with_suffix('.json');data=json.loads(path.read_text(encoding='utf-8'))
        data['file']='2026-10-11.mp3';path.write_text(json.dumps(data),encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(gp.load_episode_metadata(audio),{})

    def test_pruning_removes_only_expired_episode_sidecar(self):
        old=self.store/'2026-01-01.mp3';old.write_bytes(b'old');gp.save_episode_metadata(old,'old','old')
        recent=self.store/'2026-10-10.mp3';recent.write_bytes(b'recent');gp.save_episode_metadata(recent,'new','new')
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,12,tzinfo=gp.JST)
        with patch.object(gp,'datetime',Clock):self.assertEqual(gp.prune_old(self.store),1)
        self.assertFalse(old.with_suffix('.json').exists());self.assertTrue(recent.with_suffix('.json').exists())


if __name__=='__main__':
    unittest.main(argv=[__file__])
