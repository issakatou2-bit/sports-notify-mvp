"""本人の上田綺世の誤読、辞書欠測、query不一致、背景材料の誤検出を再現。"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_reading_guard as guard
import club_display_names as clubs
import notability_engine as ne


def query(kana):
    import voice_accent_common as common
    moras=[{'text':c} for c in common.moras(kana)]
    return {'accent_phrases':[{'moras':moras,'accent':len(moras)}]}


class Readings(unittest.TestCase):
    def test_all_roster_players_and_96_clubs_registered(self):
        for p in ne.JP_PLAYERS_SOCCER+ne.JP_PLAYERS_MLB:
            self.assertTrue(guard.player_reading(p['name_jp']),p['name_jp'])
            self.assertTrue(guard.player_reading(p['name_en']),p['name_en'])
        table=json.loads((ROOT/'data/club_display_names.json').read_text(encoding='utf8'))
        self.assertEqual(len(table['clubs']),96)
        for c in table['clubs']:
            self.assertTrue(c['reading'],c['id'])
            self.assertEqual(clubs.lookup(c['id'])['id'],c['id'])

    def test_ueda_space_and_english_alias(self):
        for text in ('上田綺世です。','上田 綺世です。','Ayase Uedaです。'):
            self.assertIn('ウエダアヤセ',ne.apply_readings(text))
            guard.assert_known(text,[('player',text[:-3])])

    def test_omitted_existing_reading_stops(self):
        data=copy.deepcopy(guard.player_data());data['readings'].pop('上田綺世')
        with patch.object(guard,'player_data',return_value=data):
            with self.assertRaisesRegex(guard.NameReadingError,'上田綺世'):
                guard.assert_known('上田綺世が得点です。')

    def test_new_live_roster_without_dictionary_stops(self):
        with patch.object(ne,'JP_PLAYERS_SOCCER',ne.JP_PLAYERS_SOCCER+[dict(name_jp='試験太郎',name_en='Taro Test')]):
            with self.assertRaisesRegex(guard.NameReadingError,'試験太郎'):
                guard.assert_known('試験太郎が出場です。')

    def test_unknown_spoken_entity_stops_background_only_does_not(self):
        guard.assert_known('今日は試合です。',[('player','試験太郎'),('club','未登録FC')])
        with self.assertRaises(guard.NameReadingError):
            guard.validate_dialogue({'segments':[dict(kind='jp_player',text='試験太郎が出場です。',meta=dict(name='試験太郎'))]})
        with self.assertRaises(guard.NameReadingError):
            guard.assert_known('未登録FCの試合です。',[('club','未登録FC')])

    def test_named_manager_and_generic_words(self):
        guard.assert_known('森保一監督です。代表監督と新監督、リバプール監督。')
        with self.assertRaisesRegex(guard.NameReadingError,'監督名'):
            guard.assert_known('未登録太郎監督が話しました。')

    def test_new_japanese_player_role_and_generic_players(self):
        guard.assert_known('日本人選手と主力選手、先発投手です。')
        with self.assertRaisesRegex(guard.NameReadingError,'日本人選手名'):
            guard.assert_known('未登録太郎選手が出場しました。')
        with self.assertRaises(guard.NameReadingError):
            guard.validate_dialogue(dict(segments=[dict(kind='cover',text='試験太郎が出場です。',meta=dict(name='試験太郎'))]))

    def test_saved_real_generic_phrases_are_not_people(self):
        for text in ('ドジャース監督が体調を明かす','エンゼルス監督復帰を支持','再度監督契約する','49代目監督に指名','両先発投手','日本人複数選手が激突','好調投手と対峙','伝説的選手だ','月間最優秀選手候補','野球選手か慈善家か','構成選手の変化','最速投手ホプキンスを昇格'):
            guard.assert_known(text)
        self.assertEqual(guard.apply('大谷選手です。'),'オオタニ選手です。')

    def test_missing_club_reading(self):
        rows=copy.deepcopy(clubs.rows());next(c for c in rows if c['id']=='Aston Villa FC')['reading']=''
        with patch.object(clubs,'rows',return_value=rows):
            clubs.index.cache_clear()
            try:
                with self.assertRaises(guard.NameReadingError):guard.assert_known('アストンヴィラの試合です。')
            finally:clubs.index.cache_clear()

    def test_ordinary_english_and_ambiguous_abbreviation(self):
        self.assertIsNone(clubs.lookup('BRE'))
        self.assertFalse(any(r['kind']=='club' for r in guard.occurrences('Nice goal! BRE')))
        self.assertEqual(ne.apply_readings('山路を歩く。'),'山路を歩く。')

    def test_audio_query_wrong_ueda_stops(self):
        guard.validate_query('上田綺世が得点です。',query('ウエダアヤセガトクテンデス'))
        with self.assertRaisesRegex(guard.NameReadingError,'query'):
            guard.validate_query('上田綺世が得点です。',query('ウエダキヨガトクテンデス'))

    def test_query_checks_repeated_names(self):
        with self.assertRaises(guard.NameReadingError):
            guard.validate_query('上田綺世。上田綺世。',query('ウエダアヤセウエダキヨ'))

    def test_long_vowels_are_not_false_positives(self):
        guard.validate_query('大谷翔平です。',query('オータニショーヘーデス'))
        guard.validate_query('グアルディオラ監督です。',query('グアルディオラカントクデス'))

    def test_previous_sentence_yo_does_not_change_ueda_to_oeda(self):
        original='リールは3位で、勝点は15よ。上田綺世所属のチームね。'
        q=query('リイルワサンイデカチテンワジュウゴヨウエダアヤセショゾクノチイムネ')
        # 旧検査は文全体を先に長音化し、ヨ＋ウエダをヨオエダとした。
        raw=''.join(m['text'] for p in q['accent_phrases'] for m in p['moras'])
        self.assertIn('ヨオエダ',guard.normalized_kana(raw))
        guard.validate_query(original,q,check_phrases=False)
        locations=guard.query_name_locations(original,q)
        name=next(r for r in locations if r['name']=='上田綺世')
        self.assertEqual(q['accent_phrases'][name['first'][0]]['moras'][name['first'][1]]['text'],'ウ')
        with self.assertRaises(guard.NameReadingError):
            guard.validate_query(original,query('リイルワサンイデカチテンワジュウゴヨオエダアヤセショゾクノチイムネ'),check_phrases=False)

    def test_previous_de_does_not_change_ito_to_eto(self):
        original='ブンデスリーガで伊藤洋輝選手のバイエルンは、いま何位なのだ?'
        q=query('ブンデスリイガデイトオヒロキセンシュノバイエルンワイマナンイナノダ')
        guard.validate_query(original,q,check_phrases=False)
        with self.assertRaises(guard.NameReadingError):
            guard.validate_query(original,query('ブンデスリイガデエトオヒロキセンシュノバイエルンワイマナンイナノダ'),check_phrases=False)

    def test_name_boundary_locations_are_shared_with_accent_check(self):
        import name_accent_guard
        for original,kana in [('15よ。上田綺世です。','ジュウゴヨウエダアヤセデス'),
                              ('ブンデスリーガで伊藤洋輝です。','ブンデスリイガデイトオヒロキデス')]:
            q=query(kana)
            # 検証済み高低を適用する段階でも同じ位置が見つかる。
            located=name_accent_guard.locations(original,q)
            self.assertEqual(len(located),1)
            self.assertEqual(guard.name_phrase_spans(original,q)[0]['first'],0)

    def test_repeated_boundary_names_do_not_reuse_one_correct_occurrence(self):
        with self.assertRaises(guard.NameReadingError):
            guard.validate_query('15よ。上田綺世。上田綺世。',query('ジュウゴヨウエダアヤセウエダキヨ'),check_phrases=False)

    def test_engine_foreign_name_overrides_keep_expected_reading(self):
        self.assertEqual(guard.apply('アストンヴィラです。'),'あすとんゔぃらです。')
        self.assertEqual(guard.apply('ポチェッティーノ監督です。'),'ぽチェッティーノ監督です。')
        guard.validate_query('ポチェッティーノ監督です。',query('ポチェッティイノカントクデス'))

    def test_synthesis_cannot_swallow_mismatch(self):
        import synthesize_narration as sn
        reply=Mock();reply.json.return_value=query('ウエダキヨデス')
        with tempfile.TemporaryDirectory() as d,patch.object(sn.requests,'post',return_value=reply) as post:
            with self.assertRaises(guard.NameReadingError):sn.synth_one('上田綺世です。',2,Path(d)/'voice.wav')
            self.assertEqual(post.call_count,1)  # /synthesisへ進まない。

    def test_dictionary_missing_stops_before_engine_fallback(self):
        import synthesize_narration as sn
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'narration.json';path.write_text(json.dumps(dict(segments=[dict(kind='jp_player',text='試験太郎です。',meta=dict(name='試験太郎'))]),ensure_ascii=False),encoding='utf8')
            with patch.object(sys,'argv',['synthesize_narration','--narration',str(path),'--out-dir',d]),patch.object(sn,'engine_available',return_value=False) as available:
                with self.assertRaises(guard.NameReadingError):sn.main()
                available.assert_not_called()


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
