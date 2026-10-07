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
