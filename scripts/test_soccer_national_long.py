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
        for key,opponent,planned,history_count,count in [('brazil','ブラジル','2026-11-13T20:00:00+09:00',2,'招集28人'),('paraguay','パラグアイ','2026-11-16T20:00:00+09:00',1,'代表27人')]:
            data=long.material(key,AS_OF,self.sheet);doc=long.dialogue(data);long.validate_document(doc)
            self.assertEqual(data['game']['opponent'],opponent)
            self.assertEqual(data['planned_publish_at'],planned)
            self.assertEqual(len(data['history']),history_count)
            self.assertFalse(long.metadata(doc)['publication_enabled'])
            self.assertIn(opponent+'戦へ '+count,doc['title'])

    def test_withdrawn_player_is_left_out_and_said(self):
        # 11/14 JFA「鎌田大地 所属クラブの都合で離脱」：パラグアイ戦の回だけ外し、外したことを言う。
        data=long.material('paraguay',AS_OF,self.sheet);doc=long.dialogue(data);long.validate_document(doc)
        self.assertNotIn('鎌田大地',[p['name'] for p in data['players']])
        self.assertEqual((len(data['players']),data['called']),(27,28))
        self.assertNotIn('鎌田大地',[p['name'] for p in data['numbers']['players']])
        talk=[(s['speaker'],s['text']) for s in doc['segments'] if s['kind']=='talk']
        i=talk.index((3,'離脱したのは、誰なのだ？'))
        self.assertEqual(talk[i+1],(2,'鎌田大地です。11月14日のJFAの発表で、理由は所属クラブの都合です。'))
        self.assertIn('招集28人のうち、離脱を除く27人です。',talk[i-1][1])
        text=long.description(doc)
        self.assertIn('離脱：鎌田大地（所属クラブの都合、11月14日 JFA発表）',text)
        self.assertIn('https://www.jfa.jp/samuraiblue/news/00037030/',text)
        # ブラジル戦の回は離脱の前の発表どおり28人
        self.assertEqual(len(long.material('brazil',AS_OF,self.sheet)['players']),28)

    def test_withdrawal_needs_jfa_source_and_a_called_player(self):
        roster=long.n.read(long.ROOT/'data/soccer_national_squad.json')
        bad=dict(roster,withdrawals=[dict(roster['withdrawals'][0],source_url='https://example.com/x')])
        with self.assertRaises(ValueError):long.withdrawals(bad,'paraguay')
        bad=dict(roster,withdrawals=[dict(roster['withdrawals'][0],name_en='Taro Notcalled')])
        with self.assertRaises(ValueError):long.withdrawals(bad,'paraguay')
        self.assertEqual(long.withdrawals(roster,'brazil'),{})

    def test_zundamon_only_asks(self):
        # 11/14 本人「ずんだもんの疑問にめたんが答える形」：ずんだもんの台詞は問いだけで、数字はめたんが読む。
        talk=[s for s in self.doc['segments'] if s['kind']=='talk' and s['speaker']==3]
        self.assertTrue(talk)
        for seg in talk:self.assertTrue(seg['text'].endswith('？'),seg['text'])

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

    def with_previous(self,rows=None):
        """結果の一覧に前の試合を足した材料。ファイルは変えず、読む所だけ差し替える。"""
        real=long.n.read
        rows=rows if rows is not None else [dict(date='2026-11-08',competition='親善試合',opponent='ブラジル',gf=2,ga=1,result='win',scorers=['鎌田大地','坂元達裕'])]
        def fake(path,*a,**k):
            data=real(path,*a,**k)
            if Path(path).name=='soccer_national_results.json':
                data=copy.deepcopy(data);data['matches']=data['matches']+rows
            return data
        return patch.object(long.n,'read',fake)

    def test_previous_chapter_only_when_result_exists(self):
        plain=long.dialogue(long.material('paraguay',AS_OF,self.sheet))
        self.assertNotIn('previous',plain['panels']);self.assertEqual([c['id'] for c in plain['chapters']][0],'positions')
        self.assertIn('パラグアイ戦へ 代表27人を今季の数字で',plain['title'])
        with self.with_previous():
            data=long.material('paraguay',AS_OF,self.sheet);doc=long.dialogue(data);long.validate_document(doc)
        self.assertEqual(data['previous_match']['opponent'],'ブラジル')
        self.assertEqual([c['id'] for c in doc['chapters']][:3],['opening','previous','positions'])
        text=' '.join(s['text'] for s in doc['segments'] if s['panel']=='previous')
        self.assertIn('2対1で日本の勝ち',text);self.assertIn('鎌田大地',text)
        # 前の試合の章は冒頭の次
        self.assertEqual(list(doc['panels'])[:2],['opening','previous'])

    def test_previous_match_is_not_made_up_outside_the_call_window_or_after_the_game(self):
        old=[dict(date='2026-10-05',competition='キリンカップ',opponent='ニュージーランド',gf=2,ga=1,result='win')]
        with self.with_previous(rows=old):
            self.assertIsNone(long.material('paraguay',AS_OF,self.sheet)['previous_match'])
        # 取得日より後の結果・その試合の当日以降の結果は入れない
        later=[dict(date='2026-11-14',competition='親善試合',opponent='ブラジル',gf=2,ga=1,result='win'),
               dict(date='2026-11-17',competition='親善試合',opponent='パラグアイ',gf=1,ga=0,result='win')]
        with self.with_previous(rows=later):
            self.assertIsNone(long.material('paraguay',AS_OF,self.sheet)['previous_match'])
            self.assertIsNone(long.material('brazil',AS_OF,self.sheet)['previous_match'])

    def test_title_switches_and_stays_within_fifty(self):
        with self.with_previous():
            data=long.material('paraguay',AS_OF,self.sheet)
        title=long.title(data)
        self.assertEqual(title,'ブラジル戦の結果と パラグアイ戦へ 代表27人の今季')
        self.assertLessEqual(len(title),50)
        for bad in ('【','】','！','？'):self.assertNotIn(bad,title)
        data['previous_match']['opponent']='あ'*60
        self.assertLessEqual(len(long.title(data)),50)
        self.assertIn('を今季の数字で',long.title(data))

    def test_due_only_on_the_day_before_an_unpublished_match(self):
        from datetime import datetime,timedelta,timezone
        jst=timezone(timedelta(hours=9))
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'published.json'
            at=lambda d,h,m=30:datetime(2026,11,d,h,m,tzinfo=jst)
            self.assertEqual(long.due(at(16,12),record=record),'paraguay')
            self.assertEqual(long.due(at(13,12),record=record),'brazil')
            for day in (12,14,15,17,18):self.assertIsNone(long.due(at(day,12),record=record),day)
            record.write_text('{"soccer_national_long":{"paraguay":{"video_id":"abc"}}}',encoding='utf8')
            self.assertIsNone(long.due(at(16,12),record=record))
            self.assertEqual(long.due(at(13,12),record=record),'brazil')

    def upload_args(self,**kw):
        import types
        base=dict(narration='n.json',games='m.json',force=False,video_date='paraguay',publish_at='20:00')
        base.update(kw);return types.SimpleNamespace(**base)

    def test_publish_at_is_previous_day_twenty_and_late_runs_stop(self):
        from datetime import datetime,timedelta,timezone
        jst=timezone(timedelta(hours=9))
        data=long.material('paraguay',AS_OF,self.sheet,publish=True)
        self.assertEqual(data['planned_publish_at'],'2026-11-16T20:00:00+09:00')
        # 検証用の架空数値の拒否は別の試験で見る。ここでは日時の判定だけ。
        data['numbers']['fixture']=False
        doc=long.dialogue(data)
        def run(now,**kw):
            with patch.object(long.n,'read',lambda path:doc if str(path)=='n.json' else data),patch.object(long,'validate_document',lambda d:None):
                return long.validate_upload(self.upload_args(**kw),now)
        ok=datetime(2026,11,16,12,40,tzinfo=jst)
        self.assertIsNone(run(ok))
        for now in (datetime(2026,11,16,19,55,tzinfo=jst),datetime(2026,11,16,21,0,tzinfo=jst),datetime(2026,11,15,12,40,tzinfo=jst),datetime(2026,11,17,9,0,tzinfo=jst)):
            with self.subTest(now=now),self.assertRaises(ValueError):run(now)
        with self.assertRaises(ValueError):run(ok,publish_at='21:00')
        with self.assertRaises(ValueError):run(ok,video_date='brazil')
        with self.assertRaises(ValueError):run(ok,force=True)

    def test_sample_material_cannot_be_published(self):
        from datetime import datetime,timedelta,timezone
        jst=timezone(timedelta(hours=9))
        data=long.material('paraguay',AS_OF,self.sheet,publish=True);doc=long.dialogue(data)
        with patch.object(long.n,'read',lambda path:doc if str(path)=='n.json' else data),patch.object(long,'validate_document',lambda d:None):
            with self.assertRaises(ValueError):long.validate_upload(self.upload_args(),datetime(2026,11,16,12,40,tzinfo=jst))
        plain=long.dialogue(self.data)
        with patch.object(long.n,'read',lambda path:plain if str(path)=='n.json' else self.data),patch.object(long,'validate_document',lambda d:None):
            with self.assertRaises(ValueError):long.validate_upload(self.upload_args(video_date='brazil'),datetime(2026,11,13,12,40,tzinfo=jst))

    def test_description_has_sources_fetch_date_credit_and_flag_path(self):
        doc=long.dialogue(long.material('paraguay',AS_OF,self.sheet,publish=True));long.validate_document(doc)
        meta=long.metadata(doc);text=meta['snippet']['description']
        self.assertTrue(meta['publication_enabled'])
        self.assertIn('https://www.jfa.jp/samuraiblue/news/00036974/',text)
        self.assertIn('取得日',text);self.assertIn('音声：VOICEVOX 四国めたん / ずんだもん',text)
        self.assertIn(doc['national_long_material']['numbers']['players'][0]['source'],text)
        self.assertLessEqual(len(meta['snippet']['title']),50)
        self.assertFalse(long.metadata(long.dialogue(self.data))['publication_enabled'])

    def test_upload_youtube_knows_the_kind_and_keeps_the_record_key(self):
        import upload_youtube as up
        self.assertIn('soccer_national_long',up.DATED_KINDS);self.assertIn('soccer_national_long',up.LANDSCAPE_KINDS)
        self.assertEqual(up.record_kind('soccer_national_long'),'soccer_national_long')
        self.assertEqual(up.material_date_key('soccer_national_long','soccer',{},'paraguay'),'paraguay')

    def test_workflow_publishes_only_on_schedule_or_publish_true(self):
        text=(ROOT/'.github/workflows/soccer_national_long.yml').read_text(encoding='utf8')
        for required in ('sample_only:','render_only:','publish:','default: false',"cron: '30 3 * * *'",'contents: write','--require-audio',
                         '--kind soccer_national_long','--privacy public',"--publish-at '20:00'",'frames/opening.png','verify_national_long.py',
                         'commit_data.sh','--due','group: soccer-national-long','cancel-in-progress: false',
                         "github.event_name == 'schedule' || inputs.publish"):
            self.assertIn(required,text)
        self.assertIn('test "$PUBLISH" = true || test "$SAMPLE_ONLY" = true || test "$RENDER_ONLY" = true',text)
        self.assertEqual(text.count('upload_youtube.py'),1)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
