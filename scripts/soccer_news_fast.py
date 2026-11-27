
"""ESPNの国内リーグ記事を拾い、保存済みの順位・直近の結果を添える。"""
from datetime import datetime, timedelta
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import market_watch as common

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEAGUES = {'eng.1': 'PL', 'esp.1': 'PD', 'ita.1': 'SA', 'ger.1': 'BL1', 'fra.1': 'FL1'}
API = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
DEPARTURE = re.compile(r'\b(?:sack(?:s|ed)?|dismiss(?:es|ed)?|part(?:s|ed)? (?:company|ways)|steps down|resigns)\b', re.I)
APPOINTMENT = re.compile(r'\b(?:appoint(?:s|ed)?|name[ds]?|hires?|hired|takes charge|as (?:new |interim )?(?:head coach|manager))\b', re.I)
MANAGER = re.compile(r'\b(?:manager|coach|boss)\b', re.I)
INJURY = re.compile(r'\b(?:injur(?:y|ed|ies)|ruled out|sidelined|knock|hamstring|fracture)\b', re.I)
TRANSFER = re.compile(r'\b(?:transfer|sign(?:s|ed|ing)?|(?:set|agree[ds]?) to join|loan deal)\b', re.I)
MONEY = re.compile(r'([€£$])\s*(\d+(?:\.\d+)?)\s*(?:m(?:illion)?|mn)\b', re.I)
RUMOR = re.compile(r'\b(?:rumou?rs?|could|may|eyeing|interested|consider(?:s|ing)?|odds|tip(?:s|ped)?|if|should|to sack|could be|linked)\b', re.I)
MANAGER_EVENT = re.compile(r'\b(?:confirm(?:s|ed)?|announce(?:s|d)?)\b', re.I)


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not result.tzinfo:
        raise ValueError('日時にタイムゾーンがありません')
    return result


def names(load):
    verified = {r['name_en']: r for r in load('soccer_player_names.json')['players'] if r.get('status') == 'confirmed'}
    roster = {r['name_en']: r for r in load('soccer_voice_names.json')['players']}
    return {en: {**roster.get(en, {}), **r} for en, r in verified.items()}


def club_key(value):
    return re.sub(r'\b(?:fc|afc|cf|calcio|osc|sv)\b|[^a-z0-9]+', '', common.fold(value))


def team_parts(article, player):
    tags = {str(c.get('teamId')): c.get('team') or {}
            for c in article.get('categories', []) if c.get('type') == 'team' and c.get('teamId')}
    label = player.get('team_en', '') if player else ''
    if label:
        for team_id, team in tags.items():
            options = [team.get(key, '') for key in ('description', 'shortDisplayName')]
            if any(club_key(s) == club_key(label) for s in options):
                return team_id, label
    if len(tags) == 1:
        team_id, team = next(iter(tags.items()))
        return team_id, team.get('description', '')
    return '', label


def article_record(article, league, players, now):
    url = article.get('links', {}).get('web', {}).get('href', '')
    if not url.startswith('https://') or not re.fullmatch(r'(?:[\w-]+\.)?espn\.com', urlsplit(url).hostname or ''):
        return None
    article_id = str(article.get('id', ''))
    if not article_id.isdecimal() or not article.get('published') or not article.get('headline'):
        return None
    stamp = instant(article['published'])
    if not now - timedelta(days=2) <= stamp <= now:
        return None
    head = article['headline']
    lead = article.get('description') or ''
    player_hits = common.find_targets(head, {en: p['name_jp'] for en, p in players.items()})
    if not player_hits:
        player_hits = common.find_targets(lead, {en: p['name_jp'] for en, p in players.items()})
    # 複数選手の記事も課題へ届ける。どの選手の発表かを自動では断定しない。
    player = players[player_hits[0][0]] if len(player_hits) == 1 else {}
    team_id, team_en = team_parts(article, player)
    role = MANAGER.search(head + ' ' + lead)
    departure, appointment = DEPARTURE.search(head), APPOINTMENT.search(head)
    large = next((m for m in MONEY.finditer(head + ' ' + lead) if float(m[2]) >= 50), None)
    manager_change = bool(role and (departure or appointment)
                          and not re.search(r'(?i)\b(?:last (?:season|year)|had been|next manager odds|favourite to)\b', head))
    rumor = bool(RUMOR.search(head + ' ' + lead))
    if manager_change and not rumor:
        kind = '監督退任' if departure else '監督就任'
    elif player_hits:
        kind = 'けが' if INJURY.search(head + ' ' + lead) else '移籍・契約' if TRANSFER.search(head + ' ' + lead) else '日本人選手'
    elif large and TRANSFER.search(head + ' ' + lead):
        kind = '大型移籍'
    else:
        return None
    return dict(key=f'news-espn-{article_id}', published=stamp.isoformat(), headline=head, description=lead, outlet='ESPN',
                league=league, url=url, kind=kind, team_id=team_id, team_en=team_en,
                players=[p[1] for p in player_hits], player_en=player.get('name_en'), reading=player.get('reading'),
                january=stamp.month == 1, reported_fee=large[0] if large else '',
                confirmed=bool(MANAGER_EVENT.search(head + ' ' + lead) and not rumor))


def context(report, load):
    from notability_engine import club_name_jp

    document = load('soccer_preview.json')
    code = LEAGUES[report['league']]
    comp = next((r for r in document.get('competitions', []) if r['code'] == code), {})
    if not comp or comp.get('stale') or not document.get('generated_at'):
        return {}
    reported = instant(report['published'])
    asof = instant(document['generated_at'])
    if abs(asof - reported) > timedelta(days=7):
        return {}
    team = report['team_en']
    label = club_name_jp(team)
    tables = [row for row in comp.get('table', []) if club_key(row['team']) == club_key(team)
              or club_name_jp(row['team']) == label]
    if len(tables) != 1:
        return {}
    row = tables[0]
    if any(type(row.get(k)) is not int for k in ('position', 'points', 'played')):
        return {}
    snapshot = comp.get('preview_angle_context', {})
    table_source = snapshot.get('standings', {}).get('source')
    if not table_source:
        return {}
    checks = snapshot.get('finished', {})
    matches_input = checks.get('payload', {}).get('matches', [])
    if any(match.get('status') == 'FINISHED' and match.get('utcDate')
           and reported <= instant(match['utcDate']) <= asof for match in matches_input):
        return {}
    matches = []
    for match in matches_input:
        if match.get('status') != 'FINISHED' or not match.get('utcDate') or instant(match['utcDate']) >= reported:
            continue
        home, away = [match.get(k, {}).get('name', '') for k in ('homeTeam', 'awayTeam')]
        is_home = home == row['team']
        if not is_home and away != row['team']:
            continue
        score = match.get('score', {}).get('fullTime', {})
        gf, ga = (score.get('home'), score.get('away')) if is_home else (score.get('away'), score.get('home'))
        if type(gf) is int and type(ga) is int:
            matches.append((match['utcDate'], gf, ga))
    last = sorted(set(matches), reverse=True)[:5]
    form = [sum(a > b for _, a, b in last), sum(a == b for _, a, b in last), sum(a < b for _, a, b in last)]
    season = [row.get(k) for k in ('won', 'draw', 'lost')]
    return dict(team=label, league=comp['name_jp'], position=row['position'], points=row['points'],
                day=asof.astimezone(common.JST).date().isoformat(), form=form if len(last) == 5 else [],
                table_source=table_source, results_source=checks.get('source', ''),
                season=season if all(type(value) is int for value in season) and sum(season) == row['played'] else [])


def material(report, saved):
    """監督交代など事実を限定できる記事だけ公開候補にする。"""
    kind = report['kind']
    if not saved or not saved.get('team'):
        raise ValueError('所属クラブと保存順位の照合が必要')
    team = saved['team']
    outlet = report['outlet']
    main_rows = [['クラブ', team]]
    head = kind
    if kind in {'監督退任', '監督就任'}:
        headline = f'{team} {kind}'
        coach = report.get('coach')
        verb = '監督を解任した' if re.search(r'\b(?:sack|dismiss)', report['headline'], re.I) else (
            '監督が退任した' if kind == '監督退任' else '新監督が就任した')
        if verb == '監督を解任した':
            said = f'{outlet}は、{team}が{verb}と伝えたわ。'
        else:
            said = f'{outlet}は、{team}で{verb}と伝えたわ。'
        opening = f'{team}のベンチに動きがあったのだ！'
        readings = {}
        if coach and kind == '監督就任':
            headline = f'{team} {coach["name"]}が監督就任'
            said = f'{team}は、{coach["name"]}の監督就任を発表したわ。'
            readings[coach['name']] = coach['reading']
            main_rows.append(['新監督', coach['name']])
        publishable = outlet == 'ESPN' and report['confirmed']
    elif kind in {'けが', '移籍・契約'} and len(report['players']) == 1 and report['reading']:
        name = report['players'][0]
        # 相手選手のけがや「復帰した」の誤読を防ぎ、名前とけがの述語の結び付きを求める。
        text = report['headline'] + '。' + report['description']
        player_en = re.escape(common.fold(report.get('player_en') or ''))
        if not player_en:
            raise ValueError('選手名と記事の文面を照合する必要')
        if kind == 'けが':
            pattern = player_en + r"\s+(?:(?:is|was|has been) )?(?:injured|ruled out|sidelined|has an? .{0,16}injury|suffered)\b"
            if not re.search(pattern, common.fold(text)):
                raise ValueError('選手本人のけがと記事の文面を照合する必要')
            headline = f'{name}のけがを{outlet}が報道'
            said = f'{outlet}が{name}のけがを伝えたわ。'
        else:
            transfer = player_en + r'\s+(?:signs?|signed|agreed to (?:sign|join)|joins?|joined)\b|\b(?:signs?|signed)\s+' + player_en
            if not re.search(transfer, common.fold(text)) or RUMOR.search(text):
                raise ValueError('選手本人の合意や契約と記事の文面を照合する必要')
            headline = f'{name}の契約を{outlet}が報道'
            said = f'{outlet}は、{name}の契約について伝えたわ。'
        opening = f'{name}のニュース、気になるのだ！'
        readings = {name: report['reading']}
        main_rows.append(['選手', name])
        publishable = outlet == 'ESPN' and report['confirmed']
    else:
        raise ValueError('記事の要点を日本語にするには確認が必要')
    pos, pts = saved['position'], saved['points']
    month, day = map(int, saved['day'].split('-')[1:])
    context_word = f'{month}月{day}日時点で、{saved["league"]}の{pos}位、勝点{pts}よ。'
    rows = [['順位', f'{pos}位'], ['勝点', str(pts)]]
    if saved['form'] and saved['results_source']:
        record, stat_label, source = saved['form'], '直近5試合', saved['results_source']
        stat_text = '報道前のリーグ戦、直近5試合は'
    elif saved['season']:
        record, stat_label, source = saved['season'], 'ここまでの戦績', saved['table_source']
        stat_text = f'その時点までのリーグ戦{sum(record)}試合は'
    else:
        raise ValueError('節目の順位と比較できる保存試合が足りない')
    wins, draws, losses = record
    form = f'{wins}勝{draws}分け{losses}敗'
    return dict(checked_on=instant(report['published']).astimezone(common.JST).date().isoformat(),
                title=headline, readings=readings, opening=opening, publishable=publishable,
                items=[dict(ask=opening, text=said, head=head, rows=main_rows,
                            source_names=outlet, sources=[report['url']]),
                       dict(ask='リーグ戦での位置も気になるのだ。', text=context_word, head='リーグ戦の状況',
                            rows=rows, source_names='保存順位表', sources=[saved['table_source']]),
                       dict(ask='最近の戦いぶりも見ておきたいのだ。', text=f'{stat_text}{form}だったわ。',
                            head=stat_label, rows=[['リーグ戦', form]], source_names='リーグ戦記録', sources=[source])],
                news=dict(report=report, context=saved))


def fetch(league):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(f'{API}/{league}/news', timeout=12)
        response.raise_for_status()
        articles = response.json().get('articles')
        if not isinstance(articles, list):
            raise ValueError('ESPNのニュース記事一覧がありません')
        return articles
