"""本物の保存見出し、日本語音声/英語字幕、禁止取得元、#160の訳を通信なしで検査。"""
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import japan_reacts as jr


def response(text): return NS(content=[NS(type='text',text=text)],stop_reason='end_turn',usage=NS(input_tokens=1,output_tokens=1))


class Tests(unittest.TestCase):
    def setUp(self): self.data=jr.read(jr.ROOT/'scripts/fixtures/japan-reacts/sponichi-saved.json')

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


if __name__=='__main__': unittest.main(argv=['test_japan_reacts'])
