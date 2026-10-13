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
        self.assertEqual({r['name'] for r in confirmed},set(['ダルビッシュ有', 'ヌートバー', '上田綺世', '中村草太', '久保建英', '今井達也', '今永昇太', '伊藤敦樹', '伊藤洋輝', '佐々木朗希', '佐藤龍之介', '佐野海舟', '冨安健洋', '前田大然', '千賀滉大'])|{'鎌田大地'})
        for row in confirmed:
            self.assertEqual(row['pattern'],'L'+'H'*(common.mora_count(row['reading'])-1))
            self.assertEqual(row['source'],'コレスポ 加藤さん10/12' if row['name']=='鎌田大地' else 'コレスポ 加藤さん10/13')
        self.assertEqual(len([r for r in rows if r['status']=='UNVERIFIED']),44)

    def test_all_confirmed_names_corrected_in_sentences_for_both_speakers(self):
        for row in accents.entries():
            if not row['pattern']:
                continue
            for speaker in (2,3):
                for suffix in ('ガ','デス'):
                    with self.subTest(name=row['name'],speaker=speaker,suffix=suffix):
                        reading=row['reading']+suffix
                        q=dict(accent_phrases=[phrase(reading,1)])
                        original=copy.deepcopy(q)
                        reply=Mock();reply.json.return_value=[phrase(reading,common.mora_count(reading))]
                        with patch('requests.post',return_value=reply):
                            result=guard.prepare_query(row['name']+('が' if suffix=='ガ' else 'です。'),q,speaker,'http://engine')
                        self.assertEqual(q,original)
                        self.assertEqual(accents.inspect(row['name'],result)[0]['status'],'PASS')

    def test_pending_comparison_contains_both_voices_and_every_choice(self):
        import preview_name_accents_pending as preview
        rows=[]
        for index,row in enumerate(accents.entries(),1):
            if row['status']=='UNVERIFIED':
                rows.append(dict(row,id=index,candidate_pattern='L'+'H'*(common.mora_count(row['reading'])-1),voices=[
                    dict(speaker=s,actual='unknown',current_file=f'{index}-{s}-current.wav',candidate_file=f'{index}-{s}-flat.wav') for s in (2,3)]))
        text=preview.render(rows)
        self.assertEqual(text.count('<audio '),176)
        self.assertEqual(text.count('type="radio"'),132)
        self.assertIn('未確認44呼称',text)
        self.assertIn('localStorage.setItem',text)
        self.assertIn('unselected',text)
        self.assertIn('name-accent-picks2.json',text)

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
        q=dict(accent_phrases=[phrase('ミトマカオルデス',1)])
        with patch('requests.post') as post:self.assertIs(guard.prepare_query('三笘薫です。',q,2,'http://engine'),q)
        post.assert_not_called()
        checked=guard.validate_query('三笘薫です。',q)
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
