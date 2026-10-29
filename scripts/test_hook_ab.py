import copy
import json
from pathlib import Path
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import hook_ab as h
from hook_ab_test_support import HookFixtureTestCase, press_data, season_spec


class HookABTest(HookFixtureTestCase):
    def test_assignment_off_and_date_blocks(self):
        with patch.dict('os.environ', {}, clear=True):
            for kind in h.KINDS:
                self.assertEqual(h.assignment(kind, '2026-10-23')['ab_variant'], 'A')
        import host_split
        expected = {
            'morning_press': ['A', 'B', 'B', 'A', 'A', 'B', 'B'],
            'asset:season_player': ['B', 'B', 'A', 'A', 'B', 'B', 'A'],
        }
        for kind in h.KINDS:
            days = [h.assignment(kind, f'2026-10-{d}', True)['ab_variant'] for d in range(23, 30)]
            self.assertEqual(days, expected[kind])
            self.assertEqual(days[:4].count('A'), 2)
            self.assertEqual(days[:4].count('B'), 2)
            # 既存司会の交互割付とA/Bが同じ並びにならない。
            for variant in ('A','B'):
                hosts = {host_split.plan(kind,f'2026-10-{d}')['planned_host'] for d in range(23,27)
                         if h.assignment(kind,f'2026-10-{d}',True)['ab_variant']==variant}
                self.assertEqual(hosts, {'ui','metan'})
        self.assertEqual(h.assignment('daily', '2026-10-23', True)['ab_variant'], 'A')
        self.assertEqual(h.assignment(h.KINDS[0], '2026-10-22', True)['ab_variant'], 'A')
        self.assertEqual(h.publication_day('2026-10-22T16:00:00Z'), '2026-10-23')

    def test_environment_switch_controls_real_assignment(self):
        import generate_morning_short as g
        source = g.build_narration(press_data(), 'press')
        for setting in ('', 'off', 'ON', 'on'):
            for day, variant in (('2026-10-22', 'A'), ('2026-10-23', 'A'), ('2026-10-24', 'B')):
                with self.subTest(setting=setting, day=day), patch.dict('os.environ', {'COLLESPO_HOOK_AB': setting}):
                    result = h.prepare(source, 'morning_press', day)
                    expected = variant if setting == 'on' else 'A'
                    self.assertEqual(result['hook_ab']['ab_variant'], expected)
                    self.assertEqual(result['hook_ab']['ab_enabled'], setting == 'on' and day >= '2026-10-23')
                    if expected == 'A':
                        self.assertEqual(result['segments'], source['segments'])
                    else:
                        self.assertTrue(result['segments'][0]['meta']['press_hook'])
        self.assertNotIn('hook_ab', source)

    def test_default_publication_day_uses_frozen_jst_clock(self):
        import generate_morning_short as g
        day = self.now.astimezone(h.JST).date().isoformat()
        self.assertEqual(h.publication_day(), day)
        self.assertEqual(h.publication_day('18:00'), day)
        source = g.build_narration(press_data(), 'press')
        with patch.dict('os.environ', {'COLLESPO_HOOK_AB': 'on'}):
            result = h.prepare(source, 'morning_press')
        plan = result['hook_ab']
        for key, value in h.assignment('morning_press', day, True).items():
            self.assertEqual(plan[key], value)

    def test_unrelated_material_keeps_a_in_legacy_and_modern(self):
        import generate_morning_short as g
        import review_render_v3 as r3
        for design, look in (('legacy', 'v3'), ('v3', 'v3'), ('v3', 'v4')):
            with self.subTest(design=design, look=look), patch.dict('os.environ', {'COLLESPO_PRESS_DESIGN': design}), patch.object(r3, 'LOOK', look):
                data = press_data()
                data['reporters']['headlines'][2]['jp'] = '大谷翔平のユニフォームが高額で落札された'
                data['reporters']['posts'] = []
                source = g.build_narration(data, 'press')
                result = h.prepare(source, 'morning_press', '2026-10-24', preview='B')
                self.assertEqual(result['hook_ab']['ab_variant'], 'A')
                self.assertFalse(result['hook_ab']['ab_content_eligible'])
                self.assertIn('ab_fallback_reason', result['hook_ab'])
                self.assertEqual(result['segments'], source['segments'])

    def test_press_preserves_all_quotes_and_factual_validation(self):
        import daily_v3
        import generate_morning_short as g
        import review_render_v3 as r3
        data = press_data()
        for look in ('v3', 'v4'):
            with self.subTest(look=look), patch.dict('os.environ', {'COLLESPO_PRESS_DESIGN':'v3'}), patch.object(r3, 'LOOK', look):
                a = g.build_narration(data, 'press')
                b = h.prepare(a, 'morning_press', '2026-10-23', preview='B')
                self.assertEqual(b['hook_ab']['ab_variant'], 'B')
                self.assertNotIn('現地の報道です', b['segments'][0]['text'])
                self.assertEqual(a['label'], b['label'])
                self.assertCountEqual([(s['kind'], s['meta']) for s in a['segments']],
                    [(s['kind'], {k:v for k,v in s['meta'].items() if k!='press_hook'}) for s in b['segments']])
                self.assertTrue(b['segments'][0]['meta']['press_hook'])
                self.assertEqual(b['segments'][1]['kind'], 'headlines')
                self.assertTrue(any('大谷翔平' in row['said'] and '感謝' in row['said']
                                    for row in b['segments'][1]['meta']['quote_rows']
                                    if not row.get('fact') and row.get('read', True)))
                self.assertNotIn('press_hook',a['segments'][0]['meta'])
                self.assertEqual(a['segments'][-1], b['segments'][-1])
                # 既存の独立した原材料照合をA/B双方に実行。
                for n in (a,b):
                    design = daily_v3.prepare(data, n, 'press')
                    with patch('press_v3.frame', return_value='same-renderer') as render:
                        for seg in n['segments'][:-1]:
                            daily_v3.frame(0, seg, design, 5)
                        self.assertEqual(render.call_count, len(n['segments'])-(2 if n is b else 1))

    def test_season_same_render_calls_title_and_numbers(self):
        import generate_asset_video as g
        import review_render_v3 as r3
        import v3_rules
        topic = 'season_player_test'
        spec = season_spec()
        self.enterContext(patch.object(g, 'LIST_TOPICS', {topic: copy.deepcopy(spec)}))
        a = g.build_narration(topic)
        b = h.prepare(a, 'asset:season_player', '2026-10-23', spec, preview='B')
        self.assertEqual(b['hook_ab']['ab_variant'], 'B')
        self.assertEqual(spec, g.LIST_TOPICS[topic])
        self.assertEqual(a['label'], b['label'])
        self.assertEqual([s['kind'] for s in a['segments']], [s['kind'] for s in b['segments']])
        self.assertEqual([s['meta'] for s in a['segments']], [s['meta'] for s in b['segments']])
        self.assertEqual(a['segments'][1:], b['segments'][1:])
        self.assertFalse(v3_rules.check_speech(spec, spec['items']))
        self.assertFalse(v3_rules.numbers(b['segments'][0]['text']) - v3_rules.numbers(str(spec)))
        for n in (a, b):
            with patch.object(r3,'intro', return_value='same-renderer') as render, patch.object(r3,'LOOK','v3'):
                seg=n['segments'][0]
                self.assertEqual(g.render_v3(0, seg['kind'], seg['meta'], spec, topic, seg, 5), 'same-renderer')
                render.assert_called_once_with(0, spec, 'シーズンまとめ')

    def test_off_unchanged_and_idempotent(self):
        source={'label':'題', 'segments':[{'kind':'intro','text':'元の導入','meta':{}}]}
        original=copy.deepcopy(source)
        with patch.dict('os.environ', {}, clear=True):
            a=h.prepare(source, 'morning_press', '2026-10-23')
        self.assertEqual(a['segments'], source['segments'])
        self.assertEqual(source, original)
        self.assertIs(h.prepare(a, 'morning_press', '2026-10-24'), a)
        b=h.prepare(source, 'morning_press', '2026-10-23', preview='B')
        self.assertEqual(b['hook_ab']['ab_variant'], 'A')
        self.assertIn('ab_fallback_reason', b['hook_ab'])
        comparison=h.prepare(source, 'morning_press', '2026-10-23', preview='A')
        self.assertEqual(comparison['hook_ab']['ab_content_eligible'],b['hook_ab']['ab_content_eligible'])

    def test_legacy_quotes_remain_complete_and_in_sync(self):
        import generate_morning_short as g
        data=press_data()
        with patch.dict('os.environ', {'COLLESPO_PRESS_DESIGN':'legacy'}):
            a=g.build_narration(data,'press')
        b=h.prepare(a,'morning_press','2026-10-23',preview='B')
        self.assertEqual(b['hook_ab']['ab_variant'],'B')
        original=next(s for s in a['segments'] if s['kind']=='headlines')
        changed=b['segments'][1]
        self.assertEqual(changed['meta']['picked'],[2,1])
        self.assertCountEqual(original['meta']['picked'],changed['meta']['picked'])
        self.assertCountEqual(original['meta']['source_headlines'],changed['meta']['source_headlines'])
        self.assertEqual(a['segments'][-1],b['segments'][-1])
        for index,row in zip(changed['meta']['picked'],changed['meta']['source_headlines']):
            self.assertEqual(row,data['reporters']['headlines'][index])
            self.assertIn(row['jp'],changed['text'])

    def test_preview_blocked_from_publication_and_stale_audio(self):
        root=Path('build/hook_ab_tests')/uuid.uuid4().hex
        root.mkdir(parents=True)
        video=root/'video.mp4'; video.write_bytes(b'fake')
        source={'segments':[{'kind':'intro','text':'原稿','meta':{}}]}
        n=h.prepare(source,'morning_press','2026-10-23',preview='A')
        with self.assertRaises(ValueError):
            h.bind_video(video,n,[{'kind':'intro','text':'古い原稿'}],[3],24)
        h.bind_video(video,n,n['segments'],[3],24)
        with self.assertRaises(ValueError): h.publication(video,'2026-10-23')

    def test_card_page_boundaries_are_measured_not_animation_frames(self):
        recorder=h.SceneRecorder()
        for frame, page, item in [(0,0,0),(1,0,0),(48,1,0),(49,1,0),(96,0,1)]:
            image=SimpleNamespace(info={'asset_v4':{'kind':'stats','page':page,'item':item,'animation_time':frame/24}})
            original=copy.deepcopy(image.info)
            recorder.observe(image,frame,24,1)
            self.assertEqual(image.info,original)
        self.assertEqual(recorder.starts,[0,2,4])

    def test_timing_and_both_publication_records(self):
        import upload_youtube as uploader
        # 依頼どおり生成物は削除せずbuild/に残す。
        folder=Path('build/hook_ab_tests')/uuid.uuid4().hex
        folder.mkdir(parents=True)
        video=Path(folder)/'sample.mp4'; video.write_bytes(b'fake-video')
        n={'hook_ab':h.assignment('morning_press','2026-10-23',True), 'segments':[
            {'kind':'intro','text':'台詞1','speaker':2,'meta':{'screen':1}},
            {'kind':'headlines','text':'台詞2','speaker':2,'meta':{'screen':1}},
            {'kind':'outro','text':'締め','speaker':2,'meta':{}}]}
        h.bind_video(video,n,n['segments'],[3.01,5.02,4],24,[2])
        record=h.publication(video,'2026-10-23T18:00:00+09:00')
        self.assertEqual(record['scene_starts'],[0,2,8])
        self.assertEqual([x['start'] for x in record['dialogue_starts']],[0,3.01,8.03])
        for function, args, filename in [(uploader.record_published,('season_player_1','id','private'),'assets.json'),
                                          (uploader.record_video,('asset','season_player_1','id','題'),'videos.json')]:
            path=Path(folder)/filename
            function(*args,path=str(path),experiment=record)
            data=json.loads(path.read_text(encoding='utf-8'))
            row=(data.get('assets') or data['asset'])['season_player_1']
            self.assertEqual(row['ab_test'],h.TEST)
            self.assertEqual(row['scene_starts'],record['scene_starts'])
        with self.assertRaises(ValueError): h.publication(video,'2026-10-24T18:00:00+09:00')
        video.write_bytes(b'changed')
        with self.assertRaises(ValueError): h.publication(video,'2026-10-23')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
