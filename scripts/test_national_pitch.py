"""ポジションを推測しない表示・読み・時刻の回帰。実通信は行わない。"""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import soccer_national as n
import soccer_national_pitch as pitch
import soccer_national_render as render


class Pitch(unittest.TestCase):
    def setUp(self):
        self.data=n.squad(n.read(ROOT/'data/soccer_national_squad.json'),{},'2026-11-09T10:15:00+09:00',4)

    def test_official_positions_are_complete_and_not_formation(self):
        points=pitch.points(self.data)
        self.assertEqual(len(points),28)
        self.assertEqual(len({p['name'] for p in points}),28)
        declared={p['name']:p['position'] for p in self.data['squad_roster']}
        self.assertTrue(all(p['position']==declared[p['name']] for p in points))
        self.assertEqual({p['position'] for p in points},{'GK','DF','MF/FW'})
        for y in {p['y'] for p in points}:
            xs=sorted(p['x'] for p in points if p['y']==y)
            gaps=[b-a for a,b in zip(xs,xs[1:])]
            if gaps:self.assertAlmostEqual(max(gaps),min(gaps))

    def test_roster_or_league_tamper_rejected(self):
        for field in ('roster','league'):
            data=copy.deepcopy(self.data)
            if field=='roster':data['squad_roster'][-1]['position']='MF'
            else:data['players'][0]['league']={'label':'推測リーグ'}
            doc=n.narration(data)
            # フィールド内の位置だけを書き換えても、原名簿との不一致を止める。
            if field=='roster':
                data['players'][0]['position']='FW';doc=n.narration(data)
            self.assertTrue(n.check(doc))

    def test_only_registered_league_and_club_pair_is_used(self):
        self.assertEqual(pitch.league_for('Arsenal FC')['label'],'イングランド1部')
        self.assertIsNone(pitch.league_for('未登録のFC'))
        self.assertIsNone(pitch.league_for('FC町田ゼルビア'))

    def test_card_is_still_during_speech_and_returns_to_its_own_point(self):
        point=pitch.points(self.data)[0]
        held=[pitch.card_state(t,3.2,point) for t in (.3,1,2,2.9)]
        self.assertTrue(all(row['box']==list(pitch.CARD) and row['alpha']==1 for row in held))
        start=pitch.card_state(0,3.2,point);end=pitch.card_state(3.2,3.2,point)
        self.assertEqual(start,end);self.assertEqual(start['alpha'],0)
        self.assertAlmostEqual((start['box'][0]+start['box'][2])/2,point['x'],delta=1)

    def test_all_pages_keep_facts_and_short_varied_lines(self):
        roster=n.read(ROOT/'data/soccer_national_squad.json')
        for page in range(9):
            data=n.squad(roster,{},'2026-11-09T10:15:00+09:00',page)
            doc=n.narration(data)
            self.assertEqual(n.check(doc),[])
            self.assertEqual(doc['segments'][-1]['text'],'毎日更新しています。')
            texts=[s['text'] for s in doc['segments'] if 'player' in s['meta']]
            self.assertTrue(all('発表されたポジションは' not in text for text in texts))
            self.assertEqual(len(texts),len(data['players']))
            for p,text in zip(data['players'],texts):self.assertIn(p['name'],text)

    def test_speech_slot_never_cuts_or_speeds_long_audio(self):
        doc=n.narration(self.data);audio=[dict(duration=1.8) for _ in doc['segments']]
        times=pitch.durations(doc,audio,[2.0]*len(audio))
        self.assertEqual(times[0],2)
        self.assertEqual(times[1],3.2)
        # 長い声は札を伸ばして収める（切らない・速めない）。出入りの0.3秒ずつを足す。
        audio[1]['duration']=4.1
        self.assertAlmostEqual(pitch.durations(doc,audio,[2.0]*len(audio))[1],4.7)
        audio[1]['duration']=5.5
        with self.assertRaisesRegex(ValueError,'原稿'):pitch.durations(doc,audio,[2.0]*len(audio))
        audio[1]['duration']=1.8
        measured=[2.0]*len(audio);measured[1]=5.5
        with self.assertRaisesRegex(ValueError,'原稿'):pitch.durations(doc,audio,measured)
        audio[0]['duration']=2.6
        self.assertAlmostEqual(pitch.durations(doc,audio,[2.0]*len(audio))[0],2.6)
        audio[0]['duration']=3.1
        with self.assertRaisesRegex(ValueError,'原稿'):pitch.durations(doc,audio,[2.0]*len(audio))

    def test_first_frame_and_captions_have_the_same_active_player(self):
        import review_render_v3 as r3
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan'):
            doc=n.narration(self.data);clubs=render.clubs_for(self.data)
            for i,p in enumerate(self.data['players']):
                seg=doc['segments'][i+1]
                r3.set_program_clock(0);r3.set_caption(seg['text'],3.2,20,speaker=2)
                for t in (0,.15,.3,1,2.9,3.19):
                    r3.set_program_clock(t);im=render.frame(t,seg,self.data,clubs)
                    self.assertEqual(im.info['national_pitch']['active'],p['name'])
                    self.assertEqual(len(im.info['national_pitch']['points']),28)
                    if 'short_caption_suppressed' not in im.info:
                        self.assertEqual(im.info.get('caption_alpha'),im.info['national_pitch']['card']['alpha'])
                        if t==0:self.assertFalse(im.info['timeline_subtitle_visible'])
                    actual=''.join(im.info.get('timeline_subtitles',[]))
                    for other in self.data['players']:
                        if other['name']!=p['name']:self.assertNotIn(other['name'],actual)
            r3.set_program_clock(None);r3.set_caption('',0,0)

    def test_duplicate_caption_does_not_flash_as_the_card_grows(self):
        import review_render_v3 as r3
        with patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SOCCER_FOCUS='on',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOLO_HOST='metan'):
            doc=n.narration(self.data);seg=doc['segments'][1]
            r3.set_program_clock(0);r3.set_caption(seg['text'],3.2,20,speaker=2)
            for t in (0,.15,.3,1,3.1):
                r3.set_program_clock(t);im=render.frame(t,seg,self.data,render.clubs_for(self.data))
                self.assertEqual(im.info['short_caption_suppressed']['reason'],'duplicate')
                self.assertFalse(im.info.get('timeline_subtitles'))
            r3.set_program_clock(None);r3.set_caption('',0,0)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
