"""本人の鎌田大地、文中位置、未確認・別名・助詞・再計算不正を検査。"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_reading_guard as guard
import name_accent_guard as accents
import voice_accent_common as common


def phrase(reading,accent,pause=None):
    return dict(moras=[dict(text=m) for m in common.moras(reading)],accent=accent,pause_mora=pause,is_interrogative=False)


class Accents(unittest.TestCase):
    def test_dictionary_confirmed_and_unverified_are_separate(self):
        rows=accents.entries();self.assertEqual(len(rows),60)
        confirmed=[r for r in rows if r['pattern']]
        self.assertEqual([(r['name'],r['pattern']) for r in confirmed],[('鎌田大地','LHHHHH')])
        self.assertEqual(len([r for r in rows if r['status']=='UNVERIFIED']),59)

    def test_shared_functions_handle_moras_and_flat_accent(self):
        self.assertEqual(common.mora_count('オオタニショウヘイ'),8)
        self.assertEqual(common.mora_count('カマダダイチ'),6)
        self.assertEqual(common.pattern_to_accent('LHHHHH'),0)
        self.assertEqual(common.phrase_pattern(6,6),'LHHHHH')

    def test_wrong_accent_stops_in_existing_query_gate(self):
        for a in (1,4):
            with self.assertRaisesRegex(guard.NameReadingError,'氏名高低'):
                guard.validate_query('鎌田大地です。',dict(accent_phrases=[phrase('カマダダイチデス',a)]))

    def test_correction_preserves_pause_and_high_particle(self):
        pause=dict(text='、');q=dict(accent_phrases=[phrase('カマダダイチガ',1,pause)])
        reply=Mock();reply.json.return_value=[phrase('カマダダイチガ',7,pause)]
        before=copy.deepcopy(q)
        with patch('requests.post',return_value=reply) as post:
            result=guard.prepare_query('鎌田大地が',q,2,'http://engine')
        self.assertEqual(q,before);self.assertEqual(post.call_count,1)
        self.assertEqual(result['accent_phrases'][0]['pause_mora'],pause)
        self.assertEqual(common.phrase_pattern(7,result['accent_phrases'][0]['accent']),'LHHHHHH')
        self.assertEqual(guard.validate_query('鎌田大地が',result)['name_accents'][0]['status'],'PASS')

    def test_name_within_phrase_splits_prefix_without_pause(self):
        q=dict(accent_phrases=[phrase('キョオカマダダイチガ',1,dict(text='。'))])
        reply=Mock();reply.json.return_value=[phrase('キョオ',1),phrase('カマダダイチガ',7,dict(text='。'))]
        with patch('requests.post',return_value=reply):result=guard.prepare_query('今日鎌田大地が',q,3,'http://engine')
        self.assertIsNone(result['accent_phrases'][0]['pause_mora'])
        self.assertEqual(result['accent_phrases'][1]['accent'],7)

    def test_unknown_names_not_replaced_or_passed_as_confirmed(self):
        q=dict(accent_phrases=[phrase('ウエダアヤセデス',1)])
        with patch('requests.post') as post:self.assertIs(guard.prepare_query('上田綺世です。',q,2,'http://engine'),q)
        post.assert_not_called()
        checked=guard.validate_query('上田綺世です。',q)
        self.assertEqual(checked['name_accents'][0]['status'],'UNVERIFIED')

    def test_english_alias_and_repeated_name_corrected(self):
        q=dict(accent_phrases=[phrase('カマダダイチ',6),phrase('カマダダイチデス',8)])
        rows=guard.validate_query('Daichi Kamada。鎌田大地です。',q)['name_accents']
        self.assertEqual([r['status'] for r in rows],['PASS','PASS'])

    def test_corrupt_recomputation_cannot_pass(self):
        q=dict(accent_phrases=[phrase('カマダダイチデス',1)])
        reply=Mock();reply.json.return_value=[phrase('カマダダイチデス',1)]
        with patch('requests.post',return_value=reply),self.assertRaises(guard.NameReadingError):
            guard.prepare_query('鎌田大地です。',q,2,'http://engine')


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
