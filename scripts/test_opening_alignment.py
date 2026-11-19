import io
from contextlib import redirect_stdout
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opening_alignment as alignment
import render_timeline


class OpeningAlignmentTests(unittest.TestCase):
    def test_hook_overrules_layout_and_voice_can_supply_a_number(self):
        doc = {'segments': [
            {'meta': {'opening_hook': {'subject': '大谷翔平', 'value': 2, 'unit': '本塁打'}},
             'text': '試合を振り返ります。'},
            {'text': '大谷翔平は３打点です。'},
            {'text': '5安打です。'},
        ]}
        report = alignment.inspect('大谷 ２本塁打３打点5安打 #Shorts', doc, recorded=['別の札'])
        self.assertEqual(report['opening_source'], 'hook')
        self.assertEqual(report['subjects'], [dict(subject='大谷翔平', opening=True, voice=True)])
        self.assertEqual([(n['opening'], n['voice']) for n in report['numbers']],
                         [(True, False), (False, True), (False, False)])
        self.assertEqual([w['value'] for w in report['warnings']], ['5安打'])

    def test_reversed_score_and_other_subject_do_not_pass(self):
        doc = {'segments': [{'meta': {'head': '日本対ブラジル 3-2'}, 'text': '日本は3対2です。'}]}
        report = alignment.inspect('11月18日 日本対パラグアイは2-3', doc)
        self.assertEqual(report['warnings'], [
            dict(code='subject_missing_from_opening', value='パラグアイ'),
            dict(code='number_missing_from_opening_and_voice', value='2-3'),
        ])

    def test_calendar_and_age_class_are_not_stats(self):
        report = alignment.inspect('2026年11月18日 U21日本対エジプト 19時15分',
                                   {'segments': [{'meta': {'head': 'U21日本 対 エジプト 19:15'},
                                                  'text': '19時15分です。'}]})
        self.assertEqual(report['warnings'], [])
        self.assertEqual(len(report['numbers']), 1)

    def test_number_in_a_different_unit_does_not_count(self):
        report = alignment.inspect('塩貝健人が2得点',
                                   {'segments': [{'meta': {'head': '塩貝健人 2部でプレー'},
                                                  'text': '塩貝健人は2部でプレーします。'}]})
        self.assertEqual([row['value'] for row in report['warnings']], ['2得点'])

    def test_leeds_is_not_extracted_from_the_word_series(self):
        report = alignment.inspect('ドジャースの地区シリーズ 第3戦',
                                   {'segments': [{'meta': {'head': 'ドジャース 第三戦'},
                                                  'text': '第3戦の結果です。'}]})
        self.assertEqual(report['warnings'], [])
        self.assertEqual([item['subject'] for item in report['subjects']], ['ドジャース'])

    def test_years_since_an_event_are_checked_and_known_short_club_names_are_matched(self):
        report = alignment.inspect('PSVが50年ぶりに勝利',
                                   {'segments': [{'meta': {'head': 'PSVが勝利'}, 'text': 'PSVの結果です。'}]})
        self.assertEqual([row['value'] for row in report['warnings']], ['50年ぶり'])
        self.assertEqual([row['subject'] for row in report['subjects']], ['PSV'])

    def test_national_squad_and_opponent_names_extend_the_live_player_list(self):
        catalogues = {
            'soccer_national_squad.json': {'source_url': 'https://www.jfa.jp/example/',
                'players': [{'name_jp': '中村敬斗', 'name_en': 'Keito Nakamura', 'reading': 'ナカムラケイト'}]},
            'soccer_national_opponent_names.json': {'Vinícius Júnior': {
                'name': 'ヴィニシウス・ジュニオール', 'short': 'ヴィニシウス'}},
        }
        load = alignment.read
        alignment.name_groups.cache_clear()
        self.addCleanup(alignment.name_groups.cache_clear)
        with patch.object(alignment, 'read', side_effect=lambda p: catalogues[p.name] if p.name in catalogues else load(p)):
            report = alignment.inspect('中村敬斗とヴィニシウスが得点',
                                       {'segments': [{'meta': {'head': 'ヴィニシウス・ジュニオールが得点'},
                                                      'text': 'ナカムラケイトとヴィニシウスです。'}]})
        self.assertEqual([row['value'] for row in report['warnings']], ['中村敬斗'])
        self.assertTrue(next(row for row in report['subjects'] if row['subject'] == '中村敬斗')['voice'])

    def test_missing_opening_is_counted_separately(self):
        report = alignment.inspect('大谷翔平が2本塁打', {'segments': [{'text': '大谷翔平です。'}]})
        self.assertEqual(report['missing'], ['opening'])
        self.assertEqual(report['warnings'], [])

    def test_formatter_records_only_first_card_text(self):
        from PIL import Image
        rows = [{'text': 'ドジャース', 'role': 'text'}, {'text': '声だけ', 'role': 'caption'},
                {'text': 'コレスポ', 'role': 'header'}, {'text': 'MLB公式', 'role': 'source'}]
        image = Image.new('RGB', (1, 1))
        lines = [{'text': '最初'}, {'text': '次'}]
        timeline = render_timeline.Recorder(30, lines)
        timeline.select(lines[0], 0)
        timeline.write(io.BytesIO(), b'\0', image)
        image.info['v3_layout'] = rows
        timeline.write(io.BytesIO(), b'\0', image)
        timeline.select(lines[1], 1)
        image.info['v3_layout'] = [{'text': '後の札', 'role': 'text'}]
        timeline.write(io.BytesIO(), b'\0', image)
        self.assertEqual(timeline.opening_card, ['ドジャース'])

    def test_report_is_written_and_write_failure_does_not_raise(self):
        doc = {'segments': [{'meta': {'head': 'パドレス'}, 'text': 'パドレスです。'}]}
        load = alignment.read

        def saved(path):
            path = Path(path)
            if path == Path('narration.json'):
                return doc
            return load(path) if path.is_absolute() else None

        for fail in (None, OSError('unwritable')):
            out = io.StringIO()
            with patch.object(alignment, 'read', side_effect=saved), \
                 patch('voice_manifest.write_json', side_effect=fail) as write, redirect_stdout(out):
                alignment.before_upload('ドジャース', 'narration.json', 'build/short.mp4', 'daily')
            target, report = write.call_args.args
            self.assertEqual(target.parent, Path('build/opening_alignment'))
            self.assertEqual(report['warnings'][0]['value'], 'ドジャース')
            self.assertIn('[warn]', out.getvalue())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
