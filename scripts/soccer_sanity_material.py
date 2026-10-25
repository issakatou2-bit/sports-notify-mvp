"""保存したサッカー材料で順位・勝点の指摘を照合する。通信しない。"""
import json
import re
from datetime import datetime
from pathlib import Path

import club_display_names as clubs


def compact(data):
    games = [{k: g[k] for k in ('game_id', 'league', 'home_team_name', 'away_team_name',
             'home_standing', 'away_standing', 'fixture_sources', 'start_time_jst',
             'start_time_utc') if k in g} for g in data.get('games') or []]
    competitions = [{k: c[k] for k in ('code', 'name_jp', 'season', 'stale', 'table',
                     'last_season', 'last_season_year', 'lines') if k in c}
                    for c in data.get('competitions') or []]
    return dict(source=data.get('source') or 'football-data.org',
                retrieved_at=data.get('generated_at') or data.get('updated_at'),
                date_jst=data.get('date_jst') or data.get('date') or
                (data.get('generated_at') or data.get('updated_at') or '')[:10],
                games=games, competitions=competitions)


def grounding(documents):
    result = []
    for document in documents:
        if not document.get('soccer_v4_mode'):
            continue
        candidates = [document['soccer_material']] if document.get('soccer_material') else []
        if not candidates:
            for filename in ('data/soccer_games.json', 'data/soccer_race.json', 'data/soccer_preview.json'):
                try:
                    candidates.append(dict(compact(json.loads(Path(filename).read_text(encoding='utf-8'))),
                                           snapshot_path=filename))
                except (OSError, ValueError, TypeError):
                    pass
        for source in candidates:
            day = document.get('date_jst') or (document.get('soccer_material') or {}).get('date_jst')
            if not day:
                # 旧原稿には「10月24日（土）」のlabelだけがある。
                label = document.get('label') or ''
                try:
                    at = datetime.fromisoformat(source['date_jst'])
                except (KeyError, ValueError):
                    continue
                if not label.startswith(f'{at.month}月{at.day}日'):
                    continue
                day = source['date_jst']
            if day == source.get('date_jst') and source.get('retrieved_at'):
                result.append(dict(source, sport='soccer'))
    return result


def aliases(name):
    row = clubs.lookup(name) or {}
    return sorted({n for n in (name, row.get('display'), row.get('current'), row.get('legacy'),
                              row.get('short'), row.get('id'), *row.get('aliases', [])) if n}, key=len, reverse=True)


def for_document(document, materials):
    """別の日の原稿へ、同時に点検した回の順位を流用しない。"""
    day = document.get('date_jst') or (document.get('soccer_material') or {}).get('date_jst')
    label = document.get('label') or ''
    result = []
    for source in materials or []:
        if source.get('sport') != 'soccer':
            continue
        if day and day == source.get('date_jst'):
            result.append(source)
        elif not day:
            try:
                at = datetime.fromisoformat(source['date_jst'])
            except (KeyError, ValueError):
                continue
            if label.startswith(f'{at.month}月{at.day}日'):
                result.append(source)
    return result


def review(text, materials, why=None, context=None):
    """戻り値は一致/矛盾/確認不能。指摘された種類だけを免除する。"""
    if re.search(r'昨季|昨年|前季|ではない|ではなく|だった|でした', text):
        return None
    targets = set()
    if why is not None:
        if re.search(r'順位|首位|何位|\d+位', why):
            targets.add('rank')
        if re.search(r'勝点|勝ち点', why):
            targets.add('points')
        # 別の主張を順位の一致だけで免除しない。
        if re.search(r'スコア|所属|得点|日程|時刻|開催地', why):
            return None
        if not targets:
            return None
    values = {'rank': [], 'points': []}
    for source in materials or []:
        if source.get('sport') != 'soccer':
            continue
        games = list(source.get('games') or [])
        for comp in source.get('competitions') or []:
            for line in comp.get('lines') or []:
                rows = line.get('inside', []) + line.get('outside', [])
                boundary = [next((r for r in rows if r.get('position') == pos), {})
                            for pos in (line.get('at'), (line.get('at') or 0)+1)]
                if all(r.get('team_en') for r in boundary):
                    games.append({**{s+'_team_name': r['team_en'] for s, r in zip(('home', 'away'), boundary)},
                                  **{s+'_standing': dict(rank=r['position'], points=r.get('points'))
                                     for s, r in zip(('home', 'away'), boundary)}})
        for game in games:
            names = [game.get(s+'_team_name') for s in ('home', 'away')]
            if not all(names) or not all(any(n in (context or text) for n in aliases(name)) for name in names):
                continue
            standings = [game.get(s+'_standing') or {} for s in ('home', 'away')]
            ranks = [s.get('rank') for s in standings]
            remainder = text
            for name, standing in zip(names, standings):
                for alias in aliases(name):
                    pattern = re.escape(alias)
                    for match in re.finditer(r'(首位|\d+位)(?:の)?'+pattern+'|'+pattern+r'(?:は|が|の)?(?:、)?(首位|\d+位)', text):
                        rank = next(v for v in match.groups() if v)
                        values['rank'].append(standing.get('rank') == (1 if rank == '首位' else int(rank[:-1])) if standing.get('rank') is not None else None)
                        remainder = remainder.replace(match[0], '')
            anonymous = re.search(r'首位チームと(\d+)位の対戦', text)
            if anonymous:
                values['rank'].append(sorted(ranks) == [1, int(anonymous[1])] if all(type(r) is int for r in ranks) else None)
                remainder = remainder.replace(anonymous[0], '')
            if re.search(r'首位(?!争い)|\d+位', remainder):
                values['rank'].append(None)
            for match in re.finditer(r'勝(?:ち)?点差(?:は)?(\d+)', text):
                import soccer_match_interest
                gap = soccer_match_interest.point_gap(*standings)
                values['points'].append(gap == int(match[1]) if gap is not None else None)
    selected = [v for key in (targets or values.keys()) for v in values[key]]
    if False in selected:
        return False
    if why is not None and any(not values[key] for key in targets):
        return None
    return True if selected and all(v is True for v in selected) else None
