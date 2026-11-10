"""実材料の固定抜粋と窓境界・欠測・投稿条件。通信や音声生成はしない。"""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import soccer_weekly_long as w

FIXTURE = Path(__file__).parent/'fixtures/soccer_weekly_long.json'


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.nights = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.data = w.aggregate(self.nights, '2026-11-02')

    def test_window_edges_use_completion(self):
        source = self.nights[0]['games'][0]
        games = []
        for i, ended in enumerate(('2026-10-25T23:59:59Z', '2026-10-26T00:00:00Z',
                                   '2026-11-01T23:59:59Z', '2026-11-02T00:00:00Z')):
            g = copy.deepcopy(source)
            g['id'] = str(i)
            g['finished_utc'] = ended
            for p in g['players']:
                p['event_id'] = g['id']
            games.append(g)
        data = w.aggregate([dict(date_jst='2026-10-26', games=games)], '2026-11-02')
        self.assertEqual({g['id'] for g in data['games']}, {'1', '2'})
        self.assertEqual(w.nightly_days('2026-11-02'), [f'2026-10-{n}' for n in range(26, 32)]+['2026-11-01', '2026-11-02'])

    def test_duplicate_and_conflict(self):
        data = w.aggregate(self.nights+self.nights, '2026-11-02')
        self.assertEqual(data['players'], self.data['players'])
        wrong = copy.deepcopy(self.nights)
        wrong[0]['games'][0]['score']['home'] += 1
        with self.assertRaisesRegex(ValueError, '重複'):
            w.aggregate(self.nights+wrong, '2026-11-02')

    def test_sort_and_absent(self):
        self.assertEqual(self.data['players'][0]['name'], '坂元達裕')
        self.assertEqual(self.data['players'][-1]['name'], '遠藤航')
        kamada = next(p for p in self.data['players'] if p['name'] == '鎌田大地')
        self.assertEqual(len(kamada['matches']), 2)
        self.assertTrue(kamada['appeared'])
        doc = w.dialogue(self.data)
        self.assertIn('遠藤航', str(doc['panels']['absent']))
        self.assertEqual(sum(k.startswith('game_') for k in doc['panels']), sum(any(p['status'] != 'none' for p in g['players']) for g in self.data['games']))

    def test_less_than_three_distinct_appearances_skip(self):
        data = w.aggregate([self.nights[0]]*4, '2026-11-02')
        self.assertFalse(data['can_make'])
        self.assertIn('3人未満', data['reason'])
        self.assertEqual(w.dialogue(data)['segments'], [])

    def test_no_minutes_is_not_full_match(self):
        seko = next(p for p in self.data['players'] if p['name'] == '瀬古歩夢')
        text = w.appearance(seko['matches'][0])
        self.assertEqual(text, '先発')
        self.assertNotIn('フル', text)
        sugawara = next(p for p in self.data['players'] if p['name'] == '菅原由勢')
        self.assertIn('約90分出場', w.appearance(sugawara['matches'][0]))

    def test_title_and_no_results_headline(self):
        self.assertEqual(w.title(self.data), '【欧州サッカー】坂元達裕が1得点｜日本人選手の1週間（10/28〜11/2）')
        for p in self.data['players']:
            p['goals'] = p['assists'] = 0
        self.assertEqual(w.title(self.data), '【欧州サッカー】日本人選手の1週間（10/28〜11/2）')

    def test_script_and_cards_reject_invented_numbers(self):
        import sanity_internal
        doc = w.dialogue(self.data)
        self.assertEqual(sanity_internal.check([doc]), [])
        for section in ('segments', 'panels'):
            wrong = copy.deepcopy(doc)
            if section == 'segments':
                wrong['segments'][4]['text'] += '99得点です。'
            else:
                wrong['panels']['game_401879247']['rows'][0] += ' 99得点'
            with self.assertRaises(ValueError):
                w.validate_document(wrong)
            self.assertTrue(sanity_internal.check([wrong]))

    def test_context_missing_and_present(self):
        self.assertFalse(any('standing' in p or 'next' in p for p in self.data['players']))
        person = self.data['players'][0]
        ident = w.identity(person['club'])
        self.assertIsNotNone(ident)
        context = dict(tables={ident: dict(rank=7, competition='PL', as_of='2026-11-02T00:00:00Z')},
                       upcoming=[dict(home=person['club'], away='Liverpool', start_utc='2026-11-07T15:00:00Z', source='football-data.org')])
        data = w.aggregate(self.nights, '2026-11-02', context)
        self.assertEqual(data['players'][0]['standing']['rank'], 7)
        self.assertEqual(data['players'][0]['next']['date'], '2026-11-08')
        doc = w.dialogue(data)
        w.validate_document(doc)
        # 順位と次戦はその試合の中で1文。最後の羅列にしない。「A 対 B」でホーム・アウェーを示唆しない。
        notes = [s['text'] for s in doc['segments'] if 'いまプレミアリーグ7位' in s['text']]
        self.assertEqual(len(notes), 1)
        self.assertIn('リバプールと対戦します', notes[0])
        self.assertFalse(any('の予定です' in s['text'] for s in doc['segments']))

    def test_cup_table_does_not_replace_domestic_rank(self):
        import soccer_result_context
        g = copy.deepcopy(self.nights[0]['games'][0])
        g['league'] = 'CL'
        def context(data, preview):
            code = preview['games'][0]['competition_code']
            if code in ('BL1', 'CL'):
                return {}, {'same': dict(rank=8 if code == 'BL1' else 20, competition=code)}, []
            return {}, {}, []
        with patch.object(soccer_result_context, 'after_context', side_effect=context):
            result = w.fetch_context([g])
        self.assertEqual(result['tables']['same']['rank'], 8)

    def test_collect_calls_existing_daily_for_boundary_night(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def runner(cmd, check):
                calls.append(cmd)
                self.assertTrue(check)
                Path(cmd[-1]).write_text(json.dumps(dict(date_jst=cmd[-3], games=[])), encoding='utf8')
            with patch.object(w.results, 'validate_data') as validate:
                rows = w.collect('2026-11-02', temp, runner)
            self.assertEqual(len(rows), 8)
            self.assertEqual(validate.call_count, 8)
            self.assertTrue(all(Path(c[1]).name == 'soccer_results.py' for c in calls))
            self.assertEqual(calls[0][-3], '2026-10-26')

    def test_metadata_classification_and_week_key(self):
        import upload_youtube as upload
        import playlist_classification as pc
        import backfill_records as br
        doc = w.dialogue(self.data)
        meta = w.metadata(doc)
        self.assertNotIn('Shorts', str(meta))
        self.assertNotIn('MLB', str(meta))
        self.assertEqual(pc.classify(meta['snippet']['title']), 'soccer_weekly')
        self.assertEqual(br.kind_of(meta['snippet']['title']), 'soccer_weekly')
        self.assertIn('soccer_weekly', upload.LANDSCAPE_KINDS)
        self.assertIn('soccer_weekly', upload.DATED_KINDS)
        self.assertEqual(upload.material_date_key('soccer_weekly', 'soccer', self.data), '2026-11-02')
        with self.assertRaises(ValueError):
            upload.material_date_key('soccer_weekly', 'soccer', self.data, '2026-11-03')

    def test_upload_switch_date_and_time(self):
        with tempfile.TemporaryDirectory() as temp:
            doc = Path(temp)/'dialogue.json'
            material = Path(temp)/'material.json'
            w.save(doc, w.dialogue(self.data))
            w.save(material, self.data)
            args = SimpleNamespace(narration=doc, games=material, force=False, video_date='2026-11-02', publish_at='20:30')
            with patch.dict(os.environ, {w.SWITCH: 'off'}):
                with self.assertRaisesRegex(ValueError, '無効'):
                    w.validate_upload(args, datetime(2026, 11, 2, 10, tzinfo=w.JST))
            with patch.dict(os.environ, {w.SWITCH: 'on'}):
                w.validate_upload(args, datetime(2026, 11, 2, 10, tzinfo=w.JST))
                with self.assertRaisesRegex(ValueError, '締め前'):
                    w.validate_upload(args, datetime(2026, 11, 2, 8, tzinfo=w.JST))
                with self.assertRaises(ValueError):
                    w.validate_upload(args, datetime(2026, 11, 3, 7, tzinfo=w.JST))
                with self.assertRaises(ValueError):
                    w.validate_upload(args, datetime(2026, 11, 2, 20, 45, tzinfo=w.JST))

    def test_card_fits_all_text_with_bundled_font(self):
        from PIL import Image, ImageDraw
        import longform_render_v3 as v3
        import render_soccer_weekly as render
        doc = w.dialogue(self.data)
        for panel in doc['panels'].values():
            image = Image.new('RGBA', (v3.CARD_W, v3.CARD_BOTTOM-v3.CARD_Y))
            bottom = render.draw_panel(image, ImageDraw.Draw(image), panel, 8, {})
            self.assertLessEqual(bottom+20, v3.CARD_BOTTOM-v3.CARD_Y)

    def test_nine_am_keeps_kubo_and_current_week_boundary(self):
        self.assertIn('久保建英', [p['name'] for p in self.data['players']])
        self.assertEqual(w.current_week(datetime(2026, 11, 2, 8, 59, tzinfo=w.JST)), '2026-10-26')
        self.assertEqual(w.current_week(datetime(2026, 11, 2, 9, 0, tzinfo=w.JST)), '2026-11-02')

    def test_each_shared_match_is_introduced_once(self):
        doc = w.dialogue(self.data)
        for ident, names in (('401884749', ['宇野禅斗', '橋岡大樹', '町野修斗']),
                             ('401876421', ['中村草太', '瀬古歩夢', '水多海斗']),
                             ('401884752', ['堂安律', '小杉啓太']),
                             ('401878763', ['守田英正', '前田大然'])):
            rows = [s for s in doc['segments'] if s.get('event_id') == ident]
            self.assertEqual(len(rows), 2+len(names))
            self.assertEqual(sum('対' in s['text'] and s['speaker'] == 3 for s in rows[:2]), 1)
            for name in names:
                self.assertIn(name, str(doc['panels']['game_'+ident]))
        headings = [s['panel'] for s in doc['segments'] if str(s.get('panel')).startswith('league_')]
        self.assertEqual(headings, ['league_results', 'league_PL', 'league_PD', 'league_BL1', 'league_SA', 'league_FL1', 'league_cups'])
        intros = [s['text'] for s in doc['segments'] if s.get('event_id') and s['speaker'] == 3]
        self.assertFalse(any('試合を確認するのだ' in t for t in intros))
        self.assertEqual(doc, w.dialogue(self.data))

    def test_zero_stats_omitted_and_only_one_extra_stat(self):
        doc = w.dialogue(self.data)
        public = ' '.join(s['text'] for s in doc['segments'])+str(doc['panels'])+w.description(self.data)
        self.assertNotIn('0得点', public)
        self.assertNotIn('0アシスト', public)
        text = w.appearance(dict(status='starter', yellow_cards=1, red_cards=1, shots=4, on_target=2, goals=0, assists=0))
        self.assertIn('警告1回', text)
        self.assertIn('退場1回', text)
        self.assertIn('枠内シュート2本', text)
        self.assertNotIn('シュート4本', text)
        self.assertIn('4セーブ', w.appearance(dict(status='starter', saves=4)))

    def test_english_club_names_stop_and_hamburg_is_shared(self):
        self.assertEqual(w.results.ne.club_name_jp('Hamburg SV'), 'ハンブルガーSV')
        doc = w.dialogue(self.data)
        self.assertIn('ハンブルガーSV', str(doc['panels']))
        self.assertNotIn('Hamburg', str(doc['panels']))
        # 表示名の表にある英字入りの日本語名は止めない（11/3 次戦の「マンチェスターU」で止まった）。
        w.check_public_names('次はマンチェスターU、その次はボルシアMGとハンブルガーSVです。')
        with self.assertRaisesRegex(ValueError, 'Manchester'):
            w.check_public_names('次はManchester United')
        # 表に英字だけで載せた名前（PSV 等）も止めない（11/9 15時の長編が「PSV」で止まった）。
        self.assertEqual(w.club_label('PSV'), 'PSV')
        w.check_public_names('佐野航大のPSVは、次はAZと当たります。')
        with self.assertRaisesRegex(ValueError, 'PSVX'):
            w.check_public_names('次はPSVXです。')
        bad = copy.deepcopy(self.nights)
        bad[0]['games'][0]['away']['name_jp'] = 'Mystery FC'
        with self.assertRaisesRegex(ValueError, '英字'):
            w.dialogue(w.aggregate(bad, '2026-11-02'))
        for field in ('title', 'panels', 'segments'):
            wrong = copy.deepcopy(doc)
            if field == 'title':
                wrong['title'] += ' Hamburg SV'
            elif field == 'segments':
                wrong['segments'][4]['text'] += 'Hamburg SV'
            else:
                wrong['panels']['opening']['rows'].append('Hamburg SV')
            with self.assertRaises(ValueError):
                w.validate_document(wrong)

    def test_injury_age_date_only_translation_and_missing_appearance(self):
        available = json.loads((FIXTURE.parent/'soccer_weekly_availability.json').read_text(encoding='utf8'))
        data = w.aggregate(self.nights, '2026-11-02', availability=available)
        mitoma = next(p for p in data['players'] if p['name'] == '三笘薫')
        self.assertFalse(mitoma['matches'])
        self.assertEqual(mitoma['injury_note'], 'けがで離脱中、11月22日に復帰見込み')
        self.assertNotIn('Hamstring', w.description(data))
        self.assertIn('三笘薫', str(w.dialogue(data)['panels']['absent']))
        w.validate_document(w.dialogue(data))
        available['updated_at'] = '2026-10-31T00:00:00Z'
        self.assertTrue(w.injury_notes(available, w.week_window('2026-11-02')[1]))
        available['updated_at'] = '2026-10-30T23:59:59Z'
        self.assertEqual(w.injury_notes(available, w.week_window('2026-11-02')[1]), {})
        available['updated_at'] = '2026-11-02T00:00:00Z'
        available['players']['三笘薫']['news'] = 'Hamstring injury - Expected back soon'
        self.assertEqual(w.injury_notes(available, w.week_window('2026-11-02')[1])['三笘薫']['note'], 'けがで離脱中')
        available['players']['三笘薫']['news'] = 'Suspended - Expected back 22 Nov'
        self.assertNotIn('三笘薫', w.injury_notes(available, w.week_window('2026-11-02')[1]))

    def test_chapters_only_from_matching_completed_video_timeline(self):
        from voice_manifest import sha256
        doc = w.dialogue(self.data)
        self.assertEqual(w.rendered_chapters(doc), [])
        self.assertNotIn('0:00 冒頭', w.metadata(doc)['snippet']['description'])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'render_timeline.json'
            video = Path(temp)/'collespo_longform.mp4'
            video.write_bytes(b'fixed test video identity')
            sources = [dict(line_id=i, text=s['text'], speaker=s['speaker']) for i, s in enumerate(doc['segments'], 1)]
            rows = [dict(start=i*11.25, source_line_ids=[i]) for i in range(1, len(doc['segments'])+1)]
            w.save(path, dict(video_sha256=sha256(video), source_lines=sources, lines=rows))
            chapters = w.rendered_chapters(doc, path)
            self.assertEqual(chapters[0], '0:00 冒頭')
            index = next(i for i, s in enumerate(doc['segments'], 1) if s.get('chapter') == 'PD')
            seconds = int(index*11.25)
            self.assertIn(f'{seconds//60}:{seconds%60:02d} ラ・リーガ', chapters)
            video.write_bytes(b'different video')
            with self.assertRaises(ValueError):
                w.rendered_chapters(doc, path)

    def test_existing_v3_calls_and_closing(self):
        import review_render_v3
        doc = w.dialogue(self.data)
        for pair in (doc['segments'][:2], doc['segments'][-2:]):
            self.assertEqual([s['speaker'] for s in pair], [3, 2])
            self.assertEqual([s['text'] for s in pair], ['コレスポ', 'コレスポ'])
            self.assertTrue(all(s['panel'] is None for s in pair))
        self.assertEqual(doc['segments'][-3]['text'], review_render_v3.INSEASON_OUTRO_TEXT)

    def test_names_and_return_phrase_are_not_broken_on_cards(self):
        from PIL import Image, ImageDraw
        import longform_render_v3 as v3
        import render_soccer_weekly as render
        d = ImageDraw.Draw(Image.new('RGB', (1080, 600)))
        text = 'ボルシアMG 対 パーダーボルン'
        lines = render.wrap_row(d, text, v3.font(36), 400, ('ボルシアMG', 'パーダーボルン'))
        self.assertTrue(any('ボルシアMG' in row for row in lines))
        self.assertTrue(any('パーダーボルン' in row for row in lines))
        lines = render.wrap_row(d, '先発、1得点、警告1回、枠内シュート1本', v3.font(36), 400)
        self.assertTrue(any('枠内シュート1本' in row for row in lines))
        available = w.load(FIXTURE.parent/'soccer_weekly_availability.json')
        doc = w.dialogue(w.aggregate(self.nights, '2026-11-02', availability=available))
        panel = doc['panels']['absent']
        self.assertIn('\n11月22日に復帰見込み', str('\n'.join(panel['rows'])))
        render.preflight(doc)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
