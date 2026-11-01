"""同じ札の取り違え、追加成績の材料一致、辞書変更後の古い音声の再利用を検査。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
os.environ.update(COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_DUO='off')
import preview_soccer_v5 as preview
import soccer_results as results
import soccer_results_render as render
import soccer_slots_v4 as slots
import soccer_v5_cards as cards
import soccer_v5_program as program
import review_render_v3 as r3


class Feedback(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_DUO='off');self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(r3.set_caption,'',0,0);self.addCleanup(r3.set_program_clock,None)

    def test_real_match_cards_remain_distinct(self):
        source=json.loads((ROOT/'scripts/fixtures/soccer-interest/saved-preview-20261011.json').read_text(encoding='utf8'))
        data=copy.deepcopy(source);plan=slots.program('preview',data)
        self.assertEqual(len({g['league'] for g in data['games']}),3)
        for game in data['games']:
            original=next(g for g in source['games'] if g['game_id']==game['game_id'])
            for key in ('game_id','home_team_name','away_team_name','start_time_jst','league'):
                self.assertEqual(game[key],original[key])
        identities=[];pixels=[]
        for seg in plan['narration']['segments']:
            if seg['kind']!='preview':continue
            im=slots.frame(3,seg,plan)
            self.assertFalse(slots.check_frame(im,plan))
            identities.append(tuple(c['club_id'] for c in im.info['v4_badges']))
            pixels.append(im.tobytes())
        self.assertEqual(len(set(identities)),3)
        self.assertEqual(len(set(pixels)),3)

    def test_all_three_options_use_same_actual_person_and_game(self):
        fix=ROOT/'scripts/fixtures/soccer-results'
        data=results.build(json.loads((fix/'scoreboards.json').read_text(encoding='utf8')),json.loads((fix/'summaries.json').read_text(encoding='utf8')),'2026-09-20')
        before=copy.deepcopy(data);narr=program.add_player_scene(render.narration(data),data)
        person=next(p for p in data['players'] if p['status']!='none')
        game=next(g for g in data['games'] if g['id']==person['event_id']);clubs=render.resolve_clubs(data)
        self.assertEqual(data,before)
        self.assertEqual(person['name'],'上田綺世');self.assertEqual(person['goals'],1)
        new=narr['segments'][1]
        self.assertEqual(new['meta']['event_id'],person['event_id'])
        self.assertIn('1得点',new['text']);self.assertIn('1対2',new['text'])
        for kind in ('score','appearance','plays'):
            for t in (0,.35,1.5,3,18):
                im=program.player_result_frame(t,person,game,clubs,render.program_spec(data),kind)
                self.assertFalse(cards.check_frame(im,clubs),(kind,t))
                self.assertEqual(im.info['v5_player_detail']['game_id'],person['event_id'])
                self.assertEqual(im.info['v5_player_detail']['person'],person)

    def test_a_b_differ_at_35px_and_keep_club_identity(self):
        from PIL import Image
        clubs={c['team_en']:c for c in cards.original.load_clubs().values()}
        for club in clubs.values():
            ims=[]
            for variant in ('A','B'):
                im=Image.new('RGB',(150,45),cards.PITCH);cards.scarf(im,(8,5,142,40),club,variant=variant)
                self.assertEqual(im.info['v4_badges'][0]['club_id'],club['team_en'])
                ims.append(im)
            self.assertNotEqual(ims[0].tobytes(),ims[1].tobytes(),club['team_en'])

    def test_old_same_text_audio_without_query_is_rebuilt(self):
        import synthesize_narration as sn
        narr={'segments':[dict(kind='intro',text='上田綺世です。',speaker=2,meta={})]}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);audio=out/'audio';audio.mkdir();(audio/'00.wav').write_bytes(b'old voice')
            (audio/'manifest.json').write_text(json.dumps(narr),encoding='utf8')
            with patch.object(sn,'synth_one',return_value=True) as synth,patch.object(sn,'audio_duration',return_value=1):
                preview.audio_for(narr,out)
                synth.assert_called_once()


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
