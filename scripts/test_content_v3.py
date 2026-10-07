"""⑮の編集順、引用同期、全シリーズ、ページの安全域。保存材料のみ。"""
from datetime import datetime
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import bignumber_render as bn
import comment_render as cr
import daily_v3
import generate_morning_short as g
import ps_program as ps
import ps_unified_v3 as unified
import review_render_v3 as r3
import v3_slot_render as common

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


class Content(unittest.TestCase):
    def test_players_order_brand_and_material(self):
        data=read('scripts/fixtures/bignumber/morning_recap.json')
        data['players']=g.sort_players(data['players'])
        bn._no_network()
        with patch.object(g,'week_line',return_value=('',[])),patch.dict(os.environ,{'COLLESPO_PLAYERS_DESIGN':'bignumber'}):
            narration=g.build_narration(data,'players')
        self.assertEqual([s['kind'] for s in narration['segments'][:4]],['cover','ranking','hero','list'])
        scenes=bn.scenes_from_morning(data,narration)
        self.assertFalse(bn.check_scenes(scenes,narration,data))
        self.assertTrue(all(s['team_id'] is None for s in scenes))
        ranks=scenes[1]['ranking']
        self.assertEqual([(r['rank'],r['name'],r['abbr']) for r in ranks],[(1,'松井裕樹','SD'),(2,'佐々木朗希','LAD'),(3,'大谷翔平','LAD')])
        with patch.dict(os.environ,{'COLLESPO_PLAYERS_DESIGN':'legacy'}),patch.object(g,'week_line',return_value=('',[])):
            self.assertEqual(g.build_narration(data,'players')['segments'][0]['kind'],'intro')

    def test_quotes_once_disclaimer_and_exact_reading_order(self):
        voices=read('scripts/fixtures/comment/local_voices-preview.json')
        narration=g.build_narration({'players':[],'voices':voices,'date_jst':'2026-10-07'},'voices')
        all_quotes=[]
        for seg in narration['segments']:
            if seg['kind'] in ('intro','thread','voices'):
                quotes=cr.voices_for_segment(seg,voices)
                timed=cr.reading_times(quotes,seg['text'],20)
                all_quotes += [v['said'] for v in quotes]
                self.assertEqual([v['at'] for v in timed],sorted(v['at'] for v in timed))
                self.assertTrue(all(0<=v['at']<v['end']<=20 for v in timed))
        parent=voices['voices'][narration['segments'][0]['meta']['used_voice']]['ja']
        self.assertEqual(all_quotes.count(parent),1)
        self.assertNotIn('コレスポの見解ではありません',''.join(s['text'] for s in narration['segments']))
        self.assertIn('コレスポの見解ではありません',cr._voices_source(voices))
        self.assertEqual(common.screen_text('出典\nコレスポの見解ではありません'),'出典\nコレスポの見解ではありません')

    def test_pages_hold_all_rows_and_safe_boxes(self):
        spec={'heading':'PS全シリーズ'}
        rows=[(f'DS 第{i+1}戦','2勝　大谷翔平・佐々木朗希・山本由伸') for i in range(9)]
        pages=common.paginate(spec,rows)
        self.assertGreater(len(pages),1)
        self.assertEqual([cell['row'] for p in pages for cell in p],list(range(9)))
        self.assertFalse(common.check_pages(spec,rows))
        long='「'+'全文を次ページへ送り読み上げる。'*100+'」'
        parts=common.paginate(spec,[('現地の記者',long)])
        self.assertEqual(''.join(c['body'][1:-1] for p in parts for c in p),long[1:-1])
        self.assertFalse(common.check_pages(spec,[('現地の記者',long)]))

    def test_quotes_split_on_actual_audio_boundaries(self):
        for mode,filename in [('voices','local_voices-preview.json'),('press','local_reporters-preview.json')]:
            material=read('scripts/fixtures/comment/'+filename)
            data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}
            with patch.dict(os.environ,{'COLLESPO_COMMENTS_DESIGN':'legacy','COLLESPO_PRESS_DESIGN':'legacy'}):
                before=g.build_narration(data,mode)
            with patch.dict(os.environ,{'COLLESPO_COMMENTS_DESIGN':'comments','COLLESPO_PRESS_DESIGN':'v3'}):
                after=g.build_narration(data,mode)
                daily_v3.prepare(data,after,mode)
            self.assertEqual(''.join(s['text'] for s in before['segments'] if s['kind']!='outro'),''.join(s['text'] for s in after['segments'] if s['kind']!='outro'))
            self.assertEqual(after['segments'][-1]['text'],r3.OUTRO_TEXT)
            read_quotes=[]
            for seg in after['segments']:
                rows=seg.get('meta',{}).get('quote_rows',[])
                if not rows:continue
                active=[v for v in rows if v.get('read')]
                self.assertEqual(len(active),1)
                timed=cr.reading_times(rows,seg['text'],7.3)
                self.assertEqual((timed[-1]['at'],timed[-1]['end']),(0,7.3))
                self.assertTrue(all(v['end']==0 for v in timed[:-1]))
                self.assertAlmostEqual(g.plan_durations([dict(seg,duration=1)])[0],1.7)
                read_quotes += [v['said'] for v in active if not v.get('fact')]
            self.assertTrue(read_quotes)
            self.assertEqual(len(read_quotes),len(set(read_quotes)))

    def test_forecast_lists_all_then_details_and_no_rings(self):
        saved=read('scripts/fixtures/ps-design/2026-10-07.json')
        with patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            program=ps.prepare(saved['snapshot'],saved['evidence'],'forecast',datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        ps.check_program(program)
        cover=program['segments'][0]
        self.assertEqual(cover['meta']['card']['headline'],'明日の全試合の一覧')
        self.assertEqual(len(cover['meta']['card']['items']),len(program['game_ids']))
        for row in cover['meta']['card']['items']:
            self.assertIn(row['home'],cover['text']);self.assertIn(row['away'],cover['text'])
            self.assertIn('home_wins',row);self.assertIn('away_wins',row)
        for seg in program['segments']:
            self.assertTrue(all('win' not in c for c in unified.spec(seg['meta']['card'])['v3']['chips']))
            unified.check_layout(seg['meta']['card'])

    def test_situation_includes_unchanged_both_leagues(self):
        saved=read('scripts/fixtures/ps-design/2026-10-07.json')
        stamp=datetime.fromisoformat(saved['evidence']['retrieved_at'])
        with patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            program=ps.prepare(saved['snapshot'],saved['evidence'],'situation',stamp,saved['ledger'])
        active=[r for r in program['series'] if not r['over'] and len(r['teams'])==2]
        displayed=[set(r['name'] for r in s['meta']['card']['scoreboard']['rows']) for s in program['segments'] if s['meta']['card'].get('scoreboard')]
        self.assertEqual({r['league_jp'] for r in active},{'ア・リーグ','ナ・リーグ'})
        self.assertTrue(all(set(t['name'] for t in row['teams']) in displayed for row in active))
        ps.check_program(program)

    def test_shared_outro_adapter_and_fallback(self):
        spec={'heading':'コレスポ'}
        with patch.object(r3,'outro',None):
            self.assertIsNone(common.outro(1,spec,'morning'))
        sentinel=object()
        with patch.object(r3,'outro',return_value=sentinel,create=True) as end:
            self.assertIs(common.outro(1,spec,'コレスポ'),sentinel)
            end.assert_called_once_with(1,spec,'コレスポ','音声: VOICEVOX:四国めたん　データ: MLB Stats API')
            narration={'kind':'outro','text':'コレスポ。'}
            self.assertIs(daily_v3.frame(1,narration,{'mode':'voices'},5),sentinel)
            self.assertIs(bn.scene(1,{'kind':'outro','head':'コレスポ'}),sentinel)
            self.assertIs(daily_v3.frame(1,narration,{'mode':'press'},5),sentinel)
            self.assertIs(unified.frame(1,{'outro':True,'date':'2026-10-07','layout':'facts','headline':'コレスポ','items':[]}),sentinel)

    def test_active_quote_bright_and_finished_quote_dim(self):
        spec={'heading':'引用'};rows=[('先の引用','「最初の言葉」'),('次の引用','「次の言葉」')]
        pages=common.paginate(spec,rows)
        self.assertEqual(len(pages),1)
        first=common.frame(1,spec,rows,'コメント',times=[0,5],ends=[4,9])
        later=common.frame(6,spec,rows,'コメント',times=[0,5],ends=[4,9])
        p=(900,pages[0][0]['box'][1]+100)
        q=(900,pages[0][1]['box'][1]+100)
        self.assertGreater(first.getpixel(p)[0],later.getpixel(p)[0])
        self.assertEqual(first.getpixel(p),later.getpixel(q))


    def test_source_name_is_read_with_its_quote(self):
        import content_v3
        self.assertEqual(content_v3.source_lead('現地の見出しです。ESPN。',{'who':'ESPN'}),'ESPN。')
        self.assertEqual(content_v3.source_lead('翻訳したものです。Baltimore Bannerの記者。',
                                                {'who':'Baltimore Banner / Andy Kostka'}),'Baltimore Bannerの記者。')
        self.assertEqual(content_v3.source_lead('コメント欄から。',{'who':'高評価1,054件のコメント'}),'')

if __name__=='__main__':unittest.main(argv=[__file__])
