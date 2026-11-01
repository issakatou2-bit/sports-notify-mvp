"""保存済みの視聴者向け文を数える。通信なし・原稿を書き換えない。

最新のtracked出力と指定期間のorigin/main履歴を収集。試験材料/作業メモ/
生成プロンプトは除外。同じ文・原文・材料の組は1件、出所は全て保持する。
判定は人がannotations JSONで付ける。未判定を誤検出と決めつけない。
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess

import backstage_guard
import comment_actors
import game_fact_guard
import soccer_venue

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT_KEYS = {'ai_summary', 'notification_hook', 'ja', 'jp', 'gist', 'topic_jp',
             'headline', 'description', 'narration', 'subtitle', 'caption'}
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def candidate(path):
    return (path.endswith(('.json', '.srt', '.vtt'))
            and path.startswith(('archive/', 'data/', 'content/'))
            and not any(x in path for x in ('/planning/', '/fixtures/', 'token_usage', 'dialogue_batch')))


def sources(root, since, until, history=True):
    """blob単位で読み出す。同一ファイルの同一blobは履歴で重複しない。"""
    objects = {}
    paths = git(root, 'ls-files').decode('utf-8').splitlines()
    for path in paths:
        if candidate(path):
            objects[('working', path)] = [(ROOT.name, 'working')]
    if history:
        lines = git(root, 'log', '--format=commit:%H:%cs', '--name-only',
                    '--since='+since+'T00:00:00+09:00',
                    '--until='+until+'T23:59:59+09:00', 'origin/main',
                    '--', 'archive', 'data', 'content').decode('utf-8').splitlines()
        revisions = {}
        for line in lines:
            if line.startswith('commit:'):
                _, rev, day = line.split(':')
                revisions[rev] = {'day': day, 'paths': set()}
            elif candidate(line):
                revisions[rev]['paths'].add(line)
        for rev, entry in revisions.items():
            tree = git(root, 'ls-tree', '-r', rev).decode('utf-8').splitlines()
            for line in tree:
                meta, path = line.split('\t', 1)
                if path in entry['paths']:
                    sha = meta.split()[2]
                    objects.setdefault((sha, path), []).append((rev, entry['day']))
    # cat-fileを1プロセスで使う。大量のgit showの反復を避ける。
    hashes = sorted({sha for sha, _ in objects if sha != 'working'})
    blobs = {}
    if hashes:
        raw = subprocess.run(['git', 'cat-file', '--batch'], cwd=root,
                             input=('\n'.join(hashes)+'\n').encode(), capture_output=True, check=True).stdout
        pos = 0
        for sha in hashes:
            end = raw.index(b'\n', pos)
            header = raw[pos:end].split()
            size = int(header[2])
            blobs[sha] = raw[end+1:end+1+size].decode('utf-8-sig')
            pos = end+size+2
    for (sha, path), refs in objects.items():
        raw = (root/path).read_text(encoding='utf-8-sig') if sha == 'working' else blobs[sha]
        yield path, sha, refs, raw


def day_of(node, fallback):
    if isinstance(node, dict):
        for key in ('date_jst', 'date', 'game_date', 'video_published_at', 'published_at', 'at', 'generated_at', 'updated_at'):
            val = node.get(key)
            if isinstance(val, str) and DATE.match(val):
                if 'T' in val:
                    try:
                        return dt.datetime.fromisoformat(val.replace('Z', '+00:00')).astimezone(
                            dt.timezone(dt.timedelta(hours=9))).date().isoformat()
                    except ValueError:
                        pass
                return val[:10]
    return fallback


def texts(node, path='', day='', evidence=None, game=None, context='', segment_reviews=None):
    """構造が同じ保存材料だけを添える。現在のAPI値と過去の文を結び付けない。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from texts(item, f'{path}/{i}', day, evidence, game, context, segment_reviews)
    elif isinstance(node, dict):
        day = day_of(node, day)
        if node.get('game_material'):
            evidence = node['game_material']
        elif node.get('mode') == 'numbers' and node.get('material'):
            evidence = node['material']
        if node.get('segments') and evidence:
            whole = game_fact_guard.review(dict(node, game_material=evidence))
            segment_reviews = {}
            for i in range(1, len(node['segments'])+1):
                segment_reviews[f'{path}/segments/{i-1}/text'] = {
                    'errors': [s for s in whole['errors'] if s.startswith(str(i)+'行目:')],
                    'warnings': [s for s in whole['warnings'] if s.startswith(str(i)+'行目:')],
                    'omit': [i] if i in whole['omit'] else []}
        if node.get('home_team_name') and node.get('away_team_name'):
            # MLBにもホーム/アウェー表現はあるがサッカー用検査へ混ぜない。
            if node.get('league') not in ('MLB', 'NPB'):
                game = {k: node.get(k) for k in ('home_team_name', 'away_team_name', 'neutral_site', 'neutralSite')}
        original = node.get('original') or node.get('title') or node.get('text') or ''
        replies = node.get('reply_texts') or []
        own_context = '\n'.join(x if isinstance(x, str) else x.get('text', '') for x in replies)
        for key, value in node.items():
            viewer = key in TEXT_KEYS or (key == 'text' and '/segments/' in path)
            viewer = viewer or (key == 'title' and ('video_id' in node or 'guid' in node))
            if viewer and isinstance(value, str) and value.strip():
                yield {'path': path+'/'+key, 'date': day, 'text': value, 'field': key,
                       'evidence': evidence, 'game': game,
                       'original': original if key in ('ja', 'jp') else '',
                       'context': context+'\n'+own_context,
                       'game_review': (segment_reviews or {}).get(path+'/'+key)}
            elif isinstance(value, (dict, list)):
                # facts/material/provenanceは出力ではない。これらの文字列を数えない。
                if key not in ('game_material', 'material', 'facts', 'input', 'prompt', 'source_headlines'):
                    yield from texts(value, path+'/'+key, day, evidence, game,
                                     (original+'\n'+own_context) if key == 'reply_ja' else context,
                                     segment_reviews)


def collect(root, since, until, history=True, supplement=None):
    records, errors, scanned = {}, [], 0
    saved = list(sources(root, since, until, history))
    for entry in supplement or []:
        saved.append((entry['source']['path'], entry['source']['sha256'],
                      [('supplement', entry['date'])],
                      json.dumps(entry['document'], ensure_ascii=False)))
    for file, blob, refs, raw in saved:
        scanned += 1
        file_day = DATE.search(file)
        fallback = (refs[0][1] if refs[0][0] == 'supplement'
                    else file_day[0] if file_day else '')
        try:
            rows = (texts(json.loads(raw), day=fallback) if file.endswith('.json')
                    else ({'path': '/'+str(i), 'date': fallback, 'text': line, 'field': 'subtitle',
                           'evidence': None, 'game': None, 'original': '', 'context': ''}
                          for i, line in enumerate(raw.splitlines(), 1)
                          if line.strip() and not line.strip().isdigit() and '-->' not in line and line != 'WEBVTT'))
            for row in rows:
                # 本文+検査に使う同じ根拠で重複を除く。出所/日付の違いは保持。
                signature = {k: row[k] for k in ('text', 'field', 'evidence', 'game', 'original', 'context')}
                uid = hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
                source = {'file': file, 'blob': blob, 'path': row['path'], 'date': row['date'],
                          'revisions': [rev for rev, _ in refs]}
                if uid not in records:
                    records[uid] = dict(row, id=uid, sources=[])
                records[uid]['sources'].append(source)
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append({'file': file, 'blob': blob, 'error': str(exc)})
    rows = list(records.values())
    def recent(row):
        return any(since <= s['date'] <= until for s in row['sources'] if s['date'])
    rows.sort(key=lambda row: (not recent(row), row['id']))
    return rows, {'file_versions': scanned, 'texts': len(rows),
                  'recent_texts': sum(recent(row) for row in rows),
                  'read_errors': errors}


def inspect(row):
    hits = []
    bad = backstage_guard.violations(row['text'])
    if bad:
        hits.append({'guard': 'backstage', 'reasons': bad})
    if row['evidence']:
        review = row.get('game_review') or game_fact_guard.review(
            {'game_material': row['evidence'], 'segments': [{'text': row['text']}]})
        if review['errors'] or review['omit']:
            hits.append({'guard': 'game_facts', 'reasons': review['errors'] or review['warnings']})
    if row['game']:
        bad = soccer_venue.check(row['text'], row['game'])
        if bad:
            hits.append({'guard': 'venue', 'reasons': bad})
    if row['original']:
        bad = comment_actors.check(row['original'], row['text'], row['context'])
        if bad:
            hits.append({'guard': 'comment_actor', 'reasons': bad})
    return hits


def audit(root, since, until, history=True, annotations=None, supplement=None):
    rows, coverage = collect(root, since, until, history, supplement)
    coverage['game_evidence_texts'] = sum(bool(r['evidence']) for r in rows)
    coverage['venue_evidence_texts'] = sum(bool(r['game']) for r in rows)
    coverage['comment_original_texts'] = sum(bool(r['original']) for r in rows)
    findings, counts = [], collections.defaultdict(collections.Counter)
    annotations = annotations or {}
    for row in rows:
        for hit in inspect(row):
            key = row['id']+':'+hit['guard']
            annotation = annotations.get(key, {})
            status = annotation.get('status', 'unreviewed')
            if status not in ('true_error', 'false_positive', 'unreviewed'):
                raise ValueError('不正な判定: '+key)
            counts[hit['guard']][status] += 1
            findings.append(dict(row, **hit, finding_id=key, status=status,
                                 rationale=annotation.get('rationale', '')))
    return {'since': since, 'until': until, 'scope': 'tracked snapshot + origin/main history (window)',
            'coverage': coverage, 'counts': dict(counts), 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--since', default='2026-09-13')
    parser.add_argument('--until', default='2026-10-12')
    parser.add_argument('--no-history', action='store_true')
    parser.add_argument('--annotations', type=pathlib.Path)
    parser.add_argument('--supplement', type=pathlib.Path,
                        help='実出力と同日の保存材料を結び付けた追加資料JSON。出所/hash必須')
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.since > args.until:
        parser.error('開始日が終了日より後です')
    annotations = json.loads(args.annotations.read_text(encoding='utf-8')) if args.annotations else {}
    supplement = json.loads(args.supplement.read_text(encoding='utf-8')) if args.supplement else None
    result = audit(args.root, args.since, args.until, not args.no_history, annotations, supplement)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'coverage': result['coverage'], 'counts': result['counts']}, ensure_ascii=False))
    return 1 if result['coverage']['read_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
