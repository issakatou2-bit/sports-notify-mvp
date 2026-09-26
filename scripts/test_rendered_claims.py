"""Mutation tests: reproduce missed false claims, not only the repaired helper."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import check_rendered_claims as guard
import generate_morning_short as video

DAY = '2026-09-25'


def ps():
    return {'date':DAY,'phase':'regular','leagues':{'103':{'league_short':'ア・リーグ',
        'leaders':[{'id':114,'name':'CLE','division':'中','div_champ':True,'clinched':True,'w':80,'l':60}],
        'wildcards':[{'id':145,'name':'CWS','division':'中','div_champ':False,'clinched':True,'w':79,'l':61}]}}}


def soccer():
    def club(name, pos):
        return dict(team=name,position=pos,points=10,played=5,gf=7,ga=4,jp=[])
    line={'at':4,'label':'CL圏内','inside':[club('A',4)],'outside':[club('B',5)],'diff':0}
    return {'date_jst':DAY,'picked':['PL'],'competitions':[
        {'code':'PL','name_jp':'プレミアリーグ','ready':True,'played':5,'jp':[],'lines':[line]}]}


class RenderedClaims(unittest.TestCase):
    def test_good_ps(self):
        self.assertFalse(guard.check_ps(ps(),DAY)[0])

    def test_original_clinched_bug_is_caught_from_drawing(self):
        with patch.object(video,'ps_right',return_value=('決定','地区優勝',True)):
            errors=guard.check_ps(ps(),DAY)[0]
        self.assertTrue(any('CWS' in e and '根拠' in e for e in errors))

    def test_two_champions_in_same_division(self):
        data=ps(); data['leagues']['103']['wildcards'][0]['div_champ']=True
        self.assertTrue(any('複数' in e for e in guard.check_ps(data,DAY)[0]))

    def test_dates_missing_empty_and_unknown_phase_stop(self):
        for data in [{},dict(ps(),date='2026-09-24'),dict(ps(),phase='postseason')]:
            self.assertTrue(guard.check_ps(data,DAY)[0])
        self.assertTrue(guard.check_soccer(dict(soccer(),date_jst=None),DAY)[0])

    def test_series_scope_is_not_claimed_as_a_passed_visual_audit(self):
        errors,cards,scope=guard.check_ps(dict(ps(),phase='postseason',series=[{}]),DAY)
        self.assertFalse(errors)
        self.assertFalse(cards)
        self.assertIn('対象外',scope[0])

    def test_good_soccer_tied_points(self):
        self.assertFalse(guard.check_soccer(soccer(),DAY)[0])

    def test_soccer_fake_confirmation_rendered_from_label_is_caught(self):
        data=soccer(); data['competitions'][0]['lines'][0]['label']='CL出場決定'
        self.assertTrue(any('確定扱い' in e for e in guard.check_soccer(data,DAY)[0]))

    def test_soccer_wrong_gap_and_swapped_rank_sides(self):
        for key,value in [('diff',2),('at',3)]:
            data=soccer(); data['competitions'][0]['lines'][0][key]=value
            self.assertTrue(guard.check_soccer(data,DAY)[0])

    def test_soccer_missing_points_are_not_zero(self):
        data=soccer(); data['competitions'][0]['lines'][0]['inside'][0].pop('points')
        self.assertTrue(guard.check_soccer(data,DAY)[0])

    def test_soccer_rendered_stats_corruption_is_caught(self):
        original=video.race_row
        def corrupt(draw,y,item,*a,**kw):
            modified=deepcopy(item); modified['points']+=1
            return original(draw,y,modified,*a,**kw)
        with patch.object(video,'race_row',corrupt):
            self.assertTrue(any('描画の順位' in e for e in guard.check_soccer(soccer(),DAY)[0]))


if __name__=='__main__':
    unittest.main(argv=['test_rendered_claims'])
