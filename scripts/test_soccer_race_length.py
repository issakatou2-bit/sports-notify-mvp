"""10/28・29型（1大会、境目2組、日本人2人）の再発防止。描画・通信なし。"""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]
import soccer_slots_v4 as slots
import sanity_material
import sanity_claims
import short_content


def material(day):
    # 実日の記録と同じ構造。実際の戦績を検証するための資料ではない。
    rows=[dict(position=i,team_en=name,team=name,played=9,points=pts)
          for i,name,pts in [(3,'AS Roma',21),(4,'Como 1907',20),
                             (5,'AC Milan',18),(6,'SSC Napoli',14),
                             (7,'Bologna FC 1909',14)]]
    near=dict(line=5,label='EL圏内',side='outside',diff=5,text='EL圏内まで勝点5')
    jp=[dict(name='菅原由勢',club_jp='カリアリ',position=9 if day==28 else 10,
             points=13,out=False,lines=[near]),
        dict(name='鈴木彩艶',club_jp='パルマ',position=19 if day==28 else 18,
             points=4 if day==28 else 5,out=False,lines=[])]
    lines=[dict(at=4,label='CL圏内',inside=rows[:2],outside=rows[2:4],diff=2),
           dict(at=5,label='EL圏内',inside=rows[1:3],outside=rows[3:5],diff=4)]
    return dict(date_jst=f'2026-10-{day}',updated_at=f'2026-10-{day}T10:00:00Z',
                picked=['SA'],competitions=[dict(code='SA',name_jp='セリエA',
                ready=True,played=9,lines=lines,jp=jp)])


class RaceLength(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',
                       COLLESPO_HOST_SPLIT='',COLLESPO_MOTION='')
        env.start();self.addCleanup(env.stop)
        self.look=patch.object(slots,'enabled',return_value=True)
        self.look.start();self.addCleanup(self.look.stop)

    def test_two_days_keep_boundary_rows_without_padding_and_short_material_is_held(self):
        for day in (28,29):
            data=material(day);original=copy.deepcopy(data)
            narr=slots.program('race',data)['narration'];segs=narr['segments']
            self.assertEqual([s['kind'] for s in segs],['cover','standings','outro'])
            table=segs[1]['meta'];self.assertTrue(3<=len(table['rows'])<=4)
            person=data['competitions'][0]['jp'][0]
            own=next(r for r in table['rows'] if r['team']==table['primary'])
            self.assertEqual((own['position'],own['points']),(person['position'],person['points']))
            self.assertIsNone(own['played'])  # 試合数は推測しない。
            self.assertEqual(data,original)
            self.assertEqual(short_content.assess(narr,[3,12,2],data,maximum=40)['status'],'held')
            self.assertEqual(sanity_material.check(narr,sanity_material.grounding([narr])),[])

    def test_primary_club_is_grounded_without_inheriting_another_person(self):
        narr=slots.program('race',material(28))['narration']
        mats=sanity_material.grounding([narr]);table=narr['segments'][1]
        self.assertIn('カリアリ',table['text'])
        self.assertIsNot(sanity_claims.review('菅原由勢のカリアリは9位で勝点13。',mats),False)
        self.assertIs(sanity_claims.review('菅原由勢のカリアリは9位で勝点99。',mats),False)

    def test_anonymous_continuation_and_wrong_personal_values_still_stop(self):
        narr=slots.program('race',material(29))['narration']
        mats=sanity_material.grounding([narr])
        for text,expected in [('10位で勝点13。',True),('10位で勝点99。',False),('9位で勝点13。',False)]:
            doc=dict(segments=[dict(text='菅原由勢のカリアリ。'),dict(text=text)])
            context=sanity_material.claim_context(doc,text,mats)
            self.assertIs(sanity_claims.review(text,mats,context=context),expected)
        bad=copy.deepcopy(narr)
        next(s for s in bad['segments'] if s['kind']=='standings')['text']='菅原由勢のカリアリは10位で勝点99。'
        self.assertTrue(sanity_material.check(bad,sanity_material.grounding([bad])))

    def test_empty_missing_and_unselected_material_is_not_invented(self):
        self.assertEqual(slots.program('race',dict(date_jst='2026-10-29',picked=[],competitions=[]))['narration']['segments'],[])
        data=material(29);data['competitions'][0]['jp'][1]['points']=None
        data['competitions'].append(dict(code='PL',ready=True,jp=[dict(name='別人',club_jp='別クラブ',position=1,points=99)]))
        narr=slots.program('race',data)['narration']
        extra=[s for s in narr['segments'] if s['kind']=='jp_player']
        self.assertEqual(len(extra),0)
        self.assertTrue(any(s['kind']=='standings' for s in narr['segments']))
        self.assertNotIn('別人',str(narr['segments']))

    def test_original_host_snapshot_includes_added_segments(self):
        captured=[]
        def adapt(narr,kind):
            captured.append(copy.deepcopy(narr['segments']));return narr
        with patch('host_split.adapt',side_effect=adapt):
            narr=slots.program('race',material(29))['narration']
        self.assertEqual(captured[-1],narr['segments'])
        self.assertEqual([s['kind'] for s in captured[-1]],['cover','standings','outro'])

    def test_no_duplicate_clubs_out_players_or_unnecessary_expansion(self):
        data=material(29);comp=data['competitions'][0]
        comp['jp'].insert(1,dict(comp['jp'][0],name='同じクラブの別人'))
        comp['jp'].append(dict(comp['jp'][1],club_jp='別クラブ',name='離脱中',out=True))
        narr=slots.program('race',data)['narration']
        self.assertEqual(len([s for s in narr['segments'] if s['kind']=='jp_player']),0)
        rows=next(s for s in narr['segments'] if s['kind']=='standings')['meta']['rows']
        self.assertEqual(len(rows),len({r['team'] for r in rows}))
        self.assertNotIn('同じクラブの別人',str(narr['segments']))
        self.assertNotIn('離脱中',str(narr['segments']))
        plan=dict(data=data,shared={},narration=dict(segments=[dict(kind='cover',text='長'*180)]))
        original=copy.deepcopy(plan);slots.race_details(plan)
        self.assertEqual(plan,original)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
