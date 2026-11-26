import sys
from pathlib import Path
from datetime import timedelta
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_watch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'marketwatch_1125'
NOW = market_watch.datetime(2026, 11, 25, 15, 0, tzinfo=market_watch.JST)


def feed(title, description, link, creator='Test Writer', pub='Wed, 25 Nov 2026 05:59:59 +0000'):
    return f'''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title><![CDATA[{title}]]></title><description><![CDATA[{description}]]></description><dc:creator><![CDATA[{creator}]]></dc:creator><link>{link}</link><pubDate>{pub}</pubDate></item></channel></rss>'''.encode('utf-8')


def records(*files):
    targets = market_watch.target_names()
    teams = market_watch.team_table()
    cache = {}
    result = []
    for feed_name, name in files:
        result += market_watch.collect_items((FIXTURES / name).read_bytes(), feed_name, targets, teams, cache)
    return result


def stories(*files):
    return market_watch.group_stories(records(*files))


def saved():
    return stories(('MLBTR', 'mlbtr.xml'), ('ESPN', 'espn_mlb.xml'))


class MarketWatchTest(unittest.TestCase):
    def test_saved_feeds_pick_sato_and_taira(self):
        groups = saved()
        names = {rows[0]['name_en'] for rows in groups.values()}
        self.assertIn('Teruaki Sato', names)
        self.assertIn('Kaima Taira', names)
        sato = next(rows for rows in groups.values()
                    if rows[0]['name_en'] == 'Teruaki Sato' and rows[0]['kind'] == '合意')
        self.assertEqual({row['outlet'] for row in sato}, {'MLBTR', 'ESPN'})
        self.assertEqual(market_watch.stage_for(sato), 2)
        entry = market_watch.build_stage2(market_watch.story_key('Teruaki Sato', '合意', 'Chicago Cubs'), sato, NOW)
        self.assertEqual(entry['title'], '佐藤輝明 カブスと合意と米報道')
        self.assertIn('6年総額1億2000万ドル', entry['items'][0]['text'])
        self.assertIn('ESPN', entry['items'][0]['text'])
        self.assertEqual(set(entry['items'][0]['sources']), {
            'https://www.espn.com/mlb/story/_/id/50583163/sources-cubs-teruaki-sato-reach-6-year-120m-deal',
            'https://www.mlbtraderumors.com/2026/11/cubs-to-sign-teruaki-sato.html',
        })
        taira = next(rows for rows in groups.values()
                     if rows[0]['name_en'] == 'Kaima Taira' and rows[0]['kind'] == '合意')
        taira_entry = market_watch.build_stage2(market_watch.story_key('Kaima Taira', '合意', 'Toronto Blue Jays'), taira, NOW)
        self.assertEqual(taira_entry['title'], '平良海馬 ブルージェイズと合意と米報道')
        self.assertIn('5年総額8000万ドル', taira_entry['items'][0]['text'])

    def test_saved_feeds_ignore_unrelated_and_other_sato(self):
        groups = saved()
        self.assertFalse(any(row['name_en'] == 'Teruaki Sato' and row['kind'] != '合意'
                             for rows in groups.values() for row in rows))
        other = feed('Yankees Sign Yuki Sato', 'Japanese infielder Yuki Sato agreed to a one-year deal.',
                     'https://www.mlbtraderumors.com/2026/11/yankees-yuki-sato.html')
        self.assertEqual(market_watch.collect_items(other, 'MLBTR', market_watch.target_names(),
                                                    market_watch.team_table()), [])
        surname = feed('Blue Jays To Sign Japanese Slugger Sato',
                       'The Blue Jays agreed to a deal with Japanese slugger Sato.',
                       'https://www.mlbtraderumors.com/2026/11/jays-sato.html')
        self.assertEqual(market_watch.collect_items(surname, 'MLBTR', market_watch.target_names(),
                                                    market_watch.team_table()), [])

    def test_contract_reading(self):
        sato = market_watch.parse_contract('The Cubs have agreed to a six-year, $120MM deal with Teruaki Sato.')
        self.assertEqual((sato['years'], sato['value'], sato['text']), (6, '1億2000', '1億2000万ドル'))
        taira = market_watch.parse_contract('The Blue Jays agreed to a five-year, $80 million deal with Kaima Taira.')
        self.assertEqual((taira['years'], taira['value'], taira['text']), (5, '8000', '8000万ドル'))
        billion = market_watch.parse_contract('A six-year, $1.2 billion deal.')
        self.assertEqual((billion['years'], billion['text'], billion['unit']), (6, '12億ドル', ''))
        self.assertIsNone(market_watch.parse_contract('The 27-year-old Sato played third base.'))

    def test_macron_name(self):
        found = market_watch.find_targets('The Cubs agreed with Teruaki Satō.',
                                          {'Teruaki Sato': '佐藤輝明'})
        self.assertEqual(found, [('Teruaki Sato', '佐藤輝明')])
        kana = market_watch.find_targets('ダルビッシュ有が登板した。',
                                         {'Yu Darvish': 'ダルビッシュ有'})
        self.assertEqual(kana, [('Yu Darvish', 'ダルビッシュ有')])

    def test_official_is_not_negated(self):
        self.assertEqual(market_watch.classify('The Blue Jays announced the signing of Kaima Taira.'), '正式')
        self.assertNotEqual(market_watch.classify('The deal is not official yet.'), '正式')
        self.assertNotEqual(market_watch.classify("The signing hasn't been officially announced."), '正式')

    def test_stage_one_and_two(self):
        targets = market_watch.target_names()
        teams = market_watch.team_table()
        interest = feed('Blue Jays Interested In Kaima Taira',
                        'The Blue Jays are interested in Kaima Taira.',
                        'https://www.mlbtraderumors.com/2026/11/taira-interest.html')
        one = market_watch.group_stories(market_watch.collect_items(interest, 'MLBTR', targets, teams))
        self.assertEqual([market_watch.stage_for(rows) for rows in one.values()], [1])

        mlbtr = feed('Blue Jays To Sign Kaima Taira',
                     'The Blue Jays agreed to a five-year, $80MM deal with Kaima Taira.',
                     'https://www.mlbtraderumors.com/2026/11/blue-jays-to-sign-kaima-taira.html')
        espn = feed('Sources: Taira, Blue Jays agree to 5-year, $80M deal',
                    'Kaima Taira and the Blue Jays have agreed to a five-year, $80 million deal, sources told ESPN.',
                    'https://www.espn.com/mlb/story/_/id/1/taira')
        two = market_watch.group_stories(
            market_watch.collect_items(mlbtr, 'MLBTR', targets, teams)
            + market_watch.collect_items(espn, 'ESPN', targets, teams))
        self.assertEqual([market_watch.stage_for(rows) for rows in two.values()], [2])

        passan = feed('Sources: Blue Jays agree to deal with Kaima Taira',
                      'Kaima Taira and the Blue Jays agreed to a five-year, $80 million deal, sources told ESPN\'s Jeff Passan.',
                      'https://www.espn.com/mlb/story/_/id/2/taira')
        big = market_watch.group_stories(market_watch.collect_items(passan, 'ESPN', targets, teams))
        self.assertEqual([market_watch.stage_for(rows) for rows in big.values()], [1])

        official = feed('Blue Jays announce signing of Kaima Taira',
                        'The Blue Jays announced the signing of Kaima Taira.',
                        'https://www.mlbtraderumors.com/2026/11/taira-official.html')
        done = market_watch.group_stories(market_watch.collect_items(official, 'MLBTR', targets, teams))
        self.assertEqual([market_watch.stage_for(rows) for rows in done.values()], [2])
        done_key, done_rows = next(iter(done.items()))
        done_entry = market_watch.build_stage2(done_key, done_rows, NOW)
        self.assertEqual(done_entry['title'], '平良海馬 ブルージェイズが正式発表')
        self.assertEqual(done_entry['items'][0]['head'], 'ブルージェイズが正式発表')
        self.assertIn('ブルージェイズが正式に発表しました。', done_entry['items'][0]['text'])

    def test_source_rules(self):
        good = 'https://www.mlbtraderumors.com/2026/11/cubs-to-sign-teruaki-sato.html'
        self.assertEqual(market_watch.source_ok(good), good)
        for url in ('http://www.mlbtraderumors.com/2026/11/x.html',
                    'https://www.reddit.com/r/baseball/comments/x',
                    'https://news.yahoo.co.jp/articles/x?comments=1'):
            with self.assertRaises(ValueError):
                market_watch.source_ok(url)

    def test_stage2_hides_same_player_from_stage1_summary(self):
        interest = feed('Blue Jays Interested In Kaima Taira',
                        'The Blue Jays are interested in Kaima Taira.',
                        'https://www.mlbtraderumors.com/2026/11/taira-interest.html')
        agree = feed('Blue Jays To Sign Kaima Taira',
                     'The Blue Jays agreed to a five-year, $80MM deal with Kaima Taira, reports Jeff Passan of ESPN.',
                     'https://www.mlbtraderumors.com/2026/11/blue-jays-to-sign-kaima-taira.html')
        state = {'version': 1, 'stories': {}}
        with patch.object(market_watch, 'read_source', side_effect=[interest, agree]):
            result = market_watch.run([('MLBTR', 'interest'), ('MLBTR', 'agree')], state, NOW)
        self.assertEqual(result['stage2'], {})
        self.assertEqual(len(result['stage1']), 2)
        espn = feed('Blue Jays Agree With Kaima Taira',
                    'Kaima Taira and the Blue Jays agreed to a five-year, $80 million deal.',
                    'https://www.espn.com/mlb/story/_/id/2/taira')
        with patch.object(market_watch, 'read_source', side_effect=[interest, agree, espn]):
            result = market_watch.run([('MLBTR', 'interest'), ('MLBTR', 'agree'), ('ESPN', 'espn')], state, NOW)
        self.assertEqual(result['all_stage1'], [])
        self.assertEqual(list(result['stage2']), ['kaima-taira-toronto-blue-jays-agreement'])
        self.assertEqual(state['stories']['kaima-taira-toronto-blue-jays-interest']['stage'], 1)

    def test_state_prevents_stage1_duplicate(self):
        interest = feed('Blue Jays Interested In Kaima Taira',
                        'The Blue Jays are interested in Kaima Taira.',
                        'https://www.mlbtraderumors.com/2026/11/taira-interest.html')
        state = {'version': 1, 'stories': {}}
        with patch.object(market_watch, 'read_source', side_effect=[interest, interest]):
            first = market_watch.run([('MLBTR', 'interest')], state, NOW)
            second = market_watch.run([('MLBTR', 'interest')], state, NOW + timedelta(minutes=15))
        self.assertEqual(len(first['stage1']), 1)
        self.assertEqual(second['stage1'], [])
        self.assertEqual(len(second['all_stage1']), 1)

    def test_state_prevents_duplicate(self):
        state = {'version': 1, 'stories': {}}
        first = market_watch.run([('MLBTR', str(FIXTURES / 'mlbtr.xml')),
                                  ('ESPN', str(FIXTURES / 'espn_mlb.xml'))], state, NOW)
        self.assertEqual(len(first['stage2']), 2)
        self.assertIn('teruaki-sato-chicago-cubs-agreement', first['stage2'])
        self.assertIn('kaima-taira-toronto-blue-jays-agreement', first['stage2'])
        second = market_watch.run([('MLBTR', str(FIXTURES / 'mlbtr.xml')),
                                   ('ESPN', str(FIXTURES / 'espn_mlb.xml'))],
                                  state, NOW + timedelta(minutes=15))
        self.assertEqual(second['stage2'], {})
        self.assertEqual(second['stage1'], [])


    def test_one_feed_down_is_not_a_failure(self):
        empty = feed('Unrelated Story', 'Nothing about targets.', 'https://www.mlbtraderumors.com/2026/11/other.html')
        with patch.object(market_watch, 'read_source', side_effect=[empty, OSError('HTTP 202')]),                 patch.object(market_watch, 'load_state', return_value={'version': 1, 'stories': {}}),                 patch.object(market_watch, 'save_state'), patch.object(market_watch, 'write_outputs'):
            self.assertEqual(market_watch.main(['--feed', 'MLBTR=a', '--feed', 'ESPN=b']), 0)
        with patch.object(market_watch, 'read_source', side_effect=[OSError('down'), OSError('HTTP 202')]),                 patch.object(market_watch, 'load_state', return_value={'version': 1, 'stories': {}}),                 patch.object(market_watch, 'save_state'), patch.object(market_watch, 'write_outputs'):
            self.assertEqual(market_watch.main(['--feed', 'MLBTR=a', '--feed', 'ESPN=b']), 1)

if __name__ == '__main__':
    unittest.main(argv=[__file__])
