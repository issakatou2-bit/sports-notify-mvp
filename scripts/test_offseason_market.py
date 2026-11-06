"""手入力の境界・完全一致・公開経路。通信や実際の台帳書込はしない。"""
import argparse
import contextlib
import copy
from datetime import date, datetime, timedelta
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import offseason_market as m


class MarketTests(unittest.TestCase):
    day = date(2026, 11, 3)

    def entry(self):
        return json.loads(Path('scripts/fixtures/offseason-market/example.json').read_text(encoding='utf-8'))['entries'][0]

    def real_entry(self):
        entry = self.entry()
        for row in entry['facts'] + entry['reports']:
            row['source_url'] = row['source_url'].replace('example.com', 'mlb.com')
        return entry  # 検査専用。ネット接続せず、本物の情報として保存しない。

    def document(self):
        import generate_asset_video as g
        spec = m.topic(self.entry(), self.day, sample=True)
        with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
            doc = g.build_narration(spec['key'])
        return spec, doc

    def test_shipped_entries_pass_validation(self):
        # 11/6 本番の材料に金額を足して当日の制作が止まった。足した回は取込前に赤にする。
        data = json.loads(Path(m.PATH).read_text(encoding='utf-8'))
        for entry in data['entries']:
            with self.subTest(entry=entry['id']):
                m.validate(entry)

    def test_fixture_roundtrip_and_three_information(self):
        import offseason_news as n
        import sanity_material
        import short_content
        spec, doc = self.document()
        self.assertEqual(n.check(doc), [])
        self.assertEqual(sanity_material.check(doc, sanity_material.grounding([doc])), [])
        self.assertEqual(len(short_content.information(doc, spec)), 3)
        self.assertTrue(doc['offseason_sample'])
        self.assertIn('架空', doc['segments'][0]['text'])
        self.assertEqual(doc['segments'][-1]['text'], m.OUTRO_TEXT)

    def test_numeric_additions_assertions_and_material_tampering_stop(self):
        import offseason_news as n
        _, doc = self.document()
        for before, after in [('12月15日', '12月16日'), ('と見本通信が報じています', 'ことが確定しました')]:
            changed = copy.deepcopy(doc)
            for segment in changed['segments']:
                segment['text'] = segment['text'].replace(before, after)
            self.assertTrue(n.check(changed))
        for kind in ('intro', 'list', 'outro'):
            changed = copy.deepcopy(doc)
            next(s for s in changed['segments'] if s['kind'] == kind)['text'] += '移籍金は100億円です。'
            self.assertTrue(n.check(changed))
        changed = copy.deepcopy(doc)
        changed['offseason']['events'][0]['body'] = '期限は明日です。'
        self.assertTrue(n.check(changed))
        changed = copy.deepcopy(doc)
        changed['sanity_materials'] = []
        self.assertTrue(n.check(changed))

    def test_reports_require_outlet_and_fact_forecasts_money_rejected(self):
        for sentence in ('100億円で契約します。', 'ドジャースへの移籍が有力です。', 'ドジャースへ移籍する可能性があります。'):
            entry = self.entry()
            entry['facts'][0]['text'] = sentence
            with self.assertRaises(ValueError):
                m.validate(entry, sample=True)
        for sentence in ('契約が決まりました。', '獲得すると報じています。', '獲得と別の通信が報じています。', '獲得と見本通信が報じています。決定です。'):
            entry = self.entry()
            entry['reports'][0]['text'] = sentence
            with self.assertRaises(ValueError):
                m.validate(entry, sample=True)
        entry = self.entry()
        entry['reports'][0]['text'] = '総額100億円でドジャースへの移籍を予想していると見本通信が報じています。'
        self.assertEqual(m.validate(entry, sample=True), '佐藤輝明')

    def test_forbidden_sources_and_comment_names(self):
        for url in ('https://5ch.net/test', 'https://news.yahoo.co.jp/articles/test/comments',
                    'https://www.reddit.com/r/baseball', 'https://redd.it/test', 'http://mlb.com/test',
                    'https://user:password@mlb.com/test'):
            with self.assertRaises(ValueError):
                m.source(url, sample=True)
        for text in ('Redditで話題です。', 'コメント主の名前です。'):
            entry = self.entry()
            entry['facts'][0]['text'] = text
            with self.assertRaises(ValueError):
                m.validate(entry, sample=True)

    def test_examples_not_production_and_stale_not_selected(self):
        with self.assertRaises(ValueError):
            m.topic(self.entry(), self.day)
        self.assertIsNone(m.topic(self.entry(), self.day + timedelta(days=1), sample=True))
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'off'}):
            self.assertEqual(m.load(self.day, path='not-read.json'), [])
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}):
            path = Path(tempfile.mkdtemp(prefix='market-empty-'))/'market.json'
            path.write_text('{"version": 1, "entries": []}', encoding='utf-8')
            self.assertEqual(m.load(self.day, path=path), [])

    def test_loader_uses_manual_rows_and_omits_stale_seen_entries(self):
        entry = self.real_entry()
        directory = Path(tempfile.mkdtemp(prefix='market-loader-'))
        path = directory/'market.json'
        path.write_text(json.dumps(dict(version=1, entries=[entry])), encoding='utf-8')
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}):
            topics = m.load(self.day, {}, path)
            self.assertEqual(len(topics), 1)
            self.assertEqual(topics[0]['offseason']['entry'], entry)
            self.assertEqual(m.load(self.day+timedelta(days=1), {}, path), [])
            seen = {'events': [topics[0]['offseason']['events'][0]['event_id']]}
            self.assertEqual(m.load(self.day, seen, path), [])

    def test_offseason_picker_selects_one_market_before_shared_series(self):
        import offseason_news as n
        market = m.topic(self.entry(), self.day, sample=True)
        second = copy.deepcopy(market)
        second['key'] = 'offseason_market_2026_0123456789ab'
        official = copy.deepcopy(market)
        official['key'] = 'offseason_transactions_2026_0123456789ab'
        official['offseason']['kind'] = 'transactions'
        directory = Path(tempfile.mkdtemp(prefix='market-pick-'))
        path = directory/'topics.json'
        path.write_text(json.dumps(dict(topics=[official, market, second])), encoding='utf-8')
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}), \
             patch.object(m, 'posted_today', return_value=False), \
             patch.object(sys, 'argv', ['offseason_news', '--pick', '--day', str(self.day), '--out', str(path)]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            n.main()
        picked = output.getvalue().split()
        self.assertEqual(len(picked), 1)
        self.assertTrue(picked[0].startswith(m.PREFIX))

    def test_seen_events_and_shared_series_number(self):
        spec = m.topic(self.entry(), self.day, {'topics': {'old': {'series_number': 7}}}, sample=True)
        self.assertEqual(spec['offseason']['series_number'], 8)
        state = {'events': [spec['offseason']['events'][0]['event_id']]}
        self.assertIsNone(m.topic(self.entry(), self.day, state, sample=True))
        entry = self.entry()
        entry['reports'][0]['text'] = entry['facts'][0]['text']
        with self.assertRaises(ValueError):
            m.validate(entry, sample=True)
        entry = self.entry()
        entry['reports'] = []
        with self.assertRaises(ValueError):
            m.validate(entry, sample=True)

    def test_one_per_day_uses_jst_reservation_and_unknown_date_holds(self):
        key = 'offseason_market_2026_abcdef012345'
        self.assertTrue(m.posted_today({key: {'published_at': '2026-11-02T15:00:00Z'}}, self.day))
        self.assertFalse(m.posted_today({key: {'published_at': '2026-11-02T14:59:59Z'}}, self.day))
        self.assertTrue(m.posted_today({key: {'published_at': '2026-11-02T00:00:00Z', 'publish_at': '2026-11-03T22:00:00+09:00'}}, self.day))
        self.assertTrue(m.posted_today({key: {}}, self.day))
        self.assertFalse(m.posted_today({'season_player': {}}, self.day))

    def test_publication_day_and_duplicate_gate(self):
        spec = m.topic(self.entry(), self.day, sample=True)
        at = datetime(2026, 11, 3, 22, tzinfo=m.JST)
        m.validate_publication(spec, {}, at)
        with self.assertRaises(ValueError):
            m.validate_publication(spec, {}, at + timedelta(days=1))
        with self.assertRaises(ValueError):
            m.validate_publication(spec, {spec['key']: {'publish_at': at.isoformat()}}, at)

    def test_title_cannot_add_numbers(self):
        entry = self.entry()
        entry['title'] = '佐藤輝明 99日の交渉期限'
        with self.assertRaises(ValueError):
            m.validate(entry, sample=True)
        for title in ('佐藤輝明 100億円の契約', '佐藤輝明 ドジャース移籍が有力'):
            entry = self.entry()
            entry['title'] = title
            entry['reports'][0]['text'] = '100億円でドジャースへ移籍する予想と見本通信が報じています。'
            with self.assertRaises(ValueError):
                m.validate(entry, sample=True)

    def test_market_keeps_sixty_second_upper_bound(self):
        import short_content
        spec, doc = self.document()
        report = short_content.assess(doc, [15.2] * len(doc['segments']), spec, maximum=61)
        self.assertEqual(report['maximum_seconds'], 60)
        self.assertEqual(report['status'], 'held')

    def test_api_failure_does_not_discard_handwritten_material(self):
        import offseason_news as n
        spec = m.topic(self.entry(), self.day, sample=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'topics.json'
            with patch.object(sys, 'argv', ['offseason_news', '--day', str(self.day), '--out', str(target)]), \
                 patch.object(m, 'load', return_value=[spec]), patch.object(n, 'collect', side_effect=ConnectionError):
                n.main()
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['topics'][0]['key'], spec['key'])

    def test_intro_uses_existing_series_badge_and_breaks_at_name(self):
        import asset_v4_cards as cards
        spec, _ = self.document()
        self.assertEqual(spec['hook'], '佐藤輝明\nポスティングの期限')
        calls = []
        original = cards.c.text
        def record(*args, **kwargs):
            if len(args) > 3:
                calls.append(args[3])
            return original(*args, **kwargs)
        with patch.object(cards.c, 'text', side_effect=record):
            cards.intro(2, spec, 'MLB')
        self.assertIn(spec['heading'], calls)

    def test_invalid_market_does_not_stop_other_asset_catalog(self):
        import generated_topics as gt
        with patch.object(m, 'load', side_effect=ValueError('invalid fixture')):
            with patch.object(gt, '_CACHE', None):
                topics = gt.all_topics(refresh=True)
        self.assertFalse(any(k.startswith(m.PREFIX) for k in topics))
        self.assertTrue(topics)

    def test_ui_tone_keeps_material_and_outro_exact(self):
        import solo_host
        import ui_tone
        spec, doc = self.document()
        with patch.object(solo_host, 'for_segments', return_value='ui'):
            ui = ui_tone.narration(doc)
        self.assertEqual(m.check(ui), [])
        self.assertEqual([s['text'] for s in ui['segments']], [s['text'] for s in doc['segments']])
        entry = self.entry()
        entry['facts'][0]['text'] = '交渉期限は12月15日だ。'
        with self.assertRaises(ValueError):
            m.validate(entry, sample=True)

    def test_sns_metadata_and_badge_do_not_call_reports_official(self):
        import asset_sns
        import offseason_public
        import review_render_v3 as r3
        spec, doc = self.document()
        self.assertTrue(asset_sns.TOPIC.fullmatch(spec['key']))
        self.assertTrue(offseason_public.social_kind('asset_' + spec['key']))
        meta = offseason_public.metadata(spec)
        self.assertNotIn('MLB公式の記録から', str(meta))
        self.assertIn('確定情報と報道', str(meta))
        self.assertIn('第1回', spec['heading'])
        for row in spec['offseason']['events']:
            self.assertIn(row['source'], '\n'.join(meta['lead']))
        self.assertEqual(offseason_public.voice_credit(doc), 'VOICEVOX:四国めたん')
        calls = []
        original = r3._text
        def record(*a, **kw):
            if len(a) > 2:
                calls.append(a[2])
            return original(*a, **kw)
        with patch.object(r3, '_text', side_effect=record):
            r3.outro(3, spec)
        self.assertIn('確定情報と報道を分けて', calls)
        self.assertNotIn('オフの動きを公式の記録で', calls)

    def test_next_asset_prioritizes_market_and_only_one(self):
        import generate_asset_video as g
        import next_asset as nxt
        market = m.topic(self.entry(), self.day, sample=True)
        other = copy.deepcopy(market)
        other['key'] = 'offseason_market_2026_0123456789ab'
        stock = dict(key='season_player_test', jp_stock=True, label='佐藤輝明', stock_order=1)
        catalog = {r['key']: r for r in (stock, market, other)}
        ledgers = ({'asset': {}}, {'assets': {}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'published.json'
            path.write_text('{"assets":{}}', encoding='utf-8')
            with patch.dict(g.LIST_TOPICS, catalog, clear=True), patch('player_publications.load', return_value=ledgers), \
                 patch('player_publications.recent', return_value=False), patch('jp_assets.available', return_value=True), \
                 patch('jp_stock.rotation_available', return_value=True), patch.object(nxt, 'season_material_ready', return_value=True), \
                 patch.object(nxt, 'superseded', return_value=False), patch('asset_policy.selectable', return_value=True), \
                 patch('ui_voice_stock.prioritize', side_effect=lambda x: x), contextlib.redirect_stdout(io.StringIO()) as output:
                nxt.pick_season(argparse.Namespace(published=str(path), season=3))
            picked = output.getvalue().split()
        self.assertTrue(picked[0].startswith(m.PREFIX))
        self.assertEqual(sum(k.startswith(m.PREFIX) for k in picked), 1)
        self.assertIn(stock['key'], picked)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
