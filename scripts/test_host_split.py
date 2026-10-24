"""固定日付・固定数字・単音だけ。公開APIやVoiSonaは呼ばない。"""
from collections import Counter
import copy
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import host_split as hs
import host_split_report as report
import ui_voice_queue as q
import weekly_report as weekly

SCRIPT = dict(label='固定の回', title='同じ題', segments=[dict(kind='intro', speaker=2, text='成績です。', meta={})])


def day_for(host, kind='morning'):
    return next((date(2026, 10, 12)+timedelta(days=i)).isoformat() for i in range(7)
                if hs.plan(kind, date(2026, 10, 12)+timedelta(days=i))['planned_host'] == host)


def record(host, vid, day, actual=None, kind='morning'):
    assignment = hs.plan(kind, day)
    assert assignment['planned_host'] == host
    return dict(video_id=vid, title='固定の題', published_at=day+'T08:00:00Z',
                host_assignment=assignment, planned_host=host, actual_host=actual or host, privacy='public',
                host_fallback_reason='ui_unavailable' if host == 'ui' and actual == 'metan' else None)


class HostSplitTest(unittest.TestCase):
    def setUp(self):
        (q.ROOT/'build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=q.ROOT/'build')
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, COLLESPO_HOST_SPLIT='half', COLLESPO_SOLO_HOST='metan')
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_four_weeks_balance_every_weekday_and_inventory_kind(self):
        kinds = hs.KINDS+tuple(hs.asset_kind(t) for t in ('season_game_1', 'season_story_1', 'season_spotlight_1',
                            'season_league_1', 'season_team_1', 'season_odds_1', 'season_momentum_1', 'legend_a', 'v3_rules_multi'))
        for start in (date(2026, 10, 12), date(2026, 12, 21), date(2027, 12, 27)):
            for kind in kinds:
                totals = Counter()
                for n in range(28):
                    day = start+timedelta(days=n)
                    assignment = hs.plan(kind, day)
                    totals[day.weekday(), assignment['planned_host']] += 1
                    self.assertTrue(hs.valid(assignment))
                    if n % 7:
                        self.assertNotEqual(assignment['planned_host'], hs.plan(kind, day-timedelta(days=1))['planned_host'])
                    self.assertNotEqual(assignment['planned_host'], hs.plan(kind, day+timedelta(days=7))['planned_host'])
                for weekday in range(7):
                    self.assertLessEqual(abs(totals[weekday, 'ui']-totals[weekday, 'metan']), 1)

    def test_rule_is_independent_of_execution_order_and_missing_games(self):
        days = [date(2026, 10, 12)+timedelta(days=i) for i in range(28)]
        expected = {str(day): hs.plan('daily', day) for day in days}
        for day in reversed(days[::3]):
            self.assertEqual(expected[str(day)], hs.plan('daily', day))

    def test_default_is_unchanged_and_duo_or_other_speaker_is_excluded(self):
        with patch.dict(os.environ, COLLESPO_HOST_SPLIT=''):
            self.assertIs(hs.prepare(SCRIPT, 'morning'), SCRIPT)
            self.assertEqual(hs.credit('VOICEVOX:四国めたん'), 'VOICEVOX:四国めたん')
        for seg in (dict(speaker=3, text='成績です。'), dict(text='成績です。'), dict(speaker=2, text='成績です。', meta={'duo':True})):
            source = dict(segments=[seg])
            self.assertIs(hs.prepare(source, 'morning'), source)
        self.assertIs(hs.prepare(SCRIPT), SCRIPT)

    def test_title_thumbnail_clock_are_independent_of_host(self):
        source = dict(SCRIPT, thumbnail='same-template', publish_at='17:00')
        for host in hs.HOSTS:
            prepared = hs.adapt(source, 'morning', day_for(host))
            for field in ('title', 'thumbnail', 'publish_at', 'label'):
                self.assertEqual(prepared[field], source[field])

    def test_saved_plan_is_frozen_and_invalid_plan_rejected(self):
        source = hs.prepare(SCRIPT, 'morning', day_for('ui'))
        with patch.object(hs, 'today', return_value='2027-03-01'):
            self.assertEqual(hs.prepare(source, 'morning')['host_assignment'], source['host_assignment'])
        broken = copy.deepcopy(source)
        broken['host_assignment']['planned_host'] = 'metan'
        with self.assertRaises(ValueError):
            hs.prepare(broken, 'morning')

    def test_planned_metan_and_ui_fallback_are_recorded_without_upload(self):
        import synthesize_narration as sn
        import ui_voice_stock
        import upload_youtube as upload
        from test_ui_voice_queue import tone
        for planned in hs.HOSTS:
            with self.subTest(planned=planned):
                source = hs.prepare(SCRIPT, 'morning', day_for(planned))
                path = self.folder/(planned+'.json')
                path.write_bytes(q.encoded(source))
                audio, video = self.folder/(planned+'-audio'), self.folder/(planned+'-video')
                with patch.object(sn, 'engine_available', return_value=True), \
                     patch.object(sn, 'synth_one', side_effect=lambda text, speaker, out: (tone(text, out) or True)), \
                     patch.object(ui_voice_stock, 'fulfill', return_value=None), \
                     patch.object(sys, 'argv', ['synth', '--narration', str(path), '--out-dir', str(audio)]):
                    sn.main()
                hs.render_audio(audio, video)
                (video/'fixed.mp4').write_bytes(b'fixed-video')
                hs.bind_video(video/'fixed.mp4', audio)
                receipt = hs.publication(video/'fixed.mp4')
                self.assertEqual(receipt['planned_host'], planned)
                self.assertEqual(receipt['actual_host'], 'metan')
                self.assertEqual(hs.use_audio({}, audio)['host_assignment'], source['host_assignment'])
                store = self.folder/'published.json'
                upload.record_video('morning', planned, 'video-'+planned, '同じ題', str(store), host_tracking=receipt)
                saved = json.loads(store.read_text(encoding='utf8'))['morning'][planned]
                self.assertEqual(saved['actual_host'], 'metan')
                self.assertEqual(saved['host_assignment'], source['host_assignment'])
                if planned == 'ui':
                    self.assertEqual(saved['host_fallback_reason'], 'ui_unavailable')

    def test_ready_ui_audio_carries_plan_through_queue_install_and_render(self):
        import base64
        import synthesize_narration as sn
        import ui_voice_stock as stock
        import ui_voice_worker as worker
        from test_ui_voice_queue import MemoryQueue, tone, portraits, stock_sleep
        source = hs.prepare(SCRIPT, 'morning', day_for('ui'))
        path = self.folder/'ui.json'
        path.write_bytes(q.encoded(source))
        queue = MemoryQueue()
        with patch.dict(os.environ, COLLESPO_UI_PARTS_KEY=base64.b64encode(bytes(range(32))).decode('ascii')), \
             patch.object(q, 'GitQueue', return_value=queue), \
             stock_sleep(lambda seconds: worker.process(queue, self.folder/'cache', tone, portraits())), \
             patch.object(sys, 'argv', ['synth', '--narration', str(path), '--out-dir', str(self.folder/'audio')]):
            sn.main()
        hs.render_audio(self.folder/'audio', self.folder/'video')
        (self.folder/'video/fixed.mp4').write_bytes(b'fixed-ui-video')
        hs.bind_video(self.folder/'video/fixed.mp4', self.folder/'audio')
        receipt = hs.publication(self.folder/'video/fixed.mp4')
        self.assertEqual((receipt['planned_host'], receipt['actual_host']), ('ui', 'ui'))
        self.assertEqual(os.environ['COLLESPO_SOLO_HOST'], 'ui')
        self.assertIsNone(receipt['host_fallback_reason'])

    def test_unknown_or_silent_voice_is_not_assumed_to_match(self):
        source = hs.prepare(SCRIPT, 'morning', day_for('ui'))
        path = self.folder/'source.json'
        path.write_bytes(q.encoded(source))
        video = self.folder/'fixed.mp4'
        video.write_bytes(b'fixed-video')
        (self.folder/'manifest.json').write_bytes(q.encoded(source))
        hs.bind_video(video, self.folder)
        self.assertEqual(hs.publication(self.folder/'fixed.mp4', path)['actual_host'], 'unknown')
        source['voice_resolution'] = dict(host='metan', audio_available=False)
        path.write_bytes(q.encoded(source))
        (self.folder/'manifest.json').write_bytes(q.encoded(source))
        hs.bind_video(video, self.folder)
        self.assertEqual(hs.publication(self.folder/'fixed.mp4', path)['actual_host'], 'unknown')

    def test_default_publication_record_has_no_new_fields(self):
        import upload_youtube as upload
        path = self.folder/'legacy.json'
        upload.record_video('daily', '2026-10-15', 'legacy', '題', str(path))
        saved = hs.read(path)['daily']['2026-10-15']
        self.assertEqual(set(saved), {'video_id','url','title','published_at'})

    def test_recreating_saved_ui_with_split_off_records_actual_metan(self):
        import synthesize_narration as sn
        import ui_voice_stock
        from test_ui_voice_queue import tone
        source = hs.prepare(SCRIPT, 'morning', day_for('ui'))
        source['voice_resolution'] = dict(host='ui', portrait_dir='unused')
        path = self.folder/'previous-ui.json'
        path.write_bytes(q.encoded(source))
        with patch.dict(os.environ, COLLESPO_HOST_SPLIT='', COLLESPO_SOLO_HOST='metan'), \
             patch.object(sn,'engine_available',return_value=True), \
             patch.object(sn,'synth_one',side_effect=lambda text,speaker,out:(tone(text,out) or True)), \
             patch.object(ui_voice_stock,'fulfill') as ui, \
             patch.object(sys,'argv',['synth','--narration',str(path),'--out-dir',str(self.folder/'audio')]):
            sn.main()
            ui.assert_not_called()
        self.assertEqual(hs.read(path)['voice_resolution']['host'],'metan')
        (self.folder/'fixed.mp4').write_bytes(b'fixed-video')
        hs.bind_video(self.folder/'fixed.mp4', self.folder/'audio')
        self.assertEqual(hs.publication(self.folder/'fixed.mp4',path)['actual_host'],'metan')

    def test_shared_output_folder_never_overwrites_another_videos_host(self):
        from test_ui_voice_queue import portraits
        for name, blob in portraits().items():
            (self.folder/name).write_bytes(blob)
        out = self.folder/'shared'
        out.mkdir()
        for host in hs.HOSTS:
            audio = self.folder/(host+'-audio')
            audio.mkdir()
            assignment = hs.plan('morning',day_for(host))
            resolution = dict(host=host,portrait_dir=str(self.folder))
            (audio/'manifest.json').write_bytes(q.encoded(dict(host_assignment=assignment,voice_resolution=resolution)))
            video = out/(host+'.mp4')
            video.write_bytes(host.encode('ascii'))
            hs.render_audio(audio,out)
            hs.bind_video(video,audio)
        self.assertEqual(hs.read(out/'voice-resolution.json')['voice_resolution']['host'],'ui')
        for host in hs.HOSTS:
            video = out/(host+'.mp4')
            self.assertEqual(hs.publication(video)['actual_host'],host)
            q.configure(type('Args',(),{'video':video})())
            self.assertEqual(os.environ['COLLESPO_SOLO_HOST'],host)
        (out/'ui.mp4').write_bytes(b'changed-video')
        self.assertIsNone(hs.publication(out/'ui.mp4'))

    def fixture(self, n=10):
        videos = {'morning':{}}
        snaps = {}
        for host, views, duration, percentage, likes, subs in (('metan',100,10,40,2,1), ('ui',200,20,60,3,2)):
            day = day_for(host)
            pub = date.fromisoformat(day)
            for i in range(n):
                vid = host+str(i)
                videos['morning'][vid] = record(host, vid, day)
                for days, factor in ((1,1), (3,2), (7,3)):
                    target = pub+timedelta(days=days)
                    snaps.setdefault(target, {})[vid] = dict(views=views*factor, averageViewDuration=duration,
                        averageViewPercentage=percentage, likes=likes, subscribersGained=subs)
        values = [(day, date(2026,9,1), rows) for day, rows in sorted(snaps.items())]
        return videos, values

    def test_table_calculates_windows_weighted_metrics_likes_subs_and_intervals(self):
        videos, snaps = self.fixture()
        end = date(2026,10,25)
        groups = report.aggregate(report.rows(videos, end), snaps, end)
        group = groups['morning']
        self.assertEqual(group['differences'][1]['delta'], 100)
        self.assertEqual(group['differences'][7]['interval'], (300,300))
        self.assertTrue(group['differences'][7]['enough'])
        md = report.render(videos, snaps, end, end, 2)
        self.assertIn('| めたん | 10 | 10 | 100.0（10本） | 200.0（10本） | 300.0（10本） | 10.0（10本） | 40.0（10本） | 20（10本） | 10（10本） |', md)
        self.assertIn('雨衣が多い傾向（参考）', md)
        self.assertEqual(report.bootstrap([1,5,9], [2,4,12], 'fixed'), report.bootstrap([1,5,9], [2,4,12], 'fixed'))
        self.assertEqual(report.bootstrap([1,5,9], [2,4,12], 'fixed'), report.bootstrap([9,1,5], [12,2,4], 'fixed'))
        spread = report.bootstrap([1,5,9], [2,4,12], 'fixed')
        self.assertLess(spread[0], 0)
        self.assertGreater(spread[1], 0)
        self.assertEqual(report.mean_metric([dict(views=1,averageViewDuration=10),dict(views=3,averageViewDuration=30)],'averageViewDuration', True), (25,2))

    def test_fallback_private_future_duplicate_and_unknown_are_excluded(self):
        videos, snaps = self.fixture()
        ui_day = day_for('ui')
        videos['morning']['fallback'] = record('ui','fallback',ui_day,actual='metan')
        videos['morning']['unknown'] = record('ui','unknown',ui_day,actual='unknown')
        videos['morning']['private'] = dict(record('ui','private',ui_day),privacy='private')
        videos['morning']['future'] = dict(record('ui','future',ui_day),publish_at='2030-01-01T08:00:00Z')
        videos['morning']['duplicate'] = copy.deepcopy(videos['morning']['ui0'])
        videos['morning']['legacy'] = dict(video_id='legacy',published_at=ui_day+'T08:00:00Z')
        end = date(2026,10,25)
        group = report.aggregate(report.rows(videos,end),snaps,end)['morning']
        self.assertEqual(group['fallback'],1)
        self.assertEqual(group['unavailable'],1)
        self.assertEqual(group['excluded'],2)
        self.assertEqual(group['hosts']['ui']['matched'],10)
        self.assertEqual(group['hosts']['metan']['matched'],10)

    def test_fewer_than_ten_or_missing_mature_window_never_decides(self):
        videos, snaps = self.fixture(9)
        md = report.render(videos,snaps,date(2026,10,25),date(2026,10,25),0)
        self.assertIn('まだ差は言えない（各10本未満）',md)
        self.assertNotIn('多い傾向',md)
        rec = report.rows(videos,date(2026,10,25))[0]
        self.assertIsNone(report.at_window([(rec['published'].date()+timedelta(days=2),date(2026,9,1),{rec['video_id']:dict(views=999)})],rec,1)['views'])
        self.assertIsNone(report.number(float('nan')))

    def test_weekly_report_adds_cumulative_section_and_missing_data_note(self):
        videos,snaps = self.fixture(2)
        days = {str(day+timedelta(days=2)):dict(range=[str(start),str(day)],videos=[dict(video=k,**v) for k,v in rows.items()]) for day,start,rows in snaps}
        for name, data in (('published_videos.json',videos),('published_assets.json',{}),('analytics.json',dict(days=days))):
            (self.folder/name).write_bytes(q.encoded(data))
        md = weekly.build(self.folder,date(2026,10,25),lag=2)
        self.assertIn('## めたんと雨衣の半々比較',md)
        self.assertIn('今週だけに絞らず',md)
        self.assertIn('約2日',md)
        self.assertIn('不明',md)

    def test_inventory_does_not_reorder_subjects_during_comparison(self):
        import ui_voice_stock as stock
        with patch.object(q,'GitQueue') as queue:
            self.assertEqual(stock.prioritize(['second','first']), ['second','first'])
            queue.assert_not_called()

    def test_asset_and_soccer_generation_attach_actual_inventory_kinds(self):
        import generate_asset_video as assets
        import soccer_slots_v4 as slots
        import review_render_v3 as r3
        with patch.object(hs, 'today', return_value=day_for('ui', hs.asset_kind('v3_rules_multi'))), \
             patch.object(assets, 'build_narration', return_value=copy.deepcopy(SCRIPT)), \
             patch.object(sys, 'argv', ['asset','--topic','v3_rules_multi','--narration-out',str(self.folder/'asset.json')]):
            assets.main()
        self.assertEqual(hs.read(self.folder/'asset.json')['host_assignment']['kind'],'asset:v3')
        for mode in ('preview','race','week'):
            kind = 'daily_soccer' if mode == 'preview' else 'soccer_'+mode
            with patch.dict(os.environ, COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_LOOK='v4'), \
                 patch.object(hs,'today',return_value=day_for('ui',kind)), patch.object(r3,'LOOK','v4'):
                material = hs.read(q.ROOT/'scripts/fixtures/soccer-slots'/(mode+'.json'))
                result = slots.program(mode,material)['narration']
                self.assertEqual(result['host_assignment']['kind'],kind)
                self.assertEqual(result['host_assignment']['planned_host'],'ui')

    def test_ps_script_carries_frozen_publication_day_plan(self):
        import ps_program as ps
        import review_render_v3 as r3
        from test_ps_program import fixture
        snapshot,evidence,at = fixture(29)
        with patch.dict(os.environ,COLLESPO_PS_DESIGN='v3'), patch.object(r3,'LOOK','v4'):
            program = ps.prepare(snapshot,evidence,'forecast',at,{})
        self.assertEqual(program['host_assignment']['day'],at.astimezone(hs.JST).date().isoformat())
        self.assertEqual(ps.script(program)['host_assignment'],program['host_assignment'])
        self.assertEqual(ps.content_key(program),program['edition_key'])

    def test_tracked_asset_keeps_existing_weekly_classification_and_deduplicates(self):
        rec = record('ui','asset',day_for('ui', 'asset:season_game'),kind='asset:season_game')
        items = weekly.published_items({'asset':{'season_game_1':rec}}, {'assets':{'season_game_1':rec}})
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['type'],'試合の話題')

    def test_artifacts_exclude_decrypted_portrait_sources(self):
        import yaml
        root = q.ROOT/'.github/workflows'
        for path in root.glob('*.yml'):
            data = yaml.safe_load(path.read_text(encoding='utf8'))
            if 'COLLESPO_HOST_SPLIT' not in path.read_text(encoding='utf8'):
                continue
            for job in data.get('jobs',{}).values():
                for step in job.get('steps',[]):
                    if step.get('uses','').startswith('actions/upload-artifact@'):
                        self.assertIn('!build/**/portrait/**',step.get('with',{}).get('path',''),str(path))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
