"""代表長編の根拠・全文再構成・読み・相手切替・公開経路なしの回帰。"""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import soccer_national_long as long
from test_soccer_national_numbers import fixture_sheet,AS_OF


class NationalLong(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,COLLESPO_SAMPLE_ONLY='true');env.start();self.addCleanup(env.stop)
        self.sheet=fixture_sheet();self.data=long.material('brazil',AS_OF,self.sheet);self.doc=long.dialogue(self.data)

    def test_both_opponents_and_previous_day_twenty_are_material_driven(self):
        for key,opponent,planned,history_count in [('brazil','ブラジル','2026-11-13T20:00:00+09:00',2),('paraguay','パラグアイ','2026-11-16T20:00:00+09:00',1)]:
            data=long.material(key,AS_OF,self.sheet);doc=long.dialogue(data);long.validate_document(doc)
            self.assertEqual(data['game']['opponent'],opponent)
            self.assertEqual(data['planned_publish_at'],planned)
            self.assertEqual(len(data['history']),history_count)
            self.assertFalse(long.metadata(doc)['publication_enabled'])
            self.assertIn(opponent+'戦へ 招集28人',doc['title'])

    def test_all_twenty_eight_have_table_rows_and_missing_is_not_zero(self):
        tables=[p for k,p in self.doc['panels'].items() if k.startswith('position_')]
        text='\n'.join(row for p in tables for row in p['rows'])
        self.assertEqual(sum(len(p['rows']) for p in tables),28)
        for player in self.data['players']:self.assertEqual(text.count(player['name']),1)
        self.assertEqual(text.count('今季の数値は未確認'),25)
        self.assertNotIn('リーグ戦 0試合',text)

    def test_only_proven_three_are_highlighted(self):
        self.assertEqual([p['name'] for p in long.highlighted(self.data)],['坂元達裕','鎌田大地','鈴木彩艶'])
        sheet=copy.deepcopy(self.sheet);sheet['players']=[]
        data=long.material('brazil',AS_OF,sheet);doc=long.dialogue(data)
        self.assertFalse(long.highlighted(data))
        self.assertNotIn('focus_0',doc['panels'])
        self.assertIn('確認できた選手はいません',doc['panels']['focus_intro']['rows'][0])

    def test_gk_table_does_not_invent_goalkeeping_stats(self):
        text=' '.join(self.doc['panels']['position_GK_0']['rows'])
        self.assertIn('リーグ戦 8試合',text)
        self.assertNotIn('得点',text);self.assertNotIn('無失点',text)

    def test_dialogue_panel_and_material_tamper_are_rejected(self):
        for field in ('segments','panels','title','history','game'):
            doc=copy.deepcopy(self.doc)
            if field=='segments':doc[field][0]['text']='99得点です。'
            elif field=='panels':doc[field]['history']['rows'].append('通算99勝')
            elif field=='title':doc[field]='別の題'
            elif field=='history':doc['national_long_material'][field][0]['gf']=9
            else:doc['national_long_material'][field]['kickoff_jst']='2026-11-14T20:00:00+09:00'
            with self.subTest(field=field),self.assertRaises(ValueError):long.validate_document(doc)

    def test_raw_stats_tamper_is_rejected(self):
        sheet=copy.deepcopy(self.sheet);sheet['players'][0]['values']['appearances']=999
        with self.assertRaises(ValueError):long.material('brazil',AS_OF,sheet)

    def test_name_readings_apply_only_inside_validated_long_dialogue(self):
        import name_reading_guard as guard
        import notability_engine as ne
        before=copy.deepcopy(ne.JP_PLAYERS_SOCCER)
        guard.validate_dialogue(self.doc)
        with guard.dialogue_scope(self.doc):
            for p in self.data['players']:
                self.assertEqual(guard.player_reading(p['name']),p['reading'])
        self.assertEqual(ne.JP_PLAYERS_SOCCER,before);self.assertEqual(len(before),42)

    def test_fixture_is_labelled_on_every_panel_and_never_normal_material(self):
        self.assertTrue(all('検証用・数値は架空' in p['heading'] for p in self.doc['panels'].values()))
        with patch.dict(os.environ,COLLESPO_SAMPLE_ONLY='false'):
            with self.assertRaises(ValueError):long.validate_document(self.doc)

    def test_material_rejects_unconfirmed_opponent_and_after_kickoff(self):
        with self.assertRaises(ValueError):long.material('unknown',AS_OF,self.sheet)
        sheet=copy.deepcopy(self.sheet)
        # 古い集計も試合後の回も、どちらもこの長編に通さない。
        with self.assertRaises(ValueError):long.material('brazil','2026-11-14T20:00:00+09:00',sheet)

    def test_audio_must_match_all_lines_and_three_to_four_minutes(self):
        import render_soccer_national_long as render
        import video_common
        with tempfile.TemporaryDirectory() as folder:
            audio=Path(folder)/'voice.wav'
            def manifest(seconds):
                duration=seconds/len(self.doc['segments'])-video_common.SEGMENT_TAIL
                with wave.open(str(audio),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
                    wav.writeframes(b'\0\0'*round(duration*8000))
                return {'segments':[dict(text=s['text'],speaker=s['speaker'],file=str(audio),duration=duration) for s in self.doc['segments']]}
            self.assertAlmostEqual(render.audio_duration(self.doc,manifest(210)),210,delta=.01)
            for seconds in (170,250):
                with self.assertRaises(ValueError):render.audio_duration(self.doc,manifest(seconds))
            wrong=manifest(210);wrong['segments'][0]['text']='違う原稿'
            with self.assertRaises(ValueError):render.audio_duration(self.doc,wrong)
            missing=manifest(210);missing['segments'].pop()
            with self.assertRaises(ValueError):render.audio_duration(self.doc,missing)

    def test_workflow_has_no_schedule_credentials_or_publication_path(self):
        text=(ROOT/'.github/workflows/soccer_national_long.yml').read_text(encoding='utf8')
        for forbidden in ('cron:','secrets.','upload_youtube','commit_data','published_','contents: write'):
            self.assertNotIn(forbidden,text)
        for required in ('sample_only:','render_only:','contents: read','--require-audio'):
            self.assertIn(required,text)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
