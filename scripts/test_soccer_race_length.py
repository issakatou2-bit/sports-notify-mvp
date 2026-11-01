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

    def test_two_days_add_personal_club_facts_and_pass_28_seconds(self):
        for day,old_seconds in [(28,24.867),(29,24.600)]:
            with self.subTest(day=day):
                data=material(day);original=copy.deepcopy(data)
                self.assertEqual(sum(len(line['inside'])+len(line['outside'])
                                     for line in data['competitions'][0]['lines']),8)
                narr=slots.program('race',data)['narration'];segs=narr['segments']
                extra=[s for s in segs if s['kind']=='jp_player']
                self.assertEqual(len(extra),2)
                for seg,person in zip(extra,data['competitions'][0]['jp']):
                    self.assertEqual(seg['text'],f"{person['name']}の{person['club_jp']}は{person['position']}位で勝点{person['points']}。")
                    self.assertEqual(seg['meta']['big'],str(person['position']))
                    self.assertEqual(seg['meta']['chips'],[[person['points'],'勝点']])
                self.assertEqual(data,original)
                self.assertEqual(segs[-1]['kind'],'outro')
                # 元4区間の合計を失敗時と同じにした偽音声。追加行は極端に短い1秒。
                # 既存の区間下限・30fps丸めを通しても28秒以上。合成・描画はしない。
                lengths=[old_seconds/4 if s['kind']!='jp_player' else 1 for s in segs]
                audio=[dict(s,file=__file__,duration=length) for s,length in zip(segs,lengths)]
                with patch('synthesize_narration.audio_duration',side_effect=lengths):
                    times=slots.video_times(segs,audio)
                report=short_content.assess(narr,times,data,maximum=40)
                self.assertGreaterEqual(report['planned_seconds'],28)
                self.assertEqual(report['status'],'passed')
                self.assertEqual(sanity_material.check(narr,sanity_material.grounding([narr])),[])
                base=dict(narr,segments=[s for s in segs if s['kind']!='jp_player'])
                self.assertEqual(short_content.assess(base,[old_seconds/4]*4,data)['status'],'held')

    def test_other_club_does_not_inherit_previous_person(self):
        narr=slots.program('race',material(28))['narration']
        mats=sanity_material.grounding([narr]);text=narr['segments'][1]['text']
        # 修正前に行2のNGを生んだ比較を明示的に再現する。
        self.assertIs(sanity_claims.review(text,mats,context=narr['segments'][0]['text']+text),False)
        context=sanity_material.claim_context(narr,text,mats)
        self.assertNotIn('菅原由勢',context)
        self.assertIsNot(sanity_claims.review(text,mats,context=context),False)

    def test_anonymous_continuation_and_wrong_personal_values_still_stop(self):
        narr=slots.program('race',material(29))['narration']
        mats=sanity_material.grounding([narr])
        for text,expected in [('10位で勝点13。',True),('10位で勝点99。',False),('9位で勝点13。',False)]:
            doc=dict(segments=[dict(text='菅原由勢のカリアリ。'),dict(text=text)])
            context=sanity_material.claim_context(doc,text,mats)
            self.assertIs(sanity_claims.review(text,mats,context=context),expected)
        bad=copy.deepcopy(narr)
        next(s for s in bad['segments'] if s['kind']=='jp_player')['text']='菅原由勢のカリアリは10位で勝点99。'
        self.assertTrue(sanity_material.check(bad,sanity_material.grounding([bad])))

    def test_empty_missing_and_unselected_material_is_not_invented(self):
        self.assertEqual(slots.program('race',dict(date_jst='2026-10-29',picked=[],competitions=[]))['narration']['segments'],[])
        data=material(29);data['competitions'][0]['jp'][1]['points']=None
        data['competitions'].append(dict(code='PL',ready=True,jp=[dict(name='別人',club_jp='別クラブ',position=1,points=99)]))
        narr=slots.program('race',data)['narration']
        extra=[s for s in narr['segments'] if s['kind']=='jp_player']
        self.assertEqual(len(extra),1)
        self.assertNotIn('別人',str(narr['segments']))

    def test_original_host_snapshot_includes_added_segments(self):
        captured=[]
        def adapt(narr,kind):
            captured.append(copy.deepcopy(narr['segments']));return narr
        with patch('host_split.adapt',side_effect=adapt):
            narr=slots.program('race',material(29))['narration']
        self.assertEqual(captured[-1],narr['segments'])
        self.assertEqual(sum(s['kind']=='jp_player' for s in captured[-1]),2)

    def test_no_duplicate_clubs_out_players_or_unnecessary_expansion(self):
        data=material(29);comp=data['competitions'][0]
        comp['jp'].insert(1,dict(comp['jp'][0],name='同じクラブの別人'))
        comp['jp'].append(dict(comp['jp'][1],club_jp='別クラブ',name='離脱中',out=True))
        narr=slots.program('race',data)['narration']
        self.assertEqual(len([s for s in narr['segments'] if s['kind']=='jp_player']),2)
        self.assertNotIn('同じクラブの別人',str(narr['segments']))
        self.assertNotIn('離脱中',str(narr['segments']))
        plan=dict(data=data,shared={},narration=dict(segments=[dict(kind='cover',text='長'*180)]))
        original=copy.deepcopy(plan);slots.race_details(plan)
        self.assertEqual(plan,original)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
