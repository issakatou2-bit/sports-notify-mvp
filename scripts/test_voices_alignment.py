"""10/24夕方の実材料で、敬語化から描画・効果音までの引用を照合する。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import comment_render as cr
import daily_v3
import generate_morning_short as g
import host_split
import review_render_v3 as r3
import sound_mix


class VoicesAlignment(unittest.TestCase):
    def program(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/comment/voices-20261024.json').read_text(encoding='utf-8'))
        data = fixture['data']
        import ui_voice_policy
        with patch.dict(os.environ, fixture['env']), patch.object(r3, 'LOOK', 'v4'), patch.object(ui_voice_policy,'decide',return_value=dict(version=1,planned_host='ui',reason=None,comparison_eligible=True,mode='live')):
            narration = g.build_narration(data, 'voices')
            design = daily_v3.prepare(data, narration, 'voices')
            original = copy.deepcopy(narration)
            adapted = host_split.adapt(narration, 'morning_voices', day='2026-10-24')
        return data, design, original, adapted

    def test_today_quotes_survive_host_assignment_and_repeated_tone(self):
        data, _, original, adapted = self.program()
        self.assertEqual(adapted['segments'][0]['kind'],'intro')
        self.assertEqual(adapted['segments'][-1]['kind'],'outro')
        self.assertTrue(any(s.get('speaker')==3 for s in adapted['segments']))
        self.assertNotIn('host_assignment',adapted)  # 2人の回を単独話者へ割り付けない。
        self.assertEqual(original,adapted)
        for before, after in zip(original['segments'], adapted['segments']):
            if 'quote_rows' in before['meta']:
                self.assertEqual(before['meta']['quote_rows'], after['meta']['quote_rows'])
            issues = []
            rows = cr.voices_for_segment(after, data['voices'])
            timed = cr.reading_times(rows, after['text'], 20, issues)
            self.assertEqual(issues, [])
            self.assertEqual(len(rows), len(timed))
            for row in rows:
                if not row.get('fact') and row.get('read') is not False:
                    self.assertIn(row['said'].strip().rstrip('。！!、.'), after['text'])

    def test_only_mismatched_quote_is_removed_and_cursor_recovers(self):
        rows = [dict(said=s) for s in ('先の引用。', '同じ冒頭が十二文字以上ありますが内容は元のまま。', '最後の引用。')]
        spoken = '先の引用。同じ冒頭が十二文字以上ありますが内容は言い換え。最後の引用。'
        before = copy.deepcopy(rows)
        issues = []
        timed = cr.reading_times(rows, spoken, 15, issues)
        self.assertEqual([r['said'] for r in timed], [rows[0]['said'], rows[2]['said']])
        self.assertEqual(issues[0]['action'], 'omit_screen_quote')
        self.assertEqual(issues[0]['spoken'], spoken)
        self.assertEqual(rows, before)
        self.assertAlmostEqual(timed[-1]['at'], spoken.index('最後の引用') * 15 / len(spoken))
        for body, reason in [('後の引用。先の引用。', 'out_of_order'), ('後の引用。', 'missing_or_changed')]:
            issues = []
            timed = cr.reading_times([dict(said=s) for s in ('先の引用。', '後の引用。')], body, 10, issues)
            self.assertEqual(len(timed), 1)
            self.assertEqual(issues[0]['reason'], reason)
        issues = []
        self.assertEqual(cr.reading_times([dict(said='元の引用。', clip=True)], '別の原稿。', 10, issues), [])
        self.assertEqual(len(issues), 1)

    def test_old_changed_script_finishes_mix_and_records_omission(self):
        data, design, original, adapted = self.program()
        # 修正前の敬語化を再現。既に作った音声や別経路の変更でも落とさない。
        bad = copy.deepcopy(adapted)
        index=next(i for i,s in enumerate(original['segments'])
                   if any(r.get('read') and not r.get('fact') for r in s['meta'].get('quote_rows',[])))
        quote=next(r for r in original['segments'][index]['meta']['quote_rows'] if r.get('read') and not r.get('fact'))
        # 引用を別文に変えた既存音声を再現する。反応や題は巻き込まない。
        bad['segments'][index]['text']='元の引用と異なる敬語の文です。'
        seg = bad['segments'][index]
        issues = []
        self.assertFalse(any(cue[1] in ('notify', 'marker') for cue in cr.voices_cues(seg, data['voices'], 12, issues=issues)))
        self.assertEqual(len(issues), 1)
        with patch.object(cr, 'unified_comments', return_value='frame') as draw:
            self.assertEqual(cr.voices_screen(2, seg, data['voices'], 12), 'frame')
            self.assertEqual(draw.call_args.args[1], [])
        with tempfile.TemporaryDirectory() as folder, patch.object(sound_mix, 'mix_short_file', return_value='mixed') as mix:
            self.assertEqual(daily_v3.mix('audio.wav', bad['segments'], [12]*len(bad['segments']), design, folder), 'mixed')
            report = json.loads((Path(folder)/'quote_alignment.json').read_text(encoding='utf-8'))
            self.assertEqual(len(report['omissions']), 1)
            self.assertEqual(report['omissions'][0]['segment'], index)
            self.assertEqual(report['omissions'][0]['said'], quote['said'])
            self.assertTrue(mix.call_args.kwargs['cues'])
            daily_v3.mix('audio.wav', adapted['segments'], [12]*len(bad['segments']), design, folder)
            self.assertEqual(json.loads((Path(folder)/'quote_alignment.json').read_text(encoding='utf-8'))['omissions'], [])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
