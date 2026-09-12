"""Current active rosters gate MLB previews; affiliation is not eligibility.

Missing/stale data removes player promotion, never invents a return date.
One snapshot is shared by narration, pictures and distribution in a run.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
import functools
from pathlib import Path
import sys
import urllib.request

SNAPSHOT = Path('data/mlb_availability.json')
MAX_AGE_SECONDS = 6 * 3600
API = 'https://statsapi.mlb.com/api/v1'


def fresh(snapshot, now=None):
    try:
        stamp = datetime.fromisoformat(snapshot['checked_at'].replace('Z', '+00:00'))
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        return 0 <= age <= MAX_AGE_SECONDS
    except (KeyError, TypeError, ValueError):
        return False


def load(path=SNAPSHOT):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def roster(team_id):
    url = f'{API}/teams/{team_id}/roster?rosterType=active'
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            rows = json.load(response)['roster']
        if not isinstance(rows, list) or not rows:
            raise ValueError('Empty roster')
        return str(team_id), {'source': url, 'players': [
            {'id': str(r['person']['id']), 'name': r['person']['fullName']}
            for r in rows if r.get('status', {}).get('code') == 'A']}
    except Exception as exc:
        print(f'[warn] Active roster {team_id}: {type(exc).__name__}', file=sys.stderr)
        return str(team_id), {'source': url, 'players': [], 'unavailable': True}


def collect(payload):
    ids = sorted({str(g[f]) for g in payload.get('games', []) if g.get('league') == 'MLB'
                  for f in ('home_team_id', 'away_team_id') if str(g.get(f, '')).isdigit()})
    # Record the START of fetching, not a later timestamp that hides stale input.
    checked = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=4) as pool:
        teams = dict(pool.map(roster, ids))
    return {'checked_at': checked, 'roster_type': 'active', 'teams': teams}


@functools.lru_cache(maxsize=1)
def aliases():
    from notability_engine import JP_PLAYERS_MLB
    return {p['name_jp']: p['name_en'] for p in JP_PLAYERS_MLB}


def eligible(game, name, snapshot, now=None):
    if not fresh(snapshot, now) or snapshot.get('roster_type') != 'active':
        return False
    english = aliases().get(name, name)
    for field in ('home_team_id', 'away_team_id'):
        team = snapshot.get('teams', {}).get(str(game.get(field)), {})
        if not team.get('unavailable') and any(p.get('name') == english for p in team.get('players', [])):
            return True
    return False


def prepare(games, snapshot=None, now=None):
    """Sanitize copies; existing affiliation/history never proves participation."""
    snapshot = load() if snapshot is None else snapshot
    result = deepcopy(games)
    jp = aliases()
    for game in result:
        if game.get('league') != 'MLB':
            continue
        blocked = {name for name in jp if not eligible(game, name, snapshot, now)}
        words = blocked | {jp[n] for n in blocked}
        def safe(text):
            return not any(word in str(text or '') for word in words)
        game['jp_players'] = [n for n in game.get('jp_players', []) if n not in blocked and eligible(game, n, snapshot, now)]
        game['jp_starters'] = [p for p in game.get('jp_starters', []) if eligible(game, p.get('name'), snapshot, now)]
        game['log_notes'] = [t for t in game.get('log_notes', []) if safe(t)]
        old_reasons = game.get('reasons', [])
        game['reasons'] = [r for r in old_reasons if safe(r.get('text'))]
        # Recompute the published score if unavailable-player reasons were removed.
        if len(old_reasons) != len(game['reasons']):
            game['score'] = sum(r.get('weight', 0) for r in game['reasons'])
            game['is_notable'] = game['score'] >= 3
        for field in ('notification_hook', 'ai_summary'):
            if not safe(game.get(field)):
                game.pop(field, None)
        # Foreign probable starters must also be on an active roster.
        for field in ('home_probable', 'away_probable'):
            probable = game.get(field)
            if isinstance(probable, dict) and not eligible(game, probable.get('name_en') or probable.get('name'), snapshot, now):
                game[field] = None
        game['availability_checked_at'] = snapshot.get('checked_at') if fresh(snapshot, now) else None
    return result


def check_narration(payload, narration, snapshot, now=None):
    """A deterministic publication gate; recap results are historical, not previews."""
    import re
    from notability_engine import JP_PLAYERS_MLB
    games = [g for g in payload.get('games', []) if g.get('is_notable')][:3]
    if not any(g.get('league') == 'MLB' for g in games):
        return
    if narration.get('date_label') != (games[0].get('start_time_jst') or '').split(' ')[0]:
        raise ValueError('Narration date does not match preview games')
    for segment in narration.get('segments', []):
        if segment.get('kind') not in ('intro', 'game'):
            continue
        meta = segment.get('meta', {})
        at = meta.get('game_index', meta.get('hook', {}).get('at', 0))
        if not isinstance(at, int) or not 0 <= at < len(games):
            raise ValueError('Narration game reference is invalid')
        value = segment.get('text', '') + json.dumps(meta.get('hook', {}), ensure_ascii=False)
        if re.search(r'\d+日ぶりの出場なるか', value):
            raise ValueError('An appearance gap does not support a return preview')
        for p in JP_PLAYERS_MLB:
            if any(n in value for n in (p['name_jp'], p['name_en'], p.get('kana')) if n):
                if not eligible(games[at], p['name_jp'], snapshot, now):
                    raise ValueError(f"Preview promotes an unavailable/unverified player: {p['name_jp']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', default='notable_games.json')
    parser.add_argument('--snapshot', default=str(SNAPSHOT))
    parser.add_argument('--check-narration')
    parser.add_argument('--archive-dir')
    args = parser.parse_args()
    path = Path(args.games)
    payload = json.loads(path.read_text(encoding='utf-8'))
    if args.check_narration:
        check_narration(payload, json.loads(Path(args.check_narration).read_text(encoding='utf-8')), load(args.snapshot))
        print('[info] Player availability publication gate passed')
        return
    snapshot = collect(payload)
    dest = Path(args.snapshot)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    payload['games'] = prepare(payload.get('games', []), snapshot)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.archive_dir:
        # The engine saved this edition before the availability filter. Update only
        # matching game IDs in that edition; preserve soccer and historical results.
        day = str(payload.get('generated_at', ''))[:10]
        from datetime import date
        date.fromisoformat(day)
        archive = Path(args.archive_dir) / (day + '.json')
        if archive.exists():
            previous = json.loads(archive.read_text(encoding='utf-8'))
            by_id = {str(g.get('game_id')): g for g in payload['games'] if g.get('game_id')}
            previous['games'] = [by_id.get(str(g.get('game_id')), g) for g in previous.get('games', [])]
            archive.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[info] Active roster snapshot: {len(snapshot['teams'])} teams; player previews filtered")


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
