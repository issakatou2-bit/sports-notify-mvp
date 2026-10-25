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
        for case in preview.cases():
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
                self.assertNotIn('minutes',p)
                self.assertIsNone(stats.attack(p))
        game=preview.cases()[0]['data']['games'][0]
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

    def test_attack_formula_thresholds_and_guards(self):
        p=dict(position='FW',status='starter',minutes=30,goals=1,assists=1,shots=3,on_target=2)
        self.assertEqual(stats.attack(p),dict(version='attack-v1',raw=10,level=4,notice=stats.NOTICE))
        self.assertEqual(stats.attack_label(p),'攻撃関与 ★★★★☆')
        self.assertEqual(stats.attack_label(p,'stages'),'攻撃関与 段階4')
        for delta in (dict(position='DF'),dict(position='GK'),dict(position=None),dict(minutes=None),
                      dict(minutes=29),dict(status='none'),dict(shots=None),dict(on_target=4),dict(goals=3)):
            self.assertIsNone(stats.attack(dict(p,**delta)),delta)
        for raw,level in ((0,0),(1,1),(2,1),(3,2),(5,3),(8,4),(12,5),(50,5)):
            result=stats.attack(dict(p,goals=0,assists=0,shots=raw,on_target=0))
            self.assertEqual((result['raw'],result['level']),(raw,level))

    def test_materials_and_production_frames(self):
        import soccer_results_render as render
        import soccer_readable as layout
        import review_render_v3 as r3
        import sanity_sources
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off'):
            try:
                for case in preview.cases():
                    data=case['data'];before=copy.deepcopy(data)
                    clubs=render.resolve_clubs(data);narr=render.production_narration(data)
                    self.assertIn(stats.commentary(data['games'][0]),narr['segments'][0]['text'])
                    attached=sanity_sources.collect([narr])
                    self.assertTrue(any(s['games'][0].get('match_stats')==data['games'][0]['match_stats'] for s in attached))
                    self.assertTrue(any(s['players'][0].get('stats_source') for s in attached))
                    for seg in narr['segments']:
                        r3.set_caption(seg['text'],12,60,speaker=seg['speaker'])
                        im=render.frame(3,seg,data,clubs)
                        if im.info.get('soccer_readable'):
                            self.assertFalse(render.validate_frame(im,data,clubs),(seg['kind'],render.validate_frame(im,data,clubs)))
                    self.assertEqual(data,before)
                    self.assertLess(sum(layout.minimum_seconds(s,data) for s in narr['segments']),60)
            finally:r3.set_caption('',0,0);r3.set_program_clock(None)

    def test_optional_stats_do_not_change_v4_or_missing_material(self):
        import soccer_results_render as render
        data=preview.cases()[0]['data']
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v4',COLLESPO_SHORT_LOOK='v4'):
            narr=render.production_narration(data)
            self.assertFalse(any(s['kind']=='player-stats' for s in narr['segments']))
            self.assertNotIn(stats.commentary(data['games'][0]),narr['segments'][0]['text'])
        data=copy.deepcopy(data);data['games'][0].pop('match_stats')
        for p in data['games'][0]['players']:
            for k in ('saves','conceded','shots','on_target'):p.pop(k,None)
        data['players']=copy.deepcopy(data['games'][0]['players'])
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4'):
            self.assertFalse(any(s['kind']=='player-stats' for s in render.production_narration(data)['segments']))

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
                seconds=20 if seg['kind'] in ('followup-detail','followup') else 2 if seg['kind']=='player-stats' else 5
                with wave.open(str(path),'wb') as f:
                    f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*8000*seconds)
                voices.append(dict(seg,file=str(path),duration=seconds))
            with patch.object(synth,'audio_duration',side_effect=lambda p: wave.open(str(p)).getnframes()/8000):
                fitted,audio=story.fit_to_audio(narr,voices)
                times=render.durations(fitted['segments'],audio)
                total=sum(math.ceil(max(t,layout.minimum_seconds(s))*30)/30 for t,s in zip(times,fitted['segments']))
                self.assertLessEqual(total,60)
                self.assertFalse(any(s['kind']=='followup-detail' for s in fitted['segments']))
                self.assertIn(stats.commentary(data['games'][0]),fitted['segments'][0]['text'])
            # 必須の結果だけで61秒なら、補足の省略で成功したことにしない。
            with patch.object(synth,'audio_duration',return_value=61):
                only=dict(narr,segments=[narr['segments'][0]])
                with self.assertRaisesRegex(ValueError,'60秒'):
                    story.fit_to_audio(only,[dict(voices[0],duration=61)])


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
