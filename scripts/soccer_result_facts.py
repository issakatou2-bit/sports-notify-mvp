"""結果の表示と読みを同じ材料から作る。ない数字・履歴・局面は補わない。"""
import soccer_results as results


def positive_stats(player):
    return '、'.join(f'{player[key]}{unit}' for key,unit in
                    (('goals','得点'),('assists','アシスト')) if player.get(key))


def player_line(player, expected=False):
    parts=[results.STATUS[player['status']]]
    if player['status']!='none':
        if player.get('minutes'):parts.append(f"{player['minutes']}分出場")
        stats=positive_stats(player)
        if stats:parts.append(stats)
    # 一人の出場・成績を途中の句点で別の吹き出しにしない。
    return ('期待選手の' if expected else '')+player['name']+'は'+'、'.join(parts)+'。'


def competition(game):
    label=game['league_jp']
    stage=game.get('stage')
    if stage in ('LEAGUE_PHASE','LEAGUE_STAGE'):label+=' リーグフェーズ'
    if type(game.get('matchday')) is int and game['matchday']>0:label+=f" 第{game['matchday']}節"
    return label


def goal_line(goal):
    minute=goal['minute'].replace('+','分＋')+'分'
    if '+' not in goal['minute']:minute=goal['minute']+'分'
    if goal['own_goal']:return f"{minute}に{goal['scorer']}のオウンゴール。"
    return f"{minute}に{goal['scorer']}が得点。"


def supplements(game,row):
    """短い音声補足。得点は日本人の関与を優先し、最大2件。全得点は画面へ。"""
    goals=sorted(game['goals'],key=lambda g:(not bool(g['japanese_goal'] or g['japanese_assists']),
                                          -int(g['minute'].split('+')[0])))[:2]
    units=[competition(game)+'。']
    units.extend(goal_line(g) for g in sorted(goals,key=lambda g:int(g['minute'].split('+')[0])))
    # 順位は同一大会・シーズンと前後時刻を照合した既存の別画面へ。
    return units


def display_details(game,row):
    facts=[competition(game)]
    facts.extend(goal_line(g).rstrip('。') for g in game['goals'])
    if not game['goals']:facts.append('得点なし' if game['goals_complete'] else '得点経過は未取得')
    return facts
