"""混雑した朝の保存材料と段階短縮。音声の代用品は文字数見積もりと明記する。"""
import copy
import json
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
import soccer_result_story as story
import soccer_results_render as render
import soccer_readable as layout
import synthesize_narration as synth


class RequiredFit(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_HOST_SPLIT='off')
        self.env.start();self.addCleanup(self.env.stop)
        self.data=json.loads((ROOT/'scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf8'))

    def narration(self):
        with patch('soccer_publications.load',return_value={}):return story.narration(self.data)

    def test_run_40249272204_estimate_passes_duration_gate(self):
        original=self.narration();unchanged=copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as folder:
            counter=iter(range(1000))
            def voice(seg,previous=None,stage=0):
                # 実音声ではない。6文字/秒の見積もりをWAVにし、尺検査を通す。
                path=Path(folder)/f'{next(counter)}.wav'
                seconds=max(.1,len(seg['text'])/6)
                with wave.open(str(path),'wb') as f:
                    f.setparams((1,2,8000,0,'NONE','not compressed'))
                    f.writeframes(b'\0\0'*round(8000*seconds))
                return dict(seg,file=str(path),duration=seconds)
            def measured(path):
                with wave.open(str(path)) as f:return f.getnframes()/f.getframerate()
            audio=[voice(s) for s in original['segments']]
            with patch.object(synth,'audio_duration',side_effect=measured):
                with self.assertRaisesRegex(ValueError,'60秒'):story.fit_to_audio(original,audio)
                fitted,voices=story.fit_to_audio(original,audio,data=self.data,resynthesize=voice)
                times=render.durations(fitted['segments'],voices)
            total=sum(math.ceil(max(t,layout.minimum_seconds(s,self.data))*30)/30 for t,s in zip(times,fitted['segments']))
            self.assertLessEqual(total,60)
            self.assertEqual([1,2,3],[r['stage'] for r in fitted['results_length_adjustment'] if 'stage' in r])
            self.assertEqual(9,sum(s['kind']=='followup' for s in fitted['segments']))
            self.assertTrue(any('水多海斗は1アシスト' in s['text'] for s in fitted['segments']))
            self.assertFalse(any(s['kind']=='roster' for s in fitted['segments']))
            for seg in fitted['segments']:
                if seg['kind']=='followup':
                    game=next(g for g in self.data['games'] if g['id']==seg['meta']['event_id'])
                    self.assertTrue(all(p['name'] in seg['text'] for p in game['players'] if p['status']!='none'))
            self.assertEqual(original,unchanged)
            print(f'run40249272204: 6文字/秒の見積もり＋全画面最低尺＋30fps丸め={total:.3f}秒')

    def test_small_day_script_and_audio_are_identical_without_resynthesis(self):
        import preview_soccer_stats
        for case in preview_soccer_stats.cases(supplementary=True):
            data=case['data']
            with patch('soccer_publications.load',return_value={}):original=story.narration(data)
            audio=[dict(s,file='existing.wav',duration=4) for s in original['segments']]
            with patch.object(render,'durations',return_value=[4]*len(audio)),patch.object(story,'rebuild_voice') as rebuild:
                fitted,voices=story.fit_to_audio(original,audio,data=data)
            self.assertEqual(original,fitted);self.assertEqual(audio,voices);rebuild.assert_not_called()

    def test_involved_japanese_match_first_and_names_survive_every_stage(self):
        segments=self.narration()['segments']
        first=next(s for s in segments if s['kind']=='followup')
        game=next(g for g in self.data['games'] if g['id']==first['meta']['event_id'])
        self.assertTrue(any(p.get('goals') or p.get('assists') for p in game['players']))
        for stage in (0,1,2,3):
            if stage:segments=story.shorten_required(segments,self.data,stage)
            for seg in segments:
                if seg['kind']!='followup':continue
                game=next(g for g in self.data['games'] if g['id']==seg['meta']['event_id'])
                people=[p for p in game['players'] if p['status']!='none'] or game['players']
                self.assertTrue(all(p['name'] in seg['text'] for p in people))

    def test_winning_goal_fallback_has_club_and_short_panel(self):
        import soccer_result_facts as facts
        segments=self.narration()['segments']
        for stage in (1,2,3):segments=story.shorten_required(segments,self.data,stage)
        clubs=render.resolve_clubs(self.data)
        for seg in segments:
            if seg['kind']!='followup':continue
            game=next(g for g in self.data['games'] if g['id']==seg['meta']['event_id'])
            for goal in seg['meta']['goals']:
                if not goal['japanese_goal'] and not facts.named_scorer(goal):
                    self.assertIn(game[goal['side']]['name_jp'],facts.compact_goal_line(goal,game))
            frame=render.frame(1.4,seg,self.data,clubs)
            cards=[e['box'] for e in frame.info['v3_layout'] if e['role']=='card']
            self.assertLessEqual(max(b[3] for b in cards),1300)
            if not seg['meta']['goals']:self.assertEqual(1,len(cards))

    def test_draw_result_uses_natural_japanese(self):
        import soccer_result_facts as facts
        game=next(g for g in self.data['games'] if g['score']==dict(home=1,away=1))
        self.assertIn('と1対1で引き分けました。',facts.result_line(game))

    def test_original_roster_names_are_on_fixed_page(self):
        clubs=render.resolve_clubs(self.data)
        for seg in self.narration()['segments']:
            if seg['kind']!='roster':continue
            for t in (0,4,20):
                frame=render.frame(t,seg,self.data,clubs)
                self.assertEqual(seg['meta']['player_names'],[p['name'] for p in frame.info['readable_rows']])

    def test_stage_one_keeps_goals_assists_without_shots_or_minutes(self):
        segments=story.shorten_required(self.narration()['segments'],self.data,1)
        texts=[s['text'] for s in segments if s['kind']=='player-stats']
        self.assertTrue(any('1アシスト' in t for t in texts))
        self.assertTrue(all('シュート' not in t and '分出場' not in t and 'フル出場' not in t for t in texts))

    def test_stage_two_all_ten_players_remain_on_roster_pages(self):
        segments=story.shorten_required(story.shorten_required(self.narration()['segments'],self.data,1),self.data,2)
        rosters=[s for s in segments if s['kind']=='roster']
        clubs=render.resolve_clubs(self.data);spec=render.program_spec(self.data);names=[]
        for roster in rosters:
            for t in (1,5,9):
                frame=layout.results_frame(t,roster,self.data,clubs,spec)
                visible=[p['name'] for p in frame.info['readable_rows']]
                self.assertEqual(roster['meta']['player_names'],visible)
                for p in self.data['players']:
                    if p['name'] in roster['text']:self.assertIn(p['name'],visible)
                spoken=[name for name in visible if name in roster['text']]
                self.assertEqual(spoken,sorted(spoken,key=roster['text'].index))
            names.extend(visible)
        self.assertEqual({p['name'] for p in self.data['players'] if p['status']!='none'},set(names))

    def test_stage_three_retains_only_japanese_and_winning_goals(self):
        segments=self.narration()['segments']
        for stage in (1,2,3):segments=story.shorten_required(segments,self.data,stage)
        self.assertFalse(any(s['kind']=='followup-detail' for s in segments))
        goals=[(s['meta']['event_id'],g['minute']) for s in segments if s['kind']=='followup' for g in s['meta']['goals']]
        self.assertEqual(6,len(goals))
        self.assertIn(('401876426','55'),goals)
        game=copy.deepcopy(self.data['games'][0]);game['goals'][1]['japanese_goal']=True
        game['score']={'home':0,'away':2}
        data=dict(self.data,games=[game])
        source=[dict(kind='followup',text='結果。',speaker=2,meta=dict(event_id=game['id'])),
                dict(kind='followup-detail',text='経過。',speaker=2,meta=dict(event_id=game['id']))]
        kept=story.shorten_required(source,data,3)[0]
        self.assertEqual(2,len(kept['meta']['goals']))

    def test_all_shortened_result_cards_pass_layout_and_material_checks(self):
        segments=self.narration()['segments']
        for stage in (1,2,3):segments=story.shorten_required(segments,self.data,stage)
        clubs=render.resolve_clubs(self.data)
        for seg in segments:
            if seg['kind']!='followup':continue
            frame=render.frame(1.4,seg,self.data,clubs)
            self.assertEqual([],render.validate_frame(frame,self.data,clubs))

    def test_oversize_score_still_stops_after_all_stages(self):
        narr=dict(segments=[dict(kind='followup',text='結果。',speaker=2,meta=dict(event_id=self.data['games'][0]['id']))])
        voice=dict(narr['segments'][0],file='existing.wav',duration=61)
        def rebuild(s,p,stage):return dict(s,file='existing.wav',duration=61)
        with patch.object(render,'durations',side_effect=ValueError('60秒を超えます')):
            with self.assertRaisesRegex(ValueError,'段階短縮後'):story.fit_to_audio(narr,[voice],data=self.data,resynthesize=rebuild)

    def test_unrelated_audio_error_is_never_hidden(self):
        with patch.object(render,'durations',side_effect=ValueError('音声の文が違う')):
            with self.assertRaisesRegex(ValueError,'音声の文'):story.fit_to_audio(self.narration(),[],data=self.data)

    def test_stops_at_first_sufficient_stage(self):
        original=self.narration()
        players=[s for s in original['segments'] if s['kind']=='player-stats'][:3]
        scores=[s for s in original['segments'] if s['kind']=='followup'][:2]
        roster=[s for s in original['segments'] if s['kind']=='roster'][:1]
        original['segments']=scores+players+roster
        audio=[dict(s,file='existing.wav',duration=12) for s in original['segments']]
        def times(segments,voices):
            value=[v['duration'] for v in voices]
            if sum(value)>60:raise ValueError('60秒を超えます')
            return value
        for expected in (1,2):
            def rebuild(seg,previous,stage):return dict(seg,file='short.wav',duration=2 if stage==expected else 12)
            with patch.object(render,'durations',side_effect=times):
                fitted,_=story.fit_to_audio(original,audio,data=self.data,resynthesize=rebuild)
            self.assertEqual(list(range(1,expected+1)),[r['stage'] for r in fitted['results_length_adjustment'] if 'stage' in r])

    def test_ui_changes_use_one_existing_queue_order_per_stage(self):
        narr=self.narration();audio=[dict(s,file='original.wav',duration=8,voice_host='ui') for s in narr['segments']]
        def durations(segments,voices):
            if len(segments)>15:raise ValueError('60秒を超えます')
            return [4]*len(segments)
        def queued(document,changed,directory,stage):
            self.assertEqual(3,stage)
            return [dict(s,file='queued.wav',duration=4,voice_host='ui') for s in changed]
        with patch.object(render,'durations',side_effect=durations),patch.object(story,'rebuild_ui',side_effect=queued) as queue,patch.object(story,'rebuild_voice') as local:
            fitted,voices=story.fit_to_audio(narr,audio,data=self.data)
        queue.assert_called_once();local.assert_not_called()
        self.assertTrue(all(v['voice_host']=='ui' for v in voices))
        self.assertEqual(len(fitted['segments']),len(voices))


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
