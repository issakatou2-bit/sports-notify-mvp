"""RSSから採用した原稿の出典まで。リンク先へ通信せず偽物だけで照合。"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import article_sources as sources
import generate_morning_short as morning
import local_reporters as reporters
import upload_youtube as upload


def head(title,url):
    return {'title':'Original '+title,'jp':title,'source':'Example Sports','url':url}


class ArticleSources(unittest.TestCase):
    def test_rss_url_entities_and_cdata_stay_with_the_same_title(self):
        xml='''<rss><channel><item><title><![CDATA[Ohtani RBI double - Sports Desk]]></title>
        <source url="https://publisher.invalid">Sports Desk</source><pubDate>date</pubDate>
        <link>https://news.google.com/rss/articles/test?hl=en&amp;gl=US</link></item>
        <item><title>No link</title></item></channel></rss>'''
        result=reporters.parse_headlines(xml,'Ohtani')
        self.assertEqual(result[0]['title'],'Ohtani RBI double')
        self.assertEqual(result[0]['url'],'https://news.google.com/rss/articles/test?hl=en&gl=US')
        self.assertEqual(result[0]['source'],'Sports Desk')
        self.assertEqual(result[1]['url'],'')

    def test_namespaced_feed_and_fetch_path(self):
        xml='<rss xmlns="urn:rss"><channel><item><title>One</title><link>https://example.invalid/one</link></item></channel></rss>'
        response=NS(text=xml,raise_for_status=lambda:None)
        with patch.object(reporters.requests,'get',return_value=response):out=reporters.fetch_headlines('fixture')
        self.assertEqual(out[0]['url'],'https://example.invalid/one')

    def test_unsafe_missing_or_credential_url_is_not_invented(self):
        for url in ('javascript:alert(1)','file:///tmp/private','https://user:secret@example.invalid','https://example.invalid/\nnext','',None,'https://'):
            self.assertEqual(sources.safe_url(url),'')
        self.assertEqual(sources.safe_url('https://example.invalid/article'),'https://example.invalid/article')

    def test_narration_keeps_only_the_used_headline_sources(self):
        heads=[head('大谷翔平が適時二塁打を放った','https://example.invalid/intro'),
               head('長い見出し'*100,'https://example.invalid/not-used'),
               head('鈴木誠也が本塁打を放った','https://example.invalid/body')]
        data={'date':'2026-10-11','date_jst':'2026-10-12','players':[],
              'reporters':{'headlines':heads,'posts':[],'headline_pool':heads}}
        with contextlib.redirect_stdout(io.StringIO()):narration=morning.build_narration(data,mode='press')
        refs='\n'.join(sources.references(narration))
        self.assertIn('/intro',refs);self.assertIn('/body',refs)
        self.assertNotIn('/not-used',refs)
        self.assertEqual(narration['segments'][0]['meta']['source_headlines'][0]['url'],heads[0]['url'])

    def test_reference_duplicates_budget_and_old_narration(self):
        entry=head('見出し','https://example.invalid/same')
        narration={'segments':[{'meta':{'source_headlines':[entry,entry,head('long','https://example.invalid/'+'x'*2000)]}}]}
        with contextlib.redirect_stdout(io.StringIO()):lines=sources.references(narration)
        self.assertEqual(lines.count(entry['url']),1)
        self.assertLessEqual(len('\n'.join(lines)),1520)
        self.assertFalse(sources.references({'segments':[{'kind':'intro','meta':{'used_headline':0}}]}))

    def test_press_metadata_uses_saved_narration_links_without_loading_latest_rss(self):
        with tempfile.TemporaryDirectory() as td:
            games=pathlib.Path(td)/'games.json';narration=pathlib.Path(td)/'narration.json'
            games.write_text('{"games":[]}',encoding='utf-8')
            narration.write_text(json.dumps({'segments':[{'kind':'headlines','meta':{'source_headlines':[
                head('保存した見出し','https://example.invalid/saved')]}}]},ensure_ascii=False),encoding='utf-8')
            with patch.object(upload,'top_headline',return_value='保存した見出し'):
                body=upload.build_metadata(str(games),'10月12日',kind='morning',morning_mode='press',narration_path=str(narration))
                other=upload.build_metadata(str(games),'10月12日',kind='morning',morning_mode='players',narration_path=str(narration))
        self.assertIn('https://example.invalid/saved',body['snippet']['description'])
        self.assertIn('Example Sports',body['snippet']['description'])
        self.assertNotIn('https://example.invalid/saved',other['snippet']['description'])


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
