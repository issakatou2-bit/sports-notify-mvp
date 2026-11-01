"""保存材料だけで短さ・順位・未知の数字・#168の2行を確認する。"""
import copy
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import reddit_reaction as r

FIX=Path(__file__).resolve().parent/'fixtures/reddit-rss'


def read(name):return json.loads((FIX/name).read_text(encoding='utf8'))


def preview():
    return r.program(dict(voices=[],updated_at='2026-10-14T06:00:00Z'),[],read('preview-source.json'),
                     read('youtube-preview.json'),read('youtube-translations.json'))


class ReactionTests(unittest.TestCase):
    def test_three_short_full_translations_in_observed_order(self):
        n=preview();r.validate(n)
        rows=[s for s in n['segments'] if s['kind']=='fan']
        self.assertEqual([s['meta']['likes'] for s in rows],[693,660,232])
        self.assertEqual([s['meta']['replies'] for s in rows],[29,72,10])
        self.assertTrue(all(s['meta']['quote']==s['meta']['original'] for s in rows))
        self.assertTrue(all(len(s['meta']['translation'])<=r.MAX_JA for s in rows))
        self.assertTrue(all(s['meta']['platform']=='YouTube' for s in rows))

    def test_old_reply_is_not_called_most_popular(self):
        reply=next(s for s in preview()['segments'] if s['kind']=='fan_reply')
        self.assertIsNone(reply['meta']['likes'])
        self.assertIn('順位不明',reply['meta']['heading'])
        self.assertIsNone(reply['meta']['at'])
        self.assertIn('保存なし',reply['meta']['display_time'])

    def test_observed_reply_likes_choose_largest(self):
        rows=[s for s in preview()['segments'] if s['kind']=='fan']
        rows[0]['meta']['reply_candidates']=[dict(original='Great game tonight',ja='今夜はいい試合だった。'),dict(original='What a comeback',ja='見事な逆転だ！')]
        rows[0]['meta']['reply_details']=[dict(original='Great game tonight',like_count=3),dict(original='What a comeback',like_count=12)]
        reply=r.select_reply(rows)
        self.assertEqual(reply['meta']['original'],'What a comeback');self.assertEqual(reply['meta']['likes'],12)

    def test_long_or_named_or_excerpt_is_rejected(self):
        self.assertFalse(r.short_translation('full original','あ'*40))
        self.assertFalse(r.short_translation('@someone hello','こんにちは'))
        n=preview();n['segments'][1]['meta']['quote']='shortened'
        with self.assertRaises(ValueError):r.validate(n)

    def test_more_than_three_and_wrong_source_fail(self):
        n=preview();n['segments'].insert(1,copy.deepcopy(n['segments'][1]))
        with self.assertRaises(ValueError):r.validate(n)
        with self.assertRaises(ValueError):r.youtube_rows(dict(source='unverified',voices=[]),[])

    def test_reddit_missing_numbers_are_not_zero(self):
        self.assertIsNone(r.count(None));self.assertIsNone(r.count(True))
        self.assertEqual(r.count(0),0)

    def test_existing_youtube_receiver_preserves_reply_likes(self):
        import local_voices
        payload={'items':[{'snippet':{'totalReplyCount':8,'topLevelComment':{'snippet':{
            'textOriginal':'Great baseball game tonight','likeCount':42,'publishedAt':'2026-10-14T01:00:00Z'}}},
            'replies':{'comments':[{'snippet':{'textOriginal':'What a comeback','likeCount':12}}]}}]}
        response=Mock();response.status_code=200;response.json.return_value=payload
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'buzz.json';path.write_text(json.dumps({'videos':[{'video_id':'fixture'}]}),encoding='utf8')
            with patch.dict(os.environ,{'YOUTUBE_API_KEY':'test-placeholder'}),patch('requests.get',return_value=response):
                rows=local_voices.fetch_youtube_comments(str(path))
        self.assertEqual(rows[0]['like_count'],42);self.assertEqual(rows[0]['reply_count'],8)
        self.assertEqual(rows[0]['reply_details'][0]['like_count'],12)
        self.assertNotIn('author',rows[0]['reply_details'][0])

    def test_reply_translation_order_changes_only_when_opted_in(self):
        import local_voices
        payload={'items':[{'snippet':{'totalReplyCount':2,'topLevelComment':{'snippet':{
            'textOriginal':'Great baseball game tonight','likeCount':42}}},
            'replies':{'comments':[{'snippet':{'textOriginal':'First short reply','likeCount':2}},
                                   {'snippet':{'textOriginal':'Second short reply','likeCount':12}}]}}]}
        response=Mock();response.status_code=200;response.json.return_value=payload
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'buzz.json';path.write_text(json.dumps({'videos':[{'video_id':'fixture'}]}),encoding='utf8')
            for flag,first in (('','First short reply'),('on','Second short reply')):
                with patch.dict(os.environ,{'YOUTUBE_API_KEY':'test-placeholder','COLLESPO_REDDIT':flag}),patch('requests.get',return_value=response):
                    rows=local_voices.fetch_youtube_comments(str(path))
                self.assertEqual(rows[0]['reply_texts'][0],first)

    def test_both_styles_two_rows_and_default_restored(self):
        import player_story_render as render
        n=preview();fans=[s for s in n['segments'] if s['kind'] in ('fan','fan_reply')]
        for style in ('','glass','slant'):
            with patch.dict(os.environ,{'COLLESPO_BUBBLE':style}):
                for seg in fans:
                    render.r3.set_caption(seg['text'],4,20,speaker=2)
                    render.r3.set_program_clock(1.4)
                    im=render.frame(1.4,seg,n)
                    self.assertEqual(im.info['bubble_style']['style'],style or 'glass')
                    self.assertLessEqual(im.info['duo_caption']['rows'],2)
                    render.verify_frame(im)
                self.assertEqual(os.environ['COLLESPO_BUBBLE'],style)
        render.r3.set_program_clock(None)

    def test_fan_expression_still_fits_both_styles(self):
        with patch.dict(os.environ,{'COLLESPO_EXPR':'fan'}):
            self.test_both_styles_two_rows_and_default_restored()


if __name__=='__main__':unittest.main(argv=['test_reddit_reaction'])
