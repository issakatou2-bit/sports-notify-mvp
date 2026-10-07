"""外観だけのPS移行。数字・本文・旧台帳キーと描画ゲートを保持する。"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from test_ps_program import fixture
import ps_program as p


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.env=mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'legacy'})
        self.env.start();self.addCleanup(self.env.stop)

    def make(self,slot='forecast'):
        snap,ev,now=fixture(29 if slot=='forecast' else 28)
        return p.prepare(snap,ev,slot,now,{})

    def test_default_and_rollback_preserve_original(self):
        original=self.make()
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):modern=self.make()
        self.assertEqual(self.make(),original)
        self.assertNotEqual(modern,original)
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'typo'}),self.assertRaises(ValueError):self.make()

    def test_both_slots_preserve_editorial_payload_and_identity(self):
        for slot in ('forecast','situation'):
            original=self.make(slot)
            with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):modern=self.make(slot)
            self.assertNotEqual(original['edition_key'],modern['edition_key'])
            self.assertEqual(p.content_key(modern),modern['edition_key'])
            self.assertEqual(original['game_ids'],modern['game_ids'])
            for old,new in zip(original['segments'],modern['segments']):
                if new['meta']['card']['layout']!='schedule':
                    self.assertEqual(old['text'],new['text'])
                self.assertEqual(new['speaker'],2)
                card=copy.deepcopy(new['meta']['card']);card.pop('visual_style')
                if card['layout']!='schedule':
                    self.assertEqual(card,old['meta']['card'])
                _,om=p.render_segment(old);_,nm=p.render_segment(new)
                import ps_unified_v3 as unified
                self.assertEqual([(x['text']) for x in nm['text']], [h+'　'+b for h,b in unified.rows(old['meta']['card'])])
                self.assertEqual(nm['card'],new['meta']['card'])
                if card['layout']!='schedule':
                    self.assertEqual(nm['material_gate']['text'],om['text'])
                self.assertEqual(nm['presenters'][0]['side'],'right')
            self.assertEqual(p.metadata(modern)['snippet']['description'].count('VOICEVOX:'),1)
            p.check_program(modern)

    def test_appearance_cannot_create_duplicate_edition(self):
        old=self.make()
        ledger={old['kind']:{old['date_jst']:{'program_edition':old['edition_key'],'video_id':'already-published','program_version':p.VERSION}}}
        snap,ev,now=fixture(29)
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            self.assertIsNone(p.prepare(snap,ev,'forecast',now,ledger))

    def test_idempotent_design_and_tampered_words_or_voice_blocked(self):
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            modern=self.make();key=modern['edition_key'];p.apply_design(modern)
        self.assertEqual(p.content_key(modern),key)
        for target in ('text','speaker','visual_style','wins'):
            broken=copy.deepcopy(modern)
            if target=='text':broken['segments'][0]['text']+='99勝'
            elif target=='speaker':broken['segments'][0]['speaker']=3
            elif target=='visual_style':broken['segments'][0]['meta']['card']['visual_style']='legacy'
            else:broken['segments'][1]['meta']['card']['scoreboard']['rows'][0]['wins']=99
            with self.subTest(target=target),self.assertRaises(ValueError):p.check_program(broken)

    def test_saved_official_two_slots_and_no_upload(self):
        from datetime import datetime
        saved=p.read(Path(__file__).parent/'fixtures/ps-design/2026-10-07.json')
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            for slot in ('forecast','situation'):
                modern=p.prepare(saved['snapshot'],saved['evidence'],slot,datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
                self.assertIsNotNone(modern);p.check_program(modern)
                modern['rehearsal']=True
                with self.assertRaisesRegex(ValueError,'公開しません'):p.upload(modern,[])

    def test_motion_and_sound_follow_existing_rows(self):
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):modern=self.make()
        seg=modern['segments'][1];card=seg['meta']['card']
        import ps_unified_v3 as unified
        first=unified.frame(.1,card)
        settled=unified.frame(2,card)
        later=unified.frame(6,card)
        self.assertNotEqual(first.tobytes(),settled.tobytes())
        self.assertNotEqual(settled.tobytes(),later.tobytes())
        from v3_slot_render import cues
        self.assertEqual(unified.cues(card),cues(unified.rows(card)))
        self.assertEqual(p.background_team(card),145)

    def test_wrong_speaker_audio_rejected_before_encoding(self):
        with mock.patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):modern=self.make()
        with tempfile.TemporaryDirectory() as directory:
            audio=Path(directory)/'voice.wav';audio.write_bytes(b'fake')
            segments=[dict(s,file=str(audio),duration=3) for s in modern['segments']]
            segments[0]['speaker']=3
            p.write(Path(directory)/'manifest.json',dict(segments=segments))
            with mock.patch.object(p.vc,'build_narration_track') as mix,self.assertRaisesRegex(ValueError,'音声の不一致'):
                p.movie(modern,directory,directory)
            mix.assert_not_called()


if __name__=='__main__':unittest.main(argv=[__file__])
