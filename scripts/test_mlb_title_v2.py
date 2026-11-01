"""題の短縮でも、引用・検索語・否定・旧版の出力を保つ。通信なし。"""
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import upload_youtube as uy

HEAD = 'ドジャース大谷翔平、手術を回避　2027年に二刀流で復帰の見込み'
CARD = 'ブルワーズ、初の優勝を祝うパレードのハイライト'


class MlbTitleV2(unittest.TestCase):
    def meta(self, mode, value='on', module=uy, head=HEAD, card=CARD, who=None):
        switch = {'SERIES_TITLE': ''}
        if value is not None:
            switch['COLLESPO_MLB_TITLE_V2'] = value
        with patch.dict(os.environ, switch, clear=True), \
             patch.object(module, 'top_headline', return_value=head), \
             patch.object(module, 'buzz_top', return_value={'topic_jp': card}), \
             patch.object(module, 'thread_replies', return_value=4), \
             patch.object(module, 'voiced_japanese', return_value=who or []):
            return module.build_metadata('notable_games.json', '11月1日', kind='morning',
                                         morning_mode=mode,
                                         narration_path='build/no-mlb-title-narration.json')['snippet']

    def test_off_title_contract(self):
        expected_titles = {
            'press': '【MLB】現地はこう報じた「ドジャース大谷、手術を回避　2027年に二刀流で復帰の見込み」｜11月1日 番記者の投稿と現地の見出し #Shorts',
            'voices': '【MLB】ブルワーズ、初の優勝を祝うパレードのハイライト 現地のファンは何と言ったか｜返信4件ついたコメント 11月1日更新 #Shorts',
        }
        for mode, expected in expected_titles.items():
            for value in (None, 'off', '', 'true', 'ON', '1'):
                with self.subTest(mode=mode, value=value):
                    self.assertEqual(expected, self.meta(mode, value)['title'])

    def test_press_quote_and_search_names(self):
        before, after = self.meta('press', 'off'), self.meta('press')
        self.assertEqual(after['title'],
                         '「ドジャース大谷、手術を回避　2027年に二刀流で復帰の見込み」｜現地の報道 #Shorts')
        self.assertLess(len(after['title']), len(before['title']))
        self.assertIn(before['title'], after['description'])
        for word in ('MLB', '大谷翔平', 'ドジャース'):
            self.assertIn(word, after['description'].splitlines()[0])
            self.assertIn(word, after['tags'])
        self.assertIn(before['description'], after['description'])

    def test_voices_keeps_detail_in_description(self):
        before, after = self.meta('voices', 'off'), self.meta('voices')
        self.assertEqual(after['title'], 'ブルワーズ、初の優勝を祝うパレードに現地ファンの声 #Shorts')
        for unwanted in ('【MLB】', '返信4件', '11月1日', '何と言ったか'):
            self.assertNotIn(unwanted, after['title'])
        self.assertIn(before['title'], after['description'])
        self.assertIn(before['description'], after['description'])
        self.assertIn(CARD, after['description'])
        self.assertIn('ブルワーズ', after['tags'])

    def test_fallback_and_other_modes(self):
        self.assertEqual(self.meta('press', head='')['title'], 'MLB 現地の報道まとめ #Shorts')
        self.assertEqual(self.meta('voices', card='')['title'],
                         'MLB公式ハイライトに現地ファンの声 #Shorts')
        for mode in ('players', 'local'):
            self.assertEqual(self.meta(mode, 'off'), self.meta(mode))
        title = self.meta('voices', card='ドジャース vs カブス', who=['大谷翔平'])['title']
        self.assertIn('大谷翔平', title)
        self.assertIn('ドジャース vs カブス', title)

    def test_no_mid_sentence_or_negation_cut(self):
        long = 'ドジャースが大谷翔平と契約したり' + 'するという報道' * 10 + 'したのは融資のためではない'
        pool = {'headlines': [{'jp': long}, {'jp': 'カブス今永昇太が来季も残留する見込み'}]}
        with patch.object(pathlib.Path, 'read_text', return_value=json.dumps(pool)):
            self.assertEqual(uy.top_headline(), pool['headlines'][1]['jp'])
        sentence = 'カブス今永昇太が来季も残留する見込み。' + '追加情報' * 20
        pool['headlines'] = [{'jp': sentence}]
        with patch.object(pathlib.Path, 'read_text', return_value=json.dumps(pool)):
            self.assertEqual(uy.top_headline(), sentence.split('。')[0])
        self.assertEqual(uy._clip('大谷翔平の移籍を報じた。だが球団は否定した', 18), '')

    def test_workflow_exact_switch(self):
        workflow = pathlib.Path('.github/workflows/morning_recap.yml').read_text(encoding='utf-8')
        self.assertIn("COLLESPO_MLB_TITLE_V2: ${{ vars.COLLESPO_MLB_TITLE_V2 == 'on' && 'on' || 'off' }}", workflow)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
