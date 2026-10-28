"""本人指摘の姓名の間、読点なしの複数句、文の区切りの保持を再現。"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_reading_guard as guard


def phrase(kana,pause=None):
    return dict(moras=[dict(text=c,pitch=4) for c in kana],accent=1,
                pause_mora=pause,is_interrogative=False)


class NamePhrases(unittest.TestCase):
    def test_dictionary_and_aliases_have_no_name_separators(self):
        for name in guard.player_data()['japanese_players']:
            self.assertRegex(guard.player_readings()[name],r'^[ァ-ヶー]+$')
        for text in ('鎌田大地','鎌田 大地','鎌田・大地','Daichi Kamada'):
            self.assertEqual(guard.apply(text),'カマダダイチ')

    def test_two_phrases_fail_with_or_without_pause(self):
        for name,kana in (('鎌田大地',('カマダ','ダイチ')),('上田綺世',('ウエダ','アヤセ')),
                          ('大谷翔平',('オータニ','ショーヘー'))):
            for pause in (None,dict(text='、',vowel='pau',vowel_length=.2)):
                q=dict(accent_phrases=[phrase(kana[0],pause),phrase(kana[1])])
                with self.assertRaisesRegex(guard.NameReadingError,'複数句'):
                    guard.validate_query(name,q)

    def test_join_only_internal_boundary_and_recompute(self):
        pause=dict(text='、',vowel='pau',vowel_length=.2)
        q=dict(accent_phrases=[phrase('キョオ',pause),phrase('オータニ',pause),
                              phrase('ショーヘー',pause),phrase('ウエダ'),phrase('アヤセデス')])
        before=copy.deepcopy(q)
        reply=Mock()
        ueda=phrase('ウエダアヤセデス');ueda['accent']=len(ueda['moras'])
        reply.json.return_value=[phrase('オータニショーヘー',pause),ueda]
        with patch('requests.post',return_value=reply) as post:
            result=guard.prepare_query('今日、大谷翔平、上田綺世です。',q,3,'http://engine')
        self.assertEqual(q,before)
        self.assertEqual(result['accent_phrases'][0],before['accent_phrases'][0])
        self.assertEqual(len(result['accent_phrases']),3)
        self.assertEqual(result['accent_phrases'][1]['pause_mora'],pause)
        self.assertEqual(post.call_args.kwargs['params'],{'speaker':3})
        self.assertEqual(len(post.call_args.kwargs['json']),2)
        guard.validate_query('今日、大谷翔平、上田綺世です。',result)

    def test_repeated_name_second_split_detected(self):
        q=dict(accent_phrases=[phrase('カマダダイチ'),phrase('カマダ'),phrase('ダイチ')])
        with self.assertRaises(guard.NameReadingError):guard.validate_query('鎌田大地。鎌田大地。',q)

    def test_valid_phrase_does_not_call_engine(self):
        q=dict(accent_phrases=[phrase('ウエダアヤセデス',dict(text='。'))])
        q['accent_phrases'][0]['accent']=len(q['accent_phrases'][0]['moras'])
        with patch('requests.post') as post:
            self.assertIs(guard.prepare_query('上田綺世です。',q,2,'http://engine'),q)
        post.assert_not_called()

    def test_synthesis_receives_joined_query(self):
        import synthesize_narration as sn
        import tempfile
        audio=Mock();audio.json.return_value=dict(accent_phrases=[phrase('オータニ'),phrase('ショーヘーデス')])
        mora=Mock();mora.json.return_value=[phrase('オータニショーヘーデス')]
        from voice_test_fixture import pcm_wav_bytes
        wav=Mock();wav.content=pcm_wav_bytes()
        with tempfile.TemporaryDirectory() as d,patch.object(sn.requests,'post',side_effect=[audio,mora,wav]) as post:
            self.assertTrue(sn.synth_one('大谷翔平です。',2,Path(d)/'sample.wav'))
            self.assertEqual(len(post.call_args.kwargs['json']['accent_phrases']),1)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
