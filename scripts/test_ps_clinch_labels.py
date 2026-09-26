"""Division champions, clinched berths and projected seeds are different facts."""
import itertools
import unittest
from unittest.mock import patch

import generate_morning_short as video
import postseason
import race_words


class ClinchLabels(unittest.TestCase):
    def test_flag_combinations_never_promote_a_berth_to_division_title(self):
        for champ, berth, wild in itertools.product([False,True],repeat=3):
            row=dict(div_champ=champ,clinched=berth,wc_clinched=wild,magic=None,wc_gb='+2.0')
            expected='地区優勝' if champ else 'PS進出' if berth or wild else None
            self.assertEqual(race_words.clinch_label(row),expected)
            if expected:
                self.assertEqual(video.ps_right(row),('決定',expected,True))
            else:
                self.assertNotIn('決定',video.ps_right(row))

    def test_leading_or_magic_zero_alone_is_not_a_championship(self):
        for row in ({'route':'地区首位','div_rank':1}, {'magic':0}, {'wc_gb':None}):
            self.assertIsNone(race_words.clinch_label(row))
            self.assertNotEqual(video.ps_right(row)[1],'地区優勝')

    def test_official_flags_survive_fetch_and_rendering(self):
        # Synthetic flags (not a historical claim): champion and berth-only.
        source={'records':[{'league':{'id':103},'division':{'id':202},'teamRecords':[
            {'team':{'id':114,'name':'Cleveland Guardians'},'clinched':True,'divisionChamp':True},
            {'team':{'id':145,'name':'Chicago White Sox'},'clinched':True,'divisionChamp':False,'wildCardClinched':True}
        ]}]}
        with patch.object(postseason,'_get',return_value=source):
            teams=postseason.fetch('2026')
        self.assertEqual([video.ps_right(t)[1] for t in teams],['地区優勝','PS進出'])

    def test_unsettled_division_leader_is_not_the_last_wildcard(self):
        self.assertEqual(video.ps_right({'div_rank':1,'magic':None,'wc_gb':None}),
                         ('首位','地区（未確定）',False))

    def test_elimination_is_not_a_number_of_games(self):
        self.assertEqual(video.ps_right({'wc_gb':'E'}),('敗退','PS進出',False))

    def test_actual_drawn_rows_and_heading_distinguish_projection(self):
        league={'league_short':'ア・リーグ',
                'leaders':[dict(id=114,name='CLE',div_champ=True,clinched=True,w=83,l=76)],
                'wildcards':[dict(id=145,name='CWS',div_champ=False,clinched=True,w=82,l=77)]}
        drawn=[]
        original=video.ImageDraw.ImageDraw.text
        def record(draw,xy,text,*args,**kwargs):
            drawn.append(str(text))
            return original(draw,xy,text,*args,**kwargs)
        with patch.object(video.ImageDraw.ImageDraw,'text',record):
            frame=video.render_ps_league(1,league,'103')
        self.assertEqual(frame.size,(1080,1920))
        self.assertEqual(drawn.count('地区優勝'),1)
        self.assertEqual(drawn.count('PS進出'),1)
        self.assertIn('地区首位　第1〜3シード',drawn)
        self.assertNotIn('地区優勝　第1〜3シード',drawn)


if __name__=='__main__':
    unittest.main(argv=['test_ps_clinch_labels'])
