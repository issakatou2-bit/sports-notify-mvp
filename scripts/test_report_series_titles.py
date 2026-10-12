import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parent))
import report_series_titles as report
class ReportTests(unittest.TestCase):
    def test_surname_team_and_excluded_kinds(self):
        row=report.compare('【MLB】ホワイトソックス村上、1安打｜結果 #Shorts','morning_local',['村上宗隆'])
        self.assertIn('村上宗隆の今日',row['proposal']);self.assertIn('1安打',row['proposal'])
        for kind in ('daily','morning','morning_press'):
            text='【MLB】村上宗隆のホワイトソックスが勝利 #Shorts'
            self.assertEqual(report.compare(text,kind,['村上宗隆'])['proposal'],text)
    def test_period_inclusive_and_unknown_name(self):
        videos={'daily':{'2026-09-28':dict(video_id='old',title='旧'), '2026-09-29':dict(video_id='first',title='不明'), '2026-10-12':dict(video_id='last',title='今日'),'2026-10-13':dict(video_id='future',title='未来')}}
        rows=report.rows(videos,date(2026,10,12));self.assertEqual([r['video_id'] for r in rows],['first','last'])
        self.assertTrue(all(r['current']==r['proposal'] for r in rows))
if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
