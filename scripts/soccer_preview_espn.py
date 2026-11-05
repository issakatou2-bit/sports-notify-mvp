"""ESPNの順位表を大会ごと1回取得し、保存日程のevent/team IDへ結び付ける。"""
from datetime import datetime, timezone
import math
import re

import club_display_names as clubs
import soccer_match_interest as interest

BASE = 'https://site.api.espn.com/apis/v2/sports/soccer'
LEAGUES = {
    'PL': ('eng.1', 'プレミアリーグ'), 'PD': ('esp.1', 'ラ・リーガ'),
    'BL1': ('ger.1', 'ブンデスリーガ'), 'SA': ('ita.1', 'セリエA'),
    'FL1': ('fra.1', 'リーグ・アン'), 'DED': ('ned.1', 'エールディビジ'),
    'PPL': ('por.1', 'ポルトガルリーグ'),
    'CL': ('uefa.champions', 'チャンピオンズリーグ'),
    'EL': ('uefa.europa', 'ヨーロッパリーグ'),
    'UECL': ('uefa.europa.conf', 'カンファレンスリーグ'),
}
EUROPE = {'CL', 'EL', 'UECL'}
# 2026/27のUEFA規則Article 17: 最終1〜8位は16強、9〜24位はプレーオフ。
# https://documents.uefa.com/r/Regulations-of-the-UEFA-Europa-League-2026/27/Article-17-Match-system-league-phase-Online
# CL/UECLも同じ進出順位。シーズンが変わったら再確認し、それまで境界は語らない。
RULE_SOURCE = 'https://documents.uefa.com/r/Regulations-of-the-UEFA-Europa-League-2026/27/Article-17-Match-system-league-phase-Online'


def binding(game):
    event = str(game.get('espn_event_id') or '')
    if not event.isdigit() or (str(game.get('game_id')).startswith('espn-') and str(game['game_id']) != 'espn-'+event):
        return None
    ids = {}
    for side in ('home', 'away'):
        value = (game.get('espn_team_ids') or {}).get(side) or game.get(side+'_team_id')
        if not isinstance(value, str) or not re.fullmatch(r'espn-\d+', value):
            return None
        ids[side] = value.removeprefix('espn-')
    return dict(event_id=event, team_ids=ids) if ids['home'] != ids['away'] else None


def domestic_code(game, side):
    # 名簿のリーグは取得先を選ぶためだけ。順位の対応は必ずteam IDで行う。
    row = clubs.lookup(game.get(side+'_team_name')) or {}
    code = row.get('league')
    return code if code in LEAGUES and code not in EUROPE else None


def requested(games):
    codes = set()
    for game in games:
        if not binding(game):
            continue
        code = game.get('competition_code')
        if code in LEAGUES:
            codes.add(code)
        codes.update(c for s in ('home', 'away') if (c := domestic_code(game, s)))
    return sorted(codes)


def fetch_tables(games, fetcher=None):
    if fetcher is None:
        from soccer_results import fetch_json
        fetcher = fetch_json
    saved = {}
    for code in requested(games):
        slug = LEAGUES[code][0]; url = BASE+'/'+slug+'/standings'
        try:
            payload = fetcher(url)
        except Exception:
            continue  # 再要求せず、取得不能を0位・0点へ変換しない。
        saved[code] = dict(source=url, slug=slug, retrieved_at=datetime.now(timezone.utc).isoformat(), payload=payload)
    return saved


def attach(games, tables):
    contexts = {}
    for game in games:
        bound = binding(game)
        if not bound:
            continue
        codes = {c for s in ('home', 'away') if (c := domestic_code(game, s))}
        if game.get('competition_code') in LEAGUES:
            codes.add(game['competition_code'])
        contexts[str(game['game_id'])] = dict(binding=bound, tables={c: tables[c] for c in codes if c in tables})
    return contexts


def integer(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum and value == int(value)


def entries(payload):
    """複数グループの順位を混ぜない。overallの順位表を別々に返す。"""
    result = []
    def visit(node):
        table = node.get('standings') or {}
        if isinstance(table, dict) and isinstance(table.get('entries'), list):
            if table.get('type') in (None, 0, '0', 'total', 'TOTAL', 'overall'):
                season = table.get('season', payload.get('season'))
                if isinstance(season, dict):
                    season = season.get('year')
                result.append((table['entries'], season))
        for child in node.get('children') or []:
            visit(child)
    visit(payload)
    return result


def row(entry):
    stats = {s.get('name'): s.get('value') for s in entry.get('stats', [])}
    if not all(integer(stats.get(k), 1 if k == 'rank' else 0) for k in ('rank', 'points', 'gamesPlayed')):
        return None
    if stats['gamesPlayed'] == 0:
        return None
    return dict(team_id=str((entry.get('team') or {}).get('id') or ''), rank=int(stats['rank']),
                points=int(stats['points']), played=int(stats['gamesPlayed']))


def facts(game, generated):
    ctx = (game.get('preview_angle_context') or {}).get('espn') or {}
    if not binding(game) or ctx.get('binding') != binding(game):
        return []
    kick = interest.timestamp(game.get('start_time_utc')); now = interest.timestamp(generated)
    if not kick or not now:
        return []
    season_year = kick.year if kick.month >= 7 else kick.year-1
    names = {s: clubs.display(game[s+'_team_name']) for s in ('home', 'away')}
    result = []
    for code, saved in ctx.get('tables', {}).items():
        if code not in LEAGUES or saved.get('slug') != LEAGUES[code][0] or saved.get('source') != BASE+'/'+LEAGUES[code][0]+'/standings':
            continue
        at = interest.timestamp(saved.get('retrieved_at'))
        payload = saved.get('payload') or {}
        if not at or not 0 <= (now-at).total_seconds() <= 48*3600 or at >= kick:
            continue
        league = LEAGUES[code][1]
        if code in EUROPE and game.get('phase') == 'knockout':
            continue
        def add(kind, score, text, **values):
            result.append(dict(kind=kind, score=score, text=text, source=saved['source'],
                               retrieved_at=saved['retrieved_at'], values=dict(competition=code, **values)))
        for group, year in entries(payload):
            if year != season_year:
                continue
            parsed = [r for e in group if (r := row(e))]
            hits = {s: [r for r in parsed if r['team_id'] == ctx['binding']['team_ids'][s]] for s in names}
            if code == game.get('competition_code'):
                if not all(len(hits[s]) == 1 for s in names):
                    continue
                pair = {s: hits[s][0] for s in names}
                if pair['home']['rank'] == pair['away']['rank']:
                    continue
                gap = abs(pair['home']['points']-pair['away']['points'])
                text = '、'.join(f'{names[s]}は{pair[s]["rank"]}位で勝点{pair[s]["points"]}' for s in names)
                add('european_points' if code in EUROPE else 'points', 120 if code in EUROPE else 100,
                    f'{league}では{text}。両チームの勝点差は{gap}です。', gap=gap, rows=pair, league=league)
                # 36クラブの単一表、league-phaseの季だけ。現在の位置を進出確定とは呼ばない。
                if code in EUROPE and season_year == 2026 and game.get('phase') != 'knockout' and len(parsed) == 36 and len({r['team_id'] for r in parsed}) == 36:
                    for side in names:
                        rank = pair[side]['rank']
                        zone = '16強へ直接進む1位から8位の範囲' if rank <= 8 else 'プレーオフに進む9位から24位の範囲' if rank <= 24 else 'プレーオフ圏の24位より下'
                        add('european_zone', 110, f'{names[side]}の現在の{rank}位は、{league}で{zone}です。', side=side, rank=rank, rule_source=RULE_SOURCE)
            elif code not in EUROPE:
                for side in names:
                    if domestic_code(game, side) == code and len(hits[side]) == 1:
                        r = hits[side][0]
                        add('domestic_'+side, 55, f'{names[side]}は{league}で現在{r["rank"]}位、勝点{r["points"]}です。', side=side, **r)
    return result
