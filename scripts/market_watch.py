"""公開RSSから日本人選手の移籍報道を見張り、確認用の下書きを作る。"""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
STATE = ROOT / 'data/market_watch_state.json'
FEEDS = (
    ('MLBTR', 'https://www.mlbtraderumors.com/feed'),
    ('ESPN', 'https://www.espn.com/espn/rss/mlb/news'),
)
MAX_BYTES = 512_000
UA = 'collespo-market-watch/1.0 (+https://collespo.com)'
KIND_SLUG = {'合意': 'agreement', '契約': 'contract', '関心': 'interest',
             '面談': 'meeting', 'トレード': 'trade', '正式': 'official'}
BIG_REPORTERS = {
    'Jeff Passan': ('jeff passan', 'passan'),
    'Ken Rosenthal': ('ken rosenthal', 'rosenthal'),
    'Jon Heyman': ('jon heyman', 'heyman'),
    'Mark Feinsand': ('mark feinsand', 'feinsand'),
    'Buster Olney': ('buster olney',),
    'Bob Nightengale': ('bob nightengale',),
}
TAG = re.compile(r'<[^>]+>')
NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
}


def clean(value):
    return ' '.join(TAG.sub(' ', html.unescape(value or '')).split())


def fold(value):
    text = unicodedata.normalize('NFKD', value or '')
    out = []
    for char in text:
        if unicodedata.combining(char) and out and out[-1].isascii() and out[-1].isalpha():
            continue
        out.append(char)
    return ''.join(out).casefold()


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', fold(value)).strip('-')


def target_names(root=None):
    import jp_future_catalog as series
    jp, _ = series.targets(root or (ROOT / 'data'))
    return jp


def name_variants(name_en, name_jp):
    variants = {name_en}
    parts = name_en.split()
    if len(parts) >= 2:
        variants.add(f'{parts[-1]}, {" ".join(parts[:-1])}')
    if name_jp:
        variants.add(name_jp)
    return {fold(v) for v in variants if v}


def find_targets(text, targets, cache=None):
    folded = fold(text)
    found = []
    cache = cache if cache is not None else {}
    for name_en, name_jp in targets.items():
        if name_en not in cache:
            cache[name_en] = name_variants(name_en, name_jp)
        for variant in cache[name_en]:
            if re.search(r'[a-z]', variant):
                if re.search(r'(?<![a-z])' + re.escape(variant) + r'(?![a-z])', folded):
                    found.append((name_en, name_jp))
                    break
            elif variant in folded:
                found.append((name_en, name_jp))
                break
    return found


def classify(text):
    low = text.casefold()
    official = re.search(r'\b(?:announced|official(?:ly)?|completed|finalized)\b', low)
    negated = re.search(r"(?:not|n't)\s+(?:yet\s+)?(?:been\s+)?(?:officially\s+)?(?:announced|official|finalized|completed)\b", low)
    if official and not negated:
        return '正式'
    if (re.search(r'\b(?:agree(?:d|s|ment)?|finaliz(?:e|ed|ing)|to sign)\b', low)
            or re.search(r'\breach(?:ed|es)?\b[^.]{0,40}\b(?:deal|agreement)\b', low)):
        return '合意'
    if re.search(r'\b(?:meet(?:s|ing)?|met|visit(?:s|ed|ing)?|dinner)\b', low):
        return '面談'
    if re.search(r'\b(?:interest(?:ed)?|pursu(?:e|es|ed|ing|it)|engaged|monitor(?:s|ed|ing)?|courted|target(?:s|ed|ing)?|eyeing)\b', low):
        return '関心'
    if re.search(r'\b(?:trade[ds]?|traded|acquire[ds]?|acquired)\b', low):
        return 'トレード'
    if re.search(r'\b(?:sign(?:s|ed|ing)?|contract(?:ed)?|re-sign(?:s|ed|ing)?|extension)\b', low):
        return '契約'
    return ''


def team_table():
    from notability_engine import MLB_TEAM_NAME_EN, MLB_TEAM_NAME_JP
    rows = []
    for team_id, name_en in MLB_TEAM_NAME_EN.items():
        name_jp = MLB_TEAM_NAME_JP.get(team_id)
        if not name_jp:
            continue
        words = name_en.split()
        nickname = ' '.join(words[-2:]) if len(words) >= 2 and words[-1] in ('Sox', 'Jays') else words[-1]
        for value in {name_en, nickname}:
            rows.append((value, name_en, name_jp))
    rows.sort(key=lambda row: len(row[0]), reverse=True)
    return rows


def team_in(text, table):
    for value, name_en, name_jp in table:
        if re.search(r'(?<![A-Za-z])' + re.escape(value) + r'(?![A-Za-z])', text, re.I):
            return name_en, name_jp
    return None, None


def reporter_names(text):
    low = text.casefold()
    return [name for name, aliases in BIG_REPORTERS.items()
            if any(re.search(r'(?<![a-z])' + re.escape(alias) + r'(?![a-z])', low) for alias in aliases)]


def parse_contract(text):
    year = r'\b(\d{1,2}|' + '|'.join(NUMBER_WORDS) + r')\b'
    money = r'\$(\d+(?:\.\d+)?)\s*(MM|M|million|billion|B)\b'
    first = re.compile(year + r'[ -]years?(?!-old\b|\s+old\b)\b[^.]{0,60}?' + money, re.I)
    second = re.compile(money + r'[^.]{0,60}?' + year + r'[ -]years?(?!-old\b|\s+old\b)\b', re.I)
    match = first.search(text)
    if match:
        year_value, amount, unit = match.group(1), match.group(2), match.group(3)
    else:
        match = second.search(text)
        if not match:
            return None
        amount, unit, year_value = match.group(1), match.group(2), match.group(3)
    years = int(year_value) if year_value.isdigit() else NUMBER_WORDS[year_value.casefold()]
    amount = float(amount) * (1000 if unit.casefold() in ('billion', 'b') else 1)
    value, total, unit = format_man(amount * 100)
    return dict(years=years, amount=amount * 100, value=value, unit=unit, text=total)


def format_man(amount):
    if amount >= 10000:
        oku = int(amount // 10000)
        man = amount - oku * 10000
        if man == 0:
            return f'{oku}億', f'{oku}億ドル', ''
        if man == int(man):
            return f'{oku}億{int(man)}', f'{oku}億{int(man)}万ドル', '万ドル'
        return f'{oku}億{man:g}', f'{oku}億{man:g}万ドル', '万ドル'
    if amount == int(amount):
        return str(int(amount)), f'{int(amount)}万ドル', '万ドル'
    return f'{amount:g}', f'{amount:g}万ドル', '万ドル'


def outlet_for(url, feed_name):
    host = (urlsplit(url).hostname or '').lower()
    if host == 'mlbtraderumors.com' or host.endswith('.mlbtraderumors.com'):
        return 'MLBTR'
    if host == 'espn.com' or host.endswith('.espn.com'):
        return 'ESPN'
    return feed_name


def source_ok(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
        raise ValueError('出典は資格情報なしのHTTPS URLが必要です')
    if any(host == h or host.endswith('.' + h) for h in ('5ch.net', '2ch.net', '2ch.sc', 'reddit.com', 'redd.it')):
        raise ValueError('コメント・掲示板は材料にできません')
    if 'yahoo.' in host and re.search(r'comment|comments', url, re.I):
        raise ValueError('コメント・掲示板は材料にできません')
    if host == 'example.com' or host.endswith('.example.com'):
        raise ValueError('試験用URLは本番に使えません')
    return url


def parse_date(value):
    try:
        stamp = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(JST)


def parse_feed(raw):
    root = ET.fromstring(raw)
    for item in root.iter('item'):
        link = clean(item.findtext('link'))
        if not link:
            continue
        yield dict(
            title=clean(item.findtext('title')),
            description=clean(item.findtext('description')),
            creator=clean(item.findtext('{http://purl.org/dc/elements/1.1/}creator')),
            link=link,
            published_at=parse_date(item.findtext('pubDate')),
        )


def read_source(source):
    source = str(source)
    if source.startswith('https://'):
        return fetch(source)
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    return path.read_bytes()


def fetch(url):
    import requests
    if not url.startswith('https://'):
        raise ValueError('公開RSSはHTTPSのみです')
    client = requests.Session()
    client.trust_env = False
    response = client.get(url, headers={'User-Agent': UA}, timeout=20, allow_redirects=False, stream=True)
    try:
        if response.status_code != 200:
            raise RuntimeError('HTTP ' + str(response.status_code))
        data = bytearray()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError('RSSが上限を超えました')
        return bytes(data)
    finally:
        response.close()


def collect_items(raw, feed_name, targets, teams=None, cache=None):
    teams = teams if teams is not None else team_table()
    cache = cache if cache is not None else {}
    records = []
    for item in parse_feed(raw):
        text = item['title'] + '. ' + item['description']
        head = item['title'] + '. ' + item['description'][:240]
        matched = find_targets(head, targets, cache)
        if not matched:
            continue
        kind = classify(text)
        if not kind:
            continue
        team_en, team_jp = team_in(item['title'], teams)
        if not team_en:
            team_en, team_jp = team_in(item['description'], teams)
        outlet = outlet_for(item['link'], feed_name)
        try:
            source_ok(item['link'])
        except ValueError:
            continue
        matched_map = dict(matched)
        context = ' '.join(part for part in re.split(r'(?<=[.!?])\s+', text)
                           if find_targets(part, matched_map))
        contract = parse_contract(context) or parse_contract(text)
        for name_en, name_jp in matched:
            records.append(dict(
                name_en=name_en, name_jp=name_jp, kind=kind,
                team_en=team_en, team_jp=team_jp, outlet=outlet,
                author=item['creator'], reporters=reporter_names(text),
                title=item['title'], description=item['description'],
                url=item['link'], published_at=item['published_at'],
                contract=contract,
            ))
    return records


def group_stories(records):
    groups = {}
    for row in records:
        groups.setdefault((row['name_en'], row['kind']), []).append(row)
    stories = {}
    for (name_en, kind), rows in groups.items():
        teams = {row['team_en'] for row in rows if row['team_en']}
        if len(teams) > 1:
            for team in sorted(teams):
                subset = [row for row in rows if row['team_en'] == team]
                if subset:
                    stories[story_key(name_en, kind, team)] = subset
            continue
        team = next(iter(teams), None)
        for row in rows:
            row['team_en'] = row['team_en'] or team
            if not row['team_jp'] and team:
                row['team_jp'] = next(r['team_jp'] for r in rows if r['team_en'] == team)
        stories[story_key(name_en, kind, team)] = rows
    return stories


def story_key(name_en, kind, team_en):
    return '-'.join(part for part in (slug(name_en), slug(team_en) if team_en else 'unknown', KIND_SLUG[kind]) if part)


def stage_for(records):
    kinds = {row['kind'] for row in records}
    outlets = {row['outlet'] for row in records}
    big = any(set(row['reporters']) & set(BIG_REPORTERS) for row in records)
    if '正式' in kinds:
        return 2
    if kinds & {'合意', '契約'} and (big or len(outlets) >= 2):
        return 2
    return 1


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def primary_record(records):
    for row in records:
        if row['kind'] == '正式':
            return row
    for row in records:
        if set(row['reporters']) & set(BIG_REPORTERS):
            return row
    return records[0]


def conclusion_for(kind, team_jp):
    if team_jp:
        return {'合意': f'{team_jp}と合意', '契約': f'{team_jp}と契約',
                'トレード': f'{team_jp}へトレード', '面談': f'{team_jp}と面談',
                '関心': f'{team_jp}が関心', '正式': f'{team_jp}が正式発表'}[kind]
    return {'合意': '移籍の合意', '契約': '移籍の契約', 'トレード': 'トレード',
            '面談': '面談', '関心': '関心', '正式': '正式発表'}[kind]


def report_text(row, outlets, contract):
    outlet = 'と'.join(outlets) + 'が報じています。'
    team = row['team_jp']
    if row['kind'] == '正式':
        return f'{team}が正式に発表しました。' if team else '球団が正式に発表しました。'
    if row['kind'] in ('合意', '契約'):
        verb = '合意した' if row['kind'] == '合意' else '契約した'
        if contract:
            if team:
                return f'{team}と{contract["years"]}年総額{contract["text"]}で{verb}と、{outlet}'
            return f'{contract["years"]}年総額{contract["text"]}で{verb}と、{outlet}'
        return (f'{team}と{verb}と、{outlet}' if team else f'移籍の{row["kind"]}について、{outlet}')
    if row['kind'] == '関心':
        return (f'{team}が{row["name_jp"]}に関心を持っていると、{outlet}' if team
                else f'{row["name_jp"]}への関心が報じられており、{outlet}')
    if row['kind'] == '面談':
        return (f'{team}が{row["name_jp"]}と面談したと、{outlet}' if team
                else f'{row["name_jp"]}との面談が報じられており、{outlet}')
    return (f'{team}が{row["name_jp"]}をトレードで獲得したと、{outlet}' if team
            else f'{row["name_jp"]}のトレードが報じられており、{outlet}')


def reading_for(name_jp):
    table = json.loads((ROOT / 'data/player_kana.json').read_text(encoding='utf-8'))
    return table.get('readings', {}).get(name_jp, '')


def build_stage1(key, records, now):
    row = primary_record(records)
    outlets = sorted({item['outlet'] for item in records})
    conclusion = conclusion_for(row['kind'], row['team_jp'])
    return dict(
        key=key, stage=1, name_en=row['name_en'], name_jp=row['name_jp'],
        kind=row['kind'], team_en=row['team_en'], team_jp=row['team_jp'],
        title=f'{row["name_jp"]} {conclusion}と米報道',
        outlets=outlets,
        reporters=unique(name for item in records for name in item['reporters']),
        authors=unique(item['author'] for item in records),
        sources=unique(item['url'] for item in records),
        reported_at=(row['published_at'].isoformat() if row['published_at'] else now.isoformat()),
    )


def build_stage2(key, records, now):
    row = primary_record(records)
    outlets = sorted({item['outlet'] for item in records})
    contract = next((item['contract'] for item in records if item['contract']), None)
    conclusion = conclusion_for(row['kind'], row['team_jp'])
    suffix = '' if row['kind'] == '正式' else 'と米報道'
    reporter = next((name for name in row['reporters']), row['author'])
    date_label = (f'{row["published_at"].month}月{row["published_at"].day}日' if row['published_at'] else '日付要確認')
    reading = reading_for(row['name_jp'])
    rows = [['球団', row['team_jp'] or '要確認']]
    if contract:
        rows.append(['契約', f'{contract["years"]}年 総額{contract["text"]}'])
    rows.append(['報道', ' '.join(value for value in ('・'.join(outlets), reporter, date_label) if value)])
    if row['kind'] == '正式':
        head = f'{row["team_jp"]}が正式発表' if row['team_jp'] else '正式発表'
    else:
        head = f'{row["team_jp"]}と{row["kind"]}と報道' if row['team_jp'] else f'{row["kind"]}と報道'
    item = dict(
        ask=f'{row["name_jp"]}は、どうなったのだ？',
        text=report_text(row, outlets, contract),
        head=head,
        rows=rows,
        source_names='・'.join(outlets),
        sources=unique(item['url'] for item in records),
    )
    if contract:
        item['big'] = dict(label=f'{contract["years"]}年の総額', value=contract['value'], unit=contract['unit'])
    items = [item]
    for label in ('2026年の成績', '契約の比べ', '譲渡金', 'MLBで通用するか', 'チームの事情'):
        items.append(dict(ask=f'{label}は、どうなのだ？', text='', head=label, rows=[],
                          source_names='', sources=[], status='要確認'))
    needs_review = ['出典の確認']
    if not contract:
        needs_review.append('年数・総額')
    if not reading:
        needs_review.append('読み')
    needs_review += ['2026年の成績', '契約の比べ', '譲渡金', 'MLBで通用するか', 'チームの事情']
    return dict(
        story_key=key,
        checked_on=now.date().isoformat(),
        title=f'{row["name_jp"]} {conclusion}{suffix}',
        readings={row['name_jp']: reading} if reading else {},
        reading_sources=[],
        hook=dict(score=row['name_jp'], result=conclusion + suffix,
                  subject=f'{contract["years"]}年総額' if contract else '',
                  big=contract['value'] if contract else '',
                  unit=contract['unit'] if contract else '',
                  note='正式発表' if row['kind'] == '正式' else ('正式発表はまだ' if contract else '年数・総額は要確認')),
        items=items,
        outlets=outlets,
        needs_review=needs_review,
    )


def build_entry(key, records, stage, now):
    return build_stage2(key, records, now) if stage == 2 else build_stage1(key, records, now)


def load_state(path=STATE):
    path = Path(path)
    if not path.exists():
        return dict(version=1, updated_at=None, stories={}, failures=[])
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('stories'), dict):
        raise ValueError('見張りの状態ファイルの書式が不正です')
    return data


def save_state(state, path=STATE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(feeds, state, now, targets=None):
    targets = targets if targets is not None else target_names()
    teams = team_table()
    cache = {}
    records, failures = [], []
    for feed_name, source in feeds:
        try:
            records.extend(collect_items(read_source(source), feed_name, targets, teams, cache))
        except Exception as exc:
            failures.append(dict(feed=feed_name, error=str(exc) or type(exc).__name__))
    stories = group_stories(records)
    promoted = {rows[0]['name_en'] for rows in stories.values() if stage_for(rows) == 2}
    new_stage1, new_stage2, all_stage1 = [], {}, []
    for key, rows in sorted(stories.items()):
        stage = stage_for(rows)
        entry = build_entry(key, rows, stage, now)
        if stage == 1 and rows[0]['name_en'] not in promoted:
            all_stage1.append(entry)
        previous = state.setdefault('stories', {}).get(key)
        previous_stage = int(previous.get('stage', 0)) if previous else 0
        if stage > previous_stage:
            if stage == 2:
                new_stage2[key] = entry
            elif rows[0]['name_en'] not in promoted:
                new_stage1.append(entry)
            state['stories'][key] = dict(
                stage=stage,
                name_en=rows[0]['name_en'],
                first_seen=(previous or {}).get('first_seen', now.isoformat()),
                last_seen=now.isoformat(),
                title=entry['title'],
                outlets=entry.get('outlets', []),
            )
        elif previous:
            previous['stage'] = max(previous_stage, stage)
            previous['name_en'] = rows[0]['name_en']
            previous['last_seen'] = now.isoformat()
            previous['title'] = entry['title']
            previous['outlets'] = entry.get('outlets', previous.get('outlets', []))
    state['version'] = 1
    state['updated_at'] = now.isoformat()
    state['failures'] = failures
    return dict(stage1=new_stage1, stage2=new_stage2, all_stage1=all_stage1,
                failures=failures, state=state)


def write_outputs(result, out_dir, now):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'market_watch_stage1.json').write_text(json.dumps(
        dict(updated_at=now.isoformat(), items=result['all_stage1'], new=result['stage1']),
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out_dir / 'market_watch_stage2.json').write_text(json.dumps(
        dict(updated_at=now.isoformat(), events=result['stage2']),
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out_dir / 'market_watch_report.json').write_text(json.dumps(
        dict(updated_at=now.isoformat(), stage1=len(result['stage1']), stage2=len(result['stage2']),
             failures=result['failures']), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', action='append', default=None, metavar='NAME=SOURCE')
    parser.add_argument('--state', default=str(STATE))
    parser.add_argument('--out', default=str(ROOT / 'build'))
    parser.add_argument('--now', default=None)
    args = parser.parse_args(argv)
    feeds = FEEDS
    if args.feed:
        feeds = tuple(value.split('=', 1) for value in args.feed)
    now = datetime.fromisoformat(args.now).astimezone(JST) if args.now else datetime.now(JST)
    state = load_state(args.state)
    result = run(feeds, state, now)
    write_outputs(result, args.out, now)
    save_state(result['state'], args.state)
    print(f'段1の新しい項目: {len(result["stage1"])}件 / 段2の新しい下書き: {len(result["stage2"])}件')
    for entry in result['stage1']:
        print(f'  段1 {entry["key"]}: {entry["title"]}')
    for key, entry in result['stage2'].items():
        print(f'  段2 {key}: {entry["title"]}')
    for failure in result['failures']:
        print(f'  取得失敗 {failure["feed"]}: {failure["error"]}', file=sys.stderr)
    if result['failures'] and not result['all_stage1'] and not result['stage2']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
