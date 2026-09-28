"""Draft PS headline policy; no game selection, network, or publishing."""
from datetime import date

ROUND = {'F': ('WCS', 3), 'D': ('地区シリーズ', 5),
         'L': ('リーグ優勝決定シリーズ', 7), 'W': ('ワールドシリーズ', 7)}


def situation(card):
    kind, number = card['round'], card['game_number']
    wins = [card['home_wins'], card['away_wins']]
    if kind not in ROUND or type(number) is not int:
        raise ValueError('Missing official round/game number')
    maximum = ROUND[kind][1]
    need = maximum // 2 + 1
    if not 1 <= number <= maximum or any(type(w) is not int or not 0 <= w <= need for w in wins):
        raise ValueError('Invalid series record')
    if sum(wins) > number - 1 or sum(w >= need for w in wins) > 1:
        raise ValueError('Results contradict the upcoming game')
    if max(wins) >= need:
        return 'finished'
    if sum(wins) < number - 1:
        return 'pending_results'
    if number == 1:
        return 'opening'
    if wins == [need - 1, need - 1]:
        return 'decider'
    if max(wins) == need - 1:
        return 'clinch_chance'
    return 'in_progress'


def forecast_title(cards, target_day, lead_index, lead_side):
    """Use one headline card while retaining every active card in coverage."""
    day = date.fromisoformat(target_day)
    if not cards or type(lead_index) is not int or not 0 <= lead_index < len(cards):
        raise ValueError('Select an actual forecast card')
    if lead_side not in ('home', 'away'):
        raise ValueError('Lead must be a team in this card')
    identifiers = [c.get('game_id') for c in cards]
    if any(not i for i in identifiers) or len(set(identifiers)) != len(cards):
        raise ValueError('Every scheduled game needs a distinct official ID')
    states = [situation(c) for c in cards]
    if states[lead_index] == 'finished':
        raise ValueError('Do not headline a completed series as an upcoming game')
    lead = cards[lead_index]
    state = states[lead_index]
    team = lead[lead_side]
    other = lead['away' if lead_side == 'home' else 'home']
    rnd, maximum = ROUND[lead['round']]
    nth = '第' + str(lead['game_number']) + '戦'
    if state == 'opening':
        words = team + 'の' + rnd + '初戦は' + other + '戦'
    elif state == 'decider':
        words = team + '対' + other + 'の' + rnd + nth + 'は決着戦'
    elif state == 'clinch_chance':
        mine = lead[lead_side + '_wins']
        stake = 'の世界一がかかる' if lead['round'] == 'W' else 'の突破がかかる'
        words = team + (stake if mine == maximum // 2 else 'が敗退回避に臨む') + rnd + nth
    else:
        words = team + '対' + other + 'の' + rnd + nth
    remaining = [c for c, state in zip(cards, states) if state != 'finished']
    unresolved = any(c.get('conditional') and state == 'pending_results'
                     for c, state in zip(cards, states))
    coverage = 'PS全日程（開催条件付きあり）' if unresolved else f'PS全{len(remaining)}試合'
    return f'{words}｜{day.month}/{day.day} {coverage}'
