"""公開済みの題・概要欄・タグの事故（同名の重複、検索語の羅列、URL重複、代表の台本流し込み、
得点速報のタグ欠け、同題の回）の再発防止。通信なし。"""
import copy
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import offseason_market as market
import offseason_public as op
import soccer_national as n
import soccer_national_numbers as numbers
import soccer_now
import upload_youtube as uy
from test_soccer_national_numbers import fixture_sheet, AS_OF


def voices_meta(who, card):
    switch = {'SERIES_TITLE': '', 'COLLESPO_MLB_TITLE_V2': 'on'}
    with patch.dict(os.environ, switch, clear=True), \
         patch.object(uy, 'top_headline', return_value=''), \
         patch.object(uy, 'buzz_top', return_value={'topic_jp': card}), \
         patch.object(uy, 'thread_replies', return_value=4), \
         patch.object(uy, 'voiced_japanese', return_value=who):
        return uy.build_metadata('notable_games.json', '11月13日', kind='morning',
                                 morning_mode='voices',
                                 narration_path='build/no-mlb-title-narration.json')['snippet']


class FanVoiceTitle(unittest.TestCase):
    """項目1・2。"""
    def test_player_name_not_repeated_in_title_and_description(self):
        snippet = voices_meta(['岡本和真'], '岡本和真、本塁打記録を2つ更新のハイライト')
        self.assertEqual(snippet['title'], '岡本和真、本塁打記録を2つ更新に現地ファンの声 #Shorts')
        self.assertNotIn('岡本和真｜岡本和真', snippet['title'])
        self.assertNotIn('岡本和真｜岡本和真', snippet['description'])

    def test_description_head_is_one_title_line(self):
        snippet = voices_meta(['岡本和真'], '岡本和真、本塁打記録を2つ更新のハイライト')
        head = snippet['description'].splitlines()[:3]
        self.assertEqual(head[0], '【MLB】岡本和真、本塁打記録を2つ更新のハイライト 現地のファンは何と言ったか｜返信4件ついたコメント 11月13日更新')
        self.assertNotIn('#Shorts', head[0])
        self.assertNotIn('MLB｜', head[0])
        self.assertEqual(len(set(x for x in head if x)), len([x for x in head if x]))
        # 検索語は tags 側に残る
        self.assertIn('岡本和真', snippet['tags'])
        self.assertIn('MLB', snippet['tags'])

    def test_different_player_name_is_still_added(self):
        snippet = voices_meta(['大谷翔平'], 'ドジャース vs カブス')
        self.assertIn('大谷翔平｜ドジャース vs カブス', snippet['title'])


class MarketDescription(unittest.TestCase):
    """項目3。"""
    def spec(self):
        entry = json.loads((ROOT / 'scripts/fixtures/offseason-market/example.json').read_text(encoding='utf-8'))['entries'][0]
        spec = market.topic(entry, __import__('datetime').date(2026, 11, 3), sample=True)
        spec['intro'] = spec['label'] + '。'
        return spec

    def test_no_duplicate_sentence_or_url(self):
        spec = self.spec()
        for row in spec['offseason']['events']:  # 全行同じ出典URL
            row['source'] = spec['source_url']
        lead = op.metadata(spec)['lead']
        text = '\n'.join(lead)
        self.assertEqual(text.count(spec['label'] + '。'), 1)  # 「label。確定情報と…」の1回だけ
        self.assertEqual(text.count(spec['source_url']), 1)

    def test_distinct_urls_are_kept_once_each(self):
        spec = self.spec()
        urls = [r['source'] for r in spec['offseason']['events']]
        text = '\n'.join(op.metadata(spec)['lead'])
        for u in set(urls):
            self.assertEqual(text.count(u), 1)


class SquadDescription(unittest.TestCase):
    """項目4。"""
    def setUp(self):
        env = patch.dict(os.environ, COLLESPO_SAMPLE_ONLY='true')
        env.start()
        self.addCleanup(env.stop)
        self.roster = n.read(ROOT / 'scripts/fixtures/soccer_national_squad_1110.json')
        self.sheet = fixture_sheet()

    def meta(self, page=4):
        data = numbers.attach(n.squad(self.roster, {}, AS_OF, page), self.sheet)
        doc = n.narration(data)
        return data, n.metadata(doc)['snippet']

    def test_description_shape(self):
        data, snippet = self.meta()
        desc = snippet['description']
        self.assertNotIn('sports.core.api.espn.com', desc)
        self.assertIn('今季成績: ESPN', desc)
        self.assertIn('#サッカー日本代表', desc)
        self.assertIn('#Shorts', desc)
        first = desc.splitlines()[0]
        self.assertIn('JFAが発表した日本代表の招集メンバーから', first)
        for i, p in enumerate(data['players']):
            self.assertEqual(first.count(p['name']), 1)
            self.assertIn(f"・{p['name']}（{p['club']}）", desc)
            if i < 3:
                self.assertIn(p['name'], snippet['tags'])
                self.assertIn('#' + p['name'], desc)
        self.assertLessEqual(len([t for t in snippet['tags'] if t not in ('サッカー', '日本代表', 'コレスポ')]), 3)

    def test_numbers_only_from_material(self):
        data, snippet = self.meta()
        for p in data['players']:
            row = next(x for x in snippet['description'].splitlines() if x.startswith(f"・{p['name']}（"))
            vals = (p.get('season_numbers') or {}).get('values') or {}
            units = {'goals': '得点', 'assists': 'アシスト', 'minutes': '分出場', 'appearances': '試合出場'}
            if vals:
                for k, v in vals.items():
                    self.assertIn(f"{v}{units[k]}", row)
            else:
                self.assertNotIn('今季', row)

    def test_script_text_is_not_dumped(self):
        _, snippet = self.meta()
        self.assertNotIn('続いて', snippet['description'])
        self.assertNotIn('最後は', snippet['description'])


class GoalShortMeta(unittest.TestCase):
    """項目5。"""
    def test_hashtags_and_tags(self):
        data = dict(games=[dict(finished_utc='2026-11-09T21:00:00Z')],
                    players=[dict(name='鈴木唯人', status='started', goals=1),
                             dict(name='久保建英', status='started', assists=1),
                             dict(name='佐野海舟', status='none')])
        with patch.object(soccer_now.results, 'description_lines', return_value=['x', '・鈴木唯人']), \
             patch.object(soccer_now.results, 'title', return_value='鈴木唯人が得点'):
            meta = soccer_now.goal_short_metadata(data)
        self.assertIn('#サッカー #鈴木唯人 #Shorts', meta['description'])
        self.assertEqual(meta['tags'], ['サッカー', '欧州サッカー', '海外サッカー', 'コレスポ', '鈴木唯人'])
        self.assertNotIn('久保建英', meta['tags'])


class ScheduleTitle(unittest.TestCase):
    """項目6。"""
    def spec(self, day):
        return dict(label='MLBオフの主な予定', heading='MLBオフの主な予定',
                    offseason=dict(kind='schedule', day=day))

    def test_title_has_date_and_differs_by_day(self):
        a = op.metadata(self.spec('2026-11-05'))['title']
        b = op.metadata(self.spec('2026-11-11'))['title']
        self.assertEqual(a, '【MLB】MLBオフの主な予定 11月5日時点 #Shorts')
        self.assertIn('時点', b)
        self.assertNotEqual(a, b)

    def test_other_kinds_unchanged(self):
        spec = dict(label='x', heading='2025年のMLB公式表彰', offseason=dict(kind='awards', day='2026-11-05'))
        self.assertEqual(op.metadata(spec)['title'], '【MLB】2025年のMLB公式表彰 #Shorts')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
