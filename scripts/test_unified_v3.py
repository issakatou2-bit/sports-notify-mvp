"""共通部品の利用、材料の不変、短いテロップ、声なし確認の入口。"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import ImageChops

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bignumber_render as bn
import ps_unified_v3 as ps
import review_render_v3 as r3
import v3_slot_render as common


class Unified(unittest.TestCase):
    def test_integer_stats_rank_and_nonempty_chips(self):
        players = [{'name':'松井裕樹','type':'pitcher','headline':'1.1回　0奪三振'},
                   {'name':'佐々木朗希','type':'pitcher','headline':'2.0回　3奪三振'},
                   {'name':'大谷翔平','type':'batter','headline':'4打数2安打'}]
        self.assertEqual(bn.pick_big('1.5奪三振','pitcher'), ('',''))
        self.assertEqual(bn._player_scene(players[0],'元の原稿',rank=1)['big'], '1')
        scenes=bn._intro_scenes({},players,'10月7日')
        chips=bn.unified_spec(scenes[-1])['v3']['chips']
        self.assertEqual([c['score'] for c in chips], ['勝利貢献 1位','3奪三振','2安打'])
        self.assertEqual(bn.unified_spec(scenes[0])['v3']['chips'], [])

    def test_comment_missing_glyph_is_screen_only(self):
        import comment_render as cr
        voices=[{'who':'ファン','said':'大谷の安打🔥\U0010ffff！','at':.1}]
        before=copy.deepcopy(voices)
        with patch.object(common,'frame',return_value=None) as frame:
            cr.unified_comments(3,voices,None,'応援🔥')
            body=frame.call_args.args[2][0][1]
            self.assertEqual(body,'「大谷の安打！」')
            self.assertEqual(frame.call_args.args[1]['v3']['ticker'],'応援')
        self.assertEqual(voices,before)

    def test_quote_wrap_uses_the_actual_font_and_preserves_text(self):
        from PIL import Image, ImageDraw
        d=ImageDraw.Draw(Image.new('RGB',(8,8)))
        text='「オリオールズのビジネスオペレーションについて報道した。'+ '長い引用を全文掲載する。'*10+'」'
        lines,size=r3._lines(d,text,52,792,100)
        self.assertEqual(''.join(lines),text)
        self.assertTrue(all(d.textbbox((0,0),line,font=r3.font(size))[2]<=792 for line in lines))

    def test_ps_single_line_ticker_and_starter_reading(self):
        card={'layout':'facts','date':'2026-10-07','glossary':'WCS 2勝\nDS 3勝',
              'items':[{'label':'ドジャース先発予定','value':'Shohei Ohtani'},
                       {'label':'相手チーム先発予定','value':'Unknown Pitcher Zzzz'}]}
        before=copy.deepcopy(card)
        self.assertNotIn('\n',ps.ticker_text(card))
        self.assertEqual(ps.ticker_text(card).count('日本時間10月7日'),1)
        self.assertFalse(any(c.isascii() and c.isalpha() for c in ps.rows(card)[0][1]))
        self.assertEqual(len(ps.rows(card)),1)
        self.assertEqual(card,before)

    def test_ps_ticker_is_drawn_once_even_at_loop_boundary(self):
        from PIL import Image, ImageDraw
        line='日本時間10月8日　5時 ホワイトソックス対ガーディアンズ　7時 ドジャース対ブレーブス'
        r3._single_ticker.cache_clear()
        original=ImageDraw.ImageDraw.text
        texts=[]
        def record(draw,xy,text,*args,**kwargs):
            texts.append(text)
            return original(draw,xy,text,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',record):
            strip=r3._single_ticker(line)
            cycle=(r3.W+strip.width)/80
            for t in (0,3,cycle-.01,cycle,cycle+.01):
                r3.ticker(Image.new('RGB',(1080,1920)),t,line,once=True)
        self.assertEqual(texts,[line])

    def test_ps_timetable_and_hidden_starter_keep_material(self):
        import json
        from datetime import datetime
        import ps_program as program
        saved=json.loads((bn.ROOT/'scripts/fixtures/ps-design/2026-10-07.json').read_text(encoding='utf-8'))
        data=program.prepare(saved['snapshot'],saved['evidence'],'forecast',datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        before=copy.deepcopy(data)
        line=ps.program_ticker(data)
        self.assertEqual(line.count('日本時間10月8日'),1)
        self.assertIn('5時 ホワイトソックス対ガーディアンズ',line)
        self.assertIn('7時 ブレーブス対ドジャース',line)
        for seg in data['segments']:
            card=seg['meta']['card']
            with patch.object(r3,'ticker',wraps=r3.ticker) as ticker:
                ps.frame(3,card,ticker_line=line)
                ticker.assert_called_once()
                self.assertEqual(ticker.call_args.args[2],line)
                self.assertTrue(ticker.call_args.kwargs['once'])
            self.assertTrue(all(b!='先発予定' for h,b in ps.rows(card)))
        self.assertEqual(data,before)

    def test_ps_transition_replaces_the_blended_band(self):
        from PIL import Image
        previous=Image.new('RGB',(1080,1920),'red').tobytes()
        current=Image.new('RGB',(1080,1920),'blue')
        line='日本時間10月8日　5時 ホワイトソックス対ガーディアンズ'
        with patch.object(r3,'ticker',wraps=r3.ticker) as ticker:
            raw=ps.transition(previous,current,2,6,20.1,line)
            ticker.assert_called_once()
            self.assertEqual(ticker.call_args.args[1],20.1)
        expected=Image.new('RGB',(1080,1920))
        r3.ticker(expected,20.1,line,once=True)
        actual=Image.frombytes('RGB',(1080,1920),raw)
        self.assertEqual(actual.crop((0,1486,1080,1574)).tobytes(),expected.crop((0,1486,1080,1574)).tobytes())

    def test_chip_long_label_uses_a_font_that_fits(self):
        from PIL import ImageDraw
        label='ホワイトソックス / 先発予定'
        original=ImageDraw.ImageDraw.text
        drawn=[]
        def record(draw,xy,text,*args,**kwargs):
            if text == label:
                drawn.append(draw.textbbox((0,0),text,font=kwargs['font'])[2])
            return original(draw,xy,text,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',record):
            r3._chip(label,'先発予定',320,(20,20,20),(200,200,200))
        self.assertTrue(drawn)
        self.assertLessEqual(drawn[0],320-48)

    def test_player_ticker_is_one_ranked_sentence_and_speech_is_unchanged(self):
        import json
        import generate_morning_short as g
        data=json.loads((bn.ROOT/'scripts/fixtures/bignumber/morning_recap.json').read_text(encoding='utf-8'))
        data['players']=g.sort_players(data['players'])
        with patch.object(g,'week_line',return_value=('',[])):
            nar=g.build_narration(data,'players')
        before=copy.deepcopy(nar)
        scenes=bn.scenes_from_morning(data,nar)
        self.assertTrue(all(s['ticker']=='きょうの日本人選手　1位 松井裕樹　2位 佐々木朗希　3位 大谷翔平' for s in scenes))
        self.assertFalse(bn.check_scenes(scenes,nar,data))
        self.assertEqual(nar,before)

    def test_player_reuses_intro_and_does_not_mutate_material(self):
        spec={'big':'3','unit':'安打','head':'大谷翔平','head2':'ドジャース','sub':'4打数3安打','rank':1,'team_id':119}
        original=copy.deepcopy(spec)
        with patch.object(r3,'intro',wraps=r3.intro) as intro:
            self.assertEqual(bn.scene(3,spec).size,(1080,1920));intro.assert_called_once()
        self.assertEqual(spec,original)
        self.assertEqual(bn.unified_spec(spec)['v3']['tag'],spec['sub'])

    def test_quotes_keep_full_body_and_share_palette_and_presenter(self):
        body='「'+'試合の話題。'*30+'」'
        with patch.object(r3,'_item_card',wraps=r3._item_card) as item, patch.object(r3,'presenter',wraps=r3.presenter) as presenter:
            common.item.cache_clear()
            image=common.frame(3,{'heading':'現地の声'},[('報道元',body)],'現地の報道')
            self.assertEqual(image.size,(1080,1920));presenter.assert_called_once()
            self.assertEqual(item.call_args.args[1],body)
            self.assertTrue(item.call_args.kwargs['attribution_above'])

    def test_short_ticker_fills_the_whole_width(self):
        strip,width=r3._ticker_strip('ホールド')
        self.assertGreaterEqual(strip.width,width+1080)

    def test_ps_rows_are_derived_without_changing_words_or_numbers(self):
        card={'headline':'ドジャース\n対ブレーブス','layout':'facts','label':'PS情勢','date':'2026-10-07',
              'card_index':1,'card_total':1,'source_url':'https://www.mlb.com','source_label':'MLB公式',
              'scoreboard':{'need':3,'rows':[{'abbr':'LAD','name':'ドジャース','wins':2,'players':['大谷翔平']}]},
              'items':[{'label':'次の試合','value':'日本時間10月8日7時'}]}
        original=copy.deepcopy(card)
        self.assertEqual(ps.rows(card),[('LAD　ドジャース','2勝　大谷翔平'),('次の試合','日本時間10月8日7時'),('シリーズの決着','3勝先取')])
        a=ps.frame(.8,card);b=ps.frame(5,card)
        self.assertIsNotNone(ImageChops.difference(a,b).getbbox());self.assertEqual(card,original)

    def test_situation_time_comes_from_the_saved_label(self):
        card={'headline':'ドジャース対ブレーブス','layout':'facts','label':'PS情勢','date':'2026-10-07',
              'source_url':'https://www.mlb.com','items':[{'label':'次の試合','value':'日本時間10月8日7時'}]}
        view=ps.spec(card)
        self.assertEqual((view['v3']['big'],view['v3']['unit']),('7','時'))
        card['items'][0]['value']='次の試合は未定'
        self.assertEqual(ps.spec(card)['v3']['big'],'')

    def test_situation_lead_includes_the_first_game(self):
        first={'headline':'ドジャース対ブレーブス','scoreboard':{'rows':[{'name':'ドジャース'}]}}
        second={'headline':'ブリュワーズ対パドレス','scoreboard':{'rows':[{'name':'ブリュワーズ'}]}}
        program={'segments':[{'meta':{'card':first}},{'meta':{'card':second}}]}
        self.assertIs(ps.lead_card(program),first)


if __name__=='__main__':unittest.main(argv=[__file__])
