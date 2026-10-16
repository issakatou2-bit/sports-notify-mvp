"""本物の保存見出し、日本語音声/英語字幕、禁止取得元、#160の訳を通信なしで検査。"""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import urllib.parse
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import japan_reacts as jr


def response(text): return NS(content=[NS(type='text',text=text)],stop_reason='end_turn',usage=NS(input_tokens=1,output_tokens=1))


class Tests(unittest.TestCase):
    def setUp(self): self.data=jr.read(jr.ROOT/'scripts/fixtures/japan-reacts/sponichi-saved.json')

    def test_oct16_logged_headlines_are_accepted_through_both_guards(self):
        rows=jr.read(jr.ROOT/'scripts/fixtures/japan-reacts/numbers-20261016.json')
        for i,row in enumerate(rows):
            with self.subTest(original=row['original']):
                client=NS(messages=Mock())
                client.messages.create.side_effect=[response(json.dumps([row['english']])),response('{"faithful":true,"actors":true,"no_abuse":true}')]
                source=dict(kind='headline',source='サンスポ',url='https://www.sanspo.com/article/fixture',original=row['original'])
                report=jr.material_report([source])
                with patch.object(jr.english_captions.token_log,'allowed',return_value=True),patch.object(jr.english_captions.token_log,'record'),patch('sys.stdout',new_callable=io.StringIO):
                    data=jr.from_rows(dict(sport='MLB' if i<4 else 'PL',name_en='Shohei Ohtani' if i<4 else 'Daichi Kamada'),[source],client,report=report)
                self.assertEqual((report['accepted'],report['rejected']),(1,0),report)
                self.assertEqual(data['segments'][0]['caption_en'],row['english'])
                jr.validate(data)

    def test_headline_word_limit_does_not_relax_other_sources(self):
        original='投球を高く評価した。'
        for kind,count,want in [('headline',60,''),('headline',61,'format'),('youtube',41,'format'),('reporter',41,'format')]:
            english=' '.join(['Pitching']*count)
            item=dict(kind=kind,original=original,english=english)
            item['review']=dict(faithful=True,actors=True,no_abuse=True,sha256=jr.digest(item))
            with self.subTest(kind=kind,words=count):self.assertEqual(jr.check_reason(item),want)

    def test_real_saved_source_and_credit(self):
        jr.validate(self.data)
        meta=jr.metadata(self.data)
        self.assertIn('VOICEVOX:四国めたん',meta['description'])
        self.assertEqual(meta['audio_language'],'ja')
        self.assertIn('2026-05-14',meta['title'])
        self.assertTrue(all(s['kind']=='headline' for s in self.data['sources']))

    def test_tampering_numbers_backstage_and_exclusions(self):
        for kind in ('yahoo_comments','5ch','personal_sns'):
            d=copy.deepcopy(self.data); d['sources'][0]['kind']=kind
            with self.assertRaises(ValueError): jr.validate(d)
        d=copy.deepcopy(self.data); d['segments'][1]['caption_en']+=' 99 goals.'
        with self.assertRaises(ValueError): jr.validate(d)
        c=dict(original='日本の反応を伝えます。',english='This is not in the provided data.')
        c['review']=dict(faithful=True,actors=True,no_abuse=True,sha256=jr.digest(c))
        self.assertFalse(jr.checked(c))

    def test_official_video_and_anonymous_comment(self):
        video={'items':[{'snippet':{'channelId':'official','title':'MLB 大谷翔平 ハイライト'}}]}
        comment={'id':'comment','snippet':{'textDisplay':'大谷の投球は見ていて楽しい。','publishedAt':'2026-10-13T00:00:00Z','authorDisplayName':'DO NOT STORE'}}
        get=Mock(side_effect=[video,{'items':[{'snippet':{'topLevelComment':comment}}]}])
        out=jr.fetch_comments('abcdefghijk',dict(channel_id='official',name='SPOTV NOW',sport='MLB'),dict(name_jp='大谷翔平',name_en='Shohei Ohtani'),get=get)
        self.assertEqual(len(out),1); self.assertNotIn('DO NOT STORE',str(out))
        get=Mock(return_value=dict(items=[dict(snippet=dict(channelId='other',title='MLB ハイライト'))]))
        with self.assertRaises(ValueError): jr.fetch_comments('abcdefghijk',dict(channel_id='official',name='SPOTV',sport='MLB'),dict(name_jp='大谷翔平'),get=get)

    def test_reporter_requires_official_registry(self):
        with self.assertRaises(ValueError): jr.collect_posts(dict(reporters=[dict(role='personal')]),dict(name_jp='大谷翔平'))

    @patch('token_log.allowed',return_value=True)
    @patch('token_log.record')
    def test_uses_160_translation_guard_and_review(self,record,allowed):
        import json
        s=self.data['segments'][0]; client=NS(messages=Mock())
        client.messages.create.side_effect=[response(json.dumps([s['caption_en']])),response('{"faithful":true,"actors":true,"no_abuse":true}')]
        out=jr.translate(client,dict(original=s['text']))
        self.assertTrue(jr.checked(out)); self.assertEqual(record.call_count,2)
        self.assertIn(jr.guard.rules()[0],client.messages.create.call_args_list[0].kwargs['messages'][-1]['content'])

    def test_english_frames_with_japanese_voice(self):
        import short_saved_render as sr
        sr.setup()
        import review_render_v3 as r3
        import v3_rules as rules
        for s in self.data['segments']:
            r3.set_caption(s['caption_en'],10,40,speaker=2,duo=False)
            im=jr.frame(self.data,1.8,s)
            self.assertFalse(rules.check_layout(im)+rules.check_spacing(im))

    def test_cue_alignment_with_japanese_commas(self):
        manifest=[dict(index=i,duration=6) for i in range(len(self.data['segments']))]
        jp,en=jr.aligned_cues(self.data,manifest)
        self.assertEqual(len(jp),len(self.data['segments']))
        self.assertEqual([(a,b) for a,b,_ in jp],[(a,b) for a,b,_ in en])
        self.assertEqual(en[-1][1],30)

    def test_checked_uses_shared_numbers_after_review(self):
        for ja,en in (('初めて1点を決めた。','Scored a goal for the first time.'),
                      ('最初の本塁打を打った。','Hit his first homer.'),
                      ('1安打を放った。','Recorded one hit.')):
            item=jr.approved_segment('voice',ja,en)
            self.assertTrue(jr.checked(dict(original=ja,english=en,review=item['review'])))
        item=jr.approved_segment('voice','2点を決めた。','Scored a goal.')
        self.assertEqual(jr.check_reason(dict(original=item['text'],english=item['caption_en'],review=item['review'])),'numbers')

    def test_rejection_counts_and_log_privacy(self):
        rows=[dict(kind=kind,source='PRIVATE SOURCE',original='非公開の材料です。')
              for kind in ('headline','headline','youtube','reporter','headline','headline')]
        rows[-1]['original']=' '
        report=jr.material_report(rows)
        errors=[ValueError('translation_numbers'),ValueError('translation_names'),
                ValueError('translation_backstage'),ValueError('PRIVATE ERROR BODY'),
                ValueError('translation_empty')]
        with patch.object(jr,'translate',side_effect=errors), patch('sys.stdout',new_callable=io.StringIO) as log:
            self.assertIsNone(jr.from_rows(dict(sport='MLB',name_en='Shohei Ohtani'),rows,Mock(),report=report))
        self.assertEqual((report['collected'],report['accepted'],report['rejected']),(6,0,6))
        self.assertEqual(report['reasons'],dict(numbers=1,names=1,backstage=1,other=1,empty=2))
        self.assertEqual(report['sources']['headline']['rejected'],4)
        self.assertIn('材料なし（理由の内訳:',log.getvalue())
        for secret in ('PRIVATE','非公開の材料'):
            self.assertNotIn(secret,log.getvalue()+json.dumps(report,ensure_ascii=False))

    def test_main_no_material_exits_without_video(self):
        for rows in ([],[dict(kind='headline',source='PRIVATE',original='非公開の材料です。')]):
            with self.subTest(collected=len(rows)), tempfile.TemporaryDirectory() as td, \
                 patch.dict(os.environ,dict(COLLESPO_JAPAN_REACTS='on',ANTHROPIC_API_KEY='test')), \
                 patch('sys.argv',['japan_reacts','--out',td]), \
                 patch.object(jr,'collect',return_value=(rows,['headlines: PRIVATE BODY'])), \
                 patch.object(jr,'translate',side_effect=ValueError('translation_numbers')), \
                 patch.object(jr,'save') as save, patch('sys.stdout',new_callable=io.StringIO) as log:
                self.assertIsNone(jr.main())
                save.assert_not_called()
                report=json.loads((Path(td)/'fetch-report.json').read_text(encoding='utf8'))
                self.assertEqual(report['accepted'],0)
                self.assertEqual(report['rejected'],len(rows))
                self.assertIn('材料なし',log.getvalue())
                self.assertNotIn('PRIVATE',log.getvalue()+json.dumps(report))
                self.assertFalse((Path(td)/'preview.mp4').exists())

    def test_mixed_rows_keep_accepted_material(self):
        row=dict(kind='headline',source='スポニチ',original='初めて1点を決めた。',url='https://example.org/source')
        text=f"{row['source']}では、{row['original']}。"
        caption='According to Sponichi, he scored a goal for the first time.'
        approved=jr.approved_segment('voice',text,caption)
        translated=dict(english=caption,review=approved['review'])
        report=jr.material_report([row,row])
        with patch.object(jr,'translate',side_effect=[ValueError('translation_names'),translated]), \
             patch('sys.stdout',new_callable=io.StringIO):
            data=jr.from_rows(dict(sport='MLB',name_en='Shohei Ohtani'),[row,row],Mock(),report=report)
        self.assertEqual((report['accepted'],report['rejected']),(1,1))
        self.assertEqual(len(data['sources']),1)
        jr.validate(data)

    def test_public_headline_diagnostics_exclude_comments(self):
        original='大谷翔平は21日に1号'
        english='Shohei Ohtani goes deep in September'
        for kind in ('headline','youtube','reporter','reddit'):
            item=dict(kind=kind,source='スポニチ',url='https://www.sponichi.co.jp/baseball/news/example.html',
                      original='スポニチでは、'+original+'。',headline_original=original)
            with self.subTest(kind=kind),patch.object(jr.guard,'create',return_value=response(json.dumps([english]))), \
                 patch('token_log.allowed',return_value=True),patch('token_log.record'), \
                 patch('sys.stdout',new_callable=io.StringIO) as log:
                with self.assertRaisesRegex(ValueError,'^translation_numbers$') as error:
                    jr.translate(Mock(),item)
            self.assertNotIn(original,str(error.exception))
            if kind=='headline':
                detail=json.loads(next(line.split(': ',1)[1] for line in log.getvalue().splitlines() if '公開見出し' in line))
                self.assertEqual((detail['original'],detail['english']),(original,english))
                self.assertEqual((detail['missing'],detail['extra']),(['1','21'],['9']))
            else:
                self.assertNotIn(original,log.getvalue())
                self.assertNotIn(english,log.getvalue())
        for url in ('https://evil.example/a','https://www.sponichi.co.jp.evil.example/a','https://[broken'):
            self.assertFalse(jr.public_headline(dict(item,kind='headline',url=url)))

    def test_headlines_use_verified_media_without_sns_registry(self):
        import xml.etree.ElementTree as ET
        feed=ET.Element('rss');channel=ET.SubElement(feed,'channel')
        inputs=[('Full-Count',f'大谷翔平の投球への評価{i}') for i in range(7)]
        inputs += [inputs[0],('サッカーキング','大谷翔平の話題'),('個人ブログ','大谷翔平の話題'),
                   ('Yahooコメント','大谷翔平の話題'),('5ch','大谷翔平の話題')]
        for i,(source,title) in enumerate(inputs):
            row=ET.SubElement(channel,'item')
            for key,value in dict(title=title+' - '+source,source=source,
                                  link=f'https://news.google.com/rss/articles/item{i}',pubDate='Fri, 16 Oct 2026 00:00:00 GMT').items():
                ET.SubElement(row,key).text=value
        config=jr.read(jr.ROOT/'data/japan_reacts_sources.json')
        with patch('requests.get',return_value=NS(text=ET.tostring(feed,encoding='unicode'),raise_for_status=Mock())) as get:
            rows=jr.collect_headlines(config,dict(sport='MLB',name_jp='大谷翔平',name_en='Shohei Ohtani'))
        self.assertEqual(len(rows),7)
        self.assertTrue(all(row['source']=='Full-Count' for row in rows))
        query=urllib.parse.parse_qs(urllib.parse.urlsplit(get.call_args.args[0]).query)['q'][0]
        self.assertEqual(query,'大谷翔平 when:2d')
        self.assertEqual(config['reporters'],[])
        with patch('topic_hub.enabled',return_value=False),patch.object(jr,'collect_youtube',return_value=([],[])), \
             patch.object(jr,'collect_posts',return_value=[]),patch.object(jr,'collect_headlines',return_value=rows):
            collected,reasons=jr.collect(config,dict(sport='MLB',name_en='Shohei Ohtani'))
        self.assertEqual(len(collected),7)
        self.assertTrue(any('未登録' in reason for reason in reasons))

    def test_candidate_pool_survives_three_rejections_and_caps_work(self):
        row=dict(kind='headline',source='スポニチ',original='投球を高く評価した。',url='https://www.sponichi.co.jp/example')
        rows=[dict(row) for _ in range(7)];report=jr.material_report(rows)
        text='スポニチでは、投球を高く評価した。。';english='According to Sponichi, the pitching was highly praised.'
        approved=jr.approved_segment('voice',text,english)
        translated=dict(english=english,review=approved['review'])
        with patch.object(jr,'translate',side_effect=[ValueError('translation_numbers')]*3+[translated]*3) as translate, \
             patch('sys.stdout',new_callable=io.StringIO):
            data=jr.from_rows(dict(sport='MLB',name_en='Shohei Ohtani'),rows,Mock(),report=report)
        self.assertEqual((report['collected'],report['accepted'],report['rejected'],report['unreviewed']),(7,3,3,1))
        self.assertEqual(translate.call_count,6)
        self.assertEqual(len(data['sources']),3)
        jr.validate(data)

    def test_youtube_one_blocked_video_does_not_discard_the_channel(self):
        now=datetime.now(timezone.utc).isoformat()
        channel=dict(name='SPOTV NOW',handle='official',channel_id='official',sport='MLB')
        info=dict(items=[dict(id='official',contentDetails=dict(relatedPlaylists=dict(uploads='playlist')))])
        playlist=dict(items=[dict(snippet=dict(title='MLB ハイライト',publishedAt=now,resourceId=dict(videoId=v))) for v in ('blocked','good')])
        row=dict(kind='youtube',original='大谷翔平の投球が素晴らしい。')
        get=Mock(side_effect=[info,playlist])
        with patch.dict(os.environ,dict(YOUTUBE_API_KEY='test')), \
             patch.object(jr,'fetch_comments',side_effect=[ValueError('comments disabled'),[row]]) as fetch:
            rows,reasons=jr.collect_youtube(dict(youtube=[channel]),'MLB',dict(name_jp='大谷翔平'),get=get)
        self.assertEqual(rows,[row]);self.assertEqual(len(reasons),1)
        self.assertEqual(fetch.call_count,2)


if __name__=='__main__': unittest.main(argv=['test_japan_reacts'])
