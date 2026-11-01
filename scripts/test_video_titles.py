"""NPBと重なる単独球団名の公開題とSNSへの回帰検査。"""
from datetime import datetime, timezone
import sys
import unittest
from unittest.mock import patch

import asset_sns
import buffer_daily
import post_tiktok
import upload_youtube as uy
import video_titles as vt


class VideoTitlesTest(unittest.TestCase):
    def test_npb_overlap_is_covered(self):
        overlap = set(vt.press_names.ne.MLB_TEAM_NAME_JP.values()) & vt.NPB_NICKNAMES
        self.assertEqual(overlap, set(vt.TEAM_CITIES))
        self.assertEqual(overlap, {'タイガース', 'ジャイアンツ'})

    def test_all_teams_in_asset_kinds(self):
        for name in vt.press_names.ne.MLB_TEAM_NAME_JP.values():
            expected = vt.TEAM_CITIES.get(name, '')
            expected = expected + '・' + name if expected else name
            for key, tail in (('season_team_116', '2026年シーズンまとめ'),
                              ('team_det', '球団の歴史'),
                              ('season_game_123', '逆転勝利の理由')):
                with self.subTest(name=name, kind=key):
                    title = f'【MLB】{name}｜{tail} #Shorts'
                    spec = {'label': name, 'title': title, 'intro': name + 'の記録。', 'items': []}
                    with patch.object(uy, 'generated_topic', return_value=spec):
                        meta = uy.build_asset_metadata(key)['snippet']
                    self.assertEqual(meta['title'], title.replace(name, expected))
                    self.assertEqual(meta['description'].splitlines()[0], expected + 'の記録。')
                    self.assertEqual(spec['intro'], name + 'の記録。')

    def test_team_topic_without_prebuilt_title(self):
        for name in ('タイガース', 'ジャイアンツ', 'ドジャース'):
            spec = {'label': name, 'where': '本拠地', 'hook': '球団の歴史', 'items': []}
            with patch.object(uy, 'generated_topic', return_value=spec):
                meta = uy.build_asset_metadata('team_test')['snippet']
            expected = vt.team_city_text(name)
            self.assertEqual(meta['title'], f'【MLB】{expected}｜球団の歴史 #Shorts')
            self.assertTrue(meta['description'].startswith(expected + '（'))

    def test_cards_and_full_names(self):
        for card in ('タイガース vs ロイヤルズ', 'ジャイアンツvs.タイガース',
                     'タイガース 対 ジャイアンツ', 'ジャイアンツ×タイガース',
                     'ジャイアンツ vs デトロイト・タイガース',
                     'タイガース vs カンザスシティ・ロイヤルズ',
                     'タイガース vs KC', 'SF vs タイガース',
                     'デトロイト・タイガース vs ジャイアンツ'):
            self.assertEqual(vt.team_city_text(card), card)
        for full in ('デトロイト・タイガース', 'サンフランシスコ・ジャイアンツ',
                     'デトロイトタイガース', '阪神タイガース', '読売ジャイアンツ'):
            self.assertEqual(vt.team_city_text(full), full)
        self.assertEqual(vt.team_city_text('タイガース vs ロイヤルズ｜タイガースの逆転'),
                         'タイガース vs ロイヤルズ｜デトロイト・タイガースの逆転')
        text = vt.team_city_text('ジャイアンツとタイガース')
        self.assertEqual(vt.team_city_text(text), text)

    def test_existing_shortening_rules(self):
        self.assertEqual(vt.public_title('【MLB】大谷翔平のタイガース'),
                         '【MLB】大谷デトロイト・タイガース')
        title = 'タイガース｜ホワイトソックス｜' + '補足' * 45
        expanded = vt.team_city_text(title)
        self.assertEqual(vt.public_title(title), vt.press_names.press_title(expanded)[:100])
        soccer = 'マンチェスター・シティ｜' + '補足' * 60
        self.assertEqual(vt.public_title(soccer, soccer=True),
                         vt.club_display_names.youtube_title(vt.press_names.press_title(soccer)))

    def test_repeated_nickname_gets_city_once(self):
        for name, city in vt.TEAM_CITIES.items():
            title = f'【MLB】{name}の殿堂入り選手｜{name}から殿堂入りした3人'
            expected = title.replace(name, city + '・' + name, 1)
            self.assertEqual(vt.team_city_text(title), expected)
            self.assertEqual(vt.team_city_text(expected), expected)
            self.assertEqual(vt.public_title(title), expected)
        title = 'タイガースとジャイアンツ｜タイガースとジャイアンツ'
        self.assertEqual(vt.team_city_text(title),
                         'デトロイト・タイガースとサンフランシスコ・ジャイアンツ｜タイガースとジャイアンツ')
        title = '阪神タイガースとタイガース｜タイガース'
        self.assertEqual(vt.team_city_text(title),
                         '阪神タイガースとデトロイト・タイガース｜タイガース')
        title = 'タイガース vs KC｜タイガースの記録｜タイガース'
        self.assertEqual(vt.team_city_text(title),
                         'タイガース vs KC｜デトロイト・タイガースの記録｜タイガース')

    def test_description_only_first_line(self):
        self.assertEqual(vt.description_head('タイガースの記録\nタイガースの札'),
                         'デトロイト・タイガースの記録\nタイガースの札')

    def test_regular_metadata_uses_common_title(self):
        for name, city in vt.TEAM_CITIES.items():
            with patch.object(uy, '_postseason_data', return_value={
                    'phase': 'regular', 'changes': [{'text': name + 'が首位'}]}):
                meta = uy.build_metadata('build/missing-games.json', '10月23日',
                                         'morning', morning_mode='postseason')['snippet']
            self.assertIn(city + '・' + name, meta['title'])

    def test_sns_and_external_card(self):
        for name, city in vt.TEAM_CITIES.items():
            record = {'title': f'【MLB】{name}｜2026年シーズンまとめ #Shorts', 'video_id': 'test'}
            for service in ('twitter', 'instagram'):
                text = buffer_daily.caption(service, '2026-10-23', record, 'asset')
                self.assertIn(city + '・' + name, text)
            self.assertIn(city + '・' + name, post_tiktok.caption(record['title']))
            card = asset_sns.bsky_record('紹介', record['title'], 'test', datetime.now(timezone.utc))
            self.assertIn(city + '・' + name, card['embed']['external']['title'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
