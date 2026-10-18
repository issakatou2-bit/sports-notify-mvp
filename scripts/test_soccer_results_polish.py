"""本人が見た10/16 runの固定材料で、話者・成績・補足・尺を検査する。"""
import copy
import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ['COLLESPO_SHORT_LOOK']='v4'
from PIL import Image
import soccer_result_facts as facts
import soccer_result_story as story
import soccer_results as results
import soccer_results_render as render
import host_split
import characters
import solo_host

FIX=Path(__file__).parent/'fixtures/soccer-results/run-38817456251.json'


def fixed():
    return json.loads(FIX.read_text(encoding='utf8'))


class ResultsPolish(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,dict(COLLESPO_SOLO_HOST='metan',COLLESPO_HOST_SPLIT='',
            COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v5',COLLESPO_BUBBLE='slant',COLLESPO_CAPTION_BREAKS='on'))
        self.env.start();self.addCleanup(self.env.stop)
        self.addCleanup(render.r3.set_program_clock,None)

    def test_every_announced_match_has_factual_details_and_no_zero_stats(self):
        data=fixed();results.validate_data(data);narr=story.narration(data)
        ids=[r['event_id'] for r in data['preview_followup']['games']]
        self.assertEqual([s['meta']['event_id'] for s in narr['segments'] if s['kind']=='followup'],ids)
        details=[s for s in narr['segments'] if s['kind']=='followup-detail']
        self.assertEqual([s['meta']['event_id'] for s in details],ids)
        text=''.join(s['text'] for s in narr['segments'])
        self.assertNotRegex(text,r'(?<!\d)0(?:得点|アシスト)')
        self.assertIn('81分に鎌田大地が得点',text)
        self.assertNotIn('第2節',text);self.assertNotIn('連発',text)
        for detail in details:
            game=next(g for g in data['games'] if g['id']==detail['meta']['event_id'])
            shown=''.join(detail['meta']['details'])
            for goal in game['goals']:
                self.assertIn(goal['scorer'],shown);self.assertIn(goal['minute'].split('+')[0],shown)

    def test_player_stats_stay_in_one_caption_even_over_normal_page_limit(self):
        player=dict(name='検査用のとても長い日本人選手の氏名です',status='substitute',minutes=35,goals=1,assists=2)
        unit=facts.player_line(player)
        self.assertGreater(len(unit),render.r3.CAPTION_CHUNK)
        score='試合は3対2。'
        render.r3.set_program_clock(0)
        render.r3.set_caption(score+unit,10,10,caption_units=[score,unit])
        for elapsed in (3,5,9.9):
            self.assertEqual(render.r3.current_sentence(elapsed,score+unit,10),unit)
        for look in ('v4','v5'):
            for style in ('','slant','glass'):
                with self.subTest(look=look,style=style),patch.dict(os.environ,{'COLLESPO_BUBBLE':style}),patch.object(characters,'place_busts'):
                    im=Image.new('RGB',(1080,1920),(20,40,30));render.r3.set_program_clock(5)
                    if look=='v5':__import__('soccer_v5_cards')._presenter(im,5)
                    else:characters.presenter(im,5)
                    self.assertEqual(im.info['duo_caption']['speaker'],'metan')
                    self.assertLessEqual(im.info['duo_caption']['rows'],3)
                    captions=[r['text'] for r in im.info['v3_layout'] if r['role']=='caption']
                    self.assertIn(unit,captions) if style or look=='v4' else None
        player.update(goals=0,assists=0)
        self.assertNotIn('0',facts.player_line(player))

    def test_ui_assignment_passes_ui_portrait_name_color_and_credit_to_drawing(self):
        data=fixed();narr=story.narration(data)
        for look in ('v4','v5'):
            for style in ('','slant','glass'):
                with self.subTest(look=look,style=style),patch.dict(os.environ,dict(COLLESPO_HOST_SPLIT='half',COLLESPO_BUBBLE=style,COLLESPO_SOCCER_LOOK=look)),patch.object(render.r3,'LOOK','v4'):
                    planned=host_split.adapt(narr,'soccer_results',day='2026-10-16')
                    self.assertEqual(planned['host_assignment']['planned_host'],'ui')
                    render.r3.set_program_clock(0);seg=planned['segments'][0]
                    render.r3.set_caption(seg['text'],10,60,caption_units=seg['caption_units'])
                    with patch.object(characters,'place_busts') as portraits:
                        im=render.frame(1.4,seg,data,story.clubs_for(data))
                    self.assertEqual(portraits.call_args.args[1],'ui')
                    self.assertEqual(portraits.call_args.args[5],('ui',))
                    self.assertEqual(im.info['duo_caption']['speaker'],'ui')
                    if style:self.assertEqual(im.info['bubble_style']['name_ground'],list(characters.COLORS['ui']))
                    else:self.assertTrue(any(e['text']=='雨衣' for e in im.info['v3_layout']) if look=='v5' else True)
                    self.assertIn(solo_host.UI_CREDIT,render.program_spec(data)['source'])
                    self.assertNotIn('VOICEVOX:四国めたん',render.program_spec(data)['source'])
                    solo_host.validate_audio([dict(s,voice_host='ui') for s in planned['segments']])
                    with self.assertRaises(ValueError):solo_host.validate_audio(planned['segments'])

    def test_over_budget_removes_last_match_supplement_and_keeps_all_results(self):
        narr=story.narration(fixed());original=copy.deepcopy(narr)
        with tempfile.TemporaryDirectory() as folder:
            voices=[];seconds={}
            for i,seg in enumerate(narr['segments']):
                path=Path(folder)/f'{i}.wav';path.write_bytes(b'fixture')
                length=8 if seg['kind']=='followup-detail' else 6 if seg['kind']=='followup' else 3
                seconds[str(path)]=length;voices.append(dict(seg,file=str(path),duration=length))
            with patch('synthesize_narration.audio_duration',side_effect=lambda p:seconds[str(p)]):
                shorter,audio=story.fit_to_audio(narr,voices)
                self.assertLessEqual(sum(render.durations(shorter['segments'],audio)),60)
            self.assertEqual(narr,original)
            self.assertEqual([s for s in shorter['segments'] if s['kind']=='followup'],[s for s in narr['segments'] if s['kind']=='followup'])
            self.assertEqual(shorter['results_length_adjustment'][0]['event_id'],narr['segments'][-4]['meta']['event_id'])
            self.assertEqual([s['text'] for s in shorter['segments']],[s['text'] for s in audio])

    def test_present_and_missing_competition_and_minutes(self):
        game=fixed()['games'][0]
        self.assertEqual(facts.competition(game),'ヨーロッパリーグ')
        self.assertEqual(facts.competition(dict(game,stage='LEAGUE_PHASE',matchday=2)),'ヨーロッパリーグ リーグフェーズ 第2節')
        p=game['players'][0]
        self.assertNotIn('分出場',facts.player_line(p))
        self.assertIn('35分出場',facts.player_line(dict(p,minutes=35)))
        self.assertNotIn('0アシスト',facts.player_line(p))
        from test_soccer_results import fixture
        boards,summaries=fixture()
        event=next(e for b in boards.values() for e in b['events'] if e['id']=='401876452')
        event['week']={'number':2};event['competitions'][0]['type']={'text':'League Phase'}
        built=results.build(boards,summaries,'2026-09-20')
        enriched=next(g for g in built['games'] if g['id']==event['id'])
        self.assertIn('リーグフェーズ 第2節',facts.competition(enriched))
        self.assertIn('/fra.1/scoreboard',enriched['matchday_source'])
        raw=dict(athlete={'id':'7','fullName':'Fixture Player','lastName':'Player'},starter=True,subbedIn=False,
                 stats=[dict(name='minutesPlayed',value=67)])
        person=results.player_result(dict(name_jp='検査選手',name_en='Fixture Player',team_jp='クラブ'),[raw],'home','fixture')
        self.assertEqual(person['minutes'],67)

    def test_lost_ui_portrait_regenerates_the_whole_episode_as_metan(self):
        import ui_voice_queue as queue
        import synthesize_narration as sn
        narr=story.narration(fixed())
        assignment=host_split.plan('soccer_results','2026-10-16')
        narr.update(host_assignment=assignment,voice_resolution=dict(host='ui',portrait_dir='missing'))
        build=render.ROOT/'build';build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as folder,patch.dict(os.environ,{'COLLESPO_HOST_SPLIT':'half'}):
            folder=Path(folder);source=folder/'narration.json';audio=folder/'audio';audio.mkdir()
            source.write_text(json.dumps(narr),encoding='utf8')
            manifest=dict(narr,narration_path=str(source),segments=[dict(s,voice_host='ui') for s in narr['segments']])
            (audio/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
            def synth(text,speaker,path):
                Path(path).write_bytes(b'test audio');return True
            with patch.object(queue,'ensure_portrait',side_effect=queue.QueueError('missing')),patch.object(sn,'engine_available',return_value=True),patch.object(sn,'synth_one',side_effect=synth) as generated,patch.object(sn,'audio_duration',return_value=1):
                queue.configure(argparse.Namespace(audio_dir=audio,out=folder/'video'))
            saved=json.loads((audio/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(generated.call_count,len(narr['segments']))
            self.assertEqual(saved['voice_resolution']['host'],'metan')
            self.assertTrue(all(s.get('voice_host','metan')=='metan' for s in saved['segments']))
            solo_host.validate_audio(saved['segments'])
            self.assertEqual(solo_host.presentation('metan',('metan',)),('metan',('metan',)))
            self.assertIn('VOICEVOX:四国めたん',render.program_spec(fixed())['source'])
            self.assertEqual(host_split.use_audio(narr,audio)['voice_resolution']['host'],'metan')

    def test_saved_material_all_frames_fit_in_v4_and_v5(self):
        data=fixed();narr=story.narration(data)
        for look in ('v4','v5'):
            with patch.dict(os.environ,{'COLLESPO_SOCCER_LOOK':look}),patch.object(render.r3,'LOOK','v4'):
                clubs=story.clubs_for(data)
                for seg in narr['segments']:
                    for time in ((3,) if seg['kind']=='outro' else (0,1.4)):
                        render.r3.set_program_clock(0)
                        render.r3.set_caption(seg['text'],15,60,caption_units=seg.get('caption_units'),hide_caption=seg['kind']=='outro')
                        render.r3.set_program_clock(time)
                        im=render.frame(time,seg,data,clubs)
                        self.assertFalse(render.validate_frame(im,data,clubs),(look,seg['kind']))


if __name__=='__main__':unittest.main(argv=[__file__])
