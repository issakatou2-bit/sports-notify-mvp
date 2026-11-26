"""朝の結果で照合済みの試合要約から、出場選手と数字に根拠のある話題を選ぶ。"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import zlib

import soccer_national as national
import soccer_national_topics as shared
import soccer_results as results
import soccer_results_clock as clock
import short_common
from duo import METAN
from video_visibility import exclusion_reason

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / 'data/soccer_club_topic_candidates.json'
LEDGER = ROOT / 'data/soccer_club_topics_published.json'
PUBLICATIONS = ROOT / 'data/published_videos.json'
PROGRAM = 'soccer_club_topic'
LEAGUES = frozenset((*results.LEAGUES, 'CL', 'EL', 'UECL'))
SPACING = timedelta(minutes=90)
LEAD = timedelta(minutes=20)
DAY_LIMIT = 4
MATCH_LIMIT = 2


def read_pool(path=POOL):
    return national.read(path) if Path(path).exists() else {}


def goal_events(summary, game):
    sides = {game[s]['id']: s for s in ('home', 'away')}
    goals = []
    for event in summary.get('keyEvents', []):
        if not event.get('scoringPlay') or event.get('shootout'):
            continue
        side = sides[str(event['team']['id'])]
        athletes = [p.get('athlete', {}) for p in event.get('participants', [])]
        own = event.get('ownGoal') or event.get('type', {}).get('text') == 'Own Goal'
        ids = [str(a.get('id', '')) for a in athletes] if not own else []
        assisted = len(ids) > 1 and 'Assisted by ' in event.get('text', '')
        goals.append(dict(side=side, minute=shared.Material.minute(event),
                          scorer=ids[0] if ids else '', name=athletes[0].get('displayName', '') if ids else '',
                          assist=ids[1] if assisted else '', assist_name=athletes[1].get('displayName', '') if assisted else ''))
    if Counter(g['side'] for g in goals) != Counter(game['score']):
        # 保存された朝の材料では、得点経過が scoreboard 側にだけあることもある。
        if not game.get('goals_complete'):
            return []
        ids = {p['name']: p['athlete_id'] for p in game['players']}
        goals = [dict(side=g['side'], minute=g['minute'], scorer='' if g['own_goal'] else g['athlete_id'],
                      name=g['scorer'], assist=ids.get(g['japanese_assists'][0], '') if len(g['japanese_assists']) == 1 else '')
                 for g in game['goals']]
    return sorted(goals, key=lambda g: tuple(map(int, g['minute'].split('+'))))


def other_side(side):
    return 'away' if side == 'home' else 'home'


def pair(game, side):
    other = other_side(side)
    return game[side]['name_jp'], game[other]['name_jp'], game['score'][side], game['score'][other]


def rank(player):
    return (4 if player.get('goals') else 3 if player.get('assists') else
            2 if player['status'] == 'starter' and player.get('subbed_out') is False else 1)


def collect(data, summaries, previous=None):
    """同じ ESPN 要約を再取得せず、選定・照合に使う項目を朝の回から引き継ぐ。"""
    previous = previous or {}
    history = {m['id']: m for m in previous.get('history', [])
               if m['date_jst'] >= (datetime.fromisoformat(data['date_jst']) - timedelta(days=400)).date().isoformat()}
    materials = []
    for game in data['games']:
        if game['league'] not in LEAGUES:
            continue
        players = [p for p in game['players'] if p['status'] in ('starter', 'substitute')]
        if not players or any(re.search(r'[a-z]{3,}', game[s]['name_jp'], re.I) for s in ('home', 'away')):
            continue
        summary = summaries[game['id']]
        summary = summary.get('summary', summary)
        try:
            goals = goal_events(summary, game)
        except (ValueError, KeyError, TypeError):
            goals = []
        groups = {}
        for team in summary.get('boxscore', {}).get('teams', []):
            keys = ('possessionPct', 'totalShots', 'shotsOnTarget', 'wonCorners', 'saves')
            groups[str(team['team']['id'])] = {s['name']: s.get('displayValue')
                                              for s in team.get('statistics', []) if s['name'] in keys}
        notes = {}
        for team in summary.get('rosters', []):
            for player in team.get('roster', []):
                pid = str(player['athlete']['id'])
                stats = {s['name']: results.integer(s.get('value', s.get('displayValue'))) for s in player.get('stats', [])}
                notes[pid] = dict(saves=stats.get('saves'), shots=stats.get('totalShots'),
                                  target=stats.get('shotsOnTarget'),
                                  keeper=(player.get('position') or {}).get('abbreviation') in ('G', 'GK'))
                for event in summary.get('keyEvents', []):
                    if (event.get('type', {}).get('type') == 'substitution' and
                            event.get('participants') and str(event['participants'][0].get('athlete', {}).get('id')) == pid):
                        try:
                            notes[pid]['entry'] = shared.Material.minute(event)
                        except (KeyError, ValueError):
                            pass
                        break
        row = {k: game[k] for k in ('id', 'league', 'league_jp', 'date_jst', 'home', 'away', 'score')}
        ids = {row[s]['id'] for s in ('home', 'away')}
        prior = [m for m in history.values() if m['date_jst'] < row['date_jst']
                 and {m[s]['id'] for s in ('home', 'away')} == ids]
        material = dict(row, players=players, goals=goals, stats={s: groups.get(row[s]['id'], {}) for s in ('home', 'away')},
                        notes=notes, previous=max(prior, key=lambda m: (m['date_jst'], m['id']), default=None))
        materials.append(material)
        history[row['id']] = row
    return dict(date_jst=data['date_jst'], matches=materials, history=list(history.values()))


def minute_number(goal):
    return sum(map(int, goal['minute'].split('+')))


def score_until(goals, index, side):
    first = sum(g['side'] == side for g in goals[:index])
    return first, index - first


def panel(question, answer, heading, *rows):
    return question, answer, heading, list(rows)


# 掛け合いの決まり（11/26 本人「淡々と質問と回答が続くのは変」「ずんだもんが喜びつつ〇〇がゴールを決めたのだ！
# えぇそうね、〇〇対〇〇の試合で〜のような始まり方、色々なパターンがあってもいい」）。
# ずんだもんは驚き・喜び・惜しさで話を始め、合いの手と問いを混ぜる。数字は言わない（数字はめたんが材料どおりに言う）。
# めたんは「ええ」「そうね」で受けてから事実を話す。始まり方は試合ごとに決まった1つ（作り直しても同じ台本になる）。


def pick(game, player, options):
    return options[zlib.crc32(f"{game['id']}:{player['athlete_id']}:{options[0]}".encode()) % len(options)]


def opening(game, player, cheers, said, head, *rows):
    club, other, _, _ = pair(game, player['side'])
    return panel(pick(game, player, cheers), f'ええ、{club}と{other}の試合ね。' + said, head, *rows)


def ending(game, player, cheers, said):
    """締めは問いでなく、ずんだもんの感想とめたんのまとめ（最終スコアは材料どおり）。"""
    club, other, a, b = pair(game, player['side'])
    return panel(pick(game, player, cheers), said, '試合結果', (club, str(a)), (other, str(b)))


def late_winner(g, p):
    goals = g['goals']
    side = p['side']
    club, other, a, b = pair(g, side)
    for index, goal in enumerate(goals):
        if goal['scorer'] != p['athlete_id'] and goal['assist'] != p['athlete_id']:
            continue
        before_a, before_b = score_until(goals, index, side)
        decisive = a > b and before_a == before_b and all(
            x > y for x, y in (score_until(goals, n, side) for n in range(index + 1, len(goals) + 1)))
        entry = g['notes'].get(p['athlete_id'], {}).get('entry')
        gap = minute_number(goal) - minute_number({'minute': entry}) if entry else None
        if not decisive or not (minute_number(goal) >= 75 or (gap is not None and 0 <= gap <= 15)):
            continue
        name, minute = p['name'], goal['minute']
        scored = goal['scorer'] == p['athlete_id']
        action = '決勝点' if scored else '決勝点をアシスト'
        when = national.minute_words(minute)
        cheers = ([f'{name}が決勝点を決めたのだ！', f'やったのだ！{name}の勝ち越しゴールなのだ！', f'{name}、終盤に大仕事なのだ！']
                  if scored else [f'{name}が決勝点をお膳立てしたのだ！', f'{name}のアシストで勝ったのだ！'])
        said = (f'{when}に決めて、{a}対{b}で勝ったわ。' if scored
                else f'{when}の決勝点をアシストして、{a}対{b}で勝ったわ。')
        panels = [opening(g, p, cheers, said, '決勝点', (name, minute + '分'), ('スコア', f'{a}-{b}'))]
        if gap is not None and gap > 0:
            panels.append(panel(pick(g, p, ['途中から出てきたのだ？', 'えっ、途中出場だったのだ？']),
                                f'そうよ。{national.minute_words(entry)}に出場して、{gap}分後の' + ('得点だったわ。' if scored else 'アシストだったわ。'),
                                '途中出場', ('交代出場', entry + '分'), ('出場から', f'{gap}分')))
        panels.append(panel('それまでは競っていたのだ？', f'そうよ。直前は{before_a}対{before_b}の同点だったわ。',
                            '決勝点の直前', (club, str(before_a)), (other, str(before_b))))
        if len(panels) < 3:
            panels.append(ending(g, p, ['勝負を決めたのだ！', '大きなゴールなのだ！'] if scored else ['大きなアシストなのだ！', '勝負を決めたのだ！'],
                                 f'ええ、最後は{a}対{b}。{club}が勝ち切ったわ。'))
        return f'{name} {minute}分に{action} {other}に{a}-{b}で勝利', panels, minute, '分', action


def keeper(g, p):
    player = g['notes'].get(p['athlete_id'], {})
    saves = player.get('saves') or 0
    club, other, a, b = pair(g, p['side'])
    opponent = other_side(p['side'])
    shots = results.integer(g['stats'][opponent].get('totalShots'))
    target = results.integer(g['stats'][opponent].get('shotsOnTarget'))
    team_saves = results.integer(g['stats'][p['side']].get('saves'))
    if (not player.get('keeper') or p['status'] != 'starter' or saves < 5 or a < b or b > 1
            or team_saves != saves or not target or not shots or not saves <= target <= shots):
        return
    name = p['name']
    result = '無失点' if b == 0 else '1失点'
    cheers = ([f'{name}が完封したのだ！', f'{name}、ゴールに鍵をかけたのだ！'] if b == 0
              else [f'{name}がゴールを守り抜いたのだ！', f'{name}、止めまくったのだ！'])
    if a > b:
        last = panel('チームも勝てたのだ？', f'ええ、{a}対{b}で勝ったわ。', '試合結果', (club, str(a)), (other, str(b)))
    else:
        last = panel('試合はどうなったのだ？', f'{a}対{b}の引き分けだったわ。', '試合結果', (club, str(a)), (other, str(b)))
    return (f'{name} {other}戦で{saves}セーブ {result}に抑える',
            [opening(g, p, cheers, f'{name}は{saves}回のセーブを記録したわ。', 'セーブ', (name, f'{saves}回'), ('失点', f'{b}点')),
             panel(pick(g, p, ['相手はたくさん打ってきたのだ？', 'そんなに攻められていたのだ？']),
                   f'そうね。{other}のシュートは{shots}本で、枠内は{target}本だったわ。',
                   '相手のシュート', ('シュート', f'{shots}本'), ('枠内', f'{target}本')), last],
            str(saves), 'セーブ', '失点 ' + str(b))


def early_goals(g, p):
    from soccer_result_facts import player_name

    goals = g['goals']
    if len(goals) < 3:
        return
    first, second = goals[:2]
    gap = minute_number(second) - minute_number(first)
    if not (first['side'] == second['side'] == p['side'] and minute_number(second) <= 45 and 0 < gap <= 5):
        return
    club, other, a, b = pair(g, p['side'])
    reply = next((goal for goal in goals[2:] if goal['side'] != p['side']), None)
    if a <= b or not reply:
        return
    scorers = []
    for goal in (first, second):
        name = player_name(goal['name'], True)
        assist = player_name(goal.get('assist_name', ''), True)
        if not name or not assist:
            return
        scorers.append((name, assist, goal['minute']))
    (n1, a1, m1), (n2, a2, m2) = scorers
    w1, w2 = national.minute_words(m1), national.minute_words(m2)
    return (f'{club} 前半{gap}分間で2得点 {other}に{a}-{b}で勝利',
            [opening(g, p, [f'{club}が立て続けに決めたのだ！', f'あっという間に{club}が突き放したのだ！'],
                     f'{w1}と{w2}に続けて決めて、{gap}分間で2点を取ったわ。', '2得点の間隔', ('先制点', m1 + '分'), ('追加点', m2 + '分')),
             panel(pick(g, p, ['誰が決めたのだ？', 'どんな形のゴールだったのだ？']),
                   f'先制点は{a1}のアシストから{n1}、追加点は{a2}のアシストから{n2}が決めたわ。',
                   '得点者', (n1, f'アシスト {a1}'), (n2, f'アシスト {a2}')),
             panel('相手も反撃してきたのだ？',
                   f'{other}は{national.minute_words(reply["minute"])}に1点目を返したわ。最後は{a}対{b}で{club}が勝ったわ。',
                   '相手の反撃', (other, reply['minute'] + '分'), ('スコア', f'{a}-{b}'))],
            str(gap), '分間で2得点', '前半' + first['minute'] + '分から')


def opponent_star(g, p):
    club, other, a, b = pair(g, p['side'])
    opponents = [goal for goal in g['goals'] if goal['side'] != p['side'] and goal['scorer']]
    for pid, count in Counter(goal['scorer'] for goal in opponents).most_common():
        if count < 2:
            break
        goals = [goal for goal in opponents if goal['scorer'] == pid]
        from soccer_result_facts import player_name
        name = player_name(goals[0]['name'], True)
        stats = g['notes'].get(pid, {})
        shots, target = stats.get('shots'), stats.get('target')
        if not name or re.search('[A-Za-z]', name) or not (shots and target and count <= target <= shots):
            continue
        minutes = 'と'.join(national.minute_words(goal['minute']) for goal in goals)
        cheers = ([f'相手の{name}にやられたのだ…', f'{name}が止められなかったのだ…'] if a < b
                  else [f'相手の{name}がすごかったのだ！', f'{name}に何度も決められたのだ！'])
        words = '勝ったわ。' if a > b else '敗れたわ。' if a < b else '引き分けたわ。'
        return (f'{other}の{name}が{count}得点 枠内シュート{target}本',
                [opening(g, p, cheers, f'{other}の{name}が{minutes}に決めて{count}得点だったわ。',
                         '相手の得点者', (name, f'{count}得点'), ('時間', '・'.join(goal['minute']+'分' for goal in goals))),
                 panel(pick(g, p, ['シュートもたくさん打っていたのだ？', 'どれくらい狙ってきたのだ？']),
                       f'{name}のシュートは{shots}本で、枠内は{target}本だったわ。',
                       'シュート', ('シュート', f'{shots}本'), ('枠内', f'{target}本')),
                 panel('それでも勝ったのだ？' if a > b else f'{club}はどうなったのだ？',
                       ('ええ、' if a > b else '') + f'{club}は{a}対{b}で{words}',
                       '試合結果', (club, str(a)), (other, str(b)))],
                str(count), '得点', f'枠内シュート{target}本')


def team_numbers(g, p):
    side = p['side']
    club, other, a, b = pair(g, side)
    if a <= b:
        return
    own, their = g['stats'][side], g['stats'][other_side(side)]
    keys = ('possessionPct', 'totalShots', 'shotsOnTarget', 'wonCorners')
    try:
        pairs = [(float(own[k]), float(their[k])) for k in keys]
    except (ValueError, TypeError, KeyError):
        return
    if not all(0 <= x < y for x, y in pairs) or not all(x.is_integer() and y.is_integer() for x,y in pairs[1:]):
        return
    possession = [shared.percent(x) for x in pairs[0]]
    if sum(map(int, possession)) != 100:
        return
    shots, opposed = map(int, pairs[1])
    rows = [('支配率', *[n+'%' for n in possession])] + [
        (label, f'{int(x)}本', f'{int(y)}本') for label, (x,y) in zip(('シュート','枠内','コーナー'), pairs[1:])]
    return (f'{club} 支配率{possession[0]}% シュート{shots}本で{other}に勝利',
            [opening(g, p, [f'{club}が勝ったのだ！', f'{club}の勝利なのだ！'],
                     f'{a}対{b}で勝ったわ。でも、数字を見ると意外なの。', '試合結果', (club, str(a)), (other, str(b))),
             ('えっ、どういうことなのだ？',
              f'{club}の支配率は{possession[0]}パーセント。シュートは{shots}本で、{other}の{opposed}本より少なかったわ。',
              '試合の数字', [('シュート', f'{shots}本')], dict(compare=dict(teams=[club,other], rows=rows[:2]))),
             (pick(g, p, ['ほかの数字も負けていたのだ？', 'それでも勝てたのは不思議なのだ！ほかの数字はどうなのだ？']),
              f'枠内シュートは{rows[2][1]}対{rows[2][2]}。コーナーも{rows[3][1]}対{rows[3][2]}だったわ。',
              '枠内とコーナー', [('枠内', rows[2][1]), ('コーナー', rows[3][1])],
              dict(compare=dict(teams=[club,other], rows=rows[2:])))],
            str(shots), '本のシュート', f'{a}得点で勝利')


def rematch(g, p):
    past = g.get('previous')
    if not past or g['league'] != past['league']:
        return
    club, other, a, b = pair(g, p['side'])
    _, _, old_a, old_b = pair(past, 'home' if past['home']['id'] == g[p['side']]['id'] else 'away')
    if not (a > b and old_a < old_b and p.get('goals')):
        return
    day = datetime.fromisoformat(past['date_jst'])
    goal = next((event for event in g['goals'] if event['scorer'] == p['athlete_id']), None)
    if not goal:
        return
    name = p['name']
    return (f'{club} 前の対戦で敗れた{other}に{a}-{b}で勝利',
            [opening(g, p, [f'{name}がゴールを決めたのだ！', f'{name}、やったのだ！'],
                     f'{name}が{national.minute_words(goal["minute"])}に決めたわ。', '今回の得点', (name, goal['minute']+'分')),
             panel('チームも勝てたのだ？', f'ええ、{a}対{b}で勝ったわ。', '試合結果', (club, str(a)), (other, str(b))),
             panel('前にも戦った相手なのだ？',
                   f'そうよ。{day.month}月{day.day}日の対戦では{club}が{old_a}対{old_b}で敗れていたわ。今回はやり返した形ね。',
                   '過去の対戦', (club, str(old_a)), (other, str(old_b)))],
            f'{a}-{b}', 'で勝利', f'以前は{old_a}-{old_b}で敗戦')


def late_goal(g, p):
    """同点・決勝には届かなかった日本人の終盤の得点に、得点前後の差を添える。"""
    side = p['side']
    club, other, a, b = pair(g, side)
    for index, goal in enumerate(g['goals']):
        if goal['scorer'] != p['athlete_id'] or minute_number(goal) < 75 or a >= b:
            continue
        x, y = score_until(g['goals'], index, side)
        if y - x != 2 or (x + 1, y) != (a, b):
            continue
        previous = g['goals'][index - 1]
        before_x, before_y = score_until(g['goals'], index - 1, side)
        if previous['side'] == side or before_y - before_x != 1:
            continue
        name, minute = p['name'], goal['minute']
        return (f'{name} {minute}分に1点差へ {other}に{a}-{b}で敗戦',
                [opening(g, p, [f'{name}がゴールを決めたのだ！', f'{name}、最後に意地のゴールなのだ！'],
                         f'{national.minute_words(minute)}に決めて、{x}対{y}から{a}対{b}に縮めたわ。',
                         '終盤の得点', (name, minute+'分'), ('得点前', f'{x}-{y}')),
                 panel(pick(g, p, ['あと少しだったのだ…。その前はどうだったのだ？', '惜しいのだ…。どうして差が開いていたのだ？']),
                       f'{other}が{national.minute_words(previous["minute"])}に追加点を挙げて、差を広げていたわ。',
                       '相手の追加点', (other, previous['minute']+'分')),
                 ending(g, p, ['悔しいけど、最後まで諦めなかったのだ！', '惜しかったのだ…。でも意地を見せたのだ！'],
                        f'そうね。{a}対{b}で敗れたけれど、{name}のゴールで1点差まで迫ったわ。')],
                minute, '分に得点', '1点差に縮める')


def equalizer(g, p):
    side = p['side']
    club, other, a, b = pair(g, side)
    if a != b or a < 2:
        return
    goals = g['goals']
    for index, goal in enumerate(goals):
        if goal['scorer'] != p['athlete_id'] or index != len(goals) - 1:
            continue
        equalizers = [previous for i, previous in enumerate(goals[:index])
                      if previous['side'] == side and len(set(score_until(goals, i + 1, side))) == 1]
        if len(equalizers) != 1:
            continue
        first, minute = equalizers[-1]['minute'], goal['minute']
        leads = [previous for i, previous in enumerate(goals[:index])
                 if previous['side'] != side and len(set(score_until(goals, i, side))) == 1]
        if len(leads) != 2:
            continue
        push_a, push_b = (national.minute_words(previous['minute']) for previous in leads)
        passers = {person['athlete_id']: person['name'] for person in g['players']}
        assist = passers.get(leads[0]['assist'])
        said = f'そうなの。{other}が{push_a}と{push_b}にリードを奪って、{club}は{national.minute_words(first)}にも一度追いついていたわ。'
        rows = [(other, '・'.join(previous['minute']+'分' for previous in leads)), (club, first+'分')]
        if assist:
            said += f'{other}の先制点は{assist}のアシストだったわ。'
            rows.append(('先制点のアシスト', assist))
        name = p['name']
        return (f'{name} {minute}分に同点弾 {club}が{other}に2度追いつく',
                [opening(g, p, [f'{name}が同点ゴールなのだ！', f'{name}が追いついたのだ！'],
                         f'{national.minute_words(minute)}に決めて{a}対{b}にしたわ。', '同点ゴール', (name, minute+'分'), ('スコア', f'{a}-{b}')),
                 panel(pick(g, p, ['ずっと追いかける展開だったのだ？', 'もしかして何度も追いついたのだ？']),
                       said, '追いかけた展開', *rows),
                 ending(g, p, ['負けなかったのはえらいのだ！', '粘り強いのだ！'],
                        f'ええ。リードされても追いついて、{a}対{b}の引き分けに持ち込んだわ。')],
                minute, '分に同点弾', '2度追いつく')


TOPICS = {'late-winner':late_winner, 'keeper':keeper, 'early-goals':early_goals,
          'opponent-star':opponent_star, 'team-numbers':team_numbers, 'rematch':rematch, 'late-goal':late_goal, 'equalizer':equalizer}


def source(event_id):
    return 'https://www.espn.com/soccer/match/_/gameId/' + event_id


def narration(game, topic, player_id):
    player = next(p for p in game['players'] if p['athlete_id'] == player_id and p['status'] in ('starter', 'substitute'))
    result = TOPICS[topic](game, player)
    if not result:
        raise shared.Unavailable('話題に必要な数字と経過がありません')
    title, panels, big, unit, note = result
    from short_content import MIN_INFORMATION
    if len(panels) < MIN_INFORMATION:
        raise shared.Unavailable('確認できる補足情報が足りません')
    side = player['side']
    club, other, a, b = pair(game, side)
    own_abbr, other_abbr = game[side]['abbr'], game[other_side(side)]['abbr']
    hook = dict(subject=player['name'] if topic in ('keeper', 'late-winner', 'late-goal', 'equalizer') else club,
                big=big, unit=unit, note=note, score=f'{own_abbr} {a}-{b} {other_abbr}',
                result='勝利' if a > b else '敗戦' if a < b else '引き分け')
    segments = shared.dialogue_segments(topic, panels, hook)
    for segment in segments:
        segment['meta']['sub'] = f'{club} 対 {other}'
    clubs = {game[s]['name_jp']: dict(team_en=game[s]['name_en'], name_jp=game[s]['name_jp'],
                                    abbr=game[s]['abbr'], primary=None, secondary=None, league=game['league_jp'])
             for s in ('home', 'away')}
    doc = shared.tone_gate(short_common.prepare(dict(
        program=PROGRAM, date_jst=game['date_jst'], title=title+' #Shorts', topic=topic, player_id=player_id,
        event_id=game['id'], topic_key=game['id']+':'+topic, source_url=source(game['id']),
        segments=segments, topic_summary=game, clubs=clubs, screen_title=game['league_jp'],
        duration_budget=dict(limit=shared.LIMIT, grace=0),
        sanity_materials=[dict(source='ESPN 試合要約', sport='soccer', facts=game)])))
    if shared.estimate(doc) > shared.LIMIT:
        raise shared.Unavailable('原稿が制限時間を超えます')
    return doc


def check(doc):
    try:
        expected = narration(doc['topic_summary'], doc['topic'], doc['player_id'])
        if shared.doc_as_json(expected) == shared.doc_as_json(doc):
            return []
    except (ValueError, KeyError, TypeError, StopIteration):
        pass
    return ['クラブ戦の原稿と材料が不一致です']


def information(doc):
    if check(doc):
        raise ValueError('原稿と材料が不一致です')
    return [dict(subject=s['meta']['head'], fact='試合の数字と経過', value=s['meta']['rows'],
                 source=source(doc['topic_summary']['previous']['id']) if s['meta']['head']=='過去の対戦' else doc['source_url'],
                 segments=[i]) for i,s in enumerate(doc['segments']) if s['speaker'] == METAN and s['kind'] != 'outro']


def metadata(doc):
    if check(doc):
        raise ValueError('原稿と材料が不一致です')
    said = '\n'.join(s['text'] for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro')
    terms = [v for k,v in shared.GLOSSARY.items() if k in said]
    urls = [doc['source_url']]
    if doc['topic'] == 'rematch':
        urls.append(source(doc['topic_summary']['previous']['id']))
    description = '\n\n'.join(filter(None, (said, '\n'.join(terms), '出典: ESPN\n'+'\n'.join(urls),
                             '音声: VOICEVOX:ずんだもん・四国めたん\n#サッカー #Shorts')))
    return dict(snippet=dict(title=doc['title'], description=description, tags=['サッカー',doc['screen_title'],'コレスポ'],
                             categoryId='17', defaultLanguage='ja', defaultAudioLanguage='ja'))


def candidates(pool, ledger, now, replaces=''):
    local_day = now.astimezone(results.JST).date()
    if pool.get('date_jst') != (local_day - timedelta(days=1)).isoformat():
        return []
    active = {key: row for key, row in ledger.items() if not replaces or row.get('video_id') != replaces}
    used_today = sum(results.utc(row['publish_at']).astimezone(results.JST).date() == local_day for row in active.values())
    if used_today >= DAY_LIMIT:
        return []
    per_match = Counter(key.split(':', 1)[0] for key in active)
    made = {}
    ordered = sorted(((g, p) for g in pool.get('matches', []) if per_match[g['id']] < MATCH_LIMIT
                      for p in g['players']), key=lambda item: (-rank(item[1]), item[0]['id'], item[1]['name']))
    for game, player in ordered:
        for topic in TOPICS:
            key = game['id'] + ':' + topic
            if key in active or key in made:
                continue
            if replaces and ledger.get(key, {}).get('video_id') != replaces:
                continue
            try:
                made[key] = narration(game, topic, player['athlete_id'])
            except (shared.Unavailable, KeyError, StopIteration):
                continue
    return list(made.values())


def occupied_times(day, ledger, publication, replaces=''):
    morning = datetime.combine(day, datetime.strptime(clock.CONFIG['publish_jst'], '%H:%M').time(), results.JST)
    spread = [morning]
    spread.extend(results.utc(row['publish_at']) for row in ledger.values()
                  if not replaces or row.get('video_id') != replaces)
    booked = []
    for kind, rows in publication.items():
        for row in rows.values():
            if exclusion_reason(row) not in (None, '予約時刻前') or (replaces and row.get('video_id') == replaces):
                continue
            value = row.get('publish_at')
            if value:
                (spread if kind == 'soccer_results' else booked).append(results.utc(value))
    return spread, booked


def is_free(at, spread, booked):
    return all(abs(at - time) >= SPACING for time in spread) and at not in booked


def reservation(now, ledger, publication, replaces=''):
    """当日の朝の結果とクラブ戦ショートから90分以上空ける。"""
    local = now.astimezone(results.JST)
    spread, booked = occupied_times(local.date(), ledger, publication, replaces)
    at = (local + LEAD).replace(second=0, microsecond=0) + timedelta(minutes=1)
    while at.date() == local.date():
        if is_free(at, spread, booked):
            return at
        at += timedelta(minutes=1)
    return None


def validate_upload(args, now=None):
    if (os.getenv('COLLESPO_CLUB_TOPICS_PUBLISH') != 'true' or os.getenv('COLLESPO_SAMPLE_ONLY') == 'true'
            or args.sport != 'soccer' or args.privacy != 'public'):
        raise ValueError('クラブ戦の予約公開が有効ではありません')
    doc = national.read(args.narration)
    if check(doc) or doc['topic_summary'] != national.read(args.games):
        raise ValueError('原稿と材料が不一致です')
    now = now or datetime.now(results.JST)
    ledger = national.read(LEDGER)
    replaces = os.getenv('COLLESPO_TOPIC_REPLACES', '').strip()
    if not any(shared.doc_as_json(d) == doc for d in candidates(read_pool(), ledger, now, replaces)):
        raise ValueError('確認済みの話題・差し替え・本数上限を照合できません')
    if not args.publish_at:
        raise ValueError('予約時刻が必要です')
    at = results.utc(args.publish_at).astimezone(results.JST)
    if at < now + timedelta(minutes=5) or at.date() != now.astimezone(results.JST).date():
        raise ValueError('当日中の未来の予約枠が必要です')
    spread, booked = occupied_times(at.date(), ledger, national.read(PUBLICATIONS), replaces)
    if not is_free(at, spread, booked):
        raise ValueError('朝の結果とクラブ戦ショートから90分以上空け、予約の重複を避けてください')
    from short_content import validate_upload as validate_video
    if validate_video(args.video)['actual_seconds'] > shared.LIMIT:
        raise ValueError(f'話題ショートは{shared.LIMIT}秒までです')
    if not (Path(args.narration).parent/'audio/voice_manifest.json').is_file():
        raise ValueError('実音声の記録がありません')


def record_published(doc, vid, publish_at):
    ledger = national.read(LEDGER)
    before = ledger.get(doc['topic_key'])
    row = dict(video_id=vid, title=doc['title'], publish_at=results.utc(publish_at).astimezone(results.JST).isoformat())
    if before:
        row['replaced'] = before.get('replaced', []) + [before['video_id']]
    ledger[doc['topic_key']] = row
    national.save(LEDGER, ledger)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', type=Path, default=POOL)
    parser.add_argument('--at', type=results.utc, help='保存材料の動作確認用時刻')
    parser.add_argument('--topic-key')
    parser.add_argument('--publication-day')
    parser.add_argument('--reserve', action='store_true')
    parser.add_argument('--out', type=Path, default=ROOT/'build/soccer_club_topics')
    args = parser.parse_args(argv)
    now = args.at or datetime.now(results.JST)
    day = now.astimezone(results.JST).date().isoformat()
    if args.publication_day and day != args.publication_day:
        print('::notice::日本時間で対象日を過ぎたため見送ります')
        return
    ledger = national.read(LEDGER)
    replaces = os.getenv('COLLESPO_TOPIC_REPLACES', '').strip()
    docs = candidates(read_pool(args.pool), ledger, now, replaces)
    selected = next((d for d in docs if not args.topic_key or d['topic_key'] == args.topic_key), None)
    at = reservation(now, ledger, national.read(PUBLICATIONS), replaces) if args.reserve else None
    if not selected or (args.reserve and not at):
        print('::notice::未使用のクラブ戦話題または当日の予約枠がありません')
        return
    national.save(args.out/'narration.json', selected)
    national.save(args.out/'material.json', selected['topic_summary'])
    (args.out/'description.txt').write_text(metadata(selected)['snippet']['description'], encoding='utf-8')
    output = os.getenv('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write(f'build=true\ntopic_key={selected["topic_key"]}\npublication_day={day}\n')
            if at:
                stream.write(f'publish_at={at.isoformat()}\n')


if __name__ == '__main__':
    main()
