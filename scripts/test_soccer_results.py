"""保存ESPNの個人成績・終了日・順位・材料/画面/尺・手動投稿の検査。"""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import soccer_results as sr
import soccer_results_render as render
import soccer_v4_cards as cards
import review_render_v3 as r3

FIXTURE=ROOT/'scripts/fixtures/soccer-results'


def fixture():
    return (json.loads((FIXTURE/'scoreboards.json').read_text(encoding='utf-8')),
            json.loads((FIXTURE/'summaries.json').read_text(encoding='utf-8')))


def fixed(day='2026-09-21'):
    boards,summaries=fixture();return sr.build(boards,summaries,day)


def inspect(data):
    narr=render.narration(data);clubs=render.resolve_clubs(data)
    for seg in narr['segments']:
        times=(3.0,) if seg['kind']=='outro' else (0,.3,.8,1.4)
        for t in times:
            r3.set_program_clock(0);r3.set_caption(seg['text'],12,32,hide_caption=seg['kind']=='outro');r3.set_program_clock(t)
            image=render.frame(t,seg,data,clubs)
            errors=render.validate_frame(image,data,clubs)
            if errors:raise AssertionError((seg['kind'],t,errors))
            if image.size!=(1080,1920):raise AssertionError('寸法')
            if image.info.get('v3_background_team') is not None:raise AssertionError('多クラブ枠の地')
    r3.set_program_clock(None)


class SoccerResults(unittest.TestCase):
    def test_native_personal_results(self):
        players={p['name']:p for day in ('2026-09-19','2026-09-20','2026-09-21') for p in fixed(day)['players']}
        for name,status in (('町野修斗','substitute'),('鈴木唯人','starter'),('上田綺世','starter')):
            self.assertEqual((players[name]['goals'],players[name]['status']),(1,status))
        for name in ('佐野海舟','堂安律','中村草太'):self.assertEqual(players[name]['assists'],1)
        self.assertEqual(players['久保建英']['status'],'none')
        self.assertEqual(players['鈴木ザイオン']['status'],'starter')
        self.assertEqual(players['前田大然']['status'],'substitute')
        self.assertEqual(players['鈴木ザイオン']['club'],'アストン・ヴィラ')

    def test_final_jst_date_not_kickoff(self):
        boards,summaries=fixture()
        game=next(g for g in fixed()['games'] if g['id']=='401876452')
        self.assertEqual(sr.utc(game['finished_utc']).astimezone(sr.JST).date().isoformat(),'2026-09-21')
        self.assertNotIn(game['id'],[g['id'] for g in sr.build(boards,summaries,'2026-09-20')['games']])
        # The September 19 14:00 UTC fixture finishes after JST midnight on September 20.
        self.assertIn('401878778',[g['id'] for g in fixed('2026-09-20')['games']])
        self.assertNotIn('401878778',[g['id'] for g in fixed('2026-09-19')['games']])
        summaries['401876452']['summary']['keyEvents']=[]
        changed=sr.build(boards,summaries,'2026-09-21')
        self.assertNotIn('401876452',[g['id'] for g in changed['games']])
        self.assertTrue(any(x['reason']=='終了実時刻なし' for x in changed['rejected']))

    def test_name_initial_and_ambiguity(self):
        rows=[{'athlete':{'id':'1','lastName':'Suzuki','fullName':'Zion Suzuki'}},
              {'athlete':{'id':'2','lastName':'Suzuki','fullName':'Yuito Suzuki'}}]
        self.assertEqual(sr.resolve_player(rows,'Zion Suzuki')['athlete']['id'],'1')
        self.assertEqual(sr.resolve_player(rows,'Yuito Suzuki')['athlete']['id'],'2')
        self.assertIsNone(sr.resolve_player(rows,'Shuto Suzuki'))
        self.assertIsNone(sr.resolve_player(rows+[deepcopy(rows[0])],'Zion Suzuki'))
        self.assertEqual(sr.resolve_player([{'athlete':{'id':'3','lastName':'Maeda','fullName':'D. Maeda'}}],'Daizen Maeda')['athlete']['id'],'3')

    def test_score_crosscheck_and_espn_disagreement(self):
        boards,summaries=fixture();data=fixed();g=next(g for g in data['games'] if g['id']=='401876452')
        fd={'FL1':[{'status':'FINISHED','utcDate':g['start_utc'],'homeTeam':{'name':'OGC Nice'},'awayTeam':{'name':'Lille OSC'},'score':{'fullTime':g['score']}}]}
        self.assertEqual(sr.football_check(g,fd),'matched')
        fd['FL1'][0]['score']['fullTime']={'home':0,'away':9}
        changed=sr.build(boards,summaries,'2026-09-21',fd)
        self.assertNotIn(g['id'],[x['id'] for x in changed['games']])
        self.assertTrue(any('football-data' in x['reason'] for x in changed['rejected']))
        self.assertEqual(sr.football_check(g,{}),'unavailable')
        summaries[g['id']]['summary']['header']['competitions'][0]['competitors'][0]['score']='99'
        self.assertNotIn(g['id'],[x['id'] for x in sr.build(boards,summaries,'2026-09-21')['games']])

    def test_rank_and_no_appearance_gate(self):
        base={'name':'選手','goals':0,'assists':0,'status':'starter'}
        rows=[dict(base,name='途中',status='substitute'),dict(base,name='先発'),dict(base,name='補助',assists=3),dict(base,name='得点',goals=1),dict(base,name='出場なし',status='none')]
        self.assertEqual([p['name'] for p in sorted(rows,key=sr.rank_key)],['得点','補助','先発','途中','出場なし'])
        data=fixed();empty=deepcopy(data)
        for p in empty['players']:p.update(status='none',goals=None,assists=None)
        empty['can_make']=False
        self.assertEqual(render.narration(empty)['segments'],[])
        self.assertEqual(sr.title(empty),'')
        text=''.join(s['text'] for s in render.narration(data)['segments'])
        self.assertNotIn('活躍',text);self.assertNotIn('久保建英',text)
        self.assertIn('上田綺世がゴール',sr.title(data))
        self.assertIn('ニース 2-1 リール',sr.title(data))

    def test_missing_stats_are_not_zero(self):
        player={'name_jp':'検査選手','name_en':'Fixture Person','team_jp':'クラブ'}
        rows=[{'athlete':{'id':'7','lastName':'Person','fullName':'Fixture Person'},'starter':True,'subbedIn':False,'stats':[]}]
        row=sr.player_result(player,rows,'home','event')
        self.assertIsNone(row['goals']);self.assertIsNone(row['assists'])
        rows[0].update(starter=False,subbedIn=False)
        rows[0]['stats']=[{'name':'totalGoals','value':1}]
        with self.assertRaises(ValueError):sr.player_result(player,rows,'home','event')

    def test_normalized_material_cannot_change_player_numbers(self):
        for day in ('2026-09-19','2026-09-20','2026-09-21'):sr.validate_data(fixed(day))
        data=fixed();data['players'][0]['goals']=999
        with self.assertRaises(ValueError):sr.validate_data(data)
        data=fixed();bench=next(p for g in data['games'] for p in g['players'] if p['status']=='none');bench['goals']=1
        with self.assertRaisesRegex(ValueError,'出場なし'):sr.validate_data(data)

    def test_native_own_goal_credited_side(self):
        boards,summaries=fixture()
        event=next(e for b in boards.values() for e in b['events'] if e['id']=='401878777')
        c=event['competitions'][0];own=next(x for x in c['details'] if x.get('ownGoal'))
        # Native ESPN team is the benefiting club, athlete.team is the conceding club.
        self.assertNotEqual(own['team']['id'],own['athletesInvolved'][0]['team']['id'])
        athlete=own['athletesInvolved'][0]
        selected={'name_en':athlete['fullName'],'name_jp':'検査用選手','team_jp':'マンチェスター・ユナイテッド','team_en':'Manchester United','league':'PL','match':'manchesterunited'}
        rows=[{'athlete':{'id':athlete['id'],'fullName':athlete['fullName'],'lastName':athlete['fullName'].split()[-1]},'starter':True,'subbedIn':False,'stats':[{'name':'totalGoals','value':0}]}]
        rows += [{'athlete':{'id':str(i),'fullName':f'Test Player{i}'},'starter':True,'subbedIn':False,'stats':[]} for i in range(10)]
        end=sr.utc(event['date'])+timedelta(hours=2)
        other_id=own['team']['id']
        other_rows=[{'athlete':{'id':'other'+str(i),'fullName':f'Other Player{i}'},'starter':True,'subbedIn':False,'stats':[]} for i in range(11)]
        summary={'header':{'competitions':[deepcopy(c)]},'rosters':[{'team':{'id':athlete['team']['id']},'roster':rows},{'team':{'id':other_id},'roster':other_rows}],
                 'keyEvents':[{'type':{'id':'83'},'period':{'number':2},'wallclock':end.isoformat()}]}
        data=sr.build({'PL_fixture':{'events':[event]}},{event['id']:summary},end.astimezone(sr.JST).date().isoformat(),roster=[selected])
        g=next(x for x in data['games'][0]['goals'] if x['own_goal'])
        self.assertEqual(g['side'],'home');self.assertFalse(g['japanese_goal'])
        self.assertEqual(data['players'][0]['goals'],0)

    def test_v4_all_native_screens_safe_badges_and_numbers(self):
        if r3.LOOK!='v4':
            with self.assertRaises(ValueError):render.frame(1,render.narration(fixed())['segments'][0],fixed())
            return
        for day in ('2026-09-19','2026-09-20','2026-09-21'):inspect(fixed(day))
        data=fixed();clubs=render.resolve_clubs(data);seg=render.narration(data)['segments'][0]
        r3.set_program_clock(0);r3.set_caption('',10,30)
        image=render.frame(1.4,seg,data,clubs)
        self.assertTrue(any(e['text']=='1' and e.get('v4_font',0)>=200 for e in image.info['v3_layout']))
        v4=__import__('short_v4_cards');v4.text(image,100,500,'9999',60,r3.GOLD,number=True)
        self.assertTrue(any('numbers_missing_from_material' in e for e in render.validate_frame(image,data,clubs)))
        blank=dict(clubs['リール'],primary=None,secondary=None)
        self.assertEqual(cards.club_colors(blank),cards.NEUTRAL)

    def test_pagination_preserves_all_players_and_goals(self):
        if r3.LOOK!='v4':return
        data=fixed('2026-09-20');base=data['players'][0]
        data['players']=[dict(base,name=f'検査選手{n}') for n in range(21)]
        segments=render.narration(data)['segments'];rows=[s for s in segments if s['kind']=='roster']
        self.assertEqual(sum(s['meta']['count'] for s in rows),21)
        clubs=render.resolve_clubs(data)
        for seg in rows:
            r3.set_caption('',12,30);im=render.frame(1.4,seg,data,clubs)
            self.assertFalse(__import__('v3_rules').check_layout(im)+cards.check_club_badges(im,clubs))
        data=fixed();game=next(g for g in data['games'] if g['id']==data['players'][0]['event_id'])
        game['goals']=[dict(game['goals'][0],minute=str(n+1),side='home') for n in range(9)]
        segments=render.narration(data)['segments'];pages=[s for s in segments if s['kind']=='result']
        self.assertEqual([len(s['meta']['goals']) for s in pages],[4,4,1])
        for s in pages:
            r3.set_caption('',12,30);self.assertFalse(__import__('v3_rules').check_layout(render.frame(1.4,s,data,clubs)))

    def test_audio_manifest_and_strict_40_seconds(self):
        segments=render.narration(fixed())['segments']
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'voice.wav'
            with wave.open(str(p),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\x00\x00'*24000)
            audio=[dict(s,file=str(p),duration=1) for s in segments]
            self.assertLess(sum(render.durations(segments,audio)),40)
            audio[0]['text']='違う原稿'
            with self.assertRaises(ValueError):render.durations(segments,audio)
            audio=[dict(s,file=str(p),duration=11) for s in segments]
            with patch('synthesize_narration.audio_duration',return_value=11):
                with self.assertRaisesRegex(ValueError,'40秒'):render.durations(segments,audio)

    def test_manual_workflow_default_closed_and_upload_metadata(self):
        import yaml
        wf=yaml.safe_load((ROOT/'.github/workflows/soccer_results.yml').read_text(encoding='utf-8'))
        trigger=wf.get('on',wf.get(True))
        self.assertEqual(list(trigger),['workflow_dispatch'])
        self.assertIs(trigger['workflow_dispatch']['inputs']['publish']['default'],False)
        for step in wf['jobs']['build']['steps']:
            if 'Upload to' in step.get('name','') or 'Confirm reservation'==step.get('name'):self.assertIn('inputs.publish',step['if'])
        import upload_youtube as upload
        with tempfile.TemporaryDirectory() as directory:
            material=Path(directory)/'soccer_results.json';material.write_text(json.dumps(fixed(),ensure_ascii=False),encoding='utf-8')
            meta=upload.build_metadata(str(material),'9月21日','soccer_results',sport='soccer')
        self.assertEqual(meta['snippet']['title'],sr.title(fixed()))
        desc=meta['snippet']['description']
        self.assertIn('ESPN',desc);self.assertIn('VOICEVOX:四国めたん',desc);self.assertNotIn('#MLB',desc)
        self.assertIn('soccer_results',upload.DATED_KINDS)


if __name__=='__main__':
    if '--material' in sys.argv:
        os.environ['COLLESPO_SHORT_LOOK']='v4'
        # Renderer modules already loaded; a subprocess gives the process-wide LOOK its correct value.
        if r3.LOOK!='v4':
            raise SystemExit(subprocess.call([sys.executable,__file__,*sys.argv[1:]],env=dict(os.environ,COLLESPO_SHORT_LOOK='v4')))
        path=Path(sys.argv[sys.argv.index('--material')+1]);data=json.loads(path.read_text(encoding='utf-8'));sr.validate_data(data);inspect(data)
        print('ok soccer results: material/layout/club badges/numbers');raise SystemExit(0)
    if '--child' in sys.argv:
        unittest.main(argv=[sys.argv[0]],verbosity=1)
    else:
        bad=0
        for look in ('v3','v4'):
            proc=subprocess.run([sys.executable,'-X','utf8',__file__,'--child'],env=dict(os.environ,COLLESPO_SHORT_LOOK=look),capture_output=True,text=True,encoding='utf-8',errors='replace')
            print(look,proc.stderr.strip()[-3500:]);bad+=bool(proc.returncode)
        print('ok soccer results v3/v4' if not bad else 'NG soccer results v3/v4');raise SystemExit(bool(bad))
