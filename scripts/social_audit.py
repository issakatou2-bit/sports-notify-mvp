"""Read-only Buffer audit. No Ledger(), reservation, mutation or state writes.

Exit 0: checked and clean; 1: suspicious posts; 2: incomplete/unavailable audit.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
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
FOREIGN = re.compile(r'【(?:応用情報|基本情報|ITパスポート)|APSC|雨衣とみる|インシデントノート|'
                     r'めたん先生のIT試験ゼミ')
STAMP = re.compile(r'^\d{1,2}/\d{1,2}更新｜')
DEFAULT_KNOWN = Path(__file__).resolve().parent.parent / 'data' / 'social_audit_known.json'


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


def normalized(text):
    """Compare the way Buffer delivers text: line breaks become spaces.

    TikTok in particular drops newlines; Instagram/X keep them. Whitespace is
    therefore not evidence of an edit.
    """
    return re.sub(r'\s+', '', text or '')


def same_text(post_text, ledger_text):
    """Ledger text is authoritative; a service may shorten the posted text."""
    post, ledger = normalized(post_text), normalized(ledger_text)
    return bool(post and ledger and (ledger.startswith(post) or post.startswith(ledger)))


def without_links(text):
    return normalized(re.sub(r'https?://\S+', '', text or ''))


def restored_links(text, entries):
    """A post Buffer copied back from X has t.co links; the ledger keeps the originals."""
    if 'https://t.co/' in text:
        for entry in entries:
            if entry.get('text') and without_links(text) == without_links(entry['text']):
                return entry['text']
    return text


def collespo_form(service, text):
    """X needs the site link; Instagram/TikTok are captions without it."""
    if service != 'twitter':
        return bool(STAMP.match(text))
    brand = any(urlparse(raw.rstrip('。、)')).hostname == 'collespo.com'
                for raw in re.findall(r'https?://[^\s<>]+', text))
    return brand or bool(re.search(r'(?:^|\s)collespo\.com(?:/[^\s]*)?(?=\s|$)', text))


def load_known(path):
    """Handled post IDs. A missing file means nothing has been handled yet."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return set()
    except Exception:
        raise Incomplete('known list unreadable') from None
    handled = data.get('handled') if isinstance(data, dict) else None
    if not isinstance(handled, dict):
        raise Incomplete('known list malformed')
    return {key for key, memo in handled.items()
            if isinstance(key, str) and key and isinstance(memo, str)}


def read_failure(exc):
    """A safe reason line: no response body, headers, token or post text."""
    detail = getattr(exc, 'detail', None)
    if callable(detail):
        try:
            return detail()
        except Exception:                                # noqa: BLE001
            pass
    # Unknown errors may embed credentials in their message; only show the type.
    return '段階=送信 種類=' + type(exc).__name__


def fetch_posts(query_fn, channel, max_pages=20, retries=2, retry_delay=1):
    """Scan all queued/sent pages, then filter on sentAt locally.

    createdAt/startDate is not sentAt: an old reservation may publish today.
    A bounded scan that does not finish is explicitly incomplete, not clean.

    The query mirrors buffer_daily.recent_posts (same filter, sort, page size
    and cursor handling). Buffer occasionally fails a request, so retry once,
    as recent_posts does. Failures raise Incomplete with a credential-free
    reason: stage, HTTP status, GraphQL messages (redacted, 200 chars) and
    top-level response key names.
    """
    posts, cursor, seen = [], None, set()
    retries = max(1, retries)
    for _ in range(max_pages):
        after = ', after: ' + json.dumps(cursor) if cursor else ''
        query = ('{ posts(first: 100' + after + ', input: { organizationId: ' +
                 json.dumps(ORG) + ', filter: {channelIds:[' + json.dumps(channel) +
                 ']}, sort:[{field:createdAt,direction:desc}]}) {'
                 'edges {node {id channelId text status dueAt sentAt}} '
                 'pageInfo {hasNextPage endCursor} } }')
        for attempt in range(retries):
            try:
                data = query_fn(query)
                break
            except Exception as exc:                     # noqa: BLE001
                if attempt + 1 < retries:
                    time.sleep(retry_delay)
                    continue
                raise Incomplete('Buffer read unavailable or malformed (' +
                                 read_failure(exc) + ')') from None
        try:
            result = data['posts']
            nodes = [edge['node'] for edge in result['edges']]
            page = result['pageInfo']
        except Exception:
            keys = (','.join(sorted(str(k) for k in data)[:10])
                    if isinstance(data, dict) else type(data).__name__)
            raise Incomplete('Buffer read unavailable or malformed '
                             '(段階=項目の取り出し 応答の項目=' +
                             (keys[:100] or 'なし') + ')') from None
        try:
            if type(page['hasNextPage']) is not bool:
                raise ValueError('hasNextPage')
            for node in nodes:
                # The channel filter scopes nodes; recent_posts does not require
                # channelId, and it may be absent. A different value is an error.
                if node.get('channelId') and node['channelId'] != channel:
                    raise ValueError('channelId')
                if not all(isinstance(node.get(k), str) and node[k]
                           for k in ('id', 'status')):
                    raise ValueError('id/status')
                # text is checked in audit() only for statuses we inspect: an
                # unfiltered page also contains drafts whose text may be empty.
            posts.extend(dict(node, channelId=channel) for node in nodes)
            if not page['hasNextPage']:
                return posts
            cursor = page['endCursor']
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError('endCursor')
            seen.add(cursor)
        except ValueError as exc:
            raise Incomplete('Buffer read unavailable or malformed '
                             '(段階=項目の取り出し 項目=' + str(exc) + ')') from None
    raise Incomplete('Buffer pagination limit reached')


def recent_delivery(entry, now):
    """Ledger records the sent observation in checked_at, not sentAt."""
    if entry.get('state') != 'sent':
        return False
    stamp = entry.get('checked_at') or entry.get('reserved_at')
    if not stamp:
        # A sent row with no usable time cannot establish an empty audit either.
        raise Incomplete('sent delivery timestamp missing')
    return now - timedelta(days=7) <= instant(stamp) <= now


def audit(posts_by_service, ledger, records, now, known=None):
    if set(posts_by_service) != set(CHANNELS):
        raise Incomplete('all three channels are required')
    deliveries = ledger.get('deliveries')
    if not isinstance(deliveries, dict):
        raise Incomplete('delivery ledger missing')
    known = set(known or ())
    owned = published_ids(records)
    if not owned:
        raise Incomplete('published video registry empty')
    findings, checked, seen = [], 0, {}
    for service, posts in posts_by_service.items():
        if not isinstance(posts, list):
            raise Incomplete('posts must be a list')
        entries = [entry for key, entry in deliveries.items()
                   if key.rsplit(':', 1)[-1] == service and isinstance(entry, dict)]
        service_checked = 0
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
            elif status in {'draft', 'error', 'failed', 'rejected', 'not_sent'}:
                continue  # Unfiltered recent_posts also returns non-target posts.
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
            service_checked += 1
            matching = [entry for entry in entries if entry.get('post_id') == pid]
            text = restored_links(text, matching)
            reasons = []
            if not matching:
                reasons.append('台帳にない投稿・予約')
            elif any(entry.get('text') and not same_text(text, entry['text'])
                     for entry in matching):
                reasons.append('台帳の本文と不一致')
            vids = video_links(text)
            expected = {entry['youtube_id'] for entry in matching if entry.get('youtube_id')}
            if service == 'twitter':
                # X posts always carry the link, so its absence is suspicious.
                if not vids or not vids <= owned:
                    reasons.append('登録済みコレスポ動画のリンクを確認できない')
                if expected and not expected <= vids:
                    reasons.append('台帳の動画IDと不一致')
            else:
                # Instagram/TikTok captions often omit the link by design.
                # The ledger's youtube_id is the durable evidence.
                if expected and not expected <= owned:
                    reasons.append('登録済みコレスポ動画のリンクを確認できない')
                elif vids and not vids <= owned:
                    reasons.append('登録済みコレスポ動画のリンクを確認できない')
                elif expected and vids and not expected <= vids:
                    reasons.append('台帳の動画IDと不一致')
            if not collespo_form(service, text) or not SPORT.search(text) or FOREIGN.search(text):
                reasons.append('コレスポ本文の形式外')
            if reasons:
                # JSON lines and escaped controls prevent GitHub command injection.
                findings.append({'service': service, 'status': status,
                                 'at': when.isoformat() if when else '未設定',
                                 'post_id': pid, 'text_head': text[:100], 'reasons': reasons})
        if not service_checked and any(recent_delivery(entry, now) for entry in entries):
            raise Incomplete(service + ': 台帳に直近7日の送信があるのに対象投稿を読めなかった')
    if not checked:
        raise Incomplete('確認0件: 対象投稿を読めなかった')
    handled = [row for row in findings if row['post_id'] in known]
    return {'checked': checked,
            'findings': [row for row in findings if row['post_id'] not in known],
            'handled': len(handled)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--published', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fixture', type=Path)
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--now', help='fixture only, ISO timestamp with timezone')
    parser.add_argument('--known', type=Path,
                        help='handled post IDs (default: data/social_audit_known.json)')
    args = parser.parse_args(argv)
    try:
        if args.live and args.now:
            raise Incomplete('--now is fixture-only')
        now = instant(args.now) if args.now else datetime.now(timezone.utc)
        ledger = json.loads(args.ledger.read_text(encoding='utf-8'))
        records = json.loads(args.published.read_text(encoding='utf-8'))
        # Asset videos (season recaps) are registered separately from daily videos.
        asset_registry = args.published.with_name('published_assets.json')
        if asset_registry.is_file() and asset_registry.resolve() != args.published.resolve():
            records = {'videos': records,
                       'assets': json.loads(asset_registry.read_text(encoding='utf-8'))}
        known = load_known(args.known or DEFAULT_KNOWN)
        if args.fixture:
            posts = json.loads(args.fixture.read_text(encoding='utf-8'))
        else:
            from buffer_api import graphql
            posts = {service: fetch_posts(graphql, channel)
                     for service, channel in CHANNELS.items()}
        for service in CHANNELS:
            rows = posts.get(service) if isinstance(posts, dict) else None
            print(service + ': 読めた投稿 ' + (str(len(rows)) if isinstance(rows, list) else '不明') + '件')
        result = audit(posts, ledger, records, now, known)
        for row in result['findings']:
            print(json.dumps(row, ensure_ascii=False))
        if result['handled']:
            print('対応済み ' + str(result['handled']) + '件')
        print(('要確認' if result['findings'] else '異常なし') + ': ' + str(result['checked']) + '件を確認')
        return 1 if result['findings'] else 0
    except Incomplete as exc:
        print('監査未完了（読めなかった）: ' + str(exc))
        return 2
    except Exception:
        print('監査未完了: 入力または取得を確認してください（詳細応答・秘密は非表示）')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
