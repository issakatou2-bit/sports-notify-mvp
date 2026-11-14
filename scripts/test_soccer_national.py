"""代表番組の失敗境界。実API・音声・公開なし。"""
import copy
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import soccer_national as n
import soccer_national_history as history


def setUpModule():
    # 試験の架空の試合（11/14 ブラジル 2-1 など）を、本物の確認一覧に入った同じ日の結果（11/14 3-2）と混ぜない。
    # 一覧は11/13までの行だけの写しにする。本物の一覧の中身は test_soccer_national_long などで見る。
    import json
    global _HISTORY_PATCH
    data=json.loads(history.PATH.read_text(encoding='utf8'))
    data['matches']=[r for r in data['matches'] if r['date']<'2026-11-14']
    data['checked_at']='2026-11-02'  # 古さの境目の試験（11/24）は11/2の確認日で数える
    tmp=Path(tempfile.mkdtemp())/'soccer_national_results.json'
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    _HISTORY_PATCH=patch.object(history,'PATH',tmp);_HISTORY_PATCH.start()


def tearDownModule():
    _HISTORY_PATCH.stop()


def event(ident='test', score=(2,1), complete=True, date='2026-11-14T10:15Z', opp='205'):
    return dict(id=ident,date=date,competitions=[dict(date=date,
        status=dict(type=dict(completed=complete)),venue=dict(fullName='Singapore National Stadium'),
        competitors=[dict(team=dict(id='627',displayName='Japan'),score=str(score[0])),
            dict(team=dict(id=opp,displayName='Brazil' if opp=='205' else 'Paraguay'),score=str(score[1]))])])


def summary(score=(2,1), names=('Ayase Ueda','Ayase Ueda','UNKNOWN'), teams=('627','627','205')):
    e=event(score=score)
    return dict(header=dict(id=e['id'],competitions=e['competitions']),keyEvents=[dict(id=str(i),
        scoringPlay=True,shootout=False,team=dict(id=team),clock=dict(displayValue=str(10+i)+"'"),
        type=dict(id='70',text='Goal'),participants=[dict(athlete=dict(displayName=name))])
        for i,(team,name) in enumerate(zip(teams,names))])


class National(unittest.TestCase):
    def setUp(self):
        self.now=n.instant('2026-11-14T12:30:00Z')
        self.future=n.match(event('next',complete=False,date='2026-11-17T13:10Z',opp='210'))
        self.schedule=dict(events=[event('old',score=(1,0),date='2026-09-28T10:25Z')])

    def result(self,raw=None):
        return n.result(raw or summary(),[self.future],self.schedule,self.now.isoformat())

    def test_real_format_score(self):
        self.assertEqual(n.number({'value':3.0}),3)
        for v in [None,True,-1,2.3]:
            with self.assertRaises(ValueError):n.number(v)

    def test_jst_neutral(self):
        d=n.match(event(complete=False))
        self.assertEqual(d['kickoff_jst'],'2026-11-14T19:15:00+09:00')
        self.assertEqual(d['venue'],'シンガポール・ナショナル・スタジアム')
        self.assertNotIn('home',d)

    def test_goals_both_sides(self):
        d=self.result()
        self.assertTrue(d['goals_complete'])
        self.assertEqual(d['goals'][0]['name'],'上田綺世')
        self.assertIsNone(d['goals'][2]['name'])
        doc=n.narration(d)
        self.assertFalse(n.check(doc))
        self.assertIn('上田綺世が2点を取りました',''.join(s['text'] for s in doc['segments']))
        self.assertNotIn('UNKNOWN',str(doc['segments']))

    def test_missing_events_suppressed(self):
        d=self.result(summary(score=(3,1),names=('Ayase Ueda','UNKNOWN'),teams=('627','205')))
        self.assertFalse(d['goals_complete']);self.assertEqual(d['goals'],[])
        doc=n.narration(d)
        self.assertNotIn('上田綺世',str(doc['segments']))
        self.assertFalse(n.check(doc))
        doc['segments'][0]['text']+='上田綺世が2点。'
        self.assertTrue(n.check(doc))

    def test_each_side_counts_not_total(self):
        d=self.result(summary(score=(2,1),teams=('627','205','205')))
        self.assertFalse(d['goals_complete'])

    def test_live_is_held(self):
        s=summary();s['header']['competitions'][0]['status']['type']['completed']=False
        with self.assertRaises(ValueError):self.result(s)

    def test_japanese_unknown_stops(self):
        with self.assertRaises(ValueError):self.result(summary(names=('UNKNOWN','Ayase Ueda','UNKNOWN')))

    def test_duplicate_stops(self):
        s=summary();s['keyEvents'][1]['id']='0'
        with self.assertRaises(ValueError):self.result(s)

    def test_shootout_excluded(self):
        s=summary();e=copy.deepcopy(s['keyEvents'][0]);e.update(id='pk',shootout=True);s['keyEvents'].append(e)
        self.assertTrue(self.result(s)['goals_complete'])

    def test_score_tamper_sanity(self):
        import sanity_material
        doc=n.narration(self.result());doc['segments'][0]['text']=doc['segments'][0]['text'].replace('2対1','9対1')
        self.assertTrue(sanity_material.check(doc))

    def test_no_future_recent(self):
        sch=dict(events=self.schedule['events']+[event('future',date='2027-01-01T00:00Z')])
        self.assertEqual(n.recent(sch,'627',self.now)[0]['id'],'old')

    def test_no_previous_invented(self):
        d=n.preview(n.match(event(complete=False)),self.schedule,self.schedule,dict(events=[]),'2026-11-13T09:00:00Z')
        self.assertEqual(d['previous']['date_jst'],'2026-06-30')
        self.assertTrue(any(s['meta'].get('panel')=='previous' for s in n.narration(d)['segments']))

    def test_preannouncement_empty(self):
        self.assertIsNone(n.squad(dict(announced_at=None),{},self.now.isoformat()))

    def test_example_not_live(self):
        with self.assertRaises(ValueError):
            n.squad(n.read(n.ROOT/'scripts/fixtures/soccer_national_squad.example.json'),{},self.now.isoformat())

    def test_squad_names_and_clubs(self):
        d=dict(announced_at='2026-11-06T05:00Z',source_url='https://www.jfa.jp/test/',window='2026-11',season='2026/27',
            players=[dict(name_en='Ayase Ueda',name_jp='上田綺世',reading='ウエダアヤセ',club='試験クラブ',position='FW')])
        out=n.squad(d,{},self.now.isoformat());self.assertEqual(out['players'][0]['name'],'上田綺世')
        self.assertIsNone(out['players'][0]['stats'])
        d['players'][0].pop('reading')
        with self.assertRaises(ValueError):n.squad(d,{},self.now.isoformat())

    def test_off_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as out, patch.dict(os.environ,{'COLLESPO_SOCCER_NATIONAL':'off'}),patch.object(n,'fetch_snapshot') as fetch:
            n.main(['--out',out]);fetch.assert_not_called();self.assertFalse(n.read(Path(out)/'gate.json')['can_make'])

    def test_direct_upload_is_also_off_before_client(self):
        import upload_youtube as u
        with patch.dict(os.environ,{'COLLESPO_SOCCER_NATIONAL':'off'}),patch.object(sys,'argv',
                ['upload_youtube.py','--kind','soccer_national','--video','MISSING.mp4']),patch.object(u,'build') as client:
            u.main();client.assert_not_called()

    def test_result_slot_and_duplicate(self):
        now=n.instant('2026-11-14T12:20Z');g=n.match(event('test',complete=False))
        loader=lambda ident:summary()
        d=n.choose([g,self.future],{'627':self.schedule,'205':self.schedule,'210':self.schedule},dict(events=[]),now,{},loader)
        self.assertEqual(d['mode'],'result');self.assertEqual(d['publish_at'],'2026-11-14T22:00:00+09:00')
        self.assertIsNone(n.choose([g],{'627':self.schedule},dict(events=[]),now,{'soccer_national':{'2026-11-14':{'video_id':'TEST'}}},loader))

    def test_late_game_next_morning(self):
        now=n.instant('2026-11-17T22:20Z')
        s=summary();s['header']['competitions'][0]['date']='2026-11-17T13:10Z'
        d=n.choose([self.future],{'627':self.schedule},dict(events=[]),now,{},lambda ident:s)
        self.assertEqual(d['mode'],'result');self.assertEqual(d['publish_at'],'2026-11-18T08:00:00+09:00')

    def test_late_kickoff_day_does_not_show_remaining_squad(self):
        now=n.instant('2026-11-17T01:15Z')
        roster=dict(announced_at='2026-11-06T05:00Z',source_url='https://www.jfa.jp/test/',window='2026-11',season='2026/27',
            players=[dict(name_en='Ayase Ueda',name_jp='上田綺世',reading='ウエダアヤセ',club='試験用クラブ',position='FW')])
        d=n.choose([self.future],{'627':self.schedule},dict(events=[]),now,{},lambda ident:summary(),roster,{})
        self.assertIsNone(d)

    def test_metadata_and_record_kind(self):
        import upload_youtube as u
        doc=n.narration(self.result())
        self.assertEqual(u.build_metadata('',doc['date_jst'],'soccer_national',narration_path=self.write_doc(doc))['snippet']['title'],doc['title'])
        self.assertIn('soccer_national',u.DATED_KINDS)
        self.assertEqual(u.material_date_key('soccer_national','soccer',doc['national_material']),'2026-11-14')

    def test_unchanged_settings_repair_short_result(self):
        import soccer_national_render as r
        import soccer_results_render as common
        import synthesize_narration as synth
        d=self.result()
        with tempfile.TemporaryDirectory() as path:
            out=Path(path);n.save(out/'material.json',d);n.save(out/'narration.json',n.narration(d));n.save(out/'audio/manifest.json',{'segments':[{}]})
            count=len(n.narration(d)['segments'])
            with patch.object(common,'durations',side_effect=[[8/(count-1)]*(count-1)+[2],[28/count]*count+[2]]),patch.object(synth,'main') as voice:
                self.assertTrue(r.fit_to_audio(out));voice.assert_called_once()
            self.assertEqual(n.read(out/'material.json')['length_level'],1)
            self.assertTrue(any(s['meta'].get('panel')=='year-record' for s in n.read(out/'narration.json')['segments']))

    def test_squad_stats_current_and_stale(self):
        row=dict(name='上田綺世',club='試験クラブ',scope='season',as_of='2026-11-13T12:00Z',source='test',goals=5)
        material=dict(games=[dict(league='試験リーグ',season_players=[row])])
        self.assertEqual(n.season_rows(material,'試験クラブ','Ayase Ueda',self.now.isoformat(),'2026/27')['values']['goals'],5)
        self.assertIsNone(n.season_rows(material,'別クラブ','Ayase Ueda',self.now.isoformat(),'2026/27'))
        self.assertIsNone(n.season_rows(material,'試験クラブ','Ayase Ueda',self.now.isoformat(),'2025/26'))
        row['as_of']='2026-10-01T00:00Z'
        self.assertIsNone(n.season_rows(material,'試験クラブ','Ayase Ueda',self.now.isoformat(),'2026/27'))

    def test_publish_disabled_expired_and_sample(self):
        import soccer_national_publish as p
        d=self.result();d['publish_at']='2026-11-14T22:00:00+09:00'
        with patch.dict(os.environ,{'COLLESPO_SOCCER_NATIONAL':'off'}):
            with self.assertRaises(ValueError):p.validate(d,self.now)
        with patch.dict(os.environ,{'COLLESPO_SOCCER_NATIONAL':'on'}):
            self.assertTrue(p.validate(d,self.now))
            self.assertEqual(p.validate(d,n.instant('2026-11-14T22:01:00+09:00')),
                             n.instant('2026-11-14T22:03:00+09:00'))
            with self.assertRaises(ValueError):p.validate(d,n.instant('2026-11-15T00:01:00+09:00'))
            d['sample']=True
            with self.assertRaises(ValueError):p.validate(d,self.now)

    def test_sns_uses_own_artifact_and_soccer_words(self):
        import buffer_daily as b
        self.assertEqual(b.source_of('soccer_national'),('soccer_national','collespo-national-social','collespo_national.mp4','soccer_national.yml'))
        self.assertEqual(b.words('soccer_national')['sport'],'soccer')

    def write_doc(self,doc):
        f=tempfile.NamedTemporaryFile(suffix='.json',delete=False);f.close();n.save(f.name,doc)
        return f.name


class Narrative(unittest.TestCase):
    def setUp(self):
        self.base=National();self.base.setUp()

    def preview(self):
        schedule=dict(events=[event('j1',score=(3,1),date='2026-09-24T10:05Z'),event('j2',score=(2,1),date='2026-09-28T10:25Z')])
        return n.preview(n.match(event(complete=False)),schedule,schedule,schedule,'2026-11-13T09:00:00Z')

    def test_particles_win_loss_draw(self):
        row=self.base.result()['japan_recent']
        for score,phrase in [((3,2),'ブラジルに3対2で勝ちました'),((1,2),'ブラジルに1対2で敗れました'),((2,2),'ブラジルと2対2で引き分けました')]:
            r=dict(row,opponent='ブラジル',gf=score[0],ga=score[1])
            self.assertIn(phrase,n.result_sentence(r,'日本'))

    def test_preview_conclusion_and_no_repeated_setup(self):
        text=''.join(s['text'] for s in n.narration(self.preview())['segments'])
        self.assertTrue(text.startswith('11月14日19時15分、日本がシンガポールでブラジルと戦います。'))
        self.assertNotIn('中立地での対戦です',text)
        self.assertNotIn('その前の親善試合で日本は',text)
        self.assertIn('6月のワールドカップで敗れた相手との再戦です',text)

    def test_recent_one_sentence_and_counted_streak(self):
        data=self.preview();text=n.recent_sentence(data,'japan')
        self.assertEqual(text,'日本は10月のキリンカップで優勝しました。決勝はニュージーランドに2対1でした。')
        self.assertEqual(n.history_record(n.recent_pair(data,'japan'),2026)['winning_streak'],1)
        text=n.recent_sentence(data,'opponent')
        self.assertNotIn('連勝',text);self.assertNotIn('直近',text)
        self.assertIn('9月28日',text)

    def test_two_scorers_aggregated_not_three_events(self):
        raw=summary(score=(3,1),names=('Ayase Ueda','Ayase Ueda','Daichi Kamada','UNKNOWN'),teams=('627','627','627','205'))
        d=self.base.result(raw);rows=[r for r in n.match_story(d)['scorers'] if r['team_id']==n.JAPAN]
        self.assertEqual(len(rows),2);self.assertEqual(sum(r['goals'] for r in rows),3)
        text=n.scorer_sentence(d)
        self.assertEqual(text.count('上田綺世'),1);self.assertEqual(text.count('鎌田大地'),1)
        self.assertIn('上田綺世が2点',text);self.assertIn('鎌田大地が1点',text)

    def test_winning_goal_beats_opponents_final_score(self):
        story=n.match_story(self.base.result())
        self.assertFalse(story['comeback']);self.assertEqual(story['decisive']['minute'],'11')

    def test_conceded_first_and_comeback(self):
        d=self.base.result(summary(names=('UNKNOWN','Ayase Ueda','Ayase Ueda'),teams=('205','627','627')))
        story=n.match_story(d)
        self.assertTrue(story['conceded_first']);self.assertTrue(story['comeback'])
        self.assertEqual(story['decisive']['minute'],'12')
        text=''.join(s['text'] for s in n.narration(d)['segments'])
        self.assertIn('逆転勝ち',text);self.assertNotIn('10分にブラジルが1点',text)

    def test_comeback_without_conceding_first(self):
        raw=summary(score=(3,2),names=('Ayase Ueda','UNKNOWN','UNKNOWN','Ayase Ueda','Daichi Kamada'),teams=('627','205','205','627','627'))
        d=self.base.result(raw);story=n.match_story(d)
        self.assertTrue(story['comeback']);self.assertFalse(story['conceded_first'])
        self.assertEqual(story['decisive']['minute'],'14')
        self.assertNotIn('先に失点',str(n.narration(d)['segments']))

    def test_draw_and_zero_have_no_decisive_goal(self):
        for raw in [summary(score=(1,1),names=('Ayase Ueda','UNKNOWN'),teams=('627','205')),summary(score=(0,0),names=(),teams=())]:
            story=n.match_story(self.base.result(raw))
            self.assertIsNone(story['decisive']);self.assertFalse(story['comeback'])

    def test_missing_events_never_get_names_or_story(self):
        d=self.base.result(summary(score=(3,1),names=('Ayase Ueda','UNKNOWN'),teams=('627','205')))
        text=''.join(s['text'] for s in n.narration(d)['segments'])
        for word in ('上田綺世','決勝点','逆転'):self.assertNotIn(word,text)
        self.assertEqual(n.title(d),'日本3-1ブラジル #Shorts')

    def test_extra_time_and_order(self):
        raw=summary(names=('Ayase Ueda','UNKNOWN','Ayase Ueda'),teams=('627','205','627'))
        for e,minute in zip(raw['keyEvents'],("90'+6'","46'","49'")):e['clock']['displayValue']=minute
        story=n.match_story(self.base.result(raw))
        self.assertEqual(story['decisive']['minute'],'90+6')
        self.assertEqual(n.minute_words('90+6'),'後半追加時間6分')

    def test_record_counts_only_given_year_and_unique_ids(self):
        row=self.base.result()['japan_recent'];old=dict(row,id='lastyear',date_jst='2025-01-01')
        r=n.history_record([row,row,old],2026)
        self.assertEqual((r['games'],r['wins'],r['losses'],r['draws']),(1,1,0,0))
        with self.assertRaises(ValueError):n.history_record([row,dict(row,gf=7)],2026)

    def test_unbeaten_count_stops_at_loss(self):
        row=self.base.result()['japan_recent']
        rows=[dict(row,id='win',gf=2,ga=1,start_utc='2026-09-28T10:00Z'),
              dict(row,id='draw',gf=1,ga=1,start_utc='2026-09-24T10:00Z'),
              dict(row,id='loss',gf=0,ga=1,start_utc='2026-05-31T10:00Z')]
        r=n.history_record(rows,2026)
        self.assertEqual((r['winning_streak'],r['unbeaten']),(1,2))

    def test_no_reading_halves_as_final_score(self):
        d=self.base.result();d['goals_complete']=False;d['goals']=[];d['goal_counts']={'627':1,'205':1}
        d['halves']=dict(japan=[1,1],opponent=[1,0])
        text=''.join(s['text'] for s in n.narration(d)['segments'])
        self.assertIn('前半を1対1で折り返し、後半に1点を加えました',text)
        self.assertNotIn('前半のスコアは',text);self.assertNotIn('後半のスコアは',text)

    def test_concise_titles(self):
        self.assertEqual(n.title(self.preview()),'日本対ブラジル 11/14 19:15 #Shorts')
        self.assertEqual(n.title(self.base.result()),'日本2-1ブラジル 上田綺世2得点 #Shorts')

    def test_length_additions_prioritize_year_before_previous_game(self):
        import soccer_national_render as r
        import soccer_results_render as common
        import synthesize_narration as synth
        d=self.base.result();count=len(n.narration(d)['segments'])
        lengths=[[13/(count-1)]*(count-1)+[2],[18/count]*count+[2],[20/count]*count+[2],[22/(count+1)]*(count+1)+[2],[28/(count+2)]*(count+2)+[2]]
        with tempfile.TemporaryDirectory() as path:
            out=Path(path);n.save(out/'material.json',d);n.save(out/'narration.json',n.narration(d));n.save(out/'audio/manifest.json',{'segments':[{}]})
            with patch.object(common,'durations',side_effect=lengths),patch.object(synth,'main'):
                self.assertTrue(r.fit_to_audio(out))
            self.assertEqual([s['level'] for s in n.read(out/'duration_repair.json')['steps']],[1,2,3,4])
            self.assertEqual(n.read(out/'material.json')['length_level'],4)


class VerifiedHistory(unittest.TestCase):
    def preview(self,at='2026-11-02T00:35Z',observed=None,opp='205'):
        return n.preview(n.match(event(complete=False,opp=opp)),observed or {'events':[]},
            {'events':[event('op',score=(0,4),date='2026-10-03T14:00Z',opp=opp)]},{},at)

    def test_total_all_competitions_and_pk_draw(self):
        d=self.preview();r=n.history_record(d['japan_history'],2026)
        self.assertEqual(tuple(r[k] for k in ('games','wins','draws','losses','gf','ga')),(11,7,3,1,18,8))
        pk=next(r for r in d['japan_history'] if r['opponent']=='エクアドル')
        self.assertEqual((pk['gf'],pk['ga'],pk['result']),(0,0,'draw'))
        self.assertEqual(n.record_sentence(d),'2026年は11試合で7勝3分1敗です。')
        self.assertNotIn('全勝',n.record_sentence(d));self.assertNotIn('すべて',n.record_sentence(d))

    def test_latest_and_previous_ignore_friendly_schedule(self):
        friendly={'events':[event('old',date='2026-09-28T10:25Z')]}
        d=self.preview(observed=friendly)
        self.assertEqual(d['japan_recent']['date_jst'],'2026-10-05')
        self.assertEqual(d['previous']['date_jst'],'2026-06-30')
        self.assertEqual((d['previous']['gf'],d['previous']['ga']),(1,2))
        self.assertEqual(d['previous_earlier']['date_jst'],'2025-10-14')

    def test_correct_openings_and_paraguay(self):
        doc=n.narration(self.preview());text=''.join(s['text'] for s in doc['segments'])
        self.assertIn('ワールドカップのラウンド32では1対2でした。その前の2025年10月の親善試合では3対2で勝っています。',text)
        self.assertEqual(n.check(doc),[])
        text=''.join(s['text'] for s in n.narration(self.preview(opp='210'))['segments'])
        self.assertIn('前回は2025年10月の親善試合で2対2でした。',text)

    def test_old_2025_previous_claim_is_rejected(self):
        doc=n.narration(self.preview())
        doc['segments'][0]['text']='前回は2025年10月に日本が3対2で勝っています。'
        self.assertTrue(n.check(doc))
        doc=n.narration(self.preview());doc['national_material']['previous']=doc['national_material']['previous_earlier']
        doc['segments']=n.segments_for(doc['national_material'])
        self.assertTrue(n.check(doc))

    def test_old_five_friendly_wins_claim_is_rejected(self):
        d=self.preview();d['length_level']=2;doc=n.narration(d)
        doc['segments'][-1]['text']='今年の親善試合は、確認できる5試合すべてで勝っています。'
        self.assertTrue(n.check(doc))
        d['japan_history']=[r for r in d['japan_history'] if r['competition']=='親善試合']
        self.assertTrue(n.check(n.narration(d)))

    def test_each_annual_number_is_checked(self):
        original=n.narration(self.preview())
        for old,new in [('11試合','12試合'),('7勝','8勝'),('3分','2分'),('1敗','0敗')]:
            doc=copy.deepcopy(original)
            for s in doc['segments']:s['text']=s['text'].replace(old,new)
            self.assertTrue(n.check(doc))

    def test_new_unlisted_completed_game_suppresses_all_history(self):
        observed={'events':[event('unlisted',date='2026-10-20T10:00Z')]}
        with self.assertWarns(UserWarning):d=self.preview(observed=observed)
        self.assertFalse(d['history_trusted']);self.assertTrue(d['history_warnings'])
        self.assertIsNone(d['previous']);self.assertEqual(d['japan_history'],[])
        text=''.join(s['text'] for s in n.narration(d)['segments'])
        for word in ('前回','直近','連勝','年間','2026年は','キリンカップ','再戦'):self.assertNotIn(word,text)
        self.assertEqual(n.check(n.narration(d)),[])

    def test_stale_and_exact_age_boundary(self):
        # 予告自体の開始時刻を未来へずらして履歴の期限だけを試験。
        def future(at):
            g=n.match(event(complete=False,date='2026-12-01T10:15Z'))
            return n.preview(g,{'events':[]},{'events':[]},{},at)
        self.assertTrue(future('2026-11-23T00:00Z')['history_trusted'])
        with self.assertWarns(UserWarning):d=future('2026-11-24T00:00Z')
        self.assertFalse(d['history_trusted']);self.assertEqual(n.record_sentence(d),'')

    def test_added_current_result_is_counted_once(self):
        d=n.result(summary(),[],{'events':[event()]},'2026-11-14T13:00Z')
        self.assertEqual(n.check(n.narration(d)),[])
        r=n.history_record(d['japan_history'],2026)
        self.assertEqual(tuple(r[k] for k in ('games','wins','draws','losses','gf','ga')),(12,8,3,1,20,9))

    def test_old_result_excludes_future_and_deduplicates_current(self):
        for date,expected in [('2026-09-24',(8,5,2,1,14,6)),('2026-09-28',(9,6,2,1,16,7))]:
            raw=summary(score=(3,1) if date.endswith('24') else (2,1))
            c=raw['header']['competitions'][0];c['date']=date+'T10:00Z'
            c['competitors'][1]['team']['displayName']='Uruguay' if date.endswith('24') else 'Venezuela'
            d=n.result(raw,[],{'events':[]},date+'T14:00Z')
            r=n.history_record(d['japan_history'],2026)
            self.assertEqual(tuple(r[k] for k in ('games','wins','draws','losses','gf','ga')),expected)
            self.assertFalse(any(v['date_jst']>date for v in d['japan_history']))

    def test_conflicting_current_score_stops(self):
        raw=summary(score=(9,0));c=raw['header']['competitions'][0]
        c['date']='2026-09-28T10:00Z';c['competitors'][1]['team']['displayName']='Venezuela'
        with self.assertRaisesRegex(ValueError,'不一致'):n.result(raw,[],{'events':[]},'2026-09-28T14:00Z')

    def test_pk_sentence_does_not_invent_shootout_score(self):
        d=self.preview('2026-10-03T00:00Z')
        self.assertEqual(n.recent_sentence(d,'japan'),'エクアドルとは0対0からPK戦で勝ちました。')

    def test_opponent_facts_are_dated_without_streak_claim(self):
        d=self.preview();text=n.recent_sentence(d,'opponent')
        self.assertIn('10月3日',text)
        self.assertNotIn('直近',text);self.assertNotIn('連勝',text)
        self.assertNotIn('親善試合',text)

    def test_all_schedule_endpoint(self):
        import requests
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'events':[event('brazil',complete=False),event('paraguay',complete=False,opp='210')]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(requests,'get',return_value=Response()) as get:
            n.fetch_snapshot(tmp,n.instant('2026-11-02T00:00Z'),days=0)
            urls=[c.args[0] for c in get.call_args_list]
            self.assertIn(n.ALL_API+'teams/627/schedule',urls)
            self.assertIn(n.ALL_API+'teams/205/schedule',urls)
            self.assertIn(n.ALL_API+'teams/210/schedule',urls)
            self.assertNotIn(n.API+'teams/627/schedule',urls)

    def test_other_unlisted_game_is_not_hidden_by_current_result(self):
        observed={'events':[event(),event('other',date='2026-10-20T10:00Z')]}
        with self.assertWarns(UserWarning):d=n.result(summary(),[],observed,'2026-11-14T13:00Z')
        self.assertFalse(d['history_trusted']);self.assertEqual(n.record_sentence(d),'')
        self.assertEqual(n.check(n.narration(d)),[])

    def test_updated_authority_requires_regeneration(self):
        import soccer_national_history as h
        doc=n.narration(self.preview())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.json';path.write_bytes(h.PATH.read_bytes()+b'\n')
            with patch.object(h,'PATH',path):self.assertTrue(n.check(doc))

    def test_cup_route_fact_is_verified_and_no_pk_score(self):
        d=self.preview();d['length_level']=3;doc=n.narration(d)
        text=next(s['text'] for s in doc['segments'] if s['meta'].get('panel')=='cup-route')
        self.assertEqual(text,'キリンカップの1回戦はエクアドルと0対0からPK戦で勝ちました。')
        self.assertEqual(n.check(doc),[])
        self.assertEqual(n.history_record(d['japan_history'],2026)['gf'],18)

    def test_partial_or_legacy_material_cannot_validate_itself(self):
        doc=n.narration(self.preview());doc['national_material'].pop('history_version')
        self.assertTrue(n.check(doc))
        doc=n.narration(self.preview());doc['national_material']['japan_recent']['gf']=9
        doc['segments']=n.segments_for(doc['national_material'])
        self.assertTrue(n.check(doc))


class ResultBoardLabel(unittest.TestCase):
    def test_japan_row_shows_stage_not_team(self):
        import soccer_national_render as R
        r=dict(team='日本',date_jst='2026-10-05T19:00:00+09:00',competition='キリンカップ',stage='決勝',gf=2,ga=1,opponent='ニュージーランド')
        self.assertEqual(R.result_board(r),('2026/10/5 決勝','2-1 ニュージーランド'))
        self.assertEqual(R.result_board(dict(r,stage=None))[0],'2026/10/5 キリンカップ')
    def test_opponent_row_keeps_team(self):
        import soccer_national_render as R
        r=dict(team='ブラジル',date_jst='2026-10-10T08:00:00+09:00',gf=3,ga=0,opponent='チリ')
        self.assertEqual(R.result_board(r)[0],'2026/10/10 ブラジル')


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
