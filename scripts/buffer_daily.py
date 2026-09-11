"""Publish the successful daily MLB Short to the three owned Buffer channels.

The source artifact is kept in a GitHub release. A separate Git branch stores a
durable reservation BEFORE each Buffer mutation. An uncertain response must be
reconciled, never blindly retried. No LLM calls or paid storage are required.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from buffer_api import graphql

REPO = 'issakatou2-bit/sports-notify-mvp'
API = 'https://api.github.com/repos/' + REPO
STATE_BRANCH = 'codex/buffer-state'
STATE_PATH = 'data/buffer_delivery.json'
JST = timezone(timedelta(hours=9))
CHANNELS = {'twitter': '6aa114c5cd8b9c702c36144a',
            'instagram': '6aa1debacd8b9c702c3cc4db',
            'tiktok': '6aa11393cd8b9c702c360d01'}
ORG = '6aa11108acee3b0c72033754'
MAX_BYTES = 80 * 1024 * 1024


def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return stamp


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        follow = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlparse(newurl).hostname != urllib.parse.urlparse(req.full_url).hostname:
            follow.remove_header('Authorization')
        return follow


def github(path, method='GET', body=None, raw=False):
    url = API + path
    req = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'User-Agent': 'Collespo/1.0'})
    with urllib.request.build_opener(SafeRedirect).open(req, timeout=60) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('GitHub response exceeds allowed size')
    return content if raw else json.loads(content) if content else {}


class Ledger:
    def __init__(self):
        try:
            github('/git/ref/heads/' + STATE_BRANCH)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            sha = github('/git/ref/heads/main')['object']['sha']
            github('/git/refs', 'POST', {'ref': 'refs/heads/' + STATE_BRANCH, 'sha': sha})
        try:
            result = github('/contents/' + STATE_PATH + '?ref=' + STATE_BRANCH)
            self.sha = result['sha']
            self.data = json.loads(base64.b64decode(result['content']))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            self.sha, self.data = None, {'version': 1, 'deliveries': {}}

    def save(self):
        body = {'message': 'Record Buffer delivery state', 'branch': STATE_BRANCH,
                'content': base64.b64encode(json.dumps(self.data, ensure_ascii=False, indent=2).encode()).decode()}
        if self.sha:
            body['sha'] = self.sha
        self.sha = github('/contents/' + STATE_PATH, 'PUT', body)['content']['sha']

    def set(self, key, value):
        self.data['deliveries'][key] = value
        self.save()


def select_record(run, records, now):
    if run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/daily_notify.yml':
        raise ValueError('Source must be the main daily MLB workflow')
    if run.get('conclusion') != 'success' or run.get('event') not in ('workflow_dispatch', 'schedule', 'workflow_run'):
        raise ValueError('Source workflow did not finish successfully')
    if run.get('repository', {}).get('full_name') != REPO:
        raise ValueError('Unexpected source repository')
    created = instant(run['created_at'])
    day = created.astimezone(JST).date().isoformat()
    if day != now.astimezone(JST).date().isoformat():
        raise ValueError('Stale source: only the current JST edition may be posted')
    record = records.get('daily', {}).get(day)
    if not record or not re.fullmatch(r'[A-Za-z0-9_-]{11}', record.get('video_id', '')):
        raise ValueError('No matching daily YouTube record')
    if not created <= instant(record['published_at']) <= instant(run['updated_at']):
        raise ValueError('Video record was not produced during this workflow run')
    if instant(record.get('publish_at') or record['published_at']) > now:
        raise ValueError('YouTube publication is still in the future')
    return day, record


def verify_youtube(record):
    query = urllib.parse.urlencode({'part': 'status,snippet', 'id': record['video_id'],
                                   'key': os.environ['YOUTUBE_API_KEY']})
    try:
        with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/videos?' + query, timeout=20) as response:
            items = json.load(response).get('items', [])
    except Exception:
        raise RuntimeError('Unable to verify YouTube publication') from None
    if not items or items[0]['status'].get('privacyStatus') != 'public':
        raise ValueError('YouTube video is not public')
    if items[0]['snippet']['channelId'] != 'UCpZ_j8X8uOex5VvKwwTJj3Q':
        raise ValueError('YouTube video belongs to a different channel')


def extract_video(archive, destination):
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        entries = source.infolist()
        if len(entries) != 1 or entries[0].filename.split('/')[-1] != 'collespo_short.mp4':
            raise ValueError('Expected one daily video in the artifact')
        entry = entries[0]
        if entry.file_size > MAX_BYTES or entry.file_size < 1000:
            raise ValueError('Invalid video size')
        # No archive path is used for extraction.
        with source.open(entry) as video:
            data = video.read(MAX_BYTES + 1)
        if len(data) != entry.file_size:
            raise ValueError('Incomplete video')
        destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def verify_media(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    media = json.loads(result.stdout)
    duration = float(media['format']['duration'])
    videos = [s for s in media['streams'] if s['codec_type'] == 'video']
    audios = [s for s in media['streams'] if s['codec_type'] == 'audio']
    if not 5 <= duration <= 140 or not videos or not audios:
        raise ValueError('Require a 5–140 second video with audio for all three platforms')
    video = videos[0]
    if video['codec_name'] != 'h264' or audios[0]['codec_name'] != 'aac':
        raise ValueError('Require H.264 and AAC')
    if abs(video['width'] / video['height'] - 9 / 16) > 0.02:
        raise ValueError('Require a vertical 9:16 video')
    return round(duration, 2)


def host_video(run, day, path, digest):
    tag = 'social-daily-' + day
    try:
        release = github('/releases/tags/' + tag)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = github('/releases', 'POST', {
            'tag_name': tag, 'target_commitish': run['head_sha'],
            'name': day + ' 明日の注目試合・配信用動画',
            'body': 'コレスポの自動生成動画。YouTubeでの公開を確認後、SNS配信に利用します。\n元の実行: ' + run['html_url'],
            'make_latest': 'false'})
    name = 'collespo-daily-' + day + '.mp4'
    asset = next((a for a in release['assets'] if a['name'] == name), None)
    if asset:
        if asset.get('digest') != 'sha256:' + digest:
            raise ValueError('Existing release video differs; refusing to replace it')
        return asset['browser_download_url']
    req = urllib.request.Request('https://uploads.github.com/repos/' + REPO + '/releases/' +
        str(release['id']) + '/assets?name=' + name, data=path.read_bytes(),
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Content-Type': 'video/mp4', 'User-Agent': 'Collespo/1.0'})
    with urllib.request.urlopen(req, timeout=120) as response:
        asset = json.load(response)
    if asset.get('digest') != 'sha256:' + digest:
        raise ValueError('Uploaded media digest mismatch')
    return asset['browser_download_url']


def caption(service, day, record):
    title = record['title'].split('｜明日の注目試合')[0].replace('【MLB】', '').strip()
    youtube = 'https://www.youtube.com/watch?v=' + record['video_id']
    if service == 'twitter':
        # Unicode outside the single-weight X ranges counts twice; URLs are 23.
        text = f'{day[5:].replace("-", "/")}更新｜明日のMLB\n{title}\n\n動画で見どころをチェック。\n{youtube}\nhttps://collespo.com/\n#MLB'
        if x_weight(text) > 280:
            raise ValueError('X caption exceeds 280 weighted characters')
        return text
    return (f'{day[5:].replace("-", "/")}更新｜明日の注目試合\n{title}\n\n'
            '試合を見る前に、先発と注目ポイントをチェック。\n'
            '動画・記事はプロフィールの collespo.com から。\n' + youtube +
            '\n\n音声：VOICEVOX:ずんだもん\n#MLB #コレスポ #野球')


def x_weight(text):
    return sum(1 if ord(c) <= 0x10ff or 0x2000 <= ord(c) <= 0x200d or
               0x2010 <= ord(c) <= 0x201f or 0x2032 <= ord(c) <= 0x2037 else 2
               for c in re.sub(r'https?://[^\s]+', 'x' * 23, text))


def recent_posts(channel):
    posts, cursor = [], None
    for _ in range(5):
        after = ', after: ' + json.dumps(cursor) if cursor else ''
        result = graphql('{ posts(first: 100' + after + ', input: { organizationId: ' +
            json.dumps(ORG) + ', filter: {channelIds:[' + json.dumps(channel) +
            ']}, sort:[{field:createdAt,direction:desc}]}) { edges {node {id text status externalLink}} pageInfo {hasNextPage endCursor} } }')['posts']
        posts.extend(e['node'] for e in result['edges'])
        if not result['pageInfo']['hasNextPage']:
            return posts
        cursor = result['pageInfo']['endCursor']
    raise RuntimeError('Too many posts to reconcile safely')


def create_payload(service, text, media_url):
    payload = {'channelId': CHANNELS[service], 'text': text, 'schedulingType': 'automatic',
               'mode': 'shareNow', 'assets': [{'video': {'url': media_url,
                           'metadata': {'thumbnailOffset': 2000}}}],
               'needsApproval': False, 'aiAssisted': True}
    if service == 'instagram':
        payload['metadata'] = {'instagram': {'type': 'reel', 'shouldShareToFeed': True, 'isAiGenerated': True}}
    elif service == 'tiktok':
        payload['metadata'] = {'tiktok': {'isAiGenerated': True}}
    return payload


def reconcile():
    """Refresh saved deliveries without creating media or posts, even after midnight."""
    ledger = Ledger()
    posts_by_channel = {service: recent_posts(channel) for service, channel in CHANNELS.items()}
    unresolved = []
    for key, entry in list(ledger.data['deliveries'].items()):
        service = key.rsplit(':', 1)[-1]
        if entry.get('state') == 'sent' or service not in posts_by_channel:
            continue
        post = next((p for p in posts_by_channel[service]
                     if p['id'] == entry.get('post_id') or p['text'] == entry.get('text')), None)
        if post:
            ledger.set(key, {**entry, 'state': post['status'], 'post_id': post['id'],
                            'external_link': post.get('externalLink'),
                            'checked_at': datetime.now(timezone.utc).isoformat()})
        row = ledger.data['deliveries'][key]
        print(key, row.get('state'), row.get('external_link'))
        if row.get('state') != 'sent':
            unresolved.append(key)
    if unresolved:
        raise SystemExit('Still unconfirmed: ' + ', '.join(unresolved))


def submit_once(ledger, key, payload, metadata, retry_rejected=False):
    old = ledger.data['deliveries'].get(key)
    posts = recent_posts(payload['channelId'])
    matches = [p for p in posts if (old and p['id'] == old.get('post_id')) or p['text'] == payload['text']]
    if matches:
        post = matches[0]
        ledger.set(key, {**metadata, 'state': post['status'], 'post_id': post['id'],
                         'external_link': post.get('externalLink')})
        return post
    if old and not (old['state'] == 'rejected' and retry_rejected):
        raise RuntimeError('Existing reservation requires inspection; will not resend: ' + key)
    entry = {**metadata, 'state': 'reserved', 'text': payload['text'],
             'reserved_at': datetime.now(timezone.utc).isoformat()}
    ledger.set(key, entry)  # Must be durable before any external post mutation.
    result = graphql('mutation($input: CreatePostInput!) { createPost(input:$input) { '
        '__typename ... on PostActionSuccess { post { id status text externalLink } } '
        '... on MutationError { message } } }', {'input': payload})['createPost']
    if result.get('__typename') != 'PostActionSuccess':
        ledger.set(key, {**entry, 'state': 'rejected', 'message': result.get('message', 'Rejected')})
        raise RuntimeError('Buffer rejected post: ' + result.get('message', 'unknown'))
    post = result['post']
    ledger.set(key, {**entry, 'state': post['status'], 'post_id': post['id'],
                     'external_link': post.get('externalLink')})
    return post


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-run', type=int)
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--retry-rejected', action='store_true')
    args = parser.parse_args()
    if args.reconcile:
        reconcile()
        return
    if not args.source_run:
        parser.error('--source-run is required for validation or publication')
    run = github('/actions/runs/' + str(args.source_run))
    records = json.loads(Path('data/published_videos.json').read_text(encoding='utf-8'))
    day, record = select_record(run, records, datetime.now(timezone.utc))
    verify_youtube(record)
    available = graphql('{channels(input:{organizationId:' + json.dumps(ORG) + '}){id name service}}')['channels']
    for service, channel in CHANNELS.items():
        if not any(c['id'] == channel and c['service'] == service and c['name'] == ('collespo' if service == 'tiktok' else 'collespo_jp') for c in available):
            raise ValueError('Owned channel is missing: ' + service)
    artifacts = github('/actions/runs/' + str(args.source_run) + '/artifacts')['artifacts']
    selected = [a for a in artifacts if a['name'] == 'collespo-video' and not a['expired']]
    if len(selected) != 1 or selected[0]['size_in_bytes'] > MAX_BYTES:
        raise ValueError('Expected one unexpired source video artifact')
    artifact = github('/actions/artifacts/' + str(selected[0]['id']) + '/zip', raw=True)
    output = Path('build/buffer'); output.mkdir(parents=True, exist_ok=True)
    video = output / 'collespo_short.mp4'
    digest = extract_video(artifact, video)
    duration = verify_media(video)
    texts = {service: caption(service, day, record) for service in CHANNELS}
    print(json.dumps({'edition': day, 'source_run': args.source_run, 'video_id': record['video_id'],
                      'duration': duration, 'sha256': digest, 'captions': texts}, ensure_ascii=False))
    if not args.publish:
        print('Validation only: no releases, reservations or posts created')
        return
    ledger = Ledger()
    url = host_video(run, day, video, digest)
    failed = False
    for service in CHANNELS:
        key = day + ':daily:' + service
        try:
            post = submit_once(ledger, key, create_payload(service, texts[service], url),
                {'source_run': args.source_run, 'youtube_id': record['video_id'], 'sha256': digest,
                 'media_url': url, 'checked_at': datetime.now(timezone.utc).isoformat()}, args.retry_rejected)
            print(service, json.dumps(post, ensure_ascii=False))
        except Exception as exc:
            print(service, 'Delivery did not complete:', type(exc).__name__, str(exc)[:300])
            failed = True
    # Give platforms time to process the uploaded video. This is a runner, not an interactive wait.
    for _ in range(12):
        pending = False
        for service, channel in CHANNELS.items():
            key = day + ':daily:' + service
            entry = ledger.data['deliveries'].get(key, {})
            if not entry.get('post_id'):
                continue
            post = next((p for p in recent_posts(channel) if p['id'] == entry['post_id']), None)
            if post:
                if entry.get('state') != post['status'] or entry.get('external_link') != post.get('externalLink'):
                    ledger.set(key, {**entry, 'state': post['status'], 'external_link': post.get('externalLink'),
                                     'checked_at': datetime.now(timezone.utc).isoformat()})
                print(service, post['status'], post.get('externalLink'))
                pending |= post['status'] not in ('sent', 'error')
        if not pending:
            break
        time.sleep(30)
    statuses = {s: ledger.data['deliveries'].get(day + ':daily:' + s, {}).get('state') for s in CHANNELS}
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as report:
            report.write('## Bufferへの動画配信\n\n' + day + ' / YouTube: https://youtu.be/' + record['video_id'] + '\n\n')
            for service in CHANNELS:
                row = ledger.data['deliveries'].get(day + ':daily:' + service, {})
                report.write(f'- {service}: {row.get("state", "未投入")} {row.get("external_link") or ""}\n')
            report.write('\n`sent`はBufferの配信結果です。公開範囲と画面・音声は各SNSでも確認してください。未確定の再実行では二重投稿しません。\n')
    if failed or any(s != 'sent' for s in statuses.values()):
        raise SystemExit('Some deliveries are unconfirmed: ' + json.dumps(statuses))


if __name__ == '__main__':
    main()
