
"""ニュースの判定、課題の下書き、動画制作用の引き渡しを記録する。"""
from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime, timedelta
from functools import cache
import json
from pathlib import Path

import market_watch as rss
import mlb_news_fast as mlb
import soccer_news_fast as soccer

ROOT = rss.ROOT
DATA = ROOT / 'data'
JST = rss.JST
FRESHNESS = timedelta(days=2)
FLAG = {'mlb': 'COLLESPO_MARKET_AUTO_PUBLISH', 'soccer': 'COLLESPO_SOCCER_NEWS_PUBLISH'}


def load_json(path, default=None):
    if default is not None and not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


@cache
def load_data(filename):
    return load_json(DATA / filename)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def pub_ledger(sport):
    import soccer_national_topics as topics
    return load_json(topics.MLB_LEDGER if sport == 'mlb' else topics.LEDGER)


def may_publish(sport, material, flag):
    return flag == 'true' and (sport == 'mlb' or material['publishable'])


def candidate(key, phase, title, sources, reason, *, material=None, detail=None):
    return dict(key=key, phase=phase, title=title, sources=sources, reason=reason, material=material, detail=detail)


def mlb_candidates(feeds, state, now, get=mlb.mlb_trends._get):
    names, roster, japanese = mlb.known_players(load_data)
    reports = dict(state.get('reports', {}))
    failures, feed_success = [], 0
    for feed, path in feeds:
        try:
            fetched = list(mlb.reports(rss.read_source(path), feed, names, japanese, now))
        except Exception as exc:
            failures.append(f'{feed}: {exc}')
        else:
            for row in fetched:
                previous = reports.get(row['url'])
                if previous:
                    row['reported_at'] = min(row['reported_at'], previous['reported_at'])
                reports[row['url']] = row
            feed_success += 1
    cutoff = now - FRESHNESS
    state['reports'] = {url: row for url, row in reports.items() if cutoff <= soccer.instant(row['reported_at']) <= now}
    grouped = defaultdict(list)
    for row in state['reports'].values():
        grouped[row['name'] or row['name_en']].append(row)
    try:
        records, source = mlb.transactions(now, get)
        official = defaultdict(list)
        for row in mlb.official_records(records, source, names, japanese):
            identity = row['name'] or row['name_en']
            if row['japanese'] or (row['terms'] and row['terms']['amount'] >= 10_000) or identity in grouped:
                official[identity].append(row)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append(f'MLB Stats API: {exc}')
        official = {}
    else:
        feed_success += 1
    results = []
    for identity in sorted(grouped.keys() | official.keys()):
        rows, transactions = grouped.get(identity, []), official.get(identity, [])
        if not any(r['japanese'] or (r['terms'] and r['terms']['amount'] >= 10_000) for r in rows + transactions):
            continue
        transaction = max(transactions, key=lambda r: r['official_day'], default=None)
        base = transaction or rows[0]
        sources = rss.unique([r['url'] for r in rows + transactions])
        seen_key = rss.slug(base['name_en'])
        evidence = [row for row in rows if row['agreement']]
        if evidence or transaction:
            state['first_seen'].setdefault(seen_key, now.isoformat())
        first_seen = state['first_seen'].get(seen_key, now.isoformat())
        detail = dict(reports=rows, transactions=transactions, first_seen=first_seen)
        fact, reason = mlb.decide(evidence, transaction)
        if len({(r['team_en'], r['action']) for r in transactions}) > 1:
            fact, reason = None, '複数の公式取引があり移籍先を照合する必要がある'
        phase = 'official' if transaction else 'report'
        key = f'news-mlb-{seen_key}-{phase}'
        prepared = None
        if fact:
            try:
                player_id = fact.get('player_id') or roster.get(base['name_en'])
                prepared = mlb.material(fact, load_data, player_id, now, first_seen, get)
                prepared['news']['report_times'] = sorted({r['reported_at'] for r in evidence})
                if transaction:
                    first_official = state.setdefault('official_seen', {})
                    prepared['news']['official_first_seen'] = first_official.setdefault(key, now.isoformat())
                detail['large_contract'] = mlb.saved_large(fact, evidence, now)
            except (ValueError, KeyError) as exc:
                reason = str(exc)
        title = prepared['title'] if prepared else f'{identity}の移籍・契約'
        results.append(candidate(key, phase, title, sources, reason, material=prepared, detail=detail))
    return results, failures, feed_success


def soccer_candidates(now, get=soccer.fetch):
    players, failures, results = soccer.names(load_data), [], {}
    success = 0
    for league in soccer.LEAGUES:
        try:
            articles = get(league)
        except (OSError, ValueError) as exc:
            failures.append(f'{league}: {exc}')
            continue
        success += 1
        for article in articles:
            try:
                report = soccer.article_record(article, league, players, now)
                if not report:
                    continue
                saved = soccer.context(report, load_data)
                reason = ''
                try:
                    material = soccer.material(report, saved)
                except ValueError as exc:
                    material, reason = None, str(exc)
                row = candidate(report['key'], 'report', material['title'] if material else report['headline'],
                                [report['url']], reason, material=material, detail=dict(article=report, context=saved))
            except (ValueError, KeyError, TypeError) as exc:
                failures.append(f'{league} 記事 {article.get("id", "")}: {exc}')
                continue
            if row['key'] not in results or (material and not results[row['key']]['material']):
                results[row['key']] = row
    return list(results.values()), failures, success


def delivery(sport, candidates, state, previews, ledger, now, flag):
    notices, queue = [], []
    for row in candidates:
        key = row['key']
        material = row['material']
        previous = state['noticed'].get(key)
        block = ''
        material_short = bool(material and len(material['items']) < 3)
        if material and sport == 'mlb':
            block = mlb.publication_block(material, key, ledger, now + timedelta(minutes=21))
        if key in ledger:
            continue
        publish = bool(material and not material_short and may_publish(sport, material, flag) and not block)
        done = key in previews and not publish
        reason = row['reason'] or ('短編の比較に使える保存材料が足りない' if material_short else '') or (
            block if flag == 'true' else '')
        # 台帳にある手動版も含め、公開済みの同じ報道には毎回見本を作らない。
        if block.startswith('同じ選手') and sport == 'mlb':
            continue
        status = reason or '動画制作待ち'
        if previous != status:
            detail = row.get('detail') or {}
            article = detail.get('article') or {}
            notices.append(dict(title=('確認待ち ' if reason else '') + row['title'],
                                key=key, reason=status, sources=row['sources'],
                                context=detail.get('context'), january=bool(article.get('january')),
                                reported_fee=article.get('reported_fee', '')))
            state['noticed'][key] = status
        if material and not material_short and not done:
            queue.append(dict(topic=key, material=material, publish=publish))
    queue.sort(key=lambda row: not row['publish'])
    return notices, queue[:1]


def issue_text(notices):
    out = []
    for item in notices:
        title = item['title'].replace('@', '＠').replace('\n', ' ').strip()
        out.extend([f'### {title}', '', item['reason'].replace('@', '＠'), ''])
        if item['january']:
            out.append('冬の移籍市場（1月）')
        if item['reported_fee']:
            out.append(f'記事見出し・概要にある金額 {item["reported_fee"]}')
        if item['context']:
            c = item['context']
            line = f'{c["day"]} の保存記録で {c["team"]} は{c["position"]}位・勝点{c["points"]}'
            if c['form']:
                wins, draws, losses = c['form']
                line += f'。直近5試合は{wins}勝{draws}分け{losses}敗'
            out.extend([line, ''])
        out.extend(f'- {rss.source_ok(url)}' for url in item['sources'])
        out.append('')
    return '\n'.join(out)


def workflow_output(path, notices, queue):
    with path.open('a', encoding='utf-8') as f:
        print(f'notify={str(bool(notices)).lower()}', file=f)
        if queue:
            row = queue[0]
            print('topic=' + row['topic'], file=f)
            print(f'publish={str(row["publish"]).lower()}', file=f)
            print('material=' + json.dumps(row['material'], ensure_ascii=False, separators=(',', ':')), file=f)


def main(argv=None):
    import os
    p = ArgumentParser(description=__doc__)
    p.add_argument('sport', choices=FLAG)
    p.add_argument('--out', type=Path)
    p.add_argument('--state', type=Path)
    p.add_argument('--preview-receipts', type=Path)
    p.add_argument('--large-material', type=Path)
    p.add_argument('--feed', action='append', metavar='NAME=SOURCE')
    p.add_argument('--now')
    p.add_argument('--github-output', type=Path)
    p.add_argument('--record-preview', nargs=2, metavar=('TOPIC', 'ARTIFACT'))
    p.add_argument('--latency', action='store_true')
    args = p.parse_args(argv)
    if args.record_preview:
        if not args.preview_receipts:
            p.error('--preview-receipts が必要です')
        topic, artifact = args.record_preview
        receipts = load_json(args.preview_receipts, {})
        receipts[topic] = dict(artifact=artifact, built_at=datetime.now(JST).isoformat())
        save(args.preview_receipts, receipts)
        return 0
    ledger = pub_ledger(args.sport)
    if args.latency:
        print(json.dumps(mlb.latency(ledger), ensure_ascii=False))
        return 0
    if not args.out or not args.state or not args.preview_receipts:
        p.error('--out / --state / --preview-receipts が必要です')
    now = soccer.instant(args.now).astimezone(JST) if args.now else datetime.now(JST)
    state = load_json(args.state, dict(noticed={}, first_seen={}, reports={}))
    previews = load_json(args.preview_receipts, {})
    old = json.dumps(state, sort_keys=True)
    feeds = tuple(item.split('=', 1) for item in args.feed) if args.feed else rss.FEEDS
    if args.sport == 'mlb':
        candidates, failures, available = mlb_candidates(feeds, state, now)
        if args.large_material:
            large = load_json(args.large_material, {'events': {}})
            additions = {entry['story_key']: entry for row in candidates
                         if (entry := row['detail'].get('large_contract')) and entry['story_key'] not in large['events']}
            if additions:
                large['events'].update(additions)
                save(args.large_material, large)
    else:
        candidates, failures, available = soccer_candidates(now)
    notices, queue = delivery(args.sport, candidates, state, previews, ledger, now, os.getenv(FLAG[args.sport], ''))
    save(args.out / 'report.json', dict(candidates=candidates, notices=notices, failures=failures,
                                       checked_at=now.isoformat(), latency=mlb.latency(ledger) if args.sport == 'mlb' else None))
    (args.out / 'issues.md').write_text(issue_text(notices), encoding='utf-8')
    if args.github_output:
        workflow_output(args.github_output, notices, queue)
    if json.dumps(state, sort_keys=True) != old:
        save(args.state, state)
    for fail in failures:
        print(fail)
    return 0 if available else 1


if __name__ == '__main__':
    raise SystemExit(main())
