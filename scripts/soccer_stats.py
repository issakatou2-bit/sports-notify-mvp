"""既存ESPN summaryだけから読む任意統計。欠測と実測0を区別する。"""
import math
import re

NOTICE = 'コレスポ独自・攻撃面のみ'
VERSION = 'attack-v1'
THRESHOLDS = (1, 3, 5, 8, 12)


def number(value, integer=True):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(str(value).removesuffix('%'))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(n) or n < 0 or (integer and not n.is_integer()):
        return None
    return int(n) if integer else n


def values(rows):
    # 重複キーは一意でないので使わない。
    out = {}
    for row in rows:
        key = row.get('name')
        out[key] = None if key in out else row.get('value', row.get('displayValue'))
    return out


def team_stats(summary, sides):
    out = {}
    teams = (summary.get('boxscore') or {}).get('teams') or []
    for side in ('home', 'away'):
        matches = [t for t in teams if str((t.get('team') or {}).get('id')) == str(sides[side]['id'])]
        if len(matches) != 1:
            return None
        raw = values(matches[0].get('statistics') or [])
        row = dict(possession=number(raw.get('possessionPct'), False),
                   shots=number(raw.get('totalShots')), on_target=number(raw.get('shotsOnTarget')))
        if any(v is None for v in row.values()) or row['possession'] > 100 or row['on_target'] > row['shots']:
            return None
        out[side] = row
    if abs(sum(v['possession'] for v in out.values()) - 100) > 1:
        return None
    return dict(source='ESPN summary.boxscore.teams.statistics', **out)


def player_stats(row):
    raw = values(row.get('stats') or [])
    pos = row.get('position') or (row.get('athlete') or {}).get('position') or {}
    code = pos.get('abbreviation', '') if isinstance(pos, dict) else str(pos)
    role = {'G': 'GK', 'GK': 'GK', 'D': 'DF', 'DF': 'DF', 'M': 'MF', 'MF': 'MF', 'F': 'FW', 'FW': 'FW'}.get(code)
    role = role or {'AM':'MF','AM-L':'MF','AM-R':'MF','CM':'MF','CM-L':'MF','CM-R':'MF',
                    'LM':'MF','RM':'MF','CD':'DF','CD-L':'DF','CD-R':'DF','LB':'DF','RB':'DF',
                    'CF-L':'FW','CF-R':'FW'}.get(code)
    out = dict(position=role, stats_source='ESPN summary.rosters.roster.stats')
    keys = (('saves', 'saves'), ('conceded', 'goalsConceded')) if role == 'GK' else (
        ('shots', 'totalShots'), ('on_target', 'shotsOnTarget'))
    out.update({dest: number(raw.get(src)) for dest, src in keys})
    if role != 'GK' and out['shots'] is not None and out['on_target'] is not None and out['on_target'] > out['shots']:
        out.update(shots=None, on_target=None)
    return out


def attack(player):
    """3G+2A+S+T。直接分・交代分・交代なし先発で出場条件を確認。"""
    if player.get('position') not in ('FW', 'MF') or player.get('status') not in ('starter', 'substitute'):
        return None
    minutes = number(player.get('minutes'))
    nums = [number(player.get(k)) for k in ('goals', 'assists', 'shots', 'on_target')]
    full_start = (player.get('status') == 'starter' and player.get('subbed_out') is False
                  and player.get('red_cards') == 0)
    if (minutes is None and not full_start) or (minutes is not None and minutes < 30) or any(n is None for n in nums):
        return None
    goals, assists, shots, target = nums
    if goals > target or target > shots:
        return None
    raw = 3 * goals + 2 * assists + shots + target
    return dict(version=VERSION, raw=raw, level=sum(raw >= t for t in THRESHOLDS), notice=NOTICE)


def attack_label(player):
    result = attack(player)
    if result is None:
        return ''
    level = result['level']
    value = '★' * level + '☆' * (5-level)
    return '攻撃関与 ' + value


def appearance_minutes(player, summary):
    """交代はparticipantsの入る/出るIDで照合。追加時間は数えない概算。"""
    if number(player.get('minutes')) is not None:
        return dict(minutes=player['minutes'], minutes_source='ESPN minutesPlayed')
    status = player.get('status')
    if status not in ('starter', 'substitute') or player.get('red_cards') != 0:
        return {}
    incoming, outgoing = [], []
    end = 120 if any((e.get('period') or {}).get('number', 0) in (3, 4)
                     for e in summary.get('keyEvents', [])) else 90
    for event in summary.get('keyEvents', []):
        kind = event.get('type') or {}
        if kind.get('type') != 'substitution' and str(kind.get('id')) != '76':
            continue
        people = event.get('participants') or []
        if len(people) != 2:
            continue
        for index, times in ((0, incoming), (1, outgoing)):
            if str((people[index].get('athlete') or {}).get('id')) == player.get('athlete_id'):
                match = re.fullmatch(r"(\d+)'?(?:\+\d+'?)?", str((event.get('clock') or {}).get('displayValue', '')).strip())
                times.append(int(match[1]) if match and int(match[1]) <= end else None)
    if status == 'starter' and not incoming and player.get('subbed_out') is True and len(outgoing) == 1:
        start, stop = 0, outgoing[0]
    elif status == 'substitute' and len(incoming) == 1:
        start = incoming[0]
        if player.get('subbed_out') is True and len(outgoing) == 1:
            stop = outgoing[0]
        elif player.get('subbed_out') is False and not outgoing:
            stop = end
        else:
            return {}
    else:
        return {}
    if start is None or stop is None or stop < start:
        return {}
    return dict(minutes=stop-start, minutes_source='ESPN keyEvents substitution', minutes_approx=True)


def minutes_label(player):
    minutes = number(player.get('minutes'))
    if minutes is None:
        return ''
    return f"約{minutes}分出場"


def personal_line(player):
    if player.get('status') == 'none':
        return ''
    if player.get('position') == 'GK':
        return '、'.join(f'{player[k]}{u}' for k, u in (('saves', 'セーブ'), ('conceded', '失点')) if player.get(k) is not None)
    if player.get('shots') is None:
        return ''
    return f"シュート{player['shots']}本" + (f"（枠内{player['on_target']}本）" if player.get('on_target') is not None else '')


def personal_narration(player):
    if player.get('status') == 'none':
        return ''
    if player.get('position') == 'GK':
        return personal_line(player) if player.get('saves', 0) else ''
    if not player.get('shots'):
        return ''
    text = f"シュート{player['shots']}本"
    target = player.get('on_target')
    if target is not None:
        text += '、枠内はなし' if target == 0 else f'、枠内は{target}本'
    return text


def result_narration(player):
    import soccer_result_facts as facts
    status=player['status']
    full=status=='starter' and player.get('subbed_out') is False and player.get('red_cards')==0
    appearance='フル出場' if full else minutes_label(player) or ('先発出場' if status=='starter' else '途中出場')
    parts=[appearance]
    positive=facts.positive_stats(player)
    if positive:parts.append(positive)
    personal=personal_narration(player)
    if personal:parts.append(personal)
    return player['name']+'は'+'、'.join(parts)+'。'


def commentary(game):
    stats = game.get('match_stats')
    if not stats:return ''
    h,a=stats['home'],stats['away']
    parts=[]
    # 差が小さい日は読み上げを増やさない。保持率は15ポイント、シュートは5本差から。
    if abs(h['shots']-a['shots'])>=5:
        parts.append(f"シュートは{game['home']['name_jp']}{h['shots']}本、{game['away']['name_jp']}{a['shots']}本")
    if abs(h['possession']-a['possession'])>=15:
        side='home' if h['possession']>a['possession'] else 'away'
        parts.append(f"保持率は{game[side]['name_jp']}が{stats[side]['possession']:g}パーセント")
    return '、'.join(parts)+'。' if parts else ''


def has_personal(game):
    return any(personal_line(p) for p in game['players'])
