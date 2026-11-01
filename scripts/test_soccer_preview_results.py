import copy
import json
import os
from pathlib import Path
import sys
import unittest
import tempfile
import wave
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['COLLESPO_SOCCER_LOOK']='v5'
os.environ['COLLESPO_SHORT_LOOK']='v4'
import soccer_results as results
import soccer_results_render as render
import soccer_result_followup as followup
import soccer_result_story as story
import soccer_preview_history as history
import name_reading_guard as readings


def fixed():
    base=Path(__file__).resolve().parent/'fixtures/soccer-results'
    boards=json.loads((base/'scoreboards.json').read_text(encoding='utf8'));summaries=json.loads((base/'summaries.json').read_text(encoding='utf8'))
    return boards,summaries,results.build(boards,summaries,'2026-09-20')


def announced(data,expect=True):
    g=next(g for g in data['games'] if g['id']=='401876452');p=next(p for p in g['players'] if p['name']=='上田綺世')
    expected=dict(name=p['name'],name_en='Ayase Ueda',goals=3,assists=0,source='fixture') if expect else None
    row=dict(game_id='forecast-1',home=g['home']['name_en'],away=g['away']['name_en'],start_utc=g['start_utc'],league=g['league_jp'],competition_code=g['league'],
             reasons=[dict(kind='rank',text='順位差2の直接対決')],expectation=expected)
    return dict(day=data['date_jst'],video_id='fixture-preview-only',games=[row])


class Tests(unittest.TestCase):
    def test_el_preview_without_japanese_players_uses_competition_registry(self):
        boards,summaries,data=fixed();preview=announced(data,expect=False)
        moved={key.replace('FL1_', 'EL_'):value for key,value in boards.items()}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/soccer_competitions.json').write_text(json.dumps({'competitions':[{'code':'EL','name':'ヨーロッパリーグ'}]}),encoding='utf8')
            with patch.object(results,'ROOT',root):
                built=results.build(moved,summaries,'2026-09-20',roster=[],preview=preview)
        results.validate_data(built)
        self.assertTrue(built['can_make']);self.assertEqual(built['players'],[])
        self.assertEqual(built['games'][0]['league'],'EL')
        from test_soccer_results import inspect
        inspect(built)

    def test_cl_results_are_not_dropped_by_five_league_filter(self):
        boards,summaries,data=fixed();preview=announced(data)
        moved={key.replace('FL1_', 'CL_'):value for key,value in boards.items()}
        built=results.build(moved,summaries,'2026-09-20',preview=preview)
        results.validate_data(built)
        self.assertEqual(next(g for g in built['games'] if g['id']=='401876452')['league'],'CL')
        self.assertTrue(built['preview_followup']['games'])

    def test_v5_cli_preserves_all_followup_games_before_player_section(self):
        _,_,data=fixed();data=followup.attach(data,announced(data))
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'data.json';source.write_text(json.dumps(data),encoding='utf8')
            output=Path(folder)/'narration.json'
            with patch.object(sys,'argv',['render','--data',str(source),'--narration-out',str(output)]):
                render.main()
            narr=json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(narr,story.narration(data))
        from test_soccer_results import inspect
        inspect(data)

    def test_measured_budget_keeps_results_and_drops_last_supplement(self):
        kinds=['followup','roster','followup-change','followup-next','outro']
        narr=dict(segments=[dict(kind=k,text='fixture',speaker=2,meta={}) for k in kinds])
        with tempfile.TemporaryDirectory() as folder:
            audio=[]
            for i,(seg,seconds) in enumerate(zip(narr['segments'],[30,3,15,15,3])):
                path=Path(folder)/f'{i}.wav'
                with wave.open(str(path),'wb') as stream:
                    stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*(8000*seconds))
                audio.append(dict(seg,file=str(path),duration=seconds))
            shorter,voices=story.fit_to_audio(narr,audio)
            self.assertEqual([s['kind'] for s in shorter['segments']],['followup','roster','followup-change','outro'])
            self.assertLessEqual(sum(render.durations(shorter['segments'],voices)),60)
            self.assertEqual(shorter['segments'][0],narr['segments'][0])
    def test_no_preview_enriches_each_material_game(self):
        _,_,data=fixed()
        self.assertEqual(followup.attach(data,None),data)
        self.assertEqual([s['meta']['event_id'] for s in story.narration(data)['segments'] if s['kind']=='followup'],[g['id'] for g in data['games']])

    def test_preview_result_first_expected_numbers_and_same_fixture_bind(self):
        boards,summaries,data=fixed();preview=announced(data)
        built=results.build(boards,summaries,'2026-09-20',preview=preview)
        results.validate_data(built);narr=story.narration(built)
        self.assertEqual(narr['segments'][0]['kind'],'followup')
        self.assertIn('期待選手の上田綺世',narr['segments'][0]['text'])
        self.assertIn('1得点',narr['segments'][0]['text'])
        self.assertEqual(built['games'][0]['id'],'401876452')
        bad=copy.deepcopy(preview);bad['games'][0]['start_utc']='2026-09-22T10:00:00Z'
        self.assertNotIn('preview_followup',followup.attach(data,bad))

    def test_expected_did_not_play_not_zero_goals_in_speech(self):
        _,_,data=fixed();preview=announced(data);g=next(g for g in data['games'] if g['id']=='401876452')
        p=next(p for p in g['players'] if p['name']=='上田綺世')
        p.update(status='none',goals=None,assists=None)
        g['goals_complete']=False;g['goals']=[]
        data['players']=sorted([p for g in data['games'] for p in g['players']],key=results.rank_key)
        changed=followup.attach(data,preview);results.validate_data(changed)
        text=story.narration(changed)['segments'][0]['text']
        self.assertIn('出場なし',text);self.assertNotIn('0得点',text)

    def test_unknown_expected_result_is_omitted_and_other_results_remain(self):
        _,_,data=fixed();preview=announced(data);preview['games'][0]['expectation']['name']='ハーランド'
        changed=followup.attach(data,preview)
        self.assertIsNone(changed['preview_followup']['games'][0]['answer'])
        self.assertNotIn('ハーランド',story.narration(changed)['segments'][0]['text'])
        self.assertTrue(changed['can_make'])

    def test_rank_then_next_only_with_same_scope_and_source(self):
        _,_,data=fixed();preview=announced(data)
        g=next(g for g in data['games'] if g['id']=='401876452');club=(followup.clubs.lookup(g['away']['name_en']) or {})['id']
        common=dict(competition='FL1',season=2026,source='fixture-table')
        before={club:dict(common,rank=5,as_of='2026-09-20T10:00:00Z')};after={club:dict(common,rank=3,as_of='2026-09-21T01:00:00Z')}
        next_game=dict(home=g['away']['name_en'],away=g['home']['name_en'],start_utc='2026-09-28T19:00:00Z',source='fixture-future')
        changed=followup.attach(data,preview,standings_before=before,standings_after=after,next_games=[next_game]);results.validate_data(changed)
        from test_soccer_results import inspect
        inspect(changed)
        kinds=[s['kind'] for s in story.narration(changed)['segments']]
        self.assertLess(kinds.index('roster'),kinds.index('followup-change'));self.assertLess(kinds.index('followup-change'),kinds.index('followup-next'))
        after[club]['season']=2025
        cold=followup.attach(data,preview,standings_before=before,standings_after=after)
        self.assertFalse(cold['preview_followup']['games'][0]['rank_changes'])

    def test_snapshot_requires_uploaded_record_and_actual_narration(self):
        _,_,data=fixed();g=data['games'][0]
        source=dict(generated_at='2026-09-20T10:00:00Z',games=[dict(game_id='fixture-1',league='リーグ・アン',home_team_name=g['home']['name_en'],away_team_name=g['away']['name_en'],start_time_utc=g['start_utc'],is_notable=True)],preview_selection=dict(selected_ids=['fixture-1']))
        narr=dict(segments=[dict(kind='preview',text='試験材料の予告。',meta=dict(game_id='fixture-1',interest=dict(reasons=[],player=None)))])
        with self.assertRaises(ValueError):history.snapshot(source,narr,{})
        published={'daily_soccer':{'2026-09-20':dict(video_id='fixture',preview_binding=history.binding(source,narr))}}
        record=history.snapshot(source,narr,published)
        self.assertEqual(record['games'][0]['game_id'],'fixture-1')
        narr['segments'][0]['meta']['game_id']='wrong'
        with self.assertRaises(ValueError):history.snapshot(source,narr,published)

    def test_frame_numbers_readings_and_fact_changes_rejected(self):
        _,_,data=fixed();changed=followup.attach(data,announced(data));narr=story.narration(changed);readings.validate_dialogue(narr)
        clubs=story.clubs_for(changed)
        for seg in narr['segments']:
            render.r3.set_caption(seg['text'],20,100,speaker=2,hide_caption=seg['kind']=='outro')
            im=render.frame(1.4,seg,changed,clubs)
            self.assertFalse(render.validate_frame(im,changed,clubs))
        bad=copy.deepcopy(changed);bad['preview_followup']['games'][0]['answer']['goals']=99
        with self.assertRaises(ValueError):results.validate_data(bad)

    def test_team_result_can_exist_without_japanese_appearance(self):
        _,_,data=fixed();preview=announced(data,expect=False)
        for g in data['games']:g['players']=[]
        data['players']=[];data['can_make']=False
        for g in data['games']:
            for goal in g['goals']:goal['japanese_goal']=False;goal['japanese_assists']=[]
        changed=followup.attach(data,preview);results.validate_data(changed)
        self.assertTrue(changed['can_make']);self.assertTrue(story.narration(changed)['segments'])
        self.assertFalse(any(s['kind']=='roster' for s in story.narration(changed)['segments']))
if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
