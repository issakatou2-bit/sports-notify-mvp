import copy
import unittest
import ps_focus as f
import ps_program as p
from test_ps_program import fixture


class FocusTests(unittest.TestCase):
    def games(self):
        snap,ev,now=fixture(29)
        games=ev['schedule']['dates'][0]['games']
        for g in games:
            if g['gameType']=='F':g['venue']={'id':1,'name':'Fixture Park'}
        return snap,ev,now,games

    def test_only_lead_opening_three_rows_preserves_other_cards(self):
        snap,ev,now,games=self.games()
        pr=p.prepare(snap,ev,'forecast',now)
        details=[s for s in pr['segments'] if s['meta']['card'].get('card_index')]
        chosen=[s for s in details if s['meta']['card'].get('focus_evidence')]
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['meta']['game_ids'],[1001])
        self.assertEqual(len(chosen[0]['meta']['card']['items']),3)
        self.assertIn('勝者の地区シリーズの相手',str(chosen[0]))
        self.assertIn('第3戦が必要になった場合',chosen[0]['text'])
        self.assertNotIn('全3試合とも',chosen[0]['text'])

    def test_probable_pitcher_and_later_win_counts_never_displaced(self):
        snap,ev,now,games=self.games()
        games[0]['teams']['home']['probablePitcher']={'id':650633,'fullName':'Michael King'}
        self.assertNotIn('focus_evidence',str(p.prepare(snap,ev,'forecast',now)))
        self.assertIsNone(f.venue_focus(games[1],games))

    def test_missing_conflicting_or_duplicate_venue_is_not_inferred(self):
        for change in ('missing','different','home','duplicate'):
            _,_,_,games=self.games()
            if change=='missing':games[1].pop('venue')
            if change=='different':games[1]['venue']['id']=2
            if change=='home':games[1]['teams']['home'],games[1]['teams']['away']=games[1]['teams']['away'],games[1]['teams']['home']
            if change=='duplicate':games.append(copy.deepcopy(games[0]))
            self.assertIsNone(f.venue_focus(games[0],games),change)

    def final(self):
        _,_,_,games=self.games()
        g=games[0];g['status']['abstractGameState']='Final'
        g['teams']['home'].update(score=5,isWinner=True)
        g['teams']['away'].update(score=2,isWinner=False)
        return f.previous_final(games[1],games),games

    def test_previous_only_same_series_final_not_regular_or_live(self):
        final,games=self.final();self.assertEqual(final['game_id'],1001)
        games[0]['gameType']='R';self.assertIsNone(f.previous_final(games[1],games))
        games[0]['gameType']='F';games[0]['status']['abstractGameState']='Live'
        self.assertIsNone(f.previous_final(games[1],games))

    def test_score_and_winner_conflict_rejected(self):
        _,games=self.final();games[0]['teams']['home']['score']=1
        with self.assertRaises(ValueError):f.previous_final(games[1],games)

    def test_relief_role_pitch_count_and_provenance(self):
        final,_=self.final()
        def person(pid,started,pitches):
            return {'person':{'id':pid,'fullName':'Fixture pitcher'},'stats':{'pitching':{'gamesStarted':started,'numberOfPitches':pitches}}}
        packet=dict(game_id=1001,source_url='https://statsapi.mlb.com/api/v1/game/1001/boxscore',retrieved_at='2026-09-30T12:00:00Z',
                    boxscore={'teams':{'home':{'team':{'id':117},'pitchers':[2,1,3],'players':{'ID1':person(1,1,80),'ID2':person(2,0,25),'ID3':person(3,None,10)}},
                                      'away':{'team':{'id':145},'pitchers':[],'players':{}}}})
        result=f.relief_pitches(final,packet)
        self.assertEqual([(r['subject_id'],r['value']) for r in result['facts']],[(2,25)])
        self.assertEqual(result['excluded'][0]['player_id'],3)
        self.assertFalse(result['publication_connected'])
        packet['game_id']=1002
        with self.assertRaises(ValueError):f.relief_pitches(final,packet)


if __name__=='__main__':unittest.main(argv=[__file__])
