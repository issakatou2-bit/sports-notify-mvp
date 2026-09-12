import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import content_hashtags as ht
import buffer_daily
import post_common
import upload_youtube


class HashtagTests(unittest.TestCase):
    def test_platform_limits_and_actual_player(self):
        text = 'MLB 岡本和真2安打、鈴木誠也も打点。ポストシーズンへ'
        for platform, limit in ht.LIMITS.items():
            tags = ht.select(text, platform)
            self.assertLessEqual(len(tags), limit)
            self.assertEqual(tags[0], 'MLB')
            self.assertNotIn('大谷翔平', tags)
            if limit > 1:
                self.assertIn('岡本和真', tags)

    def test_soccer_is_not_baseball_and_punctuation_is_safe(self):
        tags = ht.select('【サッカー】ラ・リーガ。レアル・ソシエダを見る', 'instagram',
                         subjects=['レアル・ソシエダ'], leagues=['PD'])
        self.assertIn('ラリーガ', tags)
        self.assertIn('レアルソシエダ', tags)
        self.assertNotIn('MLB', tags)
        self.assertNotIn('プレミアリーグ', tags)
        self.assertTrue(all(re.fullmatch(r'\w+', t) for t in tags))

    def test_nonmentioned_hint_and_unrelated_roster_never_added(self):
        tags = ht.select('MLB ドジャース8連勝', 'tiktok', subjects=['大谷翔平', 'バズれ'])
        self.assertNotIn('大谷翔平', tags)
        self.assertNotIn('バズれ', tags)

    def test_format_tag_only_on_youtube_shorts(self):
        for platform in ht.LIMITS:
            tags = ht.select('MLB ドジャース', platform, shorts=True)
            self.assertEqual('Shorts' in tags, platform == 'youtube')

    def test_bluesky_dropped_game_does_not_leave_its_tags(self):
        games = [dict(league='MLB', abbr_matchup='LAD vs MIA', notification_hook='ドジャース8連勝',
                      jp_players=['大谷翔平'], start_time_jst='09/13 05:10'),
                 dict(league='MLB', abbr_matchup='CWS vs HOU', notification_hook='村上宗隆'+'の注目点'*40,
                      start_time_jst='09/13 07:10')]
        body, tags, _ = post_common.build_post(games, 180, news_path='missing-file')
        self.assertNotIn('村上宗隆', body)
        self.assertNotIn('村上宗隆', tags)
        self.assertNotIn('大谷翔平', tags)

    def test_x_drops_optional_tags_before_rejecting_facts(self):
        # Find a boundary at which two tags would overflow but the text fits.
        checked = False
        for n in range(1, 85):
            record = {'title':'ドジャース'+'連勝'*n, 'video_id':'abcdefghijk'}
            try:
                caption = buffer_daily.caption('twitter', '2026-09-12', record)
            except ValueError:
                continue
            self.assertLessEqual(buffer_daily.x_weight(caption), 280)
            if '#ドジャース' not in caption:
                self.assertIn(record['title'], caption)
                checked = True
                break
        self.assertTrue(checked)

    def test_morning_metadata_does_not_borrow_tomorrows_players(self):
        with tempfile.TemporaryDirectory() as tmp:
            games = Path(tmp)/'games.json'
            games.write_text(json.dumps({'games':[{'is_notable':True, 'league':'MLB',
                'home_team_name':'ドジャース','away_team_name':'マーリンズ',
                'jp_players':['大谷翔平'],'start_time_jst':'09/13 05:10'}]}),encoding='utf-8')
            with patch.object(upload_youtube, '_postseason_data', return_value={}):
                data = upload_youtube.build_metadata(str(games),'9/12', kind='morning',
                        morning_mode='postseason', morning_players=[{'name':'大谷翔平'}])['snippet']
            self.assertNotIn('大谷翔平', data['tags'])
            self.assertNotIn('マーリンズ', data['description'])


if __name__ == '__main__':
    unittest.main(argv=['test_content_hashtags'])
