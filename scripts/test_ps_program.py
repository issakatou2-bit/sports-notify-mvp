"""Fixed PS cases: all four cards, series boundaries and publication gates."""
import copy
import contextlib
import io
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ps_program as p


def fixture(day=28):
    pairs = [(117,145,114,103,'HOU','CWS'), (147,111,139,103,'NYY','BOS'),
             (144,143,119,104,'ATL','PHI'), (135,112,158,104,'SD','CHC')]
    names = {117:'アストロズ',145:'ホワイトソックス',114:'ガーディアンズ',147:'ヤンキース',
             111:'レッドソックス',139:'レイズ',144:'ブレーブス',143:'フィリーズ',119:'ドジャース',
             135:'パドレス',112:'カブス',158:'ブリュワーズ'}
    snapshot = dict(date=f'2026-09-{day:02d}',phase='postseason',
                    teams={str(i):dict(name=n,clinched=True) for i,n in names.items()},
                    japanese=[dict(team_id='145',players=['検証選手'])])
    games=[]
    def team(i,lid,abbr):
        return dict(id=i,name=names.get(i,'仮の相手'),abbreviation=abbr,league=dict(id=lid))
    for index,(home,away,bye,lid,ha,aa) in enumerate(pairs):
        for n in range(1,4):
            start=datetime(2026,9,29,18+index,tzinfo=timezone.utc)+timedelta(days=n-1)
            games.append(dict(gamePk=1000+index*10+n,gameType='F',season='2026',officialDate=start.date().isoformat(),
                         gameDate=start.isoformat(),seriesGameNumber=n,gamesInSeries=3,
                         status=dict(abstractGameState='Preview',startTimeTBD=False),
                         teams=dict(home=dict(team=team(home,lid,ha)),away=dict(team=team(away,lid,aa)))))
        games.append(dict(gamePk=2000+index,gameType='D',season='2026',officialDate='2026-10-03',
                     gameDate='2026-10-03T18:00:00+00:00',seriesGameNumber=1,gamesInSeries=5,
                     status=dict(abstractGameState='Preview',startTimeTBD=True),
                     teams=dict(home=dict(team=team(bye,lid,'BYE')),away=dict(team=team(9999,lid,ha+'/'+aa)))))
        games[-1]['teams']['away']['team']['name']=ha+'/'+aa
    now=datetime(2026,9,day,7,tzinfo=timezone.utc)
    ev=dict(retrieved_at=now.isoformat(),source_url='https://statsapi.mlb.com/api/v1/schedule',schedule=dict(dates=[dict(games=games)]))
    return snapshot,ev,now


class ProgramTests(unittest.TestCase):
    def test_spoken_rounds_preserve_team_abbreviations_and_display(self):
        from notability_engine import apply_readings
        from ps_render_template import overlaps
        import synthesize_narration as synth
        source='WCS第1戦。DS・LCS・WS。ALDS / NLDS / ALCS / NLCS。CWSとWSH。'
        spoken=apply_readings(source)
        self.assertIn('ワイルドカードシリーズ第1戦',spoken)
        self.assertIn('地区シリーズ・リーグ優勝決定シリーズ・ワールドシリーズ',spoken)
        self.assertIn('ア・リーグ地区シリーズ / ナ・リーグ地区シリーズ',spoken)
        self.assertIn('ア・リーグ優勝決定シリーズ / ナ・リーグ優勝決定シリーズ',spoken)
        self.assertIn('CWSとWSH',spoken)
        self.assertEqual(apply_readings('NEWS lowercase ws CWCS'), 'NEWS lowercase ws CWCS')
        reply=mock.Mock();reply.json.return_value={};reply.content=b'audio'
        with mock.patch.object(synth.requests,'post',return_value=reply) as post:
            self.assertTrue(synth.synth_one(source,2,mock.Mock()))
            self.assertEqual(post.call_args_list[0].kwargs['params']['text'],spoken)
        snap,ev,now=fixture(29)
        program=p.prepare(snap,ev,'forecast',now)
        card=program['segments'][1]['meta']['card']
        self.assertEqual(card['round_game'],'WCS 第1戦')
        _, manifest=p.render_segment(program['segments'][1])
        text=[row['text'] for row in manifest['text']]
        self.assertIn('1/4',text)
        self.assertNotIn('カード',text)
        self.assertIn('WCS 第1戦',text)
        page=next(row for row in manifest['text'] if row['text']=='1/4')
        nth=next(row for row in manifest['text'] if row['text']=='WCS 第1戦')
        self.assertFalse(overlaps(page['box'],nth['box']))

    def test_forecast_exposes_game_day_to_existing_publication_gate(self):
        import mlb_availability
        snap,ev,now=fixture(29)
        program=p.prepare(snap,ev,'forecast',now)
        narration=p.script(program)
        self.assertEqual(program['date_jst'],'2026-09-29')
        self.assertEqual(narration['date_jst'],'2026-09-30')
        self.assertEqual(narration['date_label'],'09/30')
        payload={'games':[dict(is_notable=True,league='MLB',start_time_jst='09/30 03:00')]}
        mlb_availability.check_narration(payload,narration,{},now)
        wrong={**narration,'date_label':'09/29'}
        with self.assertRaisesRegex(ValueError,'date does not match'):
            mlb_availability.check_narration(payload,wrong,{},now)

    def test_probable_pitcher_names_keep_their_ink_inside_the_safe_area(self):
        for name in ('AJ Blubaugh', 'Alex Wood', 'José Berríos', 'Jordan Montgomery'):
            snap,ev,now=fixture(29)
            ev['schedule']['dates'][0]['games'][0]['teams']['home']['probablePitcher']=dict(id=123,fullName=name)
            pr=p.prepare(snap,ev,'forecast',now)
            manifests=p.check_program(pr)['rendered']
            ink=next(row for m in manifests for row in m['text'] if row['text']==p.display_name(name))
            self.assertGreaterEqual(ink['box'][0],72)
            self.assertLessEqual(ink['box'][2],936)

    def test_negative_font_bearing_is_aligned_without_relaxing_width(self):
        import ps_brand_components as brand
        class InkDraw:
            def textbbox(self,xy,value,font):
                x,y=xy
                return (x-1,y+5,x+100,y+35)
            def text(self,xy,value,font,fill):
                self.position=xy
        draw=InkDraw()
        with mock.patch.object(brand,'font',return_value=object()):
            box=brand.text(draw,(72,1000),'AJ Blubaugh',40,'white',width=101,minimum=40)
            self.assertEqual(box,(72,1005,173,1035))
            self.assertEqual(draw.position,(73,1000))
            with self.assertRaisesRegex(ValueError,'another line/page'):
                brand.text(draw,(72,1000),'AJ Blubaugh',40,'white',width=100,minimum=40)

    def test_unresolved_opponent_cannot_disappear_from_all_game_forecast(self):
        for tbd in (False,True):
            snap,ev,now=fixture(29)
            game=ev['schedule']['dates'][0]['games'][0]
            game['teams']['away']['team']=dict(id=9999,name='未確定',league=dict(id=103))
            game['status']['startTimeTBD']=tbd
            rows=p.series.build(ev['schedule']['dates'][0]['games'])
            ctx=dict(date_jst='2026-09-29',source_url=ev['source_url'])
            with self.assertRaisesRegex(ValueError,'対戦相手が未確定'):
                p.forecast(ctx,ev['schedule']['dates'][0]['games'],rows,now)
            # Distant placeholders do not halt the independently confirmed slate.
            game['officialDate']='2026-10-15';game['gameDate']='2026-10-15T18:00:00Z'
            self.assertEqual(len(p.forecast(ctx,ev['schedule']['dates'][0]['games'],rows,now)['game_ids']),3)

    def test_unfinished_prior_game_is_not_always_a_conditional_game(self):
        for kind,need in [('F',2),('D',3),('L',4),('W',4)]:
            snap,ev,now=fixture(29)
            games=[g for g in ev['schedule']['dates'][0]['games'] if g['gameType']=='F']
            for g in games:
                g['gameType']=kind;g['gamesInSeries']=need*2-1
                if g['seriesGameNumber']==1:g['status']['abstractGameState']='Live'
            rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
            pr=p.forecast(dict(date_jst='2026-09-30',source_url=ev['source_url']),games,rows,now,target_day='2026-10-01')
            self.assertNotIn('結果次第で開催',str(pr))
            self.assertNotIn('開催条件付き',pr['title'])
            self.assertIn('前戦は結果未確定',str(pr))
            self.assertIn('確定済みの勝数は',str(pr))
            if kind=='F':
                later=p.forecast(dict(date_jst='2026-10-01',source_url=ev['source_url']),games,rows,now,target_day='2026-10-02')
                self.assertIn('結果次第で開催',str(later))
                self.assertIn('開催条件付き',later['title'])

    def test_unconfirmed_relevant_card_blocks_all_game_claim(self):
        snap,ev,now=fixture(29)
        games=ev['schedule']['dates'][0]['games']
        games[0]['status']['startTimeTBD']=True
        with self.assertRaisesRegex(ValueError,'全試合を確定できません'):
            p.prepare(snap,ev,'forecast',now)
        missing_day=copy.deepcopy(games);missing_day[0].pop('officialDate')
        rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
        with self.assertRaisesRegex(ValueError,'全試合を確定できません'):
            p.forecast(dict(date_jst='2026-09-29',source_url=ev['source_url']),missing_day,rows,now)
        # Distant unconfirmed games and completed series do not block tomorrow.
        games[0]['officialDate']='2026-10-15'
        pr=p.prepare(snap,ev,'forecast',now)
        self.assertEqual(len(pr['game_ids']),3)
        games[0]['officialDate']='2026-09-29'
        for game in games[:2]:
            game['status']['abstractGameState']='Final'
            game['teams']['home']['isWinner']=True
        pr=p.prepare(snap,ev,'forecast',now)
        self.assertEqual(len(pr['game_ids']),3)

    def test_postponed_cancelled_cards_are_not_future_fixtures(self):
        for state in ('Postponed','Cancelled','Canceled'):
            snap,ev,now=fixture(29)
            game=ev['schedule']['dates'][0]['games'][0]
            game['status']['detailedState']=state
            pr=p.prepare(snap,ev,'forecast',now)
            self.assertNotIn(game['gamePk'],pr['game_ids'])
            self.assertEqual(len(pr['game_ids']),3)
        snap,ev,now=fixture(29)
        ev['schedule']['dates'][0]['games'][0]['status']['codedGameState']='D'
        self.assertNotIn(ev['schedule']['dates'][0]['games'][0]['gamePk'],p.prepare(snap,ev,'forecast',now)['game_ids'])

    def test_intro_does_not_duplicate_the_all_card_forecast(self):
        snap,ev,now=fixture()
        a=p.prepare(snap,ev,'situation',now)
        snap2,ev2,now2=fixture(29)
        b=p.prepare(snap2,ev2,'situation',now2)
        self.assertEqual(a['phase'],'intro_all');self.assertIsNone(b)
        self.assertEqual(len(a['game_ids']),4)
        p.check_program(a)
        self.assertEqual(len(p.prepare(snap2,ev2,'forecast',now2)['game_ids']),4)

    def test_numbering_colors_black_outfit_and_probables(self):
        snap,ev,now=fixture(29)
        first=ev['schedule']['dates'][0]['games'][0]
        first['teams']['home']['probablePitcher']=dict(id=123,fullName='Michael King')
        pr=p.prepare(snap,ev,'forecast',now)
        details=[s['meta']['card'] for s in pr['segments'][1:]]
        self.assertEqual([c['card_index'] for c in details],[1,2,3,4])
        self.assertTrue(all(c['card_total']==4 for c in details))
        self.assertNotIn('card_index',pr['segments'][0]['meta']['card'])
        self.assertIn('明日9/30',pr['segments'][0]['meta']['card']['headline'])
        self.assertEqual(details[0]['headline_colors'],[p.club_color(117),p.club_color(145)])
        self.assertEqual(details[0]['headline_secondary_colors'],['#EB6E1F','#C4CED4'])
        self.assertEqual(details[0]['round_game'],'WCS 第1戦')
        self.assertGreater(details[0]['items'][0]['value_size'],details[0]['items'][1]['value_size'])
        self.assertEqual(details[0]['items'][2]['value'],'確認中')
        self.assertNotEqual(details[0]['items'][1]['value'],'確認中')
        self.assertNotIn('0勝対0勝',pr['segments'][1]['text'])
        self.assertIn('地区シリーズ',pr['segments'][1]['text'])
        manifests=p.check_program(pr)['rendered']
        self.assertTrue(all('black' in x['presenters'][0]['asset'] for x in manifests))
        self.assertIsNone(p.probable({'probablePitcher':{'fullName':'Unidentified'}}))
        details[0]['card_index']=0
        with self.assertRaises(ValueError):p.render_segment(pr['segments'][1])

    def test_opening_details_follow_each_round_and_new_schedule(self):
        for kind,need,next_label in [('D',3,'リーグ優勝決定シリーズ'),('L',4,'ワールドシリーズ'),('W',4,'世界一')]:
            snap,ev,now=fixture(29)
            games=[g for g in ev['schedule']['dates'][0]['games'] if g['gameType']=='F']
            for game in games:game['gameType']=kind;game['gamesInSeries']=need*2-1
            rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
            pr=p.forecast(dict(date_jst='2026-09-29',source_url=ev['source_url']),games,rows,now)
            details=pr['segments'][1:]
            self.assertTrue(all(s['meta']['card']['items'][1]['value']==next_label for s in details))
            self.assertTrue(all(s['meta']['card']['items'][2]['value']==f'{need}勝先取' for s in details))
            self.assertNotIn('勝者の地区シリーズの相手',str(details))
        snap,ev,now=fixture(29)
        first=ev['schedule']['dates'][0]['games'][0]
        first['gameDate']='2026-09-29T23:30:00+00:00'
        pr=p.prepare(snap,ev,'forecast',now)
        detail=next(s for s in pr['segments'][1:] if first['gamePk'] in s['meta']['game_ids'])
        self.assertEqual(detail['meta']['card']['items'][0]['value'],'08:30')
        self.assertIn('8時30分',detail['text'])

    def test_no_tomorrow_game(self):
        snap,ev,now=fixture()
        self.assertIsNone(p.prepare(snap,ev,'forecast',now))

    def test_all_four_and_japanese_away_headline(self):
        snap,ev,now=fixture(29)
        pr=p.prepare(snap,ev,'forecast',now)
        self.assertEqual(len(pr['game_ids']),4)
        self.assertIn('ホワイトソックス',pr['title'])
        self.assertIn('PS全4試合',pr['title'])
        self.assertEqual(p.check_program(pr)['represented_game_ids'],sorted(pr['game_ids']))
        self.assertNotIn('デザイン確認用',str(p.check_program(pr)['rendered']))

    def test_source_failure_and_stale_year(self):
        snap,ev,now=fixture()
        for broken in ('empty','stale','winners','two_winners','strings'):
            case=copy.deepcopy(ev)
            if broken=='empty':case['schedule']['dates']=[]
            elif broken=='stale':case['schedule']['dates'][0]['games'][0]['officialDate']='2025-09-29'
            else:
                game=case['schedule']['dates'][0]['games'][0]
                game['status']['abstractGameState']='Final'
                if broken=='two_winners':
                    game['teams']['home']['isWinner']=True;game['teams']['away']['isWinner']=True
                elif broken=='strings':game['teams']['home']['isWinner']='false'
            with self.subTest(broken=broken),self.assertRaises(ValueError):p.prepare(snap,case,'situation',now)
        with self.assertRaises(ValueError):p.prepare(snap,ev,'situation',now+timedelta(hours=3))

    def test_swept_series_removed_from_forecast(self):
        snap,ev,now=fixture(29)
        for game in ev['schedule']['dates'][0]['games']:
            if game['gameType']=='F' and game['seriesGameNumber']<3:
                game['status']['abstractGameState']='Final';game['teams']['home']['isWinner']=True
        ctx=p.pe.editorial(snap,ev['schedule'],now,ev['source_url'])
        games=ev['schedule']['dates'][0]['games']
        rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
        self.assertIsNone(p.forecast(ctx,games,rows,datetime(2026,10,1,7,tzinfo=timezone.utc)))
        result=p.situation_program(ctx,rows,{})
        self.assertEqual(len(result['segments']),4)
        self.assertTrue(all(r['over'] for r in rows if not r.get('waiting')))

    def test_same_count_changed_winner_is_new(self):
        snap,ev,now=fixture()
        game=ev['schedule']['dates'][0]['games'][0]
        game['status']['abstractGameState']='Final';game['teams']['home']['isWinner']=True
        ctx,games=p.validate_source(snap,ev,now)
        rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
        before=dict(program_series=copy.deepcopy(rows))
        self.assertIsNone(p.situation_program(ctx,rows,before))
        game['teams']['home']['isWinner']=False;game['teams']['away']['isWinner']=True
        after=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
        self.assertIsNotNone(p.situation_program(ctx,after,before))

    def test_render_and_audio_coverage_must_match(self):
        snap,ev,now=fixture(29)
        pr=p.prepare(snap,ev,'forecast',now)
        pr['game_ids'].append(98765)
        with self.assertRaises(ValueError):p.check_program(pr)
        pr=p.prepare(snap,ev,'forecast',now)
        pr['segments'][1]['meta']['card']['items'][0]['value']='99勝'
        with self.assertRaises(ValueError):p.check_program(pr)

    def test_layout_has_explicit_hold_and_rollback(self):
        for value in ('hold','legacy','v2'):
            with mock.patch.dict(p.os.environ,PS_PROGRAM_LAYOUT=value):self.assertEqual(p.layout(),value)
        with mock.patch.dict(p.os.environ,PS_PROGRAM_LAYOUT='typo'),self.assertRaises(ValueError):p.layout()

    def test_every_round_and_world_series_final_report_once(self):
        ctx=dict(date_jst='2026-10-31',source_url='https://statsapi.mlb.com/api/v1/schedule')
        now=datetime(2026,10,31,7,tzinfo=timezone.utc)
        for kind,need in [('F',2),('D',3),('L',4),('W',4)]:
            games=[]
            for n in range(1,need+1):
                games.append(dict(gamePk=500+n,gameType=kind,seriesGameNumber=n,gamesInSeries=need*2-1,
                    officialDate='2026-10-31',gameDate='2026-10-31T18:00:00+00:00',
                    status=dict(abstractGameState='Final' if n<need else 'Preview',startTimeTBD=False),
                    teams=dict(home=dict(team=dict(id=117,name='アストロズ',league=dict(id=103)),isWinner=n<need),
                               away=dict(team=dict(id=145,name='ホワイトソックス',league=dict(id=103)),isWinner=False))))
            rows=p.series.build(games,{117:'アストロズ',145:'ホワイトソックス'})
            program=p.forecast(ctx,games,rows,now)
            with self.subTest(round=kind):
                self.assertIsNotNone(program)
                self.assertIn('世界一' if kind=='W' else '突破',program['title'])
                games[-1]['status']['abstractGameState']='Final';games[-1]['teams']['home']['isWinner']=True
                finished=p.series.build(games,{117:'アストロズ',145:'ホワイトソックス'})
                self.assertIsNone(p.forecast(ctx,games,finished,now))
                result=p.situation_program(ctx,finished,{})
                self.assertIsNotNone(result)
                self.assertIsNone(p.situation_program(ctx,finished,dict(program_series=finished)))
                if kind=='W':self.assertIn('世界一',result['title'])

    def test_unchanged_intro_and_rehearsal_cannot_publish(self):
        snap,ev,now=fixture()
        pr=p.prepare(snap,ev,'situation',now)
        ledger=dict(morning_postseason={'2026-09-28':dict(video_id='abcdef12345',program_version=p.VERSION,program_edition=pr['edition_key'])})
        self.assertIsNone(p.prepare(snap,ev,'situation',now,ledger))
        pr['rehearsal']=True
        with self.assertRaises(ValueError):p.upload(pr,[])

    def test_unconfirmed_dates_and_live_game_not_final(self):
        snap,ev,now=fixture()
        ctx,games=p.validate_source(snap,ev,now)
        rows=p.series.build(games,{int(k):v['name'] for k,v in snap['teams'].items()})
        for game in games:
            game['status']['startTimeTBD']=True
        p.verify_next_games(rows,games)
        result=p.situation_program(ctx,rows,dict(program_series=[]))
        self.assertTrue(all('開始時刻は確認中' in s['text'] for s in result['segments']))
        self.assertNotIn('9月30日',str(result))
        game=games[0];game['status']['abstractGameState']='Live'
        p.verify_next_games(rows,games)
        result=p.situation_program(ctx,rows,dict(program_series=[]))
        self.assertIn('進行中',str(result))
        self.assertIn('結果はまだ含めていません',str(result))

    def test_spoken_time_presenter_and_briefing_motion(self):
        self.assertEqual(p.spoken_clock('06:00'),'6時')
        self.assertEqual(p.spoken_start('09/30 06:05'),'9月30日6時5分')
        snap,ev,now=fixture()
        pr=p.prepare(snap,ev,'situation',now)
        for seg in pr['segments']:
            image,manifest,foreground=p.render_segment(seg,layers=True)
            expected='left' if seg['speaker']==3 else 'right'
            self.assertEqual(manifest['presenters'][0]['side'],expected)
            prepared=p.motion.prepare(foreground,seg['meta']['card'])
            early=p.motion.frame(prepared,0.1)
            settled=p.motion.frame(prepared,2)
            later=p.motion.frame(prepared,6)
            self.assertNotEqual(early.tobytes(),settled.tobytes())
            self.assertNotEqual(settled.tobytes(),later.tobytes())
            # All foreground bands must exactly settle; only the background moves.
            base=p.motion.background(seconds=2);base.paste(foreground,(0,0),foreground)
            self.assertEqual(settled.tobytes(),base.tobytes())
            self.assertEqual(image.size,early.size)

    def test_bad_series_excluded_without_blocking_shared_material(self):
        snap,ev,now=fixture()
        ctx,games=p.validate_source(snap,ev,now)
        game=games[0];game['status']['abstractGameState']='Final'
        game['teams']['home']['isWinner']=True;game['teams']['away']['isWinner']=True
        key=p.series.series_key(game['gameType'],*(game['teams'][s]['team']['id'] for s in ('home','away')))
        with self.assertRaises(ValueError):p.series.build(games)
        with contextlib.redirect_stderr(io.StringIO()) as warning:
            rows=p.series.build(games,strict=False)
        self.assertNotIn(key,[r['key'] for r in rows])
        self.assertTrue(rows)
        self.assertIn('除外',warning.getvalue())
        with self.assertRaises(ValueError):p.prepare(snap,ev,'situation',now)


if __name__=='__main__':unittest.main(argv=[__file__])
