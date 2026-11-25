import json
from pathlib import Path
import tempfile
import unittest

import metan_tone
import sanity


class MetanToneTest(unittest.TestCase):
    def test_fixes_known_endings_and_preserves_nested_quotes(self):
        line = '残留争いです。「本人は『別の話』です、とのことです。」勝点で上回りました。どうでしょう？'
        wanted = '残留争いなのよ。「本人は『別の話』です、とのことです。」勝点で上回ったわ。どうかしら？'
        self.assertEqual(metan_tone.fix(line), wanted)
        self.assertEqual(metan_tone.problems(wanted), [])

    def test_replaced_text_is_not_rewritten_by_a_later_rule(self):
        # まだです→まだよ（「まよ」にならない）、なんです→なのよ、そうだよ→そうよ
        self.assertEqual(metan_tone.fix('球団の正式発表はまだです。'), '球団の正式発表はまだよ。')
        self.assertEqual(metan_tone.fix('そういうことなんです。'), 'そういうことなのよ。')
        self.assertEqual(metan_tone.fix('そうだよ。'), 'そうよ。')
        self.assertEqual(metan_tone.fix('行くんだよ。'), '行くのよ。')

    def test_detects_each_bad_ending_and_allows_similar_words(self):
        line = '1点です。話します。昨日でした。勝ちました。どうでしょう？確認してください。そうだよ。そうだね。見直しよう。'
        self.assertEqual(len(metan_tone.problems(line)), 9)
        self.assertEqual(metan_tone.problems('見ていきましょう。どうかしら？'), [])

    def test_sanity_rejects_only_metan_line(self):
        segments = [dict(text='確認してください。', speaker=n) for n in (2, 3, 108)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'narration.json'
            path.write_text(json.dumps({'segments': segments}), encoding='utf-8')
            self.assertEqual(sanity.check_narration([path]), [
                'narration.json の1番目: めたんの語尾「ください」'])

    def test_unbracketed_quote_and_caption_units(self):
        quote = dict(speaker=2, text='いい試合でした。', meta={'quote_rows': [
            {'read': True, 'said': 'いい試合でした'}]})
        result = dict(speaker=2, text='先制しました。1得点です。',
                      caption_units=['先制しました。', '1得点です。'])
        metan_tone.revise([quote, result])
        self.assertEqual(quote['text'], 'いい試合でした。')
        self.assertEqual(result['caption_units'], ['先制したわ。', '1得点よ。'])
        self.assertEqual(list(metan_tone.check([quote, result])), [])
