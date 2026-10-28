"""短い/薄い回・重複・短縮後・古い合格記録を公開へ流さない。"""
import copy
import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import short_content as s
import short_context


def asset(count=3):
    items = [[f'事実{i}', f'値{i}'] for i in range(count)]
    data = dict(key='saved', source='https://statsapi.mlb.com/api/v1/example', items=items)
    doc = dict(segments=[dict(kind='list', text='事実を読む', meta=dict(start=0, count=count))])
    return doc, data


@contextmanager
def passed_video():
    """公開経路の単体試験用。合格判定を偽装せず、通常の記録を作る。"""
    with tempfile.TemporaryDirectory() as folder:
        doc, data = asset()
        name = 'collespo_soccer_results.mp4'
        s.require(doc, [30], folder, data, video_name=name)
        video = Path(folder)/name
        video.write_bytes(b'fixture media; probe is mocked by caller')
        at = video.with_name(name+'.short_content.json').stat().st_mtime_ns+1
        os.utime(video, ns=(at, at))
        # 尺取得は呼出し側の試験用応答を使い、実FFmpeg探索は行わない。
        with patch('shutil.which', return_value='fixture-ffmpeg'):
            yield Path(folder)


class ShortContent(unittest.TestCase):
    def test_common_content_helpers_need_no_optional_packages(self):
        import run_checks
        for filename in ('short_content.py', 'short_context.py'):
            self.assertEqual(run_checks._third_party(filename), set(), filename)

    def test_system_probe_does_not_load_optional_bundle(self):
        load = Mock()
        with passed_video() as folder, patch.object(s, 'importlib', SimpleNamespace(import_module=load)), \
                patch('subprocess.run', return_value=SimpleNamespace(stderr='Duration: 00:00:30.00')):
            self.assertEqual(s.validate_upload(folder/'collespo_soccer_results.mp4')['status'], 'passed')
            load.assert_not_called()

    def test_optional_probe_bundle_is_loaded_only_without_system_probe(self):
        load = Mock(return_value=SimpleNamespace(get_ffmpeg_exe=lambda:'bundled-ffmpeg'))
        with passed_video() as folder, patch('shutil.which', return_value=None), \
                patch.object(s, 'importlib', SimpleNamespace(import_module=load)), \
                patch('subprocess.run', return_value=SimpleNamespace(stderr='Duration: 00:00:30.00')) as probe:
            self.assertEqual(s.validate_upload(folder/'collespo_soccer_results.mp4')['status'], 'passed')
            load.assert_called_once_with('imageio_ffmpeg')
            self.assertEqual(probe.call_args.args[0][0], 'bundled-ffmpeg')

    def test_legacy_slots_keep_original_narration(self):
        plan = dict(mode='race', narration=dict(segments=[dict(kind='standings', text='元の文',
            meta=dict(rows=[dict(team='Arsenal', position=1, points=10),
                            dict(team='Liverpool', position=2, points=9)]))]))
        original = copy.deepcopy(plan)
        for look in ('v3', 'v4'):
            with patch.dict(os.environ, COLLESPO_SOCCER_LOOK=look, COLLESPO_SHORT_LOOK='v4'):
                self.assertIs(short_context.slots(plan, modern=__import__('soccer_look').v5()), plan)
                self.assertEqual(plan, original)
        for look in ('v5', 'v6'):
            with patch.dict(os.environ, COLLESPO_SOCCER_LOOK=look, COLLESPO_SHORT_LOOK='v4'):
                updated = short_context.slots(copy.deepcopy(original), modern=__import__('soccer_look').v5())
                self.assertIn('勝点10', updated['narration']['segments'][0]['text'])

    def test_28_seconds_is_the_lower_boundary(self):
        doc, data = asset()
        self.assertEqual(s.assess(doc, [28], data)['status'], 'passed')
        self.assertEqual(s.assess(doc, [27.999], data)['status'], 'held')

    def test_35_seconds_with_one_fact_is_held(self):
        doc, data = asset(1)
        self.assertEqual(s.assess(doc, [35], data)['information_count'], 1)
        self.assertEqual(s.assess(doc, [35], data)['status'], 'held')

    def test_repeated_card_is_not_three_facts(self):
        doc, data = asset(1)
        doc['segments'] *= 3
        self.assertEqual(s.assess(doc, [10,10,10], data)['information_count'], 1)

    def test_unused_material_is_not_information(self):
        doc, data = asset(10)
        doc['segments'][0]['meta']['count'] = 1
        self.assertEqual(len(s.information(doc, data)), 1)

    def test_removed_scenes_do_not_count(self):
        doc, data = asset(3)
        doc['segments'] = [dict(kind='list', text='事実', meta=dict(start=i, count=1)) for i in range(3)]
        self.assertEqual(s.assess(doc, [10]*3, data)['status'], 'passed')
        doc['segments'] = doc['segments'][:1]
        self.assertEqual(s.assess(doc, [30], data)['status'], 'held')

    def test_outro_is_not_information(self):
        doc, data = asset()
        doc['segments'][0]['kind'] = 'outro'
        self.assertEqual(len(s.information(doc, data)), 0)

    def test_existing_upper_limit_is_preserved(self):
        doc, data = asset()
        self.assertEqual(s.assess(doc, [40.01], data, maximum=40)['status'], 'held')

    def test_unknown_nan_and_mismatched_durations_hold(self):
        doc, data = asset()
        for times in ([], [float('nan')], [None], [30,30], [-1]):
            self.assertEqual(s.assess(doc, times, data)['status'], 'held')

    def test_failed_gate_records_reasons(self):
        doc, data = asset(1)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, '制作見送り'):
                s.require(doc, [19], folder, data, video_name='sample.mp4')
            report = json.loads((Path(folder)/'sample.mp4.short_content.json').read_text(encoding='utf8'))
            self.assertEqual(report['status'], 'held')
            self.assertEqual(len(report['reasons']), 2)

    def test_series_record_and_derived_clinch_are_one(self):
        card = dict(source_url='https://statsapi.mlb.com/api/v1/schedule', headline='A対B',
                    scoreboard=dict(rows=[dict(name='A',wins=3),dict(name='B',wins=0)]),
                    items=[dict(label='シリーズの現在地',value='王手')])
        doc = dict(segments=[dict(kind='ps_program',meta=dict(card=card))]*2)
        self.assertEqual(len(s.information(doc)), 1)

    def test_next_line_repeating_current_schedule_does_not_count_twice(self):
        card = dict(source_url='https://statsapi.mlb.com', headline='A対B',
                    items=[dict(label='次の試合',value='10月28日9時')])
        doc = dict(segments=[dict(kind='ps_program',meta=dict(card=card)),
                    dict(kind='next_line',meta=dict(card=dict(card,next_line=dict(screen='10月28日9時'))))])
        self.assertEqual(len(s.information(doc)), 1)

    def test_unspoken_explicit_claim_does_not_count(self):
        doc = dict(segments=[dict(kind='numbers', text='別の文', meta=dict(short_facts=[
            dict(subject='A',predicate='成績',value=3,statement='3安打',source='公式')]))])
        self.assertEqual(len(s.information(doc)), 0)

    def test_upload_without_report_stops_before_probe(self):
        with tempfile.TemporaryDirectory() as folder, patch('subprocess.run') as probe:
            video = Path(folder)/'sample.mp4';video.write_bytes(b'placeholder')
            with self.assertRaisesRegex(ValueError, '合格記録'):
                s.validate_upload(video)
            probe.assert_not_called()

    def test_upload_old_video_or_wrong_actual_length_is_held(self):
        doc, data = asset()
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder)/'sample.mp4';video.write_bytes(b'placeholder')
            s.require(doc, [30], folder, data, video_name=video.name)
            os.utime(video, ns=(1,1))
            with self.assertRaisesRegex(ValueError, '古い記録'):
                s.validate_upload(video)
            os.utime(video, ns=(2_000_000_000_000_000_000,)*2)
            with patch('subprocess.run', return_value=SimpleNamespace(stderr='Duration: 00:00:19.00')):
                with self.assertRaisesRegex(ValueError, '完成ショート'):
                    s.validate_upload(video)
            with patch('subprocess.run', return_value=SimpleNamespace(stderr='Duration: 00:00:30.00')):
                self.assertEqual(s.validate_upload(video)['status'], 'passed')

    def test_ps_supplement_requires_the_same_pair_and_numeric_final_score(self):
        program = dict(phase='situation', segments=[dict(kind='ps_program', meta=dict(card=dict(
            scoreboard=dict(rows=[dict(name='A',wins=1),dict(name='B',wins=0)]))))])
        ctx = dict(date_jst='2026-10-27',source_url='https://statsapi.mlb.com/api/v1/schedule')
        rows = [dict(round='W',teams=[dict(id=1,name='A'),dict(id=2,name='B')])]
        game = dict(gamePk=12,gameType='W',seriesGameNumber=1,gameDate='2026-10-26',
            status=dict(abstractGameState='Final'),teams=dict(away=dict(team=dict(id=1),score=3),home=dict(team=dict(id=2),score=2)))
        fixed = __import__('ps_program').previous_short_context(program,ctx,[game],rows)
        self.assertEqual(len(fixed['segments']),2)
        self.assertIn('3対2',fixed['segments'][-1]['text'])
        bad = copy.deepcopy(game);bad['teams']['home'].pop('score')
        self.assertEqual(__import__('ps_program').previous_short_context(program,ctx,[bad],rows),program)
        bad = copy.deepcopy(game);bad['gameType']='L'
        self.assertEqual(__import__('ps_program').previous_short_context(program,ctx,[bad],rows),program)

    def test_rare_supplements_require_same_player_year_and_finished_season(self):
        spec = dict(key='rare_123',items=[['WHIP','0.87']])
        peer = dict(key='season_player_123',player_id=123,ps_ended=True,label='選手の2026年シーズン',
                    items=[['今季の成績','14勝9敗 防御率2.53'],['昨季（2025年）から','勝利12から14']])
        topics = {peer['key']:peer}
        enriched = short_context.rare(spec, topics, '2026')
        self.assertEqual(len(enriched['items']),3)
        self.assertEqual(short_context.rare(enriched, topics, '2026'),enriched)
        for season in ('2025',None):
            self.assertEqual(short_context.rare(spec,topics,season),spec)
        for change in (dict(player_id=124),dict(ps_ended=False),dict(items=peer['items'][:1])):
            self.assertEqual(short_context.rare(spec,{peer['key']:dict(peer,**change)},'2026'),spec)

    def test_context_statistics_are_only_from_the_current_match(self):
        doc = dict(segments=[dict(kind='followup',text='A対Bは0対0',speaker=2,meta=dict(event_id='1'))])
        game = dict(id='1',home=dict(name_jp='A'),away=dict(name_jp='B'),
                    match_stats=dict(source='ESPN summary',home=dict(shots=13,possession=50.6),away=dict(shots=12,possession=49.4)))
        with patch.dict(os.environ, COLLESPO_SOCCER_LOOK='v6'):
            result = short_context.soccer(doc,dict(games=[game]),readable=True)
            self.assertEqual(result['segments'][-1]['meta']['event_id'],'1')
            self.assertIn('50.6',result['segments'][-1]['text'])
            bad = copy.deepcopy(game);bad['match_stats']['home'].pop('shots')
            self.assertEqual(short_context.soccer(doc,dict(games=[bad]),readable=True),doc)

    def test_supplementary_asset_material_reaches_existing_sanity(self):
        doc, data = asset()
        result = short_context.attach_asset(doc, data)
        import sanity_sources
        self.assertEqual(len(sanity_sources.collect([result])),1)
        self.assertEqual(len(result['sanity_materials'][0]['facts']),3)

    def test_all_short_render_entries_keep_gate_before_audio_join(self):
        root = Path(__file__).resolve().parent
        names = ('generate_asset_video.py','generate_morning_short.py','generate_ps_preview.py',
                 'generate_verdict_short.py','ps_program.py','short_saved_render.py','soccer_results_render.py',
                 'soccer_slots_v4.py','soccer_voices_render.py','player_story_render.py')
        for name in names:
            tree = ast.parse((root/name).read_text(encoding='utf-8-sig'))
            for function in (n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)):
                joins = [n for n in ast.walk(function) if isinstance(n,ast.Call) and
                         ((isinstance(n.func,ast.Name) and n.func.id=='build_narration_track') or
                          (isinstance(n.func,ast.Attribute) and n.func.attr=='build_narration_track'))]
                if not joins:
                    continue
                gates = [n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                         and isinstance(n.func.value,ast.Name) and n.func.value.id=='short_content' and n.func.attr=='require']
                self.assertTrue(gates,(name,function.name))
                self.assertLess(min(n.lineno for n in gates),min(n.lineno for n in joins),(name,function.name))

    def test_previous_game_card_renders_its_information_instead_of_the_lead(self):
        import ps_unified_v3 as render
        card = dict(date='2026-10-27', source_url='https://statsapi.mlb.com',source_label='MLB公式',
                    layout='facts',short_context=True,headline='A\n対B',subhead='前戦 / 終了',label='前戦の結果',
                    items=[dict(label='前戦の最終結果',value='A 10対1 B'),dict(label='前戦の開催地',value='Bのホーム')])
        lead = dict(card,short_context=False,headline='主役',items=[],scoreboard=dict(need=4,rows=[
            dict(name='A',abbr='A',wins=3,color='#174264',players=[]),dict(name='B',abbr='B',wins=0,color='#563442',players=[])]))
        with patch.object(render.r3,'LOOK','v4'):
            image = render.frame(4,card,lead,duration=12,ticker_line='日本時間10月27日')
        words = s.normalized(''.join(e.get('text','') for e in image.info.get('v3_layout',[])))
        image.close()
        self.assertIn('10対1',words)
        self.assertIn('Bのホーム',words)

    def test_capture_retries_empty_end_seek_and_keeps_real_time(self):
        import io
        from PIL import Image
        import visual_capture
        data = io.BytesIO();Image.new('RGB',(4,4),'white').save(data,format='PNG')
        with patch.object(visual_capture.subprocess,'run',side_effect=[SimpleNamespace(stdout=b''),SimpleNamespace(stdout=data.getvalue())]):
            image, actual = visual_capture.safe_video_frame('fixture.mp4',28.967,30)
        image.close()
        self.assertAlmostEqual(actual,28.867)
        with patch.object(visual_capture.subprocess,'run',return_value=SimpleNamespace(stdout=b'')):
            with self.assertRaises(ValueError):visual_capture.safe_video_frame('fixture.mp4',1,30)

    def test_old_preview_without_geometry_is_unconfirmed_not_passed(self):
        from PIL import Image
        from preview_short_content import frame_checks
        image = Image.new('RGB',(4,4))
        self.assertIn('未実施',frame_checks(image,'intro')['mode'])
        image.close()

    def test_hidden_preview_rank_metadata_does_not_survive_shortening(self):
        meta = dict(home='パリ・サンジェルマン',away='リヨン',date='10月27日',time='04:30',ranks=dict(home=5,away=4))
        doc = dict(segments=[dict(kind='preview',text='注目の一戦です。',meta=meta)])
        self.assertEqual(len(s.information(doc)),1)
        doc['segments'][0]['text']='5位パリ・サンジェルマン対4位リヨンの試合です。'
        self.assertEqual(len(s.information(doc)),3)

    def test_goal_keeps_original_player_intro(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root/'scripts/fixtures/soccer-stats/saved-cases.json').read_text(encoding='utf8'))['cases'][2]['data']
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6'):
            narr = __import__('soccer_results_render').goal_short_narration(data)
        self.assertEqual(narr['segments'][0]['kind'],'intro')
        self.assertIn(data['players'][0]['name'],narr['segments'][0]['text'])
        self.assertGreaterEqual(len(s.information(narr,data)),3)

    def test_roster_is_removed_only_when_every_person_is_already_shown(self):
        people = [dict(name=name,status='starter') for name in ('A','B')]
        data = dict(games=[dict(id='1',players=people)])
        doc = dict(segments=[dict(kind='player-stats',meta=dict(event_id='1',start=0,count=2)),
                             dict(kind='roster',meta=dict(player_names=['A','B'],absent=[]))])
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6'):
            self.assertEqual(len(short_context.soccer(doc,data,readable=True)['segments']),1)
            doc['segments'][0]['meta']['count']=1
            self.assertEqual(len(short_context.soccer(doc,data,readable=True)['segments']),2)

    def test_scoreless_result_does_not_add_a_second_empty_scene(self):
        data = dict(games=[dict(id='1',goals_complete=True,goals=[],score=dict(home=0,away=0))])
        doc = dict(segments=[dict(kind='followup',text='0対0',meta=dict(event_id='1')),
                             dict(kind='followup-detail',text='得点なし。',meta=dict(event_id='1'))])
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6'):
            self.assertEqual(len(short_context.soccer(doc,data,readable=True)['segments']),1)
            data['games'][0]['goals_complete']=False
            self.assertEqual(len(short_context.soccer(doc,data,readable=True)['segments']),2)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
