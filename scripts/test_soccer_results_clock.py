import sys, unittest
from pathlib import Path
from datetime import datetime,date,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parent))
import soccer_results_clock as clock
import soccer_results as results
class ClockTests(unittest.TestCase):
    def test_winter_end_and_exact_cutoff(self):
        day=date(2026,10,25)
        self.assertTrue(results.in_window(datetime(2026,10,26,6,50,tzinfo=clock.JST),day))
        self.assertTrue(results.in_window(datetime(2026,10,26,7,14,59,tzinfo=clock.JST),day))
        self.assertFalse(results.in_window(datetime(2026,10,26,7,15,tzinfo=clock.JST),day))
        self.assertFalse(results.in_window(datetime(2026,10,25,7,14,59,tzinfo=clock.JST),day))
    def test_latest_closed_night_and_year_end(self):
        self.assertEqual(clock.target_day(datetime(2027,1,1,7,14,tzinfo=clock.JST),scheduled=True),date(2026,12,30))
        self.assertEqual(clock.target_day(datetime(2027,1,1,7,20,tzinfo=clock.JST),scheduled=True),date(2026,12,31))
        self.assertEqual(clock.target_day(datetime(2027,1,1,7,14,tzinfo=clock.JST)),date(2026,12,31))
    def test_cron_and_publication_conditions(self):
        import yaml
        wf=yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/soccer_results.yml').read_text(encoding='utf8'))
        trigger=wf.get('on',wf.get(True));hh,mm=map(int,clock.CONFIG['generate_jst'].split(':'))
        self.assertEqual(trigger['schedule'][0]['cron'],f'{mm} {(hh-9)%24} * * *')
        self.assertFalse(trigger['workflow_dispatch']['inputs']['publish']['default'])
        self.assertIn("vars.SOCCER_RESULTS_PUBLISH == 'true'",wf['jobs']['build']['if'])
        for step in wf['jobs']['build']['steps']:
            if step.get('name') in ('Upload to YouTube','Require a future reservation','Confirm reservation'):
                self.assertIn("vars.SOCCER_RESULTS_PUBLISH == 'true'",step['if'])
                self.assertIn('inputs.publish',step['if'])
if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
