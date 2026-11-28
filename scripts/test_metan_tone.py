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

    def test_mada_yo_is_not_an_ending_error(self):
        # 「まだよ」の「だよ」は語尾の「だよ」ではない（直した後の文が誤検出されて原稿が止まった）。
        self.assertEqual(metan_tone.problems('球団の正式発表はまだよ。まだね。'), [])
        self.assertEqual(metan_tone.fix('球団の正式発表はまだよ。'), '球団の正式発表はまだよ。')
        self.assertEqual(len(metan_tone.problems('まだだよ。')), 1)

    def test_iru_endings_and_mada_yo(self):
        # 11/25 19:00 の回：「下にいます」が直らず sanity で止まった。直した「まだよ」を「だよ」と誤検出しない。
        self.assertEqual(metan_tone.fix('サバフは24位より下にいます。'), 'サバフは24位より下にいるわ。')
        self.assertEqual(metan_tone.fix('日本人が2人います。'), '日本人が2人いるわ。')
        self.assertEqual(metan_tone.problems('球団の正式発表はまだよ。'), [])
        self.assertEqual(metan_tone.problems('そう思います。'), ['ます'])

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


class OutroRotation(unittest.TestCase):
    def test_four_outros_rotate_by_day_and_stay_in_tone(self):
        # 11/28 締めを理由つきの4種に。続く4日は全部違う文、めたんの側は語尾の検査を通る。
        from datetime import date, timedelta
        import ui_tone
        days = [metan_tone.outro_index(date(2026, 11, 28) + timedelta(days=i)) for i in range(4)]
        self.assertEqual(sorted(days), [0, 1, 2, 3])
        for casual, polite in metan_tone.OUTROS:
            self.assertEqual(list(metan_tone.check([dict(kind='outro', text=casual, speaker=2)])), [], casual)
            self.assertEqual(ui_tone.text(casual), polite)
            self.assertTrue(any(word in casual for word in ('高評価', '登録')))

    def test_tests_and_local_runs_keep_the_first_outro(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, GITHUB_ACTIONS='true', COLLESPO_OUTRO_ROTATE='off'):
            self.assertEqual(metan_tone.outro_index(), 0)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': ''}):
            self.assertEqual(metan_tone.outro_index(), 0)


class Liven(unittest.TestCase):
    def test_reaction_once_after_big_number_and_only_with_room(self):
        # 11/28 散歩のノリ：要の数字を聞いた直後に、ずんだもんの反応を1回だけ。尺に余裕が無ければ足さない。
        import topic_dialogue as td
        def segs():
            return [dict(kind='list', text='どうなったのだ？', speaker=td.ZUNDA, meta={}),
                    dict(kind='list', text='ええ。6年で総額1億ドルよ。', speaker=td.METAN, meta=dict(big=dict(value='1'))),
                    dict(kind='list', text='ほかの選手はどうなのだ？', speaker=td.ZUNDA, meta={}),
                    dict(kind='list', text='そうね。比べると大きいわ。', speaker=td.METAN, meta={})]
        lively = td.liven(segs(), 'k')
        words = [s['meta'].get('reaction_word') for s in lively if s['meta'].get('reaction_word')]
        self.assertEqual(len(words), 1)
        self.assertTrue(lively[2]['text'].startswith(words[0]))
        self.assertFalse(td.NUMBER.search(words[0]))
        self.assertEqual(td.liven(lively, 'k'), lively)
        self.assertFalse(any(s['meta'].get('reaction_word') for s in td.liven(segs(), 'k', limit=8)))
