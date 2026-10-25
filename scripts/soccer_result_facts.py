"""結果の表示と読みを同じ材料から作る。ない数字・履歴・局面は補わない。"""
import json
from functools import lru_cache
import re
import soccer_results as results

# 英語のまま書くと、画面でも声でも読めない名前になる。
LATIN=re.compile(r'[A-Za-z]')


def positive_stats(player):
    return '、'.join(f'{player[key]}{unit}' for key,unit in
                    (('goals','得点'),('assists','アシスト')) if player.get(key))


def player_line(player, expected=False):
    parts=[results.STATUS[player['status']]]
    if player['status']!='none':
        if player.get('minutes') is not None:
            from soccer_stats import minutes_label
            parts.append(minutes_label(player))
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


def minute_text(minute):
    """「57」→「57分」「45+2」→「45分＋2分」。"""
    if '+' in minute:return minute.replace('+','分＋')+'分'
    return minute+'分'


@lru_cache(maxsize=1)
def player_names():
    """既存のサッカー名簿の確定表記だけ。野球用の自動収集辞書は使わない。"""
    rows=json.loads((results.ROOT/'data/soccer_voice_names.json').read_text(encoding='utf8'))['players']
    return {key:p['name_jp'] for p in rows if p.get('name_jp') and not LATIN.search(p['name_jp'])
            for key in (p['name_en'],p['name_jp'])}


def player_name(name,japanese=False):
    """当日名簿で照合した日本名、または辞書の確定表記。未登録は空。"""
    if japanese and name and not LATIN.search(name):return name
    return player_names().get(name,'')


def scorer_name(goal):
    return player_name(goal.get('scorer') or '',goal.get('japanese_goal',False))


def named_scorer(goal):
    return bool(scorer_name(goal))


def assist_names(goal):
    # japanese_assists は取得時に当日の日本人名簿と照合済み。
    return [jp for name in goal.get('japanese_assists',[]) if (jp:=player_name(name,True))]


def club_of(goal,game):
    """得点したクラブの日本語名。画面でも声でも英語の人名を出さないため。"""
    if not game:return ''
    club=game.get(goal.get('side')) or {}
    return club.get('name_jp') or ''


def goal_name(goal,game=None):
    """得点者の表す言葉。名前が確かなときは名前、そうでなければクラブ名。"""
    if named_scorer(goal):return scorer_name(goal)
    return club_of(goal,game) or '得点'


def goal_line(goal,game=None):
    """得点の1行。名前が確かなときは名前、確かでないときはクラブ名。"""
    minute=minute_text(goal['minute'])
    if named_scorer(goal):
        if goal['own_goal']:return f"{minute}に{scorer_name(goal)}のオウンゴール。"
        return f"{minute}に{scorer_name(goal)}が得点。"
    club=club_of(goal,game)
    if not club:return f"{minute}に得点。"
    if goal['own_goal']:return f"{minute}に{club}が得点。オウンゴール。"
    return f"{minute}に{club}が得点。"


def supplements(game,row):
    """短い音声補足。得点は日本人の関与を優先し、最大2件。全得点は画面へ。"""
    goals=sorted(game['goals'],key=lambda g:(not bool(g['japanese_goal'] or g['japanese_assists']),
                                          -int(g['minute'].split('+')[0])))[:2]
    units=[competition(game)+'。']
    units.extend(goal_line(g,game) for g in sorted(goals,key=lambda g:int(g['minute'].split('+')[0])))
    # 順位は同一大会・シーズンと前後時刻を照合した既存の別画面へ。
    return units


def screen_goal_line(goal,game):
    """画面用。クラブ名は札つきで描くため、クラブ名と文を分けて返す。"""
    minute=minute_text(goal['minute'])
    if named_scorer(goal):
        if goal['own_goal']:return dict(club=None,text=f"{minute}に{scorer_name(goal)}のオウンゴール")
        return dict(club=None,text=f"{minute}に{scorer_name(goal)}が得点")
    club=club_of(goal,game)
    text=f"{minute}に得点"
    if goal['own_goal']:text+="（オウンゴール）"
    return dict(club=club or None,text=text)


def display_details(game,row):
    details=[dict(club=None,text=competition(game))]
    details.extend(screen_goal_line(g,game) for g in game['goals'])
    if not game['goals']:details.append(dict(club=None,text='得点なし' if game['goals_complete'] else '得点経過は未取得'))
    return details
