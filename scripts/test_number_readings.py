"""本人の分数の指摘と助数詞の実エンジン回帰材料。"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from notability_engine import apply_readings
from scripts import number_readings


class NumberReadingsTest(unittest.TestCase):
    def test_fraction_spellings_and_denominators(self):
        for n, word in enumerate(('いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう', 'じゅう'), 1):
            for denominator in (str(n), str(n).translate(str.maketrans('0123456789', '０１２３４５６７８９')),
                                '十' if n == 10 else number_readings.DIGITS[n]):
                with self.subTest(denominator=denominator):
                    self.assertEqual(apply_readings(denominator + '分の一'), word + 'ぶんの一')
        for source, expected in [('3分の1', 'さんぶんの1'), ('三分の一', 'さんぶんの一'),
                                 ('３分の２以上', 'さんぶんの２以上'), ('6回3分の1', '6回さんぶんの1'),
                                 ('十二分の五', 'じゅうにぶんの五'), ('１００分の１', 'ひゃくぶんの１')]:
            self.assertEqual(apply_readings(source), expected)

    def test_time_and_non_fraction_stay_unchanged(self):
        for text in ('3分', '三分', '３分', '3分の休憩', '十分な休息', '午後3時3分', '1本・3杯・6回', '三分咲き'):
            self.assertEqual(apply_readings(text), text)

    def test_every_voice_gets_shared_rule(self):
        import scripts.synthesize_narration as sn
        for speaker in (2, 3, 108):
            with patch.object(sn.requests, 'post') as post, patch.object(sn.name_reading_guard, 'prepare_query', return_value={}), \
                 patch.object(sn.name_reading_guard, 'validate_query', return_value={}), patch.object(Path, 'write_text'), patch.object(Path, 'write_bytes'):
                post.return_value.json.return_value = {}
                post.return_value.content = b'wav'
                self.assertTrue(sn.synth_one('3分の1', speaker, Path('test.wav')))
                self.assertEqual(post.call_args_list[0].kwargs['params']['text'], 'さんぶんの1')

    def test_saved_counter_queries(self):
        rows = json.loads((Path(__file__).parent/'fixtures/number_readings/counters.json').read_text(encoding='utf8'))
        self.assertEqual(len(rows), 160)
        for row in rows:
            self.assertIn(row['observed'], row['expected'], row['text'])
            self.assertEqual(apply_readings(row['text']), row['text'])

    @unittest.skipUnless(os.getenv('COLLESPO_TEST_VOICEVOX_URL'), '実エンジンは明示時のみ')
    def test_live_queries(self):
        import requests
        session = requests.Session(); session.trust_env = False
        url = os.environ['COLLESPO_TEST_VOICEVOX_URL']
        rows = json.loads((Path(__file__).parent/'fixtures/number_readings/counters.json').read_text(encoding='utf8'))
        for speaker in (2, 3):
            for text, expected in [(r['text'], r['expected']) for r in rows] + [
                    ('3分の1', ['サンブンノイチ']), ('三分の一', ['サンブンノイチ']),
                    ('３分の２以上', ['サンブンノニイジョオ']), ('3分', ['サンプン'])]:
                response = session.post(url+'/audio_query', params={'text': apply_readings(text), 'speaker': speaker}, timeout=30)
                response.raise_for_status()
                got = ''.join(m['text'] for p in response.json()['accent_phrases'] for m in p['moras'])
                self.assertIn(got, expected, (speaker, text, got))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
