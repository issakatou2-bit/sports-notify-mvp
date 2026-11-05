"""予告の角度。保存した根拠から再計算し、欠測・別大会・未来の結果を使わない。"""
import copy
import json
from pathlib import Path

import club_display_names as clubs
import soccer_match_interest as interest
import soccer_selection as selection

ROOT = Path(__file__).resolve().parents[1]


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def identity(name):
    return (clubs.lookup(name) or {}).get('id')


def fresh(at, generated, hours=48):
    a, b = interest.timestamp(at), interest.timestamp(generated)
    return bool(a and b and 0 <= (b-a).total_seconds() <= hours*3600)


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}


def ledger_rows(result, game, generated):
    """保存済み結果だけ。出場をevent_idで重複排除。全季の網羅を主張しない。"""
    start = interest.timestamp(game.get('start_time_utc'))
    cutoff = interest.timestamp(generated)
    if not start or not cutoff:
        return []
    # 国内/欧州の秋春シーズンの範囲。日付だけで欧州の大会成績に混ぜない。
    year = start.year if start.month >= 7 else start.year-1
    season_start = start.replace(year=year, month=7, day=1, hour=0, minute=0, second=0)
    people = selection.visible_members(game)
    found = {}
    ambiguous = set()
    for match in result.get('games', []):
        ended = interest.timestamp(match.get('finished_utc'))
        began = interest.timestamp(match.get('start_utc'))
        if not ended or not began or not season_start <= began < ended <= cutoff < start:
            continue
        ident = str(match.get('id') or '')
        if not ident:
            continue
        for p in match.get('players', []):
            side = next((s for s in people if p.get('name') in people[s]), None)
            team = (match.get(p.get('side')) or {}).get('name_en')
            if not side or not identity(team) or identity(team) != identity(game.get(side+'_team_name')):
                continue
            if p.get('status') not in ('starter', 'substitute') or not p.get('appearance_evidence'):
                continue
            key = (p['name'], ident)
            row = dict(name=p['name'], event_id=ident, competition=match.get('league'),
                       start=match['start_utc'], finished=match['finished_utc'],
                       goals=p.get('goals'), assists=p.get('assists'),
                       stats_source=p.get('stats_source'), appearance_evidence=p['appearance_evidence'])
            if key in found and found[key] != row:
                ambiguous.add(key)
            found[key] = row
    return [row for key, row in sorted(found.items()) if key not in ambiguous]


def attach(data, fetch=False, results=None, espn_tables=None):
    """選定後に一度保存する。描画/検査から通信しない。入力・台帳は不変。"""
    result = copy.deepcopy(data)
    generated = result['generated_at']
    selected = set((result.get('preview_selection') or {}).get('selected_ids', []))
    games = [g for g in result['games'] if str(g['game_id']) in selected]
    if fetch:
        import os
        import soccer_preview
        key = os.environ.get('FOOTBALL_DATA_API_KEY')
        contexts = soccer_preview.fetch_preview_context(games, key) if key else {}
    else:
        contexts = {}
    import soccer_preview_espn as espn
    if espn_tables is None:
        espn_tables = espn.fetch_tables(games) if fetch else {}
    espn_contexts = espn.attach(games, espn_tables)
    results = read(ROOT/'data/soccer_results.json') if results is None else results
    saved = read(ROOT/'data/soccer_preview.json')
    cached = {c.get('code'): c.get('preview_angle_context') or {} for c in saved.get('competitions', [])}
    for g in games:
        ctx = g.setdefault('preview_angle_context', {})
        for name, value in cached.get(g.get('competition_code'), {}).items():
            if fresh(value.get('retrieved_at'), generated):
                ctx.setdefault(name, value)
        ctx.update(contexts.get(str(g['game_id']), {}))
        if str(g['game_id']) in espn_contexts and espn_contexts[str(g['game_id'])]['tables']:
            ctx['espn'] = espn_contexts[str(g['game_id'])]
        times = [generated]+[v['retrieved_at'] for v in contexts.get(str(g['game_id']), {}).values() if v]
        times += [v['retrieved_at'] for v in (ctx.get('espn') or {}).get('tables', {}).values() if v.get('retrieved_at')]
        ctx['evaluated_at'] = max(times, key=interest.timestamp)
        # 保存試合の順位は、その試合の大会として取得した値だけを用いる。
        ctx.setdefault('snapshot', dict(source=g.get('fixture_sources') or [result.get('source') or 'football-data.org'],
                                       retrieved_at=generated, competition=g.get('competition_code') or g.get('league')))
        ctx.setdefault('ledger', dict(source='data/soccer_results.json', retrieved_at=results.get('generated_at'),
                                     rows=ledger_rows(results, g, generated)))
        ctx.setdefault('membership', dict(source='soccer_games.json.jp_by_side / JP_PLAYERS_SOCCER', retrieved_at=generated))
        g['preview_angles'] = angles(g, generated)
        point = next((a for a in g['preview_angles'] if a['kind'] in ('points','european_points')), None)
        if point:
            for side, value in point['values']['rows'].items():
                g[side+'_standing'] = dict(value)
    result['preview_angles_version'] = 1
    if any(r['kind'] == 'season_player' for g in games for r in g['preview_angles']):
        result['source'] = (result.get('source') or 'football-data.org')+'・FPL'
    return result


def angles(game, generated):
    ctx = game.get('preview_angle_context') or {}
    generated = ctx.get('evaluated_at') or generated
    output = []
    def add(kind, weight, text, evidence, **values):
        if not evidence.get('source') or not interest.timestamp(evidence.get('retrieved_at')):
            return
        output.append(dict(kind=kind, score=weight, text=text, source=evidence['source'],
                           retrieved_at=evidence['retrieved_at'], values=values))
    names = {s: clubs.display(game.get(s+'_team_name')) for s in ('home', 'away')}
    ids = {s: identity(game.get(s+'_team_name')) for s in names}
    standings = ctx.get('standings') or {}
    snap = ctx.get('snapshot') or {}
    code = game.get('competition_code') or game.get('league')
    rows = {}
    # APIの順位表は大会・季・同一TOTAL groupを確認する。
    kick = interest.timestamp(game.get('start_time_utc'))
    payload = standings.get('payload') or {}
    season = payload.get('season') or {}
    start, end = season.get('startDate'), season.get('endDate')
    valid_table = (fresh(standings.get('retrieved_at'), generated) and
                   (payload.get('competition') or {}).get('code') == code and kick and start and end and
                   start <= kick.date().isoformat() <= end)
    if valid_table:
        for group in payload.get('standings', []):
            if group.get('type') != 'TOTAL':
                continue
            table = group.get('table') or []
            hits = {s: [r for r in table if ids[s] and identity((r.get('team') or {}).get('name')) == ids[s]] for s in names}
            if all(len(hits[s]) == 1 for s in names):
                rows = {s: dict(rank=hits[s][0].get('position'), points=hits[s][0].get('points')) for s in names}
                break
    elif fresh(snap.get('retrieved_at'), generated) and snap.get('competition') == code:
        rows = {s: game.get(s+'_standing') or {} for s in names}
    evidence = standings if valid_table and rows else snap
    league = game.get('league', '')
    for s, row in rows.items():
        rank, points = row.get('rank'), row.get('points')
        if integer(rank, 1) and integer(points):
            add('standing', 65, f'{names[s]}は{league}で{rank}位、勝点{points}です。', evidence, side=s, rank=rank, points=points)
    if len(rows) == 2 and all(integer(rows[s].get('rank'), 1) and integer(rows[s].get('points')) for s in names):
        gap = abs(rows['home']['points']-rows['away']['points'])
        add('points', 100 if gap <= 3 else 70,
            f'{names["home"]}は{rows["home"]["rank"]}位で勝点{rows["home"]["points"]}、{names["away"]}は{rows["away"]["rank"]}位で勝点{rows["away"]["points"]}。両チームの勝点差は{gap}です。',
            evidence, gap=gap, rows=rows)
    if valid_table and rows:
        for s, row in rows.items():
            # すぐ上だけ。欧州出場枠や降格枠は大会規則の裏付けなしに仮定しない。
            above = [r for r in table if integer(row.get('rank'), 2) and r.get('position') == row['rank']-1]
            if len(above) == 1 and integer(above[0].get('points')) and integer(row.get('points')):
                diff = above[0]['points']-row['points']
                if diff >= 0:
                    add('above', 75 if diff <= 3 else 50, f'{names[s]}とすぐ上の{clubs.display(above[0]["team"]["name"])}の勝点差は{diff}です。', evidence, side=s, gap=diff)
    finished = ctx.get('finished') or {}
    if fresh(finished.get('retrieved_at'), generated):
        for s in names:
            matches = []
            seen = set()
            for m in (finished.get('payload') or {}).get('matches', []):
                at = interest.timestamp(m.get('utcDate'))
                if m.get('status') != 'FINISHED' or not at or not at < interest.timestamp(generated) or not kick or not at < kick:
                    continue
                ms = m.get('season') or {}
                same_season = ((valid_table and ms.get('id') is not None and ms.get('id') == season.get('id')) or
                               (ms.get('startDate') and ms.get('endDate') and ms['startDate'] <= kick.date().isoformat() <= ms['endDate']))
                if (m.get('competition') or {}).get('code') != code or not same_season:
                    continue
                home = identity((m.get('homeTeam') or {}).get('name'))
                away = identity((m.get('awayTeam') or {}).get('name'))
                score = (m.get('score') or {}).get('fullTime') or {}
                if not ids[s] or ids[s] not in (home, away) or not all(integer(score.get(k)) for k in ('home', 'away')):
                    continue
                if not m.get('id') or m['id'] in seen:
                    continue
                seen.add(m['id'])
                a, b = (score['home'], score['away']) if ids[s] == home else (score['away'], score['home'])
                matches.append((at, 'W' if a > b else 'L' if a < b else 'D', m['id']))
            recent = sorted(matches, reverse=True)[:5]
            if len(recent) == 5:
                form = [m[1] for m in recent]
                add('form', 85, f'{names[s]}は{league}の直近5試合で{form.count("W")}勝{form.count("D")}分{form.count("L")}敗です。', finished, side=s, form=form, match_ids=[m[2] for m in recent])
    people = selection.visible_members(game)
    if all(people.values()):
        add('japanese_pair', 95, '、'.join(names[s]+'には'+'・'.join(people[s]) for s in names)+'が所属しています。', ctx.get('membership') or {}, members=people)
    # 既存の公式FPL保存分も補う。国内リーグの個人成績と大会の戦績を区別する。
    personal = interest.expectation(game)
    if personal and personal.get('japanese'):
        label = '今季のプレミアリーグで' if personal['source'] == 'https://fantasy.premierleague.com/api/bootstrap-static/' else '今季は'
        add('season_player', 82, personal['name']+'は'+label+interest.player_numbers(personal).replace(' ', '')+'です。',
            dict(source=personal['source'], retrieved_at=personal['as_of']),
            name=personal['name'], goals=personal.get('goals'), assists=personal.get('assists'))
    ledger = ctx.get('ledger') or {}
    for name in [n for group in people.values() for n in group]:
        records = [r for r in ledger.get('rows', []) if r.get('name') == name]
        if not records:
            continue
        stats = ''
        values = dict(name=name, appearances=len(records), match_ids=[r['event_id'] for r in records])
        for field, unit in [('goals', '得点'), ('assists', 'アシスト')]:
            if all(integer(r.get(field)) and r.get('stats_source') for r in records):
                values[field] = sum(r[field] for r in records)
                stats += f'、{values[field]}{unit}'
        add('ledger', 60, f'{name}は今季の保存済み結果の範囲で{len(records)}試合に出場{stats}です。', ledger, **values)
    previous = ctx.get('h2h') or {}
    if fresh(previous.get('retrieved_at'), generated):
        candidates = []
        for m in (previous.get('payload') or {}).get('matches', []):
            pair = {identity((m.get(s+'Team') or {}).get('name')) for s in names}
            at = interest.timestamp(m.get('utcDate'))
            scores = (m.get('score') or {}).get('fullTime') or {}
            if (None not in pair and pair == set(ids.values()) and m.get('status') == 'FINISHED' and at and
                    kick and at < min(kick, interest.timestamp(generated)) and all(integer(scores.get(s)) for s in names)):
                candidates.append((at, m, scores))
        if candidates:
            at, match, scores = max(candidates, key=lambda r: r[0])
            text = '対'.join(clubs.display(match[s+'Team']['name']) for s in names)
            add('h2h', 80, f'前回の対戦は{at.year}年{at.month}月{at.day}日の{text}で{scores["home"]}対{scores["away"]}でした。', previous, match_id=match.get('id'), score=scores)
    if game.get('phase') == 'knockout' and game.get('phase_source'):
        add('knockout', 90, f'この試合は{league}の決勝トーナメントです。', dict(source=game['phase_source'], retrieved_at=snap.get('retrieved_at')), phase='knockout')
    from soccer_selected_preview import preview_details
    for text in preview_details(game):
        add('previous_season', 40, text+'。', dict(source='soccer_games.json.reasons.quality', retrieved_at=snap.get('retrieved_at')))
    import soccer_preview_espn
    espn_facts = soccer_preview_espn.facts(game, generated)
    if any(r['kind'] in ('points','european_points') for r in espn_facts):
        output = [r for r in output if r['kind'] not in ('points','standing')]
    output.extend(espn_facts)
    output.sort(key=lambda r: (-r['score'], r['kind'], r['text']))
    return output


def chosen(game, generated):
    result = []
    kinds = set()
    # 片側だけの事実は日本人のいるクラブの分を使う（相手だけの順位や調子を主役にしない）。
    people = selection.visible_members(game)
    jp_sides = {s for s in people if people[s]}
    for row in angles(game, generated):
        if row['kind'] in kinds or row['kind'] == 'standing' and kinds.intersection({'points','european_points'}):
            continue
        if jp_sides and row['values'].get('side') in ('home', 'away') and row['values']['side'] not in jp_sides:
            continue
        kinds.add(row['kind']); result.append(row)
        if len(result) == 3:
            break
    return result


def headline(game, generated):
    people = selection.visible_members(game)
    side = next((s for s in people if people[s]), 'home')
    other = 'away' if side == 'home' else 'home'
    subject = (people[side][0]+'の' if people[side] else '')+clubs.display(game[side+'_team_name'])
    opponent = clubs.display(game[other+'_team_name'])
    import soccer_title_v2
    if soccer_title_v2.enabled():
        # 題は今の題と同じ新聞の書き方（「久保ソシエダ」）。本文は正式名のまま（10/10 本人）。
        who = people[side][0] if people[side] else ''
        short = soccer_title_v2.player_name(who) if who else ''
        subject = (short+('の' if short == who else '') if who else '')+soccer_title_v2.club_name(game[side+'_team_name'])
        opponent = soccer_title_v2.club_name(game[other+'_team_name'])
    rows = chosen(game, generated)
    if not rows:
        return subject+'が'+opponent+'と対戦'
    row = rows[0]; v = row['values']
    if row['kind'] in ('points', 'european_points'):
        scope = v['league']+'で' if row['kind'] == 'european_points' else ''
        rank = '' if v['rows'][other].get('tied') else f'{v["rows"][other]["rank"]}位'
        return subject+'が'+scope+f'勝点{v["gap"]}差の{rank}'+opponent+'と対戦'
    if row['kind'] == 'japanese_pair':
        return subject+'が'+'・'.join(people[other])+'所属の'+opponent+'と対戦'
    if row['kind'] == 'form':
        form=v['form']; club=clubs.display(game[v['side']+'_team_name'])
        return subject+'対'+opponent+f' {club}は直近5試合{form.count("W")}勝{form.count("D")}分{form.count("L")}敗'
    if row['kind'] == 'standing':
        return subject+'対'+opponent+' '+clubs.display(game[v['side']+'_team_name'])+f'は{v["rank"]}位で勝点{v["points"]}'
    if row['kind'] == 'h2h':
        score=v['score']
        return subject+'対'+opponent+f' 前回対戦は{score["home"]}対{score["away"]}'
    if row['kind'] == 'ledger':
        return subject+'対'+opponent+f' {v["name"]}は今季保存結果で{v["appearances"]}試合出場'
    if row['kind'] == 'season_player':
        return subject+'対'+opponent+' '+row['text'].rstrip('。')
    if row['kind'] == 'knockout':
        return subject+'対'+opponent+' '+game['league']+'の決勝トーナメント'
    return subject+'対'+opponent+' '+row['text'].rstrip('。').replace('、', '・')


def body(game, generated, opening):
    rows = chosen(game, generated)
    if rows:
        return opening+''.join(r['text'] for r in rows)
    # 角度が欠測でも、所属の事実は言える。出場予定には変換しない。
    people = selection.visible_members(game)
    return opening+''.join(clubs.display(game[s+'_team_name'])+'には'+'・'.join(people[s])+'が所属しています。' for s in people if people[s])


def preview_title(data):
    selected = (data.get('preview_selection') or {}).get('selected_ids') or []
    matches = [g for g in data.get('games', []) if selected and str(g.get('game_id')) == str(selected[0])]
    if len(matches) != 1:
        raise ValueError('予告の題を選定試合へ照合できません')
    return '【欧州サッカー】'+headline(matches[0], data['generated_at'])+' #Shorts'


def check(document):
    """表示・読み上げの改変を元の数値から再計算して止める。"""
    if document.get('preview_angles_version') != 1:
        return []
    material = document.get('soccer_material') or {}
    generated = material.get('retrieved_at')
    games = material.get('games') or []
    errors = []
    for seg in document.get('segments', []):
        if seg.get('kind') != 'preview':
            continue
        ident = str((seg.get('meta') or {}).get('game_id'))
        matches = [g for g in games if str(g.get('game_id')) == ident]
        if len(matches) != 1:
            errors.append('予告の角度: 試合IDが不一致'); continue
        g = matches[0]
        from soccer_selected_preview import opening
        from soccer_story_lines import caption_names
        expected = caption_names(body(g, generated, opening(g, generated)), [g])
        for side,name in (g.get('preview_name_fallbacks') or {}).items():
            expected=expected.replace(name,'ホームのクラブ' if side=='home' else 'アウェーのクラブ')
        if seg.get('text') != expected or (seg.get('meta') or {}).get('preview_angles') != chosen(g, generated):
            errors.append('予告の角度: 数字・名前・本文が保存材料と不一致')
    focus = document.get('preview_angles_game_id')
    lead = next((g for g in games if str(g.get('game_id')) == focus), None)
    if not lead or document.get('title') != '【欧州サッカー】'+headline(lead, generated)+' #Shorts':
        errors.append('予告の角度: 題が本文の根拠と不一致')
    elif lead:
        expected = headline(lead, generated)+'。'
        for g in games:
            for side,name in (g.get('preview_name_fallbacks') or {}).items():
                expected=expected.replace(name,'ホームのクラブ' if side=='home' else 'アウェーのクラブ')
        if any(s.get('text') != expected for s in document.get('segments', []) if s.get('kind') == 'cover'):
            errors.append('予告の角度: 表紙の数字・名前が保存材料と不一致')
    return errors
