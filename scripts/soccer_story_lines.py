"""保存数字から確定する台詞。通信・AI・順位の仮定は使わない。"""
import re
import math
import club_display_names as names

LATE_MINUTE = 76  # 75分・75+Nは含めない。76分から終盤。


def preview_conclusion(game):
    # 杯戦の勝利をリーグの勝点へ変換しない。国内リーグと分かる場合だけ。
    leagues = {'PL':'プレミアリーグ','PD':'ラ・リーガ','BL1':'ブンデスリーガ',
               'SA':'セリエA','FL1':'リーグ・アン'}
    code = game.get('competition_code')
    if game.get('phase') == 'knockout' or (code not in leagues if code else game.get('league') not in leagues.values()):
        return ''
    standings = [game.get(s+'_standing') if isinstance(game.get(s+'_standing'),dict) else {} for s in ('home', 'away')]
    def valid(p):
        return type(p) in (int, float) and math.isfinite(p) and p >= 0 and p == int(p)
    points = [s.get('points') for s in standings]
    back = [s.get('points_back') for s in standings]
    if not all(valid(p) for p in points) and all(valid(p) for p in back):
        # 同じ順位表の首位からの勝点差。同じ基準なので符号を反転して比較。
        points = [-int(p) for p in back]
    elif not all(valid(p) for p in points):
        return ''
    else:
        points = [int(p) for p in points]
        if all(valid(p) for p in back) and points[0]-points[1] != back[1]-back[0]:
            return ''
    if points:
        if points[0] == points[1]:
            return '勝点で並ぶ2チームの直接対決です。'
        low = 0 if points[0] < points[1] else 1
        gap = abs(points[0]-points[1])
        club = [names.display(game[s+'_team_name']) for s in ('home', 'away')]
        if gap > 3:
            return f'{club[low]}が勝てば、{club[1-low]}との差は勝点{gap-3}に縮まります。'
        if gap == 3:
            return f'{club[low]}が勝てば、{club[1-low]}と勝点で並びます。'
        return f'{club[low]}が勝てば、{club[1-low]}を勝点で上回ります。'
    return ''


def preview_facts(game, previous):
    from soccer_selection import visible_members
    units = []
    for side in ('home', 'away'):
        club = names.display(game[side+'_team_name'])
        standing = game.get(side+'_standing') if isinstance(game.get(side+'_standing'),dict) else {}
        rank, points = standing.get('rank'), standing.get('points')
        rank_ok = type(rank) is int and rank > 0
        point_ok = type(points) is int and points >= 0
        if rank_ok or point_ok:
            value = (f'{rank}位' if rank_ok else '')
            value += ('で' if rank_ok and point_ok else '') + (f'勝点{points}' if point_ok else '')
            units.append(f'{club}は{value}です。')
    units.extend(f+'。' for f in previous)
    for side, people in visible_members(game).items():
        if people:
            units.append(f'{names.display(game[side+"_team_name"])}の登録メンバーには、'+ '、'.join(people)+'が入っています。')
    return units


def goal_trace(game):
    """全得点・最終スコアが合う時だけ経過を確定。順序不明も推測しない。"""
    if not game.get('goals_complete'):
        return []
    goals = game.get('goals') or []
    if any(g.get('side') not in ('home', 'away') or not re.fullmatch(r'\d+(?:\+\d+)?', str(g.get('minute', ''))) for g in goals):
        return []
    ordered = sorted(goals, key=lambda g: tuple(map(int, (str(g['minute']).split('+')+['0'])[:2])))
    keys = [(g['minute'], g['side'], g.get('scorer')) for g in ordered]
    if len(set(keys)) != len(keys):
        return []
    # 同時刻で両チームの得点順を決められなければ流れを断定しない。
    for a, b in zip(ordered, ordered[1:]):
        if a['minute'] == b['minute'] and a['side'] != b['side']:
            return []
    score = dict(home=0, away=0)
    trace = []
    for goal in ordered:
        before = dict(score)
        score[goal['side']] += 1
        trace.append((goal, before, dict(score)))
    if any(type(game['score'].get(s)) is not int or score[s] != game['score'][s] for s in score):
        return []
    return trace


def flow_units(game):
    """連続得点をまとめる。日本人の得点・アシストは全件残す。"""
    from itertools import groupby
    import soccer_result_facts as facts
    trace = goal_trace(game)
    units = []
    # 片方だけが得点した試合は流れが1本なので、同じクラブ名を続けず1文にする。
    clean = next((s for s in ('home', 'away') if game['score'][s] > 0 and game['score']['away' if s == 'home' else 'home'] == 0), None)
    if trace and clean:
        count = game['score'][clean]
        club = names.display(game[clean])
        units.append(f'{club}が{count}点を奪い、無失点で勝ちました。' if count > 1 else f'{club}が1点を守り切りました。')
    if trace:
        for side, group in groupby([] if clean else trace, key=lambda row: row[0]['side']):
            run = list(group)
            other = 'away' if side == 'home' else 'home'
            before, after = run[0][1], run[-1][2]
            club = names.display(game[side])
            count = len(run)
            late = all(int(row[0]['minute'].split('+')[0]) >= LATE_MINUTE for row in run)
            when = '終盤に' if late else ''
            if not sum(before.values()):
                line = f'{club}が{count}点を先行しました。' if count > 1 else f'{club}が先制しました。'
            elif after[side] == after[other]:
                line = f'{club}が{when}同点に追いつきました。'
            elif before[side] < before[other] and after[side] > after[other]:
                line = f'{club}が{when}逆転しました。'
            elif before[side] < before[other]:
                line = f'{club}が{when}{count}点を返しました。'
            elif before[side] == before[other]:
                line = f'{club}が{when}勝ち越しました。'
            else:
                line = f'{club}が{when}{count}点を加えました。'
            units.append(line)
        for side in ('home', 'away'):
            half = [row for row in trace if row[0]['side'] == side and int(row[0]['minute'].split('+')[0]) >= 46]
            if len(half) >= 2 and len(half) < game['score'][side]:
                units.append(f'{names.display(game[side])}は後半だけで{len(half)}点を挙げました。')
    # 経過欠測でも日本人が関わった確かな得点は省かない。
    for goal in game.get('goals', []):
        if goal.get('japanese_goal'):
            units.append(facts.goal_line(goal, game))
        assists = facts.assist_names(goal)
        if assists:
            units.append(facts.minute_text(goal['minute'])+'の得点を'+ '、'.join(assists)+'がアシストしました。')
    if not units:
        units = ['両チームとも無得点でした。'] if game.get('goals_complete') and game['score'] == dict(home=0, away=0) else [facts.competition(game)+'の結果です。']
    return units


def caption_names(text, games):
    """表示名だけ統一。音声用の読みは既存辞書へ渡す。"""
    replacements = {}
    for game in games:
        for side in ('home', 'away'):
            value = game.get(side) or game.get(side+'_team_name')
            row = names.lookup(value)
            if row:
                for alias in [row['legacy'], row['current'], *row.get('aliases', [])]:
                    if alias and alias != row['display']:
                        replacements[alias] = row['display']
    for source in sorted(replacements, key=len, reverse=True):
        text = text.replace(source, replacements[source])
    return text
