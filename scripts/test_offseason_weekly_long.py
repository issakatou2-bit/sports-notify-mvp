"""オフ週刊長編：週の範囲・確定と報道の分離・数字・期限・公開日・題・概要欄・札の静止画。通信・音声生成・公開はしない。"""
import copy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ['COLLESPO_STYLE'] = 'v2'   # 札の静止画は新しい見た目（v2）で書き出す
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
import offseason_weekly_long as w
import render_offseason_weekly_long as render

FIX = ROOT/'scripts/fixtures/offseason-weekly-long'
SAMPLES = ROOT/'build/offseason_long_samples'
DAY = date(2026, 11, 11)   # 窓は 11/4〜11/11。固定材料は 11/3〜11/8 の5件（鈴木誠也2件）


def market():
    return json.loads((FIX/'market.json').read_text(encoding='utf8'))


def deadlines():
    return json.loads((FIX/'deadlines.json').read_text(encoding='utf8'))


def build(day=DAY, market_data=None, deadline_data=None):
    return w.material(day, market_data or market(), deadline_data or deadlines(), fixture=True)


class Weekly(unittest.TestCase):
    def setUp(self):
        self.data = build()
        self.doc = w.dialogue(self.data)

    # ---- 週の範囲と作る・作らない
    def test_window_is_seven_days_before_to_publish_day_inclusive(self):
        ids = lambda day: [e['id'] for e in build(day)['entries']]
        self.assertNotIn('sato-posting-open-20261103', ids(DAY))           # 11/3 は 11/11 の窓（11/4〜）の外
        self.assertIn('sato-posting-open-20261103', ids(date(2026, 11, 10)))  # 11/3 は 11/10 の窓の初日
        self.assertNotIn('suzuki-qo-eight-20261108', ids(date(2026, 11, 7)))  # 公開日より後の確認日は使わない
        self.assertIn('imanaga-free-agent-20261107', ids(date(2026, 11, 7)))  # 当日は使う

    def test_fewer_than_two_entries_is_not_made_and_succeeds(self):
        data = build(date(2026, 11, 18))
        self.assertFalse(data['can_make'])
        self.assertIn('満たない', data['reason'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'argv', [
                'x', '--sample', '--day', '2026-11-18', '--market', str(FIX/'market.json'),
                '--deadlines', str(FIX/'deadlines.json'), '--out-dir', tmp]):
            self.assertEqual(w.main(), 0)
            self.assertFalse((Path(tmp)/'dialogue.json').exists())
        with self.assertRaises(ValueError):
            w.validate_document(dict(offseason_weekly_material=data))

    def test_one_player_uses_latest_two_entries(self):
        data = market()
        base = next(e for e in data['entries'] if e['id'] == 'suzuki-qualifying-offer-20261106')
        extra = copy.deepcopy(base)
        extra.update(id='suzuki-extra-20261110', checked_on='2026-11-10')
        data['entries'].append(extra)
        picked = [e['id'] for e in build(market_data=data)['entries'] if e['name_en'] == 'Seiya Suzuki']
        self.assertEqual(picked, ['suzuki-qo-eight-20261108', 'suzuki-extra-20261110'])

    # ---- 確定と報道
    def test_reports_are_never_read_as_facts(self):
        reports = {r['text']: r['outlet'] for e in self.data['entries'] for r in e['reports']}
        facts = {r['text'] for e in self.data['entries'] for r in e['facts']}
        said = [s for s in self.doc['segments'] if s['text'] in reports]
        self.assertTrue(said)
        for seg in said:
            self.assertIn(reports[seg['text']], seg['text'])
            self.assertIn('報じています', seg['text'])
            self.assertEqual(seg['speaker'], 2)
        for seg in self.doc['segments']:
            if seg['text'] in facts:
                self.assertNotIn('報じ', seg['text'])
        for key, panel in self.doc['panels'].items():
            if key[0] == 'p':
                kinds = {r['tone'] for r in panel['v2']['rows']}
                self.assertEqual(len(kinds), 1)
                prefix = '確定｜' if kinds == {'fact'} else '報道｜'
                self.assertTrue(all(r.startswith(prefix) for r in panel['rows']))
        tampered = copy.deepcopy(self.doc)
        for seg in tampered['segments']:
            seg['text'] = seg['text'].replace('とMLB Trade Rumorsが報じています', 'ことが確定しました')
        with self.assertRaises(ValueError):
            w.validate_document(tampered)

    def test_numbers_come_only_from_material(self):
        import re
        allowed = w.allowed_numbers(self.data)
        for seg in self.doc['segments']:
            self.assertFalse(set(re.findall(r'\d+', seg['text']))-allowed, seg['text'])
        w.validate_document(self.doc)
        changed = copy.deepcopy(self.doc)
        changed['segments'][3]['text'] += '観客は99人でした。'
        with self.assertRaises(ValueError):
            w.validate_document(changed)
        for field in ('panels', 'title', 'chapters'):
            changed = copy.deepcopy(self.doc)
            changed[field] = 'x' if field == 'title' else {} if field == 'panels' else []
            with self.assertRaises(ValueError):
                w.validate_document(changed)

    def test_structure_and_speakers(self):
        self.assertEqual([c['id'] for c in self.doc['chapters']], ['opening', 'deadlines', 'players', 'next', 'closing'])
        for seg in self.doc['segments']:
            self.assertIn(seg['speaker'], (2, 3))
            if seg['kind'] == 'talk':
                self.assertIn(seg['panel'], self.doc['panels'])
                self.assertIn(seg['chapter'], [c['id'] for c in self.doc['chapters']])
        self.assertEqual(self.doc['segments'][-3]['text'], __import__('review_render_v3').OFFSEASON_OUTRO_TEXT)
        names = [p for p in self.doc['panels'] if p.startswith('p')]
        self.assertTrue(names)
        self.assertEqual(sum(len(p['rows']) for k, p in self.doc['panels'].items() if k[0] == 'p'),
                         sum(len(e['facts'])+len(e['reports']) for e in self.data['entries']))

    # ---- 期限
    def test_zundamon_asks_and_metan_answers(self):
        # 11/14 本人「ずんだもんの疑問にめたんが答える形」：ずんだもんの台詞は問いだけ、材料の文はめたんが読む。
        talk = [s for s in self.doc['segments'] if s['kind'] == 'talk']
        for seg in talk:
            if seg['speaker'] == 3:
                self.assertTrue(seg['text'].endswith('？'), seg['text'])
        metan = {s['text'] for s in talk if s['speaker'] == 2}
        for e in self.data['entries']:
            for r in e['facts'] + e['reports']:
                self.assertIn(r['text'], metan)
        self.assertEqual(w.question('返事の期限'), '返事の期限は、いつなのだ？')
        self.assertEqual(w.question('2026年の成績'), '2026年の成績は、どうだったのだ？')

    def test_deadline_status_done_and_days(self):
        qo = next(i for i in deadlines()['items'] if i['id'] == 'qo-2026')
        self.assertEqual(w.tag(qo, date(2026, 11, 11)), 'あと7日')
        self.assertEqual(w.tag(qo, date(2026, 11, 17)), 'あと1日')
        self.assertEqual(w.tag(qo, date(2026, 11, 18)), '済')      # 当日の20:00公開の時点では6:00は過ぎている
        self.assertEqual(w.tag(qo, date(2026, 11, 19)), '済')
        later = dict(qo, at_jst='2026-11-18T21:00:00+09:00')
        self.assertEqual(w.tag(later, date(2026, 11, 18)), '本日')
        rows = {r['label']: r['tag'] for r in self.doc['panels']['deadlines']['v2']['rows']}
        self.assertEqual(rows, {'QOの提示の締め切り': '済', 'QOの返事の期限': 'あと7日', '交渉の期限': 'あと36日'})
        dates = [r['date'] for r in self.doc['panels']['deadlines']['v2']['rows']]
        self.assertEqual(dates, ['11.9', '11.18', '12.17'])
        spoken = ' '.join(s['text'] for s in self.doc['segments'])
        self.assertIn('この期限は済みです。', spoken)
        self.assertIn('期限まであと7日です。', spoken)

    def test_next_week_is_at_most_three_upcoming(self):
        data = deadlines()
        for n in range(4):
            data['items'].append(dict(data['items'][1], id=f'extra-{n}', at_jst=f'2026-12-{20+n}T07:00:00+09:00',
                                      text=f'期限は12月{20+n}日7時です。', players=[]))
        doc = w.dialogue(build(deadline_data=data))
        self.assertEqual(len(doc['panels']['next']['v2']['rows']), w.NEXT_WEEK_DEADLINES)
        self.assertTrue(all(r['tag'] != '済' for r in doc['panels']['next']['v2']['rows']))
        self.assertLessEqual(len(doc['panels']['deadlines']['v2']['rows']), w.MAX_PAST_DEADLINES+w.MAX_UPCOMING_DEADLINES)

    def test_deadline_file_format_is_checked(self):
        w.check_deadlines(deadlines())
        w.check_deadlines(json.loads((ROOT/'data/offseason_deadlines.json').read_text(encoding='utf8')))
        good = deadlines()['items'][1]
        bad = {
            'http': dict(good, source_url='http://www.mlb.com/x'),
            'no-host': dict(good, source_url='https:///x'),
            'date': dict(good, at_jst='2026-11-18'),
            'zone': dict(good, at_jst='2026-11-18T06:00:00+00:00'),
            'checked': dict(good, checked_on='11/8'),
            'punct': dict(good, text='返事の期限は11月18日6時です'),
            'polite': dict(good, text='返事の期限は11月18日6時だ。'),
            'two-sentences': dict(good, text='QOの期限です。返事は6時です。'),
            'extra-field': dict(good, memo='x'),
            'comment': dict(good, source_url='https://www.reddit.com/r/baseball/x'),
            'players': dict(good, players='Seiya Suzuki'),
        }
        for name, item in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                w.check_deadlines(dict(version=1, items=[item]))
        with self.assertRaises(ValueError):
            w.check_deadlines(dict(version=1, items=[good, dict(good)]))      # ID重複
        with self.assertRaises(ValueError):
            w.check_deadlines(dict(version=2, items=[good]))
        with self.assertRaises(ValueError):
            w.check_deadlines(dict(version=1, items=[dict(good, players=['Nobody Known'])]), names={'Seiya Suzuki': '鈴木誠也'})

    # ---- 公開日
    def test_publish_day(self):
        self.assertTrue(w.is_publish_day(date(2026, 11, 18)))                    # 初回
        self.assertFalse(w.is_publish_day(date(2026, 11, 17)))
        self.assertFalse(w.is_publish_day(date(2026, 11, 11)))                   # 初回より前は水曜でも作らない
        self.assertTrue(w.is_publish_day(date(2026, 11, 25)))                    # 以後は水曜
        self.assertFalse(w.is_publish_day(date(2026, 11, 24)))
        self.assertFalse(w.is_publish_day(date(2026, 11, 18), {'2026-11-18': {'video_id': 'x'}}))   # 公開済み
        self.assertTrue(w.is_publish_day(date(2026, 11, 25), {'2026-11-18': {'video_id': 'x'}}))
        with patch.object(w, 'PUBLISH_WEEKDAY', 3):                              # 曜日は定数1つで変わる
            self.assertTrue(w.is_publish_day(date(2026, 11, 26)))
            self.assertFalse(w.is_publish_day(date(2026, 11, 25)))
        self.assertEqual(w.FIRST_DAY, date(2026, 11, 18))

    def test_not_a_publish_day_makes_nothing_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'argv', [
                'x', '--day', '2026-11-17', '--market', str(FIX/'market.json'), '--deadlines', str(FIX/'deadlines.json'),
                '--published', str(Path(tmp)/'none.json'), '--out-dir', tmp]):
            self.assertEqual(w.main(), 0)
            self.assertFalse((Path(tmp)/'material.json').exists())

    def test_upload_gate(self):
        data = market()
        for i, e in enumerate(data['entries']):
            e['checked_on'] = f'2026-11-{12+i}'
        real = w.material(date(2026, 11, 18), data, deadlines())
        doc = w.dialogue(real)
        with tempfile.TemporaryDirectory() as tmp:
            narration, games = Path(tmp)/'dialogue.json', Path(tmp)/'material.json'
            w.save(narration, doc)
            w.save(games, real)
            args = SimpleNamespace(narration=str(narration), games=str(games), force=False, video_date='2026-11-18', publish_at='20:00')
            noon = datetime(2026, 11, 18, 12, 0, tzinfo=w.JST)
            with patch.dict(os.environ, {w.SWITCH: 'on'}):
                w.validate_upload(args, noon)
                for broken, now in [(dict(publish_at='19:30'), noon), (dict(video_date='2026-11-17'), noon),
                                    (dict(force=True), noon), ({}, noon.replace(hour=19, minute=59)),
                                    ({}, noon.replace(hour=20)), ({}, noon+timedelta(days=1))]:
                    with self.subTest(broken=broken, now=now), self.assertRaises(ValueError):
                        w.validate_upload(SimpleNamespace(**dict(vars(args), **broken)), now)
            with patch.dict(os.environ, {w.SWITCH: 'off'}), self.assertRaises(ValueError):
                w.validate_upload(args, noon)
            # 検証用の材料は公開できない
            w.save(games, dict(real, fixture=True))
            with patch.dict(os.environ, {w.SWITCH: 'on'}), self.assertRaises(ValueError):
                w.validate_upload(args, noon)

    # ---- 題と概要欄
    def test_title_shape(self):
        text = w.title(self.data)
        self.assertEqual(text, '【MLB】日本人選手の来季 今週の動き｜鈴木誠也・今永昇太・伊藤大海')
        self.assertLessEqual(len(text), 50)
        self.assertEqual(self.doc['title'], text)
        for bad in ('【海外の反応】日本人', '【MLB】日本人選手の来季｜衝撃の動き', '【MLB】来季！', '【MLB】【速報】来季', '来季' + 'あ'*60):
            with self.subTest(bad), self.assertRaises(ValueError):
                w.check_title(bad)
        wide = copy.deepcopy(self.data)
        wide['names'] = {k: v+'あ'*8 for k, v in wide['names'].items()}
        self.assertLessEqual(len(w.title(wide)), 50)

    def test_description_has_every_source_url_and_credit(self):
        text = w.description(self.data, ['0:00 冒頭'])
        urls = {r['source_url'] for e in self.data['entries'] for k in ('facts', 'reports') for r in e[k]}
        urls |= {i['source_url'] for i in w.shown_deadlines(self.data['deadlines'], DAY)}
        self.assertGreater(len(urls), 5)
        for url in urls:
            self.assertIn(url, text)
        for e in self.data['entries']:
            self.assertIn(e['checked_on'], text)
        self.assertIn('音声：VOICEVOX ずんだもん / 四国めたん', text)
        self.assertIn('0:00 冒頭', text)
        self.assertLessEqual(len(text), w.DESCRIPTION_MAX)
        meta = w.metadata(self.doc)
        self.assertEqual(meta['snippet']['title'], self.doc['title'])
        self.assertIn('報道｜', meta['snippet']['description'])

    def test_upload_youtube_knows_the_kind(self):
        import upload_youtube as yt
        self.assertIn(w.KIND, yt.DATED_KINDS)
        self.assertIn(w.KIND, yt.LANDSCAPE_KINDS)
        self.assertEqual(yt.material_date_key(w.KIND, 'mlb', {'key': '2026-11-18'}), '2026-11-18')
        with tempfile.TemporaryDirectory() as tmp:
            narration = Path(tmp)/'dialogue.json'
            w.save(narration, self.doc)
            meta = yt.build_metadata('x', '2026-11-11', kind=w.KIND, narration_path=str(narration))
        self.assertEqual(meta['snippet']['title'], self.doc['title'])

    def test_workflow_is_sample_safe(self):
        text = (ROOT/'.github/workflows/offseason_weekly_long.yml').read_text(encoding='utf8')
        for required in ("cron: '30 3 * * *'", 'sample_only:', 'default: true', '--require-audio', "--publish-at '20:00'",
                         '--kind offseason_weekly_long', 'published_videos.json'):
            self.assertIn(required, text)
        upload = text.split('- name: Upload to YouTube')[1].split('- name:')[0]
        commit = text.split('- name: Commit video record')[1].split('- name:')[0]
        for step in (upload, commit):
            self.assertIn("env.SAMPLE_ONLY != 'true'", step)

    # ---- 札
    def test_frames_are_written_and_tables_fit(self):
        from PIL import Image
        render.prepare(self.doc)
        folder = render.frames(self.doc, SAMPLES)
        for key in ('opening', 'deadlines', 'p0_f0'):
            with Image.open(folder/(key+'.png')) as image:
                self.assertEqual(image.size, (1920, 1080))
            self.assertTrue(__import__('longform_v2').enabled(self.doc['panels'][key]))   # COLLESPO_STYLE=v2 の表の札

    def test_overflow_stops_instead_of_cutting(self):
        panel = copy.deepcopy(self.doc['panels']['p0_f0'])
        panel['v2']['rows'] = [dict(badge='確定', tone='fact', text='あ'*300)]*4
        with self.assertRaises(ValueError):
            render.install(self.doc)
            __import__('longform_v2').content(panel)

    def test_render_audio_check_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            render.audio_duration(self.doc, dict(segments=[]))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
