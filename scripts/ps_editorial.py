"""Choose the PS subject from verified fixtures, not just the opening date.

This adapter owns the interval between bracket confirmation and the first
game. The regular/series producers remain the source for their other phases.
No paid model calls. A failed fetch never silently reuses a race snapshot.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

JST = timezone(timedelta(hours=9))
API = 'https://statsapi.mlb.com/api/v1/'


def preview_review_required(snapshot, approved=''):
    """Hold new public formats until their concrete preview is approved."""
    return (snapshot.get('editorial', {}).get('stage') in
            ('bracket_preview', 'bracket_pending') and
            str(approved).lower() != 'true')


def fetch(url):
    with urllib.request.urlopen(url, timeout=35) as response:
        return json.load(response)


def team_id(team):
    value = team.get('id')
    name = team.get('name', '')
    return value if isinstance(value, int) and '/' not in name and 'Winner' not in name else None


def game_time(game):
    """The API supplies dummy timestamps even when startTimeTBD is true."""
    if game.get('status', {}).get('startTimeTBD', True):
        day = datetime.fromisoformat(game['officialDate']) + timedelta(days=1)
        return {'day_jst': day.date().isoformat(), 'time_jst': None,
                'label': f'{day.month}/{day.day} 時刻未定', 'start_utc': None}
    start = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00'))
    local = start.astimezone(JST)
    return {'day_jst': local.date().isoformat(), 'time_jst': local.strftime('%H:%M'),
            'label': f'{local.month}/{local.day} {local:%H:%M}',
            'start_utc': start.isoformat()}


def editorial(snapshot, schedule, now, schedule_url):
    day = now.astimezone(JST).date().isoformat()
    if snapshot.get('date') != day:
        raise ValueError('PS順位資料が当日のものではありません')
    names = {}
    qualifiers = set()
    rows = snapshot.get('teams', {})
    rows = [dict(row, id=int(key)) for key, row in rows.items()] if isinstance(rows, dict) else rows
    for row in rows:
        ident = row.get('id')
        if not isinstance(ident, int):
            continue
        names[ident] = row.get('name', str(ident))
        if row.get('clinched') or row.get('div_champ') or row.get('wc_clinched'):
            qualifiers.add(ident)
    games = [g for d in schedule.get('dates', []) for g in d.get('games', [])]
    if not games and snapshot.get('phase') == 'postseason':
        raise ValueError('PS資料の日程が欠落。取得失敗と試合なしを確認してください')
    for game in games:
        if game.get('gameType') not in ('F', 'D', 'L', 'W'):
            continue
        try:
            official_year = datetime.fromisoformat(game['officialDate']).year
            source_year = int(game.get('season', official_year))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('PS試合の年度を確認できません') from exc
        if official_year != now.astimezone(JST).year or source_year != official_year:
            raise ValueError('PS日程の年度が当年資料と一致しません')
    first = {}
    byes = []
    for game in games:
        if game.get('seriesGameNumber') != 1:
            continue
        away = game.get('teams', {}).get('away', {}).get('team', {})
        home = game.get('teams', {}).get('home', {}).get('team', {})
        aid, hid = team_id(away), team_id(home)
        if game.get('gameType') == 'F' and aid and hid:
            pair = frozenset((aid, hid))
            if pair in first and first[pair]['gamePk'] != game['gamePk']:
                raise ValueError('同一カードの第1戦が重複')
            first[pair] = game
        elif game.get('gameType') == 'D' and hid and not aid:
            byes.append(game)
    result = {'version': 1, 'date_jst': day, 'retrieved_at': now.isoformat(),
              'stage': 'race', 'source_url': schedule_url, 'warnings': [],
              'matchups': [], 'reactions': []}
    result['fixture_evidence'] = {'dates': [{'games': [g for g in games
        if g.get('gameType') in ('F', 'D') and g.get('seriesGameNumber') == 1]}]}
    # Qualifications alone cannot prove the seed/opponent assignment.
    if len(qualifiers) == 12:
        result['stage'] = 'bracket_pending'
    if len(first) != 4 or len(byes) != 4:
        if snapshot.get('phase') == 'postseason':
            result['stage'] = 'series'
        return result
    all_teams = [team_id(g['teams'][side]['team'])
                 for g in first.values() for side in ('away', 'home')]
    all_teams += [team_id(g['teams']['home']['team']) for g in byes]
    if len(set(all_teams)) != 12 or set(all_teams) != qualifiers:
        raise ValueError('公式対戦表の12球団と進出確定球団が不一致')
    for pair, game in first.items():
        matches = []
        for bye in byes:
            # Placeholder names enumerate the possible winner, not a team.
            placeholder = bye['teams']['away']['team']['name']
            abbreviations = {g['teams'][side]['team'].get('abbreviation')
                             for g in [game] for side in ('away', 'home')}
            if None not in abbreviations and set(placeholder.split('/')) == abbreviations:
                matches.append(bye)
        if len(matches) != 1:
            raise ValueError('WC勝者の進路を公式DS日程から一意に確認できません')
        bye = matches[0]
        home, away = game['teams']['home']['team'], game['teams']['away']['team']
        next_team = bye['teams']['home']['team']
        lid = home.get('league', {}).get('id')
        if lid not in (103, 104) or away.get('league', {}).get('id') != lid or next_team.get('league', {}).get('id') != lid:
            raise ValueError('対戦球団のリーグが不明/不一致')
        names.update({t['id']: names.get(t['id'], t['name']) for t in (home, away, next_team)})
        result['matchups'].append({
            'game_pk': game['gamePk'], 'league': lid,
            'home': {'id': home['id'], 'name': names[home['id']]},
            'away': {'id': away['id'], 'name': names[away['id']]},
            'bye': {'id': next_team['id'], 'name': names[next_team['id']]},
            'first_game': game_time(game), 'ds_first': game_time(bye),
            'best_of': 3, 'advance_wins': 2,
            'third_game_conditional': True,
        })
    if any(sum(m['league'] == lid for m in result['matchups']) != 2 for lid in (103, 104)):
        raise ValueError('リーグ別の対戦数が不正')
    first_start = min(datetime.fromisoformat(m['first_game']['start_utc'])
                      for m in result['matchups'] if m['first_game']['start_utc']) if any(m['first_game']['start_utc'] for m in result['matchups']) else None
    already_played = any(g.get('status', {}).get('abstractGameState') in ('Live', 'Final')
                         for g in first.values())
    result['stage'] = 'series' if already_played or (first_start and now >= first_start) else 'bracket_preview'
    result['matchups'].sort(key=lambda m: (m['first_game']['day_jst'], m['first_game']['time_jst'] or '99:99'))
    # Some official standings flags contradict the scheduled playoff route.
    # Do not repeat the false district-champion label in this presentation.
    for row in rows:
        if row.get('div_champ') and row.get('div_rank') not in (None, 1):
            result['warnings'].append(f"{row.get('name')}: 地区優勝フラグと地区順位が矛盾。公式対戦日程を使用")
    return result


def local_reactions(context, reporters, now):
    names = {m[k]['name'] for m in context['matchups'] for k in ('home', 'away', 'bye')}
    accepted = []
    for post in reporters.get('posts', []):
        jp = post.get('jp', '')
        if post.get('team') not in names or not jp or not any(w in jp for w in ('プレーオフ', 'ポストシーズン', 'ワイルドカード')):
            continue
        try:
            age = now - datetime.fromisoformat(post['at'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            continue
        if not timedelta(0) <= age <= timedelta(hours=36) or len(jp) > 100:
            continue
        uri = post.get('uri', '')
        if not uri.startswith('at://') or not post.get('handle'):
            continue
        accepted.append({'text': jp, 'original': post.get('text', ''),
                         'author': post.get('author', post['handle']),
                         'outlet': post.get('outlet', ''), 'at': post['at'],
                         'url': f"https://bsky.app/profile/{post['handle']}/post/{uri.rsplit('/', 1)[-1]}"})
    return accepted[:1]


def apply(snapshot, context):
    result = dict(snapshot)
    result['editorial'] = context
    if context['stage'] == 'bracket_preview':
        result.update(phase='postseason', headline='組み合わせ確定・日本時間の開幕日程', changes=[])
    elif context['stage'] == 'bracket_pending':
        result.update(phase='settled', headline='出場12球団決定・組み合わせは確認中', changes=[])
    return result


def edition_key(context):
    # Retrieval/date changes alone are not new editorial information.
    content = {key: context.get(key) for key in ('stage', 'matchups', 'reactions')}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='data/postseason.json')
    parser.add_argument('--reporters', default='data/local_reporters.json')
    parser.add_argument('--evidence', default='build/ps_editorial_source.json')
    args = parser.parse_args()
    path = Path(args.input)
    snapshot = json.loads(path.read_text(encoding='utf-8'))
    now = datetime.now(timezone.utc)
    year = now.astimezone(JST).year
    # Only fetch near the end of the regular season. Other months delegate.
    if now.astimezone(JST).month not in (9, 10, 11):
        snapshot['editorial'] = {'stage': 'offseason', 'date_jst': now.astimezone(JST).date().isoformat()}
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    url = (API + f'schedule?sportId=1&season={year}&startDate={year}-09-15'
           f'&endDate={year}-11-10&gameType=F,D,L,W&hydrate=team,probablePitcher')
    schedule = fetch(url)
    context = editorial(snapshot, schedule, now, url)
    reporters = Path(args.reporters)
    if reporters.exists():
        context['reactions'] = local_reactions(context, json.loads(reporters.read_text(encoding='utf-8')), now)
    context['edition_key'] = edition_key(context)
    previous = path.with_name(path.stem + '_prev.json')
    ledger = Path('data/published_videos.json')
    if context['stage'] == 'bracket_preview' and previous.exists() and ledger.exists():
        before = json.loads(previous.read_text(encoding='utf-8'))
        record = json.loads(ledger.read_text(encoding='utf-8')).get('morning_postseason', {}).get(before.get('date'), {})
        published_at = record.get('publish_at') or record.get('published_at')
        if published_at and record.get('video_id') and datetime.fromisoformat(published_at.replace('Z', '+00:00')) <= now:
            context['suppress_unchanged'] = before.get('editorial', {}).get('edition_key') == context['edition_key']
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({'retrieved_at': now.isoformat(), 'source_url': url,
                                    'schedule': schedule, 'editorial': context}, ensure_ascii=False, indent=2), encoding='utf-8')
    path.write_text(json.dumps(apply(snapshot, context), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[info] PS編集段階: {context['stage']} / 固定対戦 {len(context['matchups'])}件")


if __name__ == '__main__':
    main()
