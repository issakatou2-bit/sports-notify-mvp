"""Source-backed supplements. No network, paid model, or availability guesses."""
import hashlib
import json


def venue_focus(game, games):
    """Only a fully sourced WCS opening; no inference that a park is home turf."""
    if game.get('gameType') != 'F' or game.get('seriesGameNumber') != 1:
        return None
    pair = {game['teams'][s]['team']['id'] for s in ('home', 'away')}
    rows = [g for g in games if g.get('gameType') == 'F'
            and {g['teams'][s]['team']['id'] for s in ('home', 'away')} == pair]
    venue = game.get('venue', {})
    if (len(rows) != 3 or {g.get('seriesGameNumber') for g in rows} != {1, 2, 3}
            or not venue.get('id') or not venue.get('name')
            or any(g.get('venue') != venue or g['teams']['home']['team']['id'] != game['teams']['home']['team']['id'] for g in rows)):
        return None
    return dict(metric_type='series_venue', game_id=game['gamePk'], venue=venue['name'],
                venue_id=venue['id'], evidence_game_ids=sorted(g['gamePk'] for g in rows),
                fact_text='WCS全試合が同じ球場の予定', selection_rule='opening_lead_without_probables')


def previous_final(game, games):
    """Latest preceding game of this series, never a regular-season meeting."""
    pair = {game['teams'][s]['team']['id'] for s in ('home', 'away')}
    prior = [g for g in games if g.get('gameType') == game.get('gameType')
             and g.get('season') == game.get('season')
             and g.get('seriesGameNumber') == game.get('seriesGameNumber', 0)-1
             and {g['teams'][s]['team']['id'] for s in ('home', 'away')} == pair]
    if len(prior) != 1 or prior[0].get('status', {}).get('abstractGameState') != 'Final':
        return None
    g = prior[0]
    sides = [g['teams'][s] for s in ('home', 'away')]
    if (any(type(t.get('score')) is not int or t['score'] < 0 for t in sides)
            or any(type(t.get('isWinner')) is not bool for t in sides)
            or sum(t['isWinner'] for t in sides) != 1
            or sides[0]['score'] == sides[1]['score']
            or sides[0]['isWinner'] != (sides[0]['score'] > sides[1]['score'])):
        raise ValueError('Previous Final score/winner conflict')
    return dict(game_id=g['gamePk'], game_number=g['seriesGameNumber'],
                teams=[dict(team_id=t['team']['id'], score=t['score'], winner=t['isWinner']) for t in sides],
                metric_type='previous_game_score', sample_size=1)


def relief_pitches(final, packet):
    """Preparation only. Record actual pitches, never next-day eligibility."""
    expected=f'https://statsapi.mlb.com/api/v1/game/{final["game_id"]}/boxscore'
    if packet.get('game_id') != final['game_id'] or packet.get('source_url') != expected or not packet.get('retrieved_at'):
        raise ValueError('Boxscore provenance does not match the previous final')
    box=packet['boxscore']
    if {box['teams'][s]['team']['id'] for s in ('home','away')} != {t['team_id'] for t in final['teams']}:
        raise ValueError('Boxscore team mismatch')
    result=[];excluded=[]
    for side in ('home','away'):
        club=box['teams'][side]
        for pid in club.get('pitchers', []):
            row=club.get('players', {}).get('ID'+str(pid), {})
            stats=row.get('stats', {}).get('pitching', {})
            # A pitcher-list position is not proof of starting/relief status.
            started=stats.get('gamesStarted');pitches=stats.get('numberOfPitches')
            if type(started) is not int or started not in (0,1) or type(pitches) is not int or pitches < 0:
                excluded.append(dict(player_id=pid, reason='role_or_pitch_count_unconfirmed'));continue
            if started:continue
            if row.get('person', {}).get('id') != pid:
                raise ValueError('Pitcher identity mismatch')
            result.append(dict(subject_id=pid, team_id=club['team']['id'], display=row['person'].get('fullName'),
                               metric_type='relief_pitches_previous_game', value=pitches, sample_size=1,
                               period_game_id=final['game_id']))
    return dict(facts=result,excluded=excluded,source_url=expected,retrieved_at=packet['retrieved_at'],
                source_sha256=hashlib.sha256(json.dumps(box,sort_keys=True).encode()).hexdigest(),
                limits=['投球数だけで翌日の登板可否・疲労・監督の意図を断定しない'], publication_connected=False)
