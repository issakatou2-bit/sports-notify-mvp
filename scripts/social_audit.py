"""Read-only Buffer audit. No Ledger(), reservation, mutation or state writes.

Exit 0: checked and clean; 1: suspicious posts; 2: incomplete/unavailable audit.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse, parse_qs

# Keep aligned with buffer_daily.py; never discover destinations from the token.
CHANNELS = {'twitter': '6aa114c5cd8b9c702c36144a',
            'instagram': '6aa1debacd8b9c702c3cc4db',
            'tiktok': '6aa11393cd8b9c702c360d01'}
ORG = '6aa11108acee3b0c72033754'
ACTIVE = {'scheduled', 'sending', 'needs_approval'}
SPORT = re.compile(r'MLB|欧州サッカー|#(?:野球|サッカー|大谷翔平|山本由伸)|'
                   r'明日の注目試合|日本人選手|現地の報道|現地の反応|ファンのコメント欄|'
                   r'ポストシーズン|PS試合予告|PSカード|PS対戦表|PS進出|今夜の注目カード|進出争い')
FOREIGN = re.compile(r'【(?:応用情報|基本情報|ITパスポート)|APSC|雨衣とみる|インシデントノート')


class Incomplete(ValueError):
    """Cannot establish a complete audit; never report clean."""


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise Incomplete('invalid/missing timezone-aware timestamp') from None


def published_ids(records):
    ids = set()
    if isinstance(records, dict):
        if re.fullmatch(r'[\w-]{11}', str(records.get('video_id', '')), re.ASCII):
            ids.add(records['video_id'])
        for value in records.values():
            ids.update(published_ids(value))
    elif isinstance(records, list):
        for value in records:
            ids.update(published_ids(value))
    return ids


def video_links(text):
    ids = set()
    for raw in re.findall(r'https?://[^\s<>]+', text):
        url = urlparse(raw.rstrip('。、)'))
        if url.hostname == 'youtu.be':
            ids.add(url.path.strip('/'))
        elif url.hostname in ('youtube.com', 'www.youtube.com'):
            if url.path == '/watch':
                ids.update(parse_qs(url.query).get('v', []))
            elif url.path.startswith('/shorts/'):
                ids.add(url.path.split('/')[2])
    return ids


def fetch_posts(query_fn, channel, max_pages=20):
    """Scan all queued/sent pages, then filter on sentAt locally.

    createdAt/startDate is not sentAt: an old reservation may publish today.
    A bounded scan that does not finish is explicitly incomplete, not clean.
    """
    posts, cursor, seen = [], None, set()
    for _ in range(max_pages):
        after = ', after:' + json.dumps(cursor) if cursor else ''
        query = ('query { posts(first:100' + after + ', input:{organizationId:' +
                 json.dumps(ORG) + ',filter:{channelIds:[' + json.dumps(channel) +
                 '],status:[scheduled,sending,needs_approval,sent]},'
                 'sort:[{field:createdAt,direction:desc}]}) {'
                 'edges {node {id channelId text status dueAt sentAt}} '
                 'pageInfo {hasNextPage endCursor}}}')
        try:
            result = query_fn(query)['posts']
            nodes = [edge['node'] for edge in result['edges']]
            page = result['pageInfo']
            if type(page['hasNextPage']) is not bool:
                raise ValueError()
            for node in nodes:
                if node.get('channelId') != channel:
                    raise ValueError()
                if not all(isinstance(node.get(k), str) and node[k]
                           for k in ('id', 'text', 'status')):
                    raise ValueError()
            posts.extend(nodes)
            if not page['hasNextPage']:
                return posts
            cursor = page['endCursor']
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError()
            seen.add(cursor)
        except Exception:
            # Do not leak response text, headers, token or exception messages.
            raise Incomplete('Buffer read unavailable or malformed') from None
    raise Incomplete('Buffer pagination limit reached')


def audit(posts_by_service, ledger, records, now):
    if set(posts_by_service) != set(CHANNELS):
        raise Incomplete('all three channels are required')
    deliveries = ledger.get('deliveries')
    if not isinstance(deliveries, dict):
        raise Incomplete('delivery ledger missing')
    owned = published_ids(records)
    if not owned:
        raise Incomplete('published video registry empty')
    findings, checked, seen = [], 0, {}
    for service, posts in posts_by_service.items():
        if not isinstance(posts, list):
            raise Incomplete('posts must be a list')
        entries = [entry for key, entry in deliveries.items()
                   if key.rsplit(':', 1)[-1] == service and isinstance(entry, dict)]
        for post in posts:
            if post.get('channelId') != CHANNELS[service]:
                raise Incomplete('unexpected channel')
            status = post.get('status')
            if status == 'sent':
                when = instant(post.get('sentAt'))
                if when > now:
                    raise Incomplete('sent timestamp is in future')
                if when < now - timedelta(days=7):
                    continue
            elif status in ACTIVE:
                when = instant(post.get('dueAt')) if post.get('dueAt') else None
                if status == 'scheduled' and when is None:
                    raise Incomplete('scheduled timestamp missing')
            else:
                raise Incomplete('unexpected post status')
            pid, text = post.get('id'), post.get('text')
            if not isinstance(pid, str) or not pid or not isinstance(text, str) or not text:
                raise Incomplete('post fields missing')
            key = (service, pid)
            if key in seen:
                if seen[key] != post:
                    raise Incomplete('conflicting duplicate post')
                continue
            seen[key] = post
            checked += 1
            matching = [entry for entry in entries if entry.get('post_id') == pid]
            reasons = []
            if not matching:
                reasons.append('台帳にない投稿・予約')
            elif any(entry.get('text') and entry['text'] != text for entry in matching):
                reasons.append('台帳の本文と不一致')
            vids = video_links(text)
            if not vids or not vids <= owned:
                reasons.append('登録済みコレスポ動画のリンクを確認できない')
            expected = {entry['youtube_id'] for entry in matching if entry.get('youtube_id')}
            if expected and not expected <= vids:
                reasons.append('台帳の動画IDと不一致')
            brand = any(urlparse(raw.rstrip('。、)')).hostname == 'collespo.com'
                        for raw in re.findall(r'https?://[^\s<>]+', text))
            brand = brand or bool(re.search(r'(?:^|\s)collespo\.com(?:/[^\s]*)?(?=\s|$)', text))
            if not brand or not SPORT.search(text) or FOREIGN.search(text):
                reasons.append('コレスポ本文の形式外')
            if reasons:
                # JSON lines and escaped controls prevent GitHub command injection.
                findings.append({'service': service, 'status': status,
                                 'at': when.isoformat() if when else '未設定',
                                 'post_id': pid, 'text_head': text[:100], 'reasons': reasons})
    return {'checked': checked, 'findings': findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--published', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fixture', type=Path)
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--now', help='fixture only, ISO timestamp with timezone')
    args = parser.parse_args(argv)
    try:
        if args.live and args.now:
            raise Incomplete('--now is fixture-only')
        now = instant(args.now) if args.now else datetime.now(timezone.utc)
        ledger = json.loads(args.ledger.read_text(encoding='utf-8'))
        records = json.loads(args.published.read_text(encoding='utf-8'))
        if args.fixture:
            posts = json.loads(args.fixture.read_text(encoding='utf-8'))
        else:
            from buffer_api import graphql
            posts = {service: fetch_posts(graphql, channel)
                     for service, channel in CHANNELS.items()}
        result = audit(posts, ledger, records, now)
        for row in result['findings']:
            print(json.dumps(row, ensure_ascii=False))
        print(('要確認' if result['findings'] else '異常なし') + ': ' + str(result['checked']) + '件を確認')
        return 1 if result['findings'] else 0
    except Exception:
        print('監査未完了: 入力または取得を確認してください（詳細応答・秘密は非表示）')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
