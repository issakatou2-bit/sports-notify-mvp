"""保存原本との対応、欠測/0/GK矛盾、独自式の対象制限とv6実画面。"""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import soccer_stats as stats
import soccer_results as results
import preview_soccer_stats as preview


class Stats(unittest.TestCase):
    def test_saved_summary_extract_and_club_ids(self):
        for case in preview.cases(supplementary=True):
            game=case['data']['games'][0];raw=case['extract']
            results.validate_data(case['data'])
            self.assertEqual(stats.team_stats(raw,game),game['match_stats'])
            shuffled=copy.deepcopy(raw);shuffled['boxscore']['teams'].reverse()
            for t in shuffled['boxscore']['teams']:t['statistics'].reverse()
            self.assertEqual(stats.team_stats(shuffled,game),game['match_stats'])
            for p in game['players']:
                group=next(g for g in raw['rosters'] if str(g['team']['id'])==game[p['side']]['id'])
                row=next(r for r in group['roster'] if str(r['athlete']['id'])==p['athlete_id'])
                self.assertEqual(stats.player_stats(row),{k:p[k] for k in stats.player_stats(row)})
                actual=results.player_result(dict(name_en=p['name_en'],name_jp=p['name'],team_jp=p['club']),group['roster'],p['side'],p['event_id'],raw)
                self.assertEqual(actual,p)
                expected=stats.appearance_minutes({k:v for k,v in p.items() if k not in ('minutes','minutes_source','minutes_approx')},raw)
                self.assertEqual(expected,{k:p[k] for k in expected})
                if p.get('minutes_approx'):self.assertTrue(stats.minutes_label(p).startswith('約'))
        game=preview.cases(supplementary=True)[-1]['data']['games'][0]
        self.assertEqual(game['match_stats']['home'],dict(possession=63.8,shots=20,on_target=7))
        suzuki=game['players'][0]
        self.assertEqual((suzuki['saves'],suzuki['conceded']),(5,2))
        self.assertNotIn('shotsFaced',suzuki)

    def test_team_missing_zero_and_invalid(self):
        case=preview.cases()[0];game=case['data']['games'][0]
        for invalid in (None,'NaN',-1,'Infinity'):
            raw=copy.deepcopy(case['extract'])
            row=next(s for s in raw['boxscore']['teams'][0]['statistics'] if s['name']=='totalShots')
            row.update(value=invalid,displayValue=invalid)
            self.assertIsNone(stats.team_stats(raw,game))
        raw=copy.deepcopy(case['extract'])
        raw['boxscore']['teams'][0]['team']['id']='unrelated'
        self.assertIsNone(stats.team_stats(raw,game))
        self.assertIsNone(stats.team_stats({},game))
        self.assertEqual(stats.personal_line(dict(status='starter',shots=0,on_target=0)),'シュート0本（枠内0本）')
        self.assertEqual(stats.personal_line(dict(status='starter')),'')

    def test_personal_narration_omits_zero_shots_and_empty_segments(self):
        import soccer_results_render as render
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off'):
            for case in preview.cases(supplementary=True):
                data=copy.deepcopy(case['data'])
                game=data['games'][0]
                for p in game['players']:
                    p.update(shots=0,on_target=0,saves=0)
                narr=render.production_narration(data)
                people=[p for p in game['players'] if p['status']!='none']
                lines=[s for s in narr['segments'] if s['kind']=='player-stats']
                self.assertEqual(len(lines),len(people))
                self.assertFalse(any('シュート0本' in s['text'] for s in lines))
                self.assertEqual([s['kind'] for s in narr['segments']][:2],['followup','followup-detail'])
                for p,line in zip(people,lines):
                    self.assertTrue(line['text'].startswith(p['name']+'は'))
                    self.assertEqual(line['meta']['count'],1)
            data=copy.deepcopy(preview.cases()[0]['data'])
            people=data['games'][0]['players']
            people[0].update(position='MF',shots=1,on_target=0)
            for p in people[1:]:p.update(position='MF',shots=0,on_target=0)
            narr=render.production_narration(data)
            lines=[s for s in narr['segments'] if s['kind']=='player-stats']
            self.assertIn('シュート1本、枠内はなし。',lines[0]['text'])
            self.assertTrue(all('シュート' not in s['text'] for s in lines[1:]))
            self.assertEqual(stats.personal_line(people[-1]),'シュート0本（枠内0本）')
        for player,expected in (
            (dict(shots=2,on_target=1),'シュート2本、枠内は1本'),
            (dict(shots=1),'シュート1本'),
            (dict(shots=0,on_target=0),''),
            (dict(position='GK',saves=5,conceded=2),'5セーブ、2失点'),
            (dict(position='GK',saves=0,conceded=2),''),
            (dict(position='GK',conceded=2),''),
            (dict(status='none',shots=1,on_target=1),''),
        ):
            self.assertEqual(stats.personal_narration(player),expected)

    def test_story_order_and_significant_team_differences(self):
        import soccer_results_render as render
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off'):
            for case in preview.cases(supplementary=True):
                data=case['data'];game=data['games'][0]
                segments=render.production_narration(data)['segments']
                order={'followup':0,'followup-detail':1,'team-stats':2,'player-stats':3,'roster':4,'outro':5}
                ranks=[order[s['kind']] for s in segments if s['kind'] in order]
                self.assertEqual(ranks,sorted(ranks))
                spoken=''.join(s['text'] for s in segments if s['kind']=='followup-detail')
                import soccer_result_facts as facts
                for goal in game['goals']:self.assertIn(facts.goal_line(goal,game),spoken)
        game=copy.deepcopy(preview.cases()[0]['data']['games'][0])
        game['match_stats']=dict(home=dict(shots=10,possession=50,on_target=2),away=dict(shots=6,possession=50,on_target=2))
        self.assertEqual(stats.commentary(game),'')
        game['match_stats']['home']['shots']=11
        self.assertIn('シュート',stats.commentary(game))
        game['match_stats']['home']['possession']=57.5
        game['match_stats']['away']['possession']=42.5
        self.assertIn('保持率',stats.commentary(game))
        self.assertEqual(stats.result_narration(dict(name='小杉啓太',status='starter',subbed_out=False,red_cards=0,shots=0)),'小杉啓太はフル出場。')

    def test_attack_formula_thresholds_and_guards(self):
        p=dict(position='FW',status='starter',minutes=30,goals=1,assists=1,shots=3,on_target=2)
        self.assertEqual(stats.attack(p),dict(version='attack-v1',raw=10,level=4,notice=stats.NOTICE))
        self.assertEqual(stats.attack_label(p),'攻撃関与 ★★★★☆')
        for delta in (dict(position='DF'),dict(position='GK'),dict(position=None),dict(minutes=None),
                      dict(minutes=29),dict(status='none'),dict(shots=None),dict(on_target=4),dict(goals=3)):
            self.assertIsNone(stats.attack(dict(p,**delta)),delta)
        for raw,level in ((0,0),(1,1),(2,1),(3,2),(5,3),(8,4),(12,5),(50,5)):
            result=stats.attack(dict(p,goals=0,assists=0,shots=raw,on_target=0))
            self.assertEqual((result['raw'],result['level']),(raw,level))

    def test_appearance_boundaries_and_missing_clocks(self):
        def event(in_id,out_id,minute):
            return dict(type=dict(type='substitution'),clock=dict(displayValue=minute),
                        participants=[dict(athlete=dict(id=in_id)),dict(athlete=dict(id=out_id))])
        p=dict(athlete_id='10',status='starter',subbed_out=True,red_cards=0,
               position='MF',goals=0,assists=0,shots=1,on_target=0)
        def inferred(person,events):
            return dict(person,**stats.appearance_minutes(person,dict(keyEvents=events)))
        for minute,expected in (("29'",29),("30'",30),("45'+4'",45),("90'+6'",90)):
            person=inferred(p,[event('20','10',minute)])
            self.assertEqual(person['minutes'],expected)
            self.assertEqual(stats.attack(person) is not None,expected>=30)
        sub=dict(p,status='substitute',subbed_out=False)
        for minute,expected in (("60'",30),("61'",29),("90'+4'",0)):
            person=inferred(sub,[event('10','20',minute)])
            self.assertEqual(person['minutes'],expected)
            self.assertEqual(stats.attack(person) is not None,expected>=30)
        for person in (p,sub):
            for events in ([],[event('10','10','unknown')]):
                self.assertNotIn('minutes',inferred(person,events))
                self.assertIsNone(stats.attack(inferred(person,events)))
        full=dict(p,subbed_out=False)
        self.assertIsNotNone(stats.attack(full))
        self.assertEqual(stats.minutes_label(full),'')
        self.assertIsNone(stats.attack(dict(full,red_cards=1)))
        suboff=dict(sub,subbed_out=True)
        self.assertEqual(inferred(suboff,[event('10','20',"45'+2'"),event('30','10',"75'")])['minutes'],30)
        direct=dict(p,minutes=12)
        self.assertEqual(stats.appearance_minutes(direct,{}),dict(minutes=12,minutes_source='ESPN minutesPlayed'))
        self.assertIsNone(stats.attack(direct))
        self.assertEqual(stats.minutes_label(direct),'約12分出場')
        for case in preview.cases():
            self.assertTrue(any(stats.attack(p) for p in case['data']['players']))

    def test_materials_and_production_frames(self):
        import soccer_results_render as render
        import soccer_readable as layout
        import review_render_v3 as r3
        import sanity_sources
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off'):
            try:
                for case in preview.cases(supplementary=True):
                    data=case['data'];before=copy.deepcopy(data)
                    clubs=render.resolve_clubs(data);narr=render.production_narration(data)
                    result=narr['segments'][0]['text'];game=data['games'][0]
                    people=[p for p in game['players'] if p['status']!='none'] or game['players']
                    for p in people:self.assertIn(p['name'],result)
                    for side in ('home','away'):self.assertIn(game[side]['name_jp'],result)
                    first='away' if all(p['side']=='away' for p in people) else 'home'
                    second='home' if first=='away' else 'away'
                    self.assertIn(f"{game['score'][first]}対{game['score'][second]}で",result)
                    attached=sanity_sources.collect([narr])
                    self.assertTrue(any(s['games'][0].get('match_stats')==data['games'][0]['match_stats'] for s in attached))
                    self.assertTrue(any(s['players'][0].get('stats_source') for s in attached))
                    for seg in narr['segments']:
                        r3.set_caption(seg['text'],12,60,speaker=seg['speaker'])
                        im=render.frame(3,seg,data,clubs)
                        if im.info.get('soccer_readable'):
                            self.assertFalse(render.validate_frame(im,data,clubs),(seg['kind'],render.validate_frame(im,data,clubs)))
                            text=[e['text'] for e in im.info['v3_layout']]
                            self.assertNotIn('ホーム',text);self.assertNotIn('アウェー',text)
                            self.assertFalse(any('段階' in t for t in text))
                            if im.info.get('compact_player_statistics'):
                                cards=[e for e in im.info['v3_layout'] if e['role']=='card']
                                self.assertLess(cards[-1]['box'][3]-cards[-1]['box'][1],1000)
                                # 上下を詰めても札内の大きな空白は引き続き検出する。
                                broken=im.copy();broken.info=copy.deepcopy(im.info)
                                card=next(e for e in broken.info['v3_layout'] if e['role']=='card')
                                card['box']=list(card['box']);card['box'][3]=1440
                                self.assertTrue(any('empty_card_bottom' in e for e in render.validate_frame(broken,data,clubs)))
                    self.assertEqual(data,before)
                    self.assertLess(sum(layout.minimum_seconds(s,data) for s in narr['segments']),60)
            finally:r3.set_caption('',0,0);r3.set_program_clock(None)

    def test_optional_stats_do_not_change_v4_or_missing_material(self):
        import soccer_results_render as render
        data=preview.cases()[0]['data']
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v4',COLLESPO_SHORT_LOOK='v4'):
            narr=render.production_narration(data)
            self.assertFalse(any(s['kind']=='player-stats' for s in narr['segments']))
            self.assertFalse(any(s['kind']=='team-stats' for s in narr['segments']))
        data=copy.deepcopy(data);data['games'][0].pop('match_stats')
        for p in data['games'][0]['players']:
            for k in ('saves','conceded','shots','on_target'):p.pop(k,None)
        data['players']=copy.deepcopy(data['games'][0]['players'])
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4'):
            self.assertTrue(all('シュート' not in s['text'] for s in render.production_narration(data)['segments'] if s['kind']=='player-stats'))

    def test_frame_minimum_in_length_fitting_and_60_second_stop(self):
        import soccer_results_render as render
        import soccer_result_story as story
        import soccer_readable as layout
        import synthesize_narration as synth
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4'):
            data=preview.cases()[1]['data']
            narr=render.production_narration(data);voices=[]
            for i,seg in enumerate(narr['segments']):
                path=Path(directory)/f'{i}.wav'
                seconds=40 if seg['kind']=='team-stats' else 2 if seg['kind']=='player-stats' else 5
                with wave.open(str(path),'wb') as f:
                    f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*8000*seconds)
                voices.append(dict(seg,file=str(path),duration=seconds))
            with patch.object(synth,'audio_duration',side_effect=lambda p: wave.open(str(p)).getnframes()/8000):
                fitted,audio=story.fit_to_audio(narr,voices)
                times=render.durations(fitted['segments'],audio)
                total=sum(math.ceil(max(t,layout.minimum_seconds(s))*30)/30 for t,s in zip(times,fitted['segments']))
                self.assertLessEqual(total,60)
                self.assertFalse(any(s['kind']=='team-stats' for s in fitted['segments']))
                self.assertTrue(any(s['kind']=='followup-detail' for s in fitted['segments']))
                self.assertEqual(fitted['segments'][0]['text'],narr['segments'][0]['text'])
            # 必須の結果だけで61秒なら、補足の省略で成功したことにしない。
            with patch.object(synth,'audio_duration',return_value=61):
                only=dict(narr,segments=[narr['segments'][0]])
                with self.assertRaisesRegex(ValueError,'60秒'):
                    story.fit_to_audio(only,[dict(voices[0],duration=61)])


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
