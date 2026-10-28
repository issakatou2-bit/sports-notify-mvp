"""既存の取得済み一次資料からだけ、短い回の背景を加える。取得・尺の水増しなし。"""
import copy
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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




def attach_asset(document, spec):
    """追加した成績も既存の点検に渡す。描画だけに根拠を閉じ込めない。"""
    document.setdefault('sanity_materials', []).append(dict(source='generation.asset',
        source_url=spec.get('source'), topic=spec.get('key'),
        facts=[dict(label=head, text=body) for head,body in spec.get('items') or []
               if not any(word in head for word in ('コメント','見出し','番記者'))],
        supplementary_sources=spec.get('short_supplement_sources')))
    return document




def soccer(narr, data, *, readable):
    """短い結果/速報は、同じ試合の取得済みシュート・保持率を補足する。"""
    if readable:
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
    if not readable or sum(len(s.get('text','')) for s in narr.get('segments', [])) >= 180:
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


def slots(plan, *, modern):
    """既に画面にある順位/勝点、週末のクラブ結果を音声でも2件補う。"""
    if not modern:
        return plan  # 旧画面の台詞・画素は保つ。公開前の下限検査は全種類で実行する。
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
