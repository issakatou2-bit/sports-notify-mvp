"""既存の取得済み一次資料からだけ、短い回の背景を加える。取得・尺の水増しなし。"""
import copy
import math


def rare(spec, topics, season):
    """指標が1つの資産回に、同年・同じ選手の終了済み公式集計を添える。"""
    if not str(spec.get('key','')).startswith('rare_') or len(spec.get('items') or []) >= 3:
        return spec
    ident = spec['key'].removeprefix('rare_')
    peer = topics.get('season_player_'+ident) or {}
    if (not str(season).isdigit() or len(str(season)) != 4 or peer.get('ps_ended') is not True or str(peer.get('player_id')) != ident
            or str(season)+'年' not in str(peer.get('label',''))):
        return spec
    supplements = [copy.deepcopy(row) for row in peer.get('items') or []
                   if row[0] == '今季の成績' or row[0].startswith(f'昨季（{int(season)-1}年）')]
    if len(supplements) < 2:
        return spec
    result = copy.deepcopy(spec)
    result['items'] = result['items'] + supplements[:2]
    result['short_supplement_sources'] = dict(season=str(season), player_id=ident,
        source='MLB公式 / data/season_topics.json / '+peer['key'], items=supplements[:2])
    return result


def ps(program, ctx, games, rows):
    """PSが1組の日は直前の終了試合を補う。日程と同じ公式応答を根拠にする。"""
    import ps_program as p
    pairs = []
    names = {t['id']: t['name'] for row in rows for t in row.get('teams', [])}
    for seg in program['segments']:
        scoreboard = (seg.get('meta', {}).get('card') or {}).get('scoreboard') or {}
        pair = {r.get('name') for r in scoreboard.get('rows', [])}
        if len(pair) == 2 and pair not in pairs:
            pairs.append(pair)
    if len(pairs) != 1:
        return program
    pair = pairs[0]
    finished = []
    for game in games:
        if game.get('status', {}).get('abstractGameState') != 'Final':
            continue
        teams = game.get('teams') or {}
        if set(names.get((teams.get(side, {}).get('team') or {}).get('id')) for side in ('away', 'home')) != pair:
            continue
        if not all(type(teams[side].get('score')) is int for side in ('away', 'home')):
            continue
        finished.append(game)
    if not finished:
        return program
    game = max(finished, key=lambda g: (g.get('gameDate', ''), g['gamePk']))
    # 取得済みの当該シリーズだけ。別回戦の同じ組合せへ遡らない。
    relevant = [row for row in rows if {t['name'] for t in row.get('teams', [])} == pair and row['round'] == game['gameType']]
    if not relevant:
        return program
    away, home = (game['teams'][side] for side in ('away', 'home'))
    a, h = (names[team['team']['id']] for team in (away, home))
    rnd = p.ROUND[game['gameType']][0]
    number = game.get('seriesGameNumber')
    if not isinstance(number, int):
        return program
    label = f'{rnd}第{number}戦'
    result = f'{a} {away["score"]}対{home["score"]} {h}'
    text = f'直前に終了した{label}は、{a}対{h}が{away["score"]}対{home["score"]}でした。前戦は{h}のホームでした。'
    card = dict(p.common(ctx, '前戦の結果', program.get('target_day')),
                layout='facts', short_context=True, headline=a+'\n対'+h, subhead=label+' / 終了',
                items=[dict(label='前戦の最終結果', value=result, value_size=60),
                       dict(label='前戦の開催地', value=h+'のホーム', value_size=44)])
    # 同じ試合の既存の試合経過が残っていれば、決勝点も補足する。
    # 公式日程と得点/球団IDが一致しないtopicは混ぜない。
    import generated_topics
    topic = generated_topics.get('season_game_'+str(game['gamePk']))
    score = (topic.get('game_v4') or {}).get('score') or {}
    decisive = (topic.get('game_v4') or {}).get('decisive') or {}
    same = topic.get('game') and topic.get('game_pk') == game['gamePk'] and all(
        (score.get(side) or {}).get('id') == game['teams'][side]['team']['id']
        and (score.get(side) or {}).get('total') == game['teams'][side]['score'] for side in ('home','away'))
    detail = None
    if same and all(decisive.get(k) for k in ('inning','subject','action')):
        detail = decisive['inning']+' '+decisive['subject']+'の'+decisive['action']
        card['items'].append(dict(label='前戦の決勝点', value=detail, value_size=44))
        text += '決勝点は'+detail+'でした。'
    seg = p.segment(card, text)
    seg['meta']['context_game_id'] = game['gamePk']
    program = copy.deepcopy(program)
    program['segments'].append(seg)
    program['short_context_material'] = dict(source='generation.ps.previous_game', source_url=ctx['source_url'],
        games=[dict(game_pk=game['gamePk'], home_team_name=h, away_team_name=a,
                    final_score=dict(home=home['score'], away=away['score']))],
        facts=[dict(label='前戦の決勝点', text=detail, source='MLB公式 liveData.plays')] if detail else [])
    return program


def attach_asset(document, spec):
    """追加した成績も既存の点検に渡す。描画だけに根拠を閉じ込めない。"""
    document.setdefault('sanity_materials', []).append(dict(source='generation.asset',
        source_url=spec.get('source'), topic=spec.get('key'),
        facts=[dict(label=head, text=body) for head,body in spec.get('items') or []
               if not any(word in head for word in ('コメント','見出し','番記者'))],
        supplementary_sources=spec.get('short_supplement_sources')))
    return document


def goal(data):
    """得点回も速報と同じ試合経過・本人の出場/詳細成績を使う。"""
    import soccer_result_story
    import soccer_results_render
    # 得点の事実・最終結果・得点時刻・本人の出場/シュートを別の札にする。
    # 既存のv5/v6札を再利用し、材料がない日はgate側で止める。
    base = soccer_results_render.narration(data)
    detail = soccer_result_story.narration(data)
    # 元の得点・アシストの冒頭を保ち、後段だけを既存の詳しい結果と共有。
    if base.get('segments'):
        base['segments'] = [base['segments'][0]] + [s for s in detail['segments']
            if s['kind'] not in ('followup','roster','outro','flash-results','other-results')] + [base['segments'][-1]]
    return soccer(base, data)


def soccer(narr, data):
    """短い結果/速報は、同じ試合の取得済みシュート・保持率を補足する。"""
    import soccer_look
    if soccer_look.readable():
        covered = set()
        for seg in narr.get('segments', []):
            if seg['kind'] != 'player-stats':
                continue
            game = next((g for g in data.get('games',[]) if str(g.get('id')) == str(seg['meta'].get('event_id'))), {})
            people = [p for p in game.get('players',[]) if p.get('status')!='none']
            covered.update(p['name'] for p in people[seg['meta'].get('start',0):seg['meta'].get('start',0)+seg['meta'].get('count',1)])
        kept = []
        for seg in narr.get('segments', []):
            meta = seg.get('meta') or {}
            if seg['kind']=='roster' and meta.get('player_names') and not meta.get('absent') and set(meta['player_names']) <= covered:
                continue  # 全員を個別に示した後の同じ一覧は繰り返さない。
            if seg['kind']=='followup-detail' and seg.get('text','').strip()=='得点なし。':
                game = next((g for g in data.get('games',[]) if str(g.get('id')) == str(meta.get('event_id'))), {})
                primary = any(s['kind'] in ('intro','followup') and (s.get('meta') or {}).get('event_id')==meta.get('event_id') for s in narr['segments'])
                if primary and game.get('goals_complete') and not game.get('goals') and game.get('score')==dict(home=0,away=0):
                    continue  # 0対0の直後に「得点なし」だけの間を足さない。
            kept.append(seg)
        if len(kept) != len(narr.get('segments', [])):
            narr = copy.deepcopy(dict(narr,segments=kept))
    if not soccer_look.readable() or sum(len(s.get('text','')) for s in narr.get('segments', [])) >= 180:
        return narr
    for game in data.get('games') or []:
        if any(s['kind']=='team-stats' and str(s['meta'].get('event_id')) == str(game['id']) for s in narr['segments']):
            continue
        stats = game.get('match_stats') or {}
        if not stats.get('source'):
            continue
        if not all(type((stats.get(side) or {}).get(k)) in (int,float) for side in ('home','away') for k in ('shots','possession')):
            continue
        if not all(type(stats[side]['shots']) is int and stats[side]['shots'] >= 0
                   and math.isfinite(stats[side]['possession']) and 0 <= stats[side]['possession'] <= 100
                   for side in ('home','away')):
            continue
        home, away = game['home']['name_jp'], game['away']['name_jp']
        text = (f"試合全体のシュートは{home}{stats['home']['shots']}本、{away}{stats['away']['shots']}本。"
                f"ボール保持率は{home}{stats['home']['possession']:g}パーセント、{away}{stats['away']['possession']:g}パーセントでした。")
        narr = copy.deepcopy(narr)
        at = next((i for i,s in enumerate(narr['segments']) if s['kind']=='outro'), len(narr['segments']))
        narr['segments'].insert(at, dict(kind='team-stats', text=text, speaker=2,
            meta=dict(event_id=game['id'], short_context_stats=stats)))
        break
    return narr


def slots(plan):
    """既に画面にある順位/勝点、週末のクラブ結果を音声でも2件補う。"""
    import notability_engine as ne
    narr = plan['narration']
    if sum(len(s.get('text','')) for s in narr.get('segments', [])) >= 180:
        return plan
    if plan['mode'] == 'race':
        seg = next((s for s in narr['segments'] if s['kind']=='standings'), None)
        if seg:
            rows = [r for r in seg['meta'].get('rows', []) if type(r.get('position')) is int and type(r.get('points')) is int][:2]
            if len(rows) == 2:
                seg['text'] = ''.join(f"{ne.club_name_jp(r.get('team') or r.get('team_en'))}は{r['position']}位で勝点{r['points']}。" for r in rows)
                if type(rows[0].get('played')) is int and rows[0]['played'] == rows[1].get('played'):
                    seg['text'] += f"いずれも{rows[0]['played']}試合を消化した時点の順位です。"
    elif plan['mode'] == 'week':
        seen = set()
        for seg in narr['segments']:
            if seg['kind'] != 'jp_player':
                continue
            row = next((r for r in plan['data'].get('rows', []) if r.get('club') == seg['meta'].get('club')), None)
            if not row or row['club'] in seen or not all(type(row.get(k)) is int for k in ('gf','ga')):
                continue
            seen.add(row['club'])
            seg['text'] += f"所属クラブの{row['club']}は、{row['opp']}との試合を{row['gf']}対{row['ga']}で終えました。"
    return plan
