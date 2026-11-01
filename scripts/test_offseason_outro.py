"""保存実データで共通締めの季節切替と従来出力を確認。通信・合成なし。"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import post_common as pc
import review_render_v3 as r3
import ui_tone

ROOT = Path(__file__).resolve().parents[1]
SAVED = json.loads((ROOT/'scripts/fixtures/offseason-outro/saved.json').read_text(encoding='utf-8'))


class OffseasonOutro(unittest.TestCase):
    def test_saved_empty_day_uses_existing_decision_and_live_slots(self):
        self.assertEqual(SAVED['no_games']['date_jst'], '2026-10-30')
        self.assertEqual(SAVED['no_games']['game_count'], 0)
        ps = SAVED['offseason']
        self.assertTrue(pc.mlb_offseason(ps, '2026-10-30'))
        self.assertEqual(r3.outro_text(ps, '2026-10-30'), r3.OFFSEASON_OUTRO_TEXT)
        with patch.object(pc, '_postseason_now', return_value=ps):
            self.assertEqual([r[0] for r in pc.lineup()], ['morning_voices', 'morning_press', 'daily_soccer'])
            self.assertEqual(r3.outro_rows('morning_voices'), [('18:00', '現地の報道'), ('19:30', '欧州サッカー')])

    def test_saved_game_day_and_active_season_keep_every_character(self):
        self.assertEqual(SAVED['game_day']['game_count'], 1)
        # 決着結果を届ける当日と、PS開催中の保存材料。
        for ps, day, expected in ((SAVED['offseason'], SAVED['game_day']['date_jst'], SAVED['decisive_day_lineup']),
                                  (SAVED['active'], '2026-10-07', SAVED['active_lineup'])):
            self.assertFalse(pc.mlb_offseason(ps, day))
            self.assertEqual(r3.outro_text(ps, day), r3.INSEASON_OUTRO_TEXT)
            with patch.object(pc, 'mlb_offseason', return_value=False):
                for exclude in ['', *[r[0] for r in pc.DAILY_LINEUP]]:
                    self.assertEqual(pc.lineup(exclude, ps), [tuple(r) for r in expected if r[0] != exclude])
        self.assertEqual(r3.INSEASON_OUTRO_TEXT, 'コレスポでは毎日、日本人選手の成績や、明日の試合の見どころを届けています。チャンネル登録して、また見に来てくださいね。')

    def test_missing_invalid_and_next_year_keep_legacy_text(self):
        for ps in ({}, {'series': None}, {'series': [None]}, [], None):
            with patch.object(pc, '_postseason_now', return_value=ps):
                self.assertEqual(r3.outro_text(today='2026-10-30'), r3.INSEASON_OUTRO_TEXT)
        for day in ('not-a-date', '2027-03-01'):
            self.assertEqual(r3.outro_text(SAVED['offseason'], day), r3.INSEASON_OUTRO_TEXT)
        with patch.object(pc, '_postseason_now', side_effect=OSError):
            self.assertEqual(r3.outro_text(), r3.INSEASON_OUTRO_TEXT)

    def test_ui_both_seasons_and_quotes_are_idempotent(self):
        for text in (r3.INSEASON_OUTRO_TEXT, r3.OFFSEASON_OUTRO_TEXT):
            polite = ui_tone.text(text)
            self.assertIn('をお届けしています', polite)
            self.assertEqual(ui_tone.text(polite), polite)
            self.assertEqual(ui_tone.text('「'+text+'」'), '「'+text+'」')

    def test_existing_renderer_supports_inseason_and_zero_one_rows(self):
        import v3_rules
        with patch.object(pc, '_postseason_now', return_value=SAVED['active']):
            self.assertEqual(r3.outro_rows(), [(r[3], r[1]) for r in sorted(SAVED['active_lineup'], key=lambda r: r[3])])
        for rows in ([], [('19:30', '欧州サッカー')]):
            with patch.object(r3, 'outro_rows', return_value=rows):
                image = r3.outro(3)
                self.assertTrue(image.info['v3_outro'])
                self.assertEqual(image.size, (1080, 1920))
                self.assertFalse(v3_rules.check_spacing(image))
                # 締めでも空札の検出は保つ。
                image.info['v3_layout'].append(dict(role='card', box=[72, 850, 500, 1100]))
                if r3.LOOK == 'v4':
                    self.assertTrue(v3_rules.check_spacing(image))

    def test_body_is_unchanged_and_27_second_gate_remains(self):
        import short_content
        import soccer_selected_preview
        from test_short_content import asset
        doc, material = asset()
        doc['segments'].append(dict(kind='outro', text=r3.OFFSEASON_OUTRO_TEXT))
        self.assertEqual(short_content.MIN_SECONDS-short_content.SHORT_GRACE, 27)
        for day in ('2026-10-14', '2026-10-15'):
            fixture = json.loads((ROOT/f'scripts/fixtures/soccer-length/{day}.json').read_text(encoding='utf-8'))
            programs = []
            for closing in (r3.INSEASON_OUTRO_TEXT, r3.OFFSEASON_OUTRO_TEXT):
                with patch.object(r3, 'OUTRO_TEXT', closing):
                    programs.append(soccer_selected_preview.program(fixture['data'])['narration']['segments'])
            self.assertEqual([s for s in programs[0] if s['kind'] != 'outro'],
                             [s for s in programs[1] if s['kind'] != 'outro'])
            body = sum(seconds for seg, seconds in zip(fixture['narration']['segments'], fixture['audio_seconds']) if seg['kind'] != 'outro')
            self.assertGreaterEqual(body, 27)
        for seconds in (26.99, 27):
            report = short_content.assess(doc, [seconds/len(doc['segments'])]*len(doc['segments']), material)
            length_errors = [r for r in report['reasons'] if '下限' in r]
            self.assertEqual(bool(length_errors), seconds < 27)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
