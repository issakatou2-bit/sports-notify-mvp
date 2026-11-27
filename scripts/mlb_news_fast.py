
"""報道の取材元と契約条件を照合して、移籍ショートの材料を作る。"""
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import market_watch as rss
import mlb_trends

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AGREEMENT = re.compile(r'\b(?:agree(?:d|s|ment)?|to sign|signs?|signed|announced the signing|acquired|traded)\b', re.I)
UNCERTAIN = re.compile(r'\b(?:asking price|projected|offered?|could|may sign|up to|annually|per year|AAV|in talks|discussing|close to|expected to sign)\b', re.I)
ATTRIBUTION = re.compile(r'\b(?:reported|reports|confirmed|according to|per|first on|sources told|via)\b', re.I)
TERM_WORDS = re.compile(r'\b(?:financial terms|contract terms|terms of the (?:contract|deal)|guarantee[ds]?|agreement|contract|deal)\b', re.I)
OTHER_TERMS = re.compile(r'\b(?:signing bonus|deferrals|annual salaries|posting fee)\b', re.I)
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')
ORDINALS = 'first second third fourth fifth sixth seventh eighth ninth tenth'.split()
OPT_OUT = re.compile(r'\bopt[- ]out after (?:the )?(?:(\d+)(?:st|nd|rd|th)?|('
                     + '|'.join(ORDINALS) + r'))\s+(?:year|season)\b', re.I)
CREDITS = {
    'Jeff Passan': ('ESPN', 'jeff passan', 'passan'),
    'Ken Rosenthal': ('The Athletic', 'ken rosenthal', 'rosenthal'),
    'Jon Heyman': ('New York Post', 'jon heyman', 'heyman'),
    'Mark Feinsand': ('MLB.com', 'mark feinsand', 'feinsand'),
    'Robert Murray': ('FanSided', 'robert murray'),
    'Bob Nightengale': ('USA TODAY', 'bob nightengale', 'nightengale'),
}
CREDIT_HOSTS = {'espn.com': 'ESPN', 'nypost.com': 'New York Post', 'theathletic.com': 'The Athletic',
                'nytimes.com': 'The Athletic', 'mlb.com': 'MLB.com', 'bleachernation.com': 'Bleacher Nation'}
LEGACY = {'平良海馬': 'followup-taira-bluejays', '佐藤輝明': 'followup-sato-cubs'}
API = mlb_trends.API


def known_players(load):
    roster = {row['name']: row['id'] for row in load('roster_stats.json')['league']}
    roster.update({row['name']: int(pid) for pid, row in load('roster_snapshot.json')['players'].items()
                   if row.get('name') and pid.isdecimal()})
    snapshot = load('roster_snapshot.json')['players']
    targets = {snapshot[str(row['player_id'])]['name']: row['jp']
               for row in load('season_topics.json')['topics']
               if row.get('jp') and str(row.get('player_id')) in snapshot}
    targets.update({row['name_en']: row['name_jp'] for row in load('offseason_players.json')['players']})
    return {**dict.fromkeys(roster, ''), **load('player_kana.json')['names'], **targets}, roster, set(targets.values())


def source_origin(feed, author, lead, body):
    """転載記事の署名と、契約条件を取材した記者の名前を区別する。"""
    credits = set()
    for line in (lead, *(s for p in body for s in SENTENCE.split(p))):
        if not ATTRIBUTION.search(line) or not (rss.parse_contract(line) or TERM_WORDS.search(line) or line == lead):
            continue
        if line != lead and not rss.parse_contract(line) and not re.search(
                r'financial terms|contract terms|terms of the (?:contract|deal)', line, re.I):
            continue
        if OTHER_TERMS.search(line) and not (rss.parse_contract(line) or 'financial terms' in line.lower()):
            continue
        named = {(outlet, name) for name, (outlet, *aliases) in CREDITS.items()
                 if any(re.search(r'\b' + re.escape(alias) + r'\b', line, re.I) for alias in aliases)}
        credits.update(named or {(outlet, '') for host, outlet in CREDIT_HOSTS.items()
                                 if host in line.lower() or re.search(r'\b' + re.escape(outlet) + r'\b', line, re.I)})
    if len({outlet for outlet, _ in credits}) == 1:
        reporters = {name for _, name in credits if name}
        return next(iter(credits))[0], next(iter(reporters)) if len(reporters) == 1 else ''
    organization = r'ESPN' if feed == 'ESPN' else r'(?:MLBTR|MLB Trade Rumors)'
    if not credits and re.search(r'\bsources (?:tell|told|said to) ' + organization + r'\b', lead, re.I):
        return feed, author if author != feed else ''
    # MLBTRで取材元を明記しないまとめ記事は、2社目という根拠にはしない。
    return '', ''


def distinct_origins(rows):
    direct = [r for r in rows if r['origin'] and r['terms']]
    return any(a['origin'] != b['origin'] and
               (not a['reporter'] or not b['reporter'] or rss.fold(a['reporter']) != rss.fold(b['reporter']))
               for i, a in enumerate(direct) for b in direct[i + 1:])


def safe_terms(text):
    parsed = rss.parse_contract(text)
    if not parsed or not 1 <= parsed['years'] <= 20 or parsed['amount'] <= 0 or UNCERTAIN.search(text):
        return None
    return {key: parsed[key] for key in ('years', 'amount')}


def opt_out_year(text, terms):
    matches = {int(m[1]) if m[1] else ORDINALS.index(m[2].lower()) + 1 for m in OPT_OUT.finditer(text)}
    return next(iter(matches)) if terms and len(matches) == 1 and next(iter(matches)) < terms['years'] else None


def matching_teams(text, table):
    return {en: jp for value, en, jp in table
            if re.search(r'(?<![A-Za-z])' + re.escape(value) + r'(?![A-Za-z])', text, re.I)}


def reports(raw, feed, players, japanese, now):
    body = {}
    for node in ET.fromstring(raw).iter('item'):
        encoded = node.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or ''
        body[rss.clean(node.findtext('link'))] = [rss.clean(p) for p in re.split(r'</p>', encoded)]
    table, cache = rss.team_table(), {}
    for item in rss.parse_feed(raw):
        url, stamp = item['link'], item['published_at']
        if rss.outlet_for(url, '') != feed or not stamp or not now - timedelta(days=2) <= stamp <= now:
            continue
        rss.source_ok(url)
        title, description = item['title'], item['description']
        sentences = SENTENCE.split(description, maxsplit=2)
        lead = sentences[0]
        main_clause = re.split(r',\s+(?:who|which|while)\b', lead, maxsplit=1, flags=re.I)[0]
        intro = [main_clause, title]
        in_title = rss.find_targets(title, players, cache)
        roster = in_title if len(in_title) == 1 else rss.find_targets(main_clause, players, cache)
        if len(roster) != 1:
            continue
        name_en, name = roster[0]
        agreed = any(AGREEMENT.search(p) for p in intro) and not UNCERTAIN.search(main_clause)
        if not agreed and (name not in japanese or not rss.classify(' '.join(intro))):
            continue
        trade = re.search(r'\b(?:trade[ds]?|acquired)\b', title, re.I)
        if trade and not re.search(r'\b(?:acquire[ds]?|trade[ds]? for)\b', title, re.I):
            continue
        title_teams, lead_teams = matching_teams(title, table), matching_teams(main_clause, table)
        possible = {**title_teams, **lead_teams}
        team, jp = next(iter(possible.items())) if len(possible) == 1 else ('', '')
        if len(sentences) > 1 and re.match(r"(?:it['’]s|the (?:deal|contract))\s", sentences[1], re.I):
            intro.append(main_clause.rstrip('.!?') + ' ' + sentences[1])
        values = [t for text in intro if agreed and (t := safe_terms(text))]
        known = {(t['years'], t['amount']) for t in values}
        terms = values[0] if values else None
        if name not in japanese and not terms:
            continue
        origin, reporter = source_origin(feed, item['creator'], lead, body.get(url, []))
        yield dict(name_en=name_en, name=name, japanese=name in japanese, team_en=team, team=jp, terms=terms,
                   agreement=agreed, conflict=len(known) > 1 or len(possible) > 1,
                   origin=origin, reporter=reporter, outlet=feed, url=url, title=title, reported_at=stamp.isoformat(),
                   opt_out=opt_out_year(description, terms))


def transactions(now, get=mlb_trends._get):
    params = dict(sportId=1, startDate=(now.date() - timedelta(days=2)).isoformat(), endDate=now.date().isoformat())
    raw = get('/transactions', params)
    if 'transactions' not in raw:
        raise ValueError('MLBの取引記録を取得できません')
    return raw['transactions'], API + '/transactions?' + urlencode(params)


def official_records(rows, source, names, japanese):
    from notability_engine import MLB_TEAM_NAME_EN, MLB_TEAM_NAME_JP
    for row in rows:
        if row.get('typeCode') not in {'SGN', 'SFA', 'TR'} or not row.get('id'):
            continue
        team_id = str((row.get('toTeam') or {}).get('id') or '')
        person = row.get('person') or {}
        name_en, person_id = person.get('fullName'), person.get('id')
        description = row.get('description') or ''
        if (not team_id or not name_en or not person_id or team_id not in MLB_TEAM_NAME_EN
                or not rss.find_targets(description, {name_en: ''})
                or re.search(r'\bminor league\b|traded .* back to', description, re.I)
                or not re.search(r'\bsigned\b|\btraded\b|\bacquired\b', description, re.I)):
            continue
        name = names.get(name_en, '')
        terms = safe_terms(description)
        yield dict(name_en=name_en, name=name, player_id=person_id, team_id=team_id, team_en=MLB_TEAM_NAME_EN[team_id],
                   team=MLB_TEAM_NAME_JP[team_id], terms=terms, opt_out=opt_out_year(description, terms),
                   url=source, transaction_id=str(row['id']), official_day=date.fromisoformat(row['date']).isoformat(),
                   action='trade' if row['typeCode'] == 'TR' else 'deal', japanese=name in japanese)


def decide(records, official):
    teams = {r['team_en'] for r in records if r['team_en']}
    terms = {(r['terms']['years'], r['terms']['amount']) for r in records if r['terms']}
    if len(teams) > 1 or len(terms) > 1 or any(r['conflict'] for r in records):
        return None, '球団・年数・総額が食い違う'
    if official and teams and official['team_en'] not in teams:
        return None, '公式記録と報道の球団が食い違う'
    stated = (official or {}).get('terms')
    if stated and terms and (stated['years'], stated['amount']) not in terms:
        return None, '公式記録と報道の契約条件が食い違う'
    matching = [r for r in records if r['team_en'] and r['terms']]
    agreed = distinct_origins(matching)
    if not official and not agreed:
        return None, '球団・年数・総額が一致する独立した2報道、またはMLB公式記録を待つ'
    base = official or matching[0]
    credited = [r for r in matching if r['origin']]
    contract = stated or (credited[0]['terms'] if credited else None)
    if not base['japanese'] and not (contract and contract['amount'] >= 10_000):
        return None, '1億ドル以上の条件が確認できない'
    options = {(official or {}).get('opt_out')} - {None}
    if agreed and not options:
        for year in {r['opt_out'] for r in matching if r['opt_out']}:
            if distinct_origins([r for r in matching if r['opt_out'] == year]):
                options.add(year)
    basis = credited if contract and not stated else []
    sources = rss.unique(([official['url']] if official else []) + [r['url'] for r in basis])
    media = rss.unique((['MLB Stats API'] if official else []) + [r['origin'] for r in basis])
    return dict(base, terms=contract, opt_out=next(iter(options)) if len(options) == 1 else None,
                official=bool(official), terms_official=bool(stated), sources=sources, media=media), ''


def player_reading(name, load):
    reading = load('player_kana.json')['readings'].get(name)
    if reading:
        return reading
    if re.fullmatch(r'[ァ-ヶー・]+', name):
        return name.replace('・', '')
    # NPBの候補名簿に保存してある読みは片仮名にそろえる。
    aliases = {row['reading'].replace(' ', '') for row in load('offseason_players.json')['players']
               if row['name_jp'] == name and row.get('reading')}
    if len(aliases) == 1:
        kana = next(iter(aliases))
        if re.fullmatch(r'[ぁ-ゖー]+', kana):
            return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in kana)
    return ''


def comparisons_for(fact, load):
    historical = load('mlb_market_followups.json')['events']
    suzuki = historical['sato-cubs']['items'][1]
    label, term = next((k, v) for k, v in suzuki['rows'] if k.startswith('鈴木誠也'))
    options = [dict(name=label.split('（')[0], term=term.split('（')[0], team='カブス',
                    sources=suzuki['sources'][1:], reported=False)]
    for event in load('mlb_large_contracts.json')['events'].values():
        c = event['contract']
        options.append(dict(name=event['subject'], term=f'{c["years"]}年{c["text"]}', team=event['team'],
                            sources=[r['url'] for r in event['reports']], reported=event['state'] != '契約を発表'))
    for key, name, team in (('sato-cubs', '佐藤輝明', 'カブス'), ('taira-bluejays', '平良海馬', 'ブルージェイズ')):
        row = historical[key]['items'][0]
        options.append(dict(name=name, term=dict(row['rows'])['契約'].replace(' ', '').replace('総額', ''),
                            team=team, sources=row['sources'], reported=True))
    options.sort(key=lambda r: (r['team'] != fact['team'], r['reported']))
    return [r for r in options if r['name'] != fact['name'] and player_reading(r['name'], load)]


def previous_stats(fact, load, player_id, day, get=mlb_trends._get):
    if player_id:
        season = day.year if day.month >= 11 else day.year - 1
        for group, fields in (
            ('hitting', (('avg', '打率'), ('homeRuns', '本塁打'), ('rbi', '打点'))),
            ('pitching', (('era', '防御率'), ('wins', '勝利'), ('strikeOuts', '奪三振'))),
        ):
            params = dict(stats='season', season=season, group=group)
            route = f'/people/{player_id}/stats'
            raw = get(route, params)
            splits = [split for item in raw.get('stats', []) for split in item.get('splits', [])
                      if str(split.get('season')) == str(season)]
            total = [s['stat'] for s in splits if not s.get('team')]
            if len(splits) == 1 or len(total) == 1:
                stat = (total or [splits[0]['stat']])[0]
                if all(re.fullmatch(r'\d*\.?\d+', str(stat.get(key, ''))) for key, _ in fields):
                    return dict(year=season, rows=[[label, str(stat[key])] for key, label in fields],
                                source=API + route + '?' + urlencode(params), outlet='MLB Stats API')
    key = LEGACY.get(fact['name'])
    if key and day.year == 2026:
        row = next(r for r in load('mlb_market_followups.json')['events'][key.removeprefix('followup-')]['items']
                   if r['head'] == '2026年の成績')
        stats = [r for r in row['rows'] if r[0] in {'打率', '本塁打', '打点', '登板', '勝敗', '奪三振'}]
        return dict(year=2026, rows=stats, source=row['sources'][0], outlet='NPB公式')
    return None


def term_label(terms):
    return f'{terms["years"]}年総額{rss.format_man(terms["amount"])[1]}'


def saved_large(fact, rows, now):
    """既存の大型契約一覧と手動の話題ショートにも同じ照合済み材料を渡す。"""
    terms = fact['terms']
    if not terms or terms['amount'] < 10_000 or fact.get('action') == 'trade':
        return None
    if fact['name'] == '佐藤輝明':
        return None  # 照合済みの followup-sato-cubs と同じ契約。
    value, amount_text, unit = rss.format_man(terms['amount'])
    contract = dict(terms, value=value, text=amount_text, unit=unit)
    base = dict(name_en=fact['name_en'], name_jp=fact['name'], team_en=fact['team_en'],
                team_jp=fact['team'], contract=contract)
    reports = [dict(base, kind='合意', outlet=r['origin'], url=r['url'], reported_at=r['reported_at'])
               for r in rows if r['origin'] and r['url'] in fact['sources']]
    if fact['official']:
        reports.insert(0, dict(base, kind='正式', outlet='MLB Stats API',
                               url=fact['url'], reported_at=now.isoformat()))
    key = '-'.join((rss.slug(fact['name_en']), rss.slug(fact['team_en']), 'deal'))
    return rss.large_draft(key, reports)


def material(fact, load, player_id, now, seen, get=mlb_trends._get):
    name, team, terms = fact['name'], fact['team'], fact['terms']
    reading = player_reading(name, load)
    if not reading:
        raise ValueError('選手名の読みが辞書・保存済みの公式資料にありません')
    is_trade = fact.get('action') == 'trade'
    day = now.date()
    from notability_engine import MLB_TEAM_NAME_EN
    team_id = fact.get('team_id') or next((key for key, value in MLB_TEAM_NAME_EN.items()
                                          if value == fact['team_en']), None)
    if fact['official']:
        action = 'トレード成立' if is_trade else '契約が正式決定'
        words = (f'MLBの取引記録に{name}の{team}へのトレードが載ったわ。' if is_trade
                 else f'MLBの取引記録に{team}と{name}の契約が載ったわ。')
        if terms:
            words += (f'契約の条件は{term_label(terms)}と確認できるわ。' if fact['terms_official']
                      else f'契約の条件は{term_label(terms)}と報じられているわ。')
    else:
        action = '契約合意と報道'
        words = f'{name}と{team}が{term_label(terms)}で合意したと報じられているわ。正式発表はまだよ。'
    rows = [['球団', team]]
    if terms:
        rows.append(['契約', term_label(terms)])
    if fact['opt_out']:
        year = fact['opt_out']
        rows.append(['契約を見直せる時期', f'{year}年目の後'])
        words += f'{year}年目の後に、自分から契約を終えられる条項もあるわ。'
    items = [dict(ask='', text=words, head=action, rows=rows, source_names='・'.join(fact['media']),
                  sources=fact['sources'])]
    hook = dict(score=name, result=action, subject='', big='', unit='',
                note='MLBの取引記録' if fact['official'] else '正式発表はまだ')
    if terms:
        years = terms['years']
        value, _, unit = rss.format_man(terms['amount'])
        if not unit:
            value, unit = value.removesuffix('億'), '億ドル'
        items[0]['big'] = dict(label=f'{years}年の総額', value=value, unit=unit)
        hook.update(subject=f'{years}年総額', big=value, unit=unit)
    readings = {name: reading}
    stats = previous_stats(fact, load, player_id, day, get)
    peers = comparisons_for(fact, load)[:1 if stats else 2] if terms else []
    for index, peer in enumerate(peers):
        person, label = peer['name'], peer['term']
        readings[person] = player_reading(person, load)
        years, amount = rss.saved_contract_total(label)
        current = rss.annual_average(terms['amount'], terms['years'])
        prior = rss.annual_average(amount, years)
        current_label, prior_label = (rss.format_man(x)[1] for x in (current, prior))
        words = f'{person}は{label}' + ('と報じられているわ。' if peer['reported'] else 'だったわ。')
        words += f'年平均は{name}が約{current_label}、{person}が約{prior_label}よ。'
        ask = ('ほかの契約と並べると、どれくらいの大きさなのだ？' if index == 0
               else '別の契約と並べると、また見え方が変わるのだ。')
        items.append(dict(ask=ask, text=words,
                          head='契約を年平均で比較', rows=[[name, f'約{current_label}'], [person, f'約{prior_label}']],
                          source_names='契約報道', sources=rss.unique(fact['sources'] + peer['sources'])))
    if stats:
        year = stats['year']
        groups = [stats['rows']] if len(items) > 1 else [stats['rows'][:2], stats['rows'][2:]]
        for index, group in enumerate(g for g in groups if g):
            detail = '、'.join(value if label == '勝敗' else f'{value}本塁打' if label == '本塁打'
                               else f'{value}打点' if label == '打点' else f'{value}試合に登板' if label == '登板'
                               else f'{value}奪三振' if label == '奪三振' else f'{label}{value}'
                               for label, value in group)
            ask = '移籍前の活躍も気になるのだ。' if not index else '成績を見ると、次のシーズンが楽しみなのだ。'
            items.append(dict(ask=ask, text=f'{year}年は{detail}だったわ。',
                              head=f'{year}年の成績' if not index else group[0][0], rows=group,
                              source_names=stats['outlet'], sources=[stats['source']]))
    total = ' ' + term_label(terms) if terms else ''
    return dict(title=f'{name} {team}{total} {action}', checked_on=day.isoformat(), readings=readings,
                reading_sources=[], hook=hook, items=items,
                news=dict(name=name, first_seen=seen, official=fact['official'], official_day=fact.get('official_day'),
                          team_id=str(team_id) if team_id else None, transaction_id=fact.get('transaction_id'),
                          report_times=[fact['reported_at']] if fact.get('reported_at') else []))


def publication_block(material, topic, ledger, at):
    if topic in ledger:
        return '同じニュースは予約・投稿済みです'
    day = at.astimezone(rss.JST).date()
    if sum(datetime.fromisoformat(row['publish_at']).astimezone(rss.JST).date() == day
           for row in ledger.values() if row.get('publish_at')) >= 3:
        return 'MLB移籍のショートは日本時間で1日3本までです'
    info = material['news']
    name = info['name']
    previous = [row for key, row in ledger.items() if row.get('news_player') == name
                or key == LEGACY.get(name)
                or (key.startswith('followup-') and row.get('title', '').startswith(name + ' '))]
    if previous and (not info['official'] or any(row.get('news_official') for row in previous)):
        return '同じ選手の追加は、後から出た最初の正式発表だけです'
    if previous and not any(row.get('publish_at') and row['publish_at'][:10] <= info['official_day']
                            and datetime.fromisoformat(row.get('news_reserved_at', row['publish_at']))
                            < datetime.fromisoformat(info['official_first_seen']) for row in previous):
        return '正式発表が先に出たニュースです'
    return ''


def latency(ledger):
    rows = [r for r in ledger.values() if r.get('news_first_seen') and r.get('publish_at')]
    within = sum(timedelta() <= datetime.fromisoformat(r['publish_at']) - datetime.fromisoformat(r['news_first_seen'])
                 <= timedelta(hours=1) for r in rows)
    return dict(reserved=len(rows), within_one_hour=within, fraction=within / len(rows) if rows else None)
