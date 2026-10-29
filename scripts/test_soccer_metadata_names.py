"""題・説明欄の表示名と100字境界を、送信せず固定材料で確認。"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import club_display_names as clubs
import soccer_now
import soccer_results
import upload_youtube as upload


def material():
    player=dict(name='鎌田大地', club='パレス', status='starter', goals=1,
                assists=0, event_id='fixture')
    game=dict(id='fixture', home=dict(name_en='Lyon', name_jp='リヨン'),
              away=dict(name_en='Crystal Palace', name_jp='パレス'),
              score=dict(home=3, away=2), finished_utc='2026-10-15T21:00:00Z',
              rank_changes=[])
    return dict(can_make=True, date_jst='2026-10-15', games=[game], players=[player],
                preview_followup=dict(games=[dict(event_id='fixture', answer=player)]),
                voices=[])


class Tests(unittest.TestCase):
    def test_reported_results_title_and_description(self):
        data=material(); before=copy.deepcopy(data)
        self.assertEqual(soccer_results.title(data),
                         '【欧州サッカー】昨夜の注目試合 リヨン 3-2 クリスタルパレス｜鎌田大地がゴール #Shorts')
        self.assertIn('（クリスタルパレス）', '\n'.join(soccer_results.description_lines(data)))
        del data['preview_followup']
        self.assertIn('リヨン 3-2 クリスタルパレス', soccer_results.title(data))
        self.assertEqual(before['games'], data['games'])
        self.assertEqual(clubs.display('Crystal Palace', short=True), 'パレス')

    def test_title_length_boundaries_and_club_integrity(self):
        head='【欧州サッカー】リヨン 3-2 クリスタルパレス'
        exact=head+'｜'+'補'*(100-len(head)-1)
        self.assertEqual(clubs.youtube_title(exact), exact)
        self.assertEqual(clubs.youtube_title(exact+'足'), head)
        self.assertEqual(clubs.youtube_title(head+'｜短い補足｜'+'補'*100), head+'｜短い補足')
        self.assertEqual(clubs.youtube_title(head), head)
        self.assertEqual(clubs.youtube_title('パレス対マンC'), 'クリスタルパレス対'+clubs.display('Manchester City'))
        self.assertEqual(clubs.youtube_title('PSG対パレス'), clubs.display('Paris Saint-Germain FC')+'対クリスタルパレス')
        self.assertEqual(clubs.display_text('パレス'), 'パレス')  # 狭い画面の既存処理は維持
        self.assertEqual(upload.club_display_description('パレスの結果'), 'クリスタルパレスの結果')
        with self.assertRaises(ValueError):clubs.youtube_title('題'*101)
        self.assertEqual(clubs.youtube_title('題'*100+' #Shorts'), '題'*100)
        data=material();data['preview_followup']['games'][0]['answer']['name']='選手'*60
        self.assertEqual(soccer_results.title(data), head.replace('【欧州サッカー】', '【欧州サッカー】昨夜の注目試合 '))

    def test_results_upload_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'results.json';path.write_text(json.dumps(material()), encoding='utf8')
            meta=upload.build_metadata(str(path), '10月16日', 'soccer_results', narration_path='')['snippet']
        self.assertIn('リヨン 3-2 クリスタルパレス', meta['title'])
        self.assertIn('（クリスタルパレス）', meta['description'])
        self.assertLessEqual(len(meta['title']), 100)

    def test_other_scheduled_slots_use_display_and_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            games=Path(folder)/'games.json';games.write_text('{"games": []}', encoding='utf8')
            narr=Path(folder)/'narration.json'
            for kind, mode in [('daily', 'preview'), ('soccer_race', 'race'), ('soccer_week', 'week')]:
                for extra in ('', '｜'+'補'*100):
                    with self.subTest(kind=kind, long=bool(extra)):
                        title='【欧州サッカー】パレスの試合'+extra
                        narr.write_text(json.dumps(dict(title=title, soccer_v4_mode=mode)), encoding='utf8')
                        with patch.dict(os.environ, {'COLLESPO_SHORT_LOOK':'v4'}):
                            meta=upload.build_metadata(str(games), '10月16日', kind,
                                                       narration_path=str(narr), sport='soccer')['snippet']
                        self.assertIn('クリスタルパレス', meta['title'])
                        self.assertNotIn('クリスタル・パレス', meta['title'])
                        self.assertLessEqual(len(meta['title']), 100)

    def test_immediate_results_metadata(self):
        data=material();meta=soccer_now.metadata(data)
        self.assertEqual(meta['title'], '鎌田大地がゴール｜リヨン対クリスタルパレス')
        data['players'][0]['name']='選手'*40
        self.assertLessEqual(len(soccer_now.metadata(data)['title']), 100)


if __name__=='__main__':
    unittest.main(argv=['test_soccer_metadata_names'])
