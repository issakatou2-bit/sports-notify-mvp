"""One factual lead shared by daily narration, title and vertical cover.

Team affiliation flags come from this run's MLB currentTeam lookup. They
prioritize teams only; they never authorize a player's appearance claim.
This module intentionally has no network or image-library dependency.
"""
import re


def affiliated_team_hook(games):
    candidates = []
    for at, game in enumerate(games):
        if game.get('league') != 'MLB':
            continue
        for side in ('home', 'away'):
            team = game.get(side + '_team_name')
            if game.get(side + '_has_jp') is not True or not team:
                continue
            # Require the named team, not its opponent, to own the statistic.
            for priority, tag, pattern in (
                (0, 'ps_magic', r'地区優勝マジック[0-9]+'),
                (1, 'streak', r'[0-9]+連勝中'),
                (2, 'ps_race', r'ポストシーズン圏内'),
            ):
                for reason in game.get('reasons') or []:
                    if reason.get('tag') != tag:
                        continue
                    match = re.fullmatch(re.escape(team) + r'\s*は\s*(' + pattern + r')',
                                         (reason.get('text') or '').strip().rstrip('。'))
                    if match:
                        candidates.append((priority, at, team, match[1], reason['text']))
            opponent = game.get(('away' if side == 'home' else 'home') + '_team_name')
            if opponent:
                candidates.append((3, at, team, opponent + 'と対戦', 'currentTeam affiliation'))
    if not candidates:
        return None
    _, at, team, big, evidence = min(candidates, key=lambda item: item[:2])
    return {'big': big, 'sub': team, 'at': at, 'key': team,
            'team': team, 'game_id': str(games[at].get('game_id') or ''),
            'evidence': evidence, 'selection': 'japanese_affiliated_team'}


def cover_metadata(games, hook):
    """Resolve the original game index; never borrow another game's time/title."""
    at = hook.get('at')
    if type(at) is not int or not 0 <= at < len(games):
        raise ValueError('Missing or invalid narration game reference')
    game = games[at]
    if game.get('league') != 'MLB':
        raise ValueError('This cover is for daily MLB previews')
    if hook.get('game_id') and str(game.get('game_id')) != hook['game_id']:
        raise ValueError('Narration and cover game IDs differ')
    home, away = game.get('home_team_name'), game.get('away_team_name')
    if not home or not away:
        raise ValueError('Both teams are required')
    stamp = re.fullmatch(r'(\d{2})/(\d{2}) ([0-2]\d):([0-5]\d)',
                         game.get('start_time_jst') or '')
    if not stamp or not (1 <= int(stamp[1]) <= 12 and 1 <= int(stamp[2]) <= 31
                         and int(stamp[3]) <= 23):
        raise ValueError('Missing or invalid JST start time')
    subject = (hook.get('sub_jp') or hook.get('sub') or '').strip()
    big = (hook.get('big') or '').strip()
    if not subject or not big:
        raise ValueError('A concrete narration headline is required')
    team = hook.get('team') or (subject if subject in (home, away) else '')
    # For an explicitly announced pitcher, preserve the player and show the team.
    if not team:
        for side, name in (('home', home), ('away', away)):
            p = game.get(side + '_probable') or {}
            if hook.get('sub') in (p.get('name'), p.get('name_jp')):
                team = name
                break
    if team and team not in (home, away):
        raise ValueError('Selected team is not in this game')
    opponent = away if team == home else home if team == away else ''
    day = f'{int(stamp[1])}/{int(stamp[2])}'
    lead = f'{subject}、{big}'
    if team and team != subject:
        lead = f'{team} {subject}、{big}'
    title = f'{lead}｜{day}の注目試合【MLB】'
    if len(title) > 100:
        raise ValueError('Headline exceeds YouTube title limit')
    return {'subject': subject, 'fact': big, 'team': team,
            'matchup': f'vs {opponent}' if opponent else f'{home} vs {away}',
            'date': day, 'time': f'{day} {stamp[3]}:{stamp[4]} 日本時間',
            'game_id': str(game.get('game_id') or ''), 'game_index': at,
            'title': title, 'hook': hook}
