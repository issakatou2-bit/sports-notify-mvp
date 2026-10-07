"""公開済みv3資産動画のSNS入口。既定は検証のみ、公開は切替後だけ。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import io
import zipfile

import requests
import buffer_daily as bd
import generated_topics as gt

WORKFLOWS = {'season_review.yml': 'season-review', 'ps_game_now.yml': 'ps-game-now'}
TOPIC = re.compile(r'season_(?:momentum|game|odds)_[A-Za-z0-9_]+\Z')


def select(run, assets, topics, now):
    """同じmain実行が実際に制作した当日版だけ。過去の在庫は出さない。"""
    wf = run.get('path', '').rsplit('/', 1)[-1]
    if (wf not in WORKFLOWS or run.get('head_branch') != 'main'
            or run.get('conclusion') != 'success'
            or run.get('repository', {}).get('full_name') != bd.REPO
            or run.get('event') not in ('schedule', 'workflow_run', 'workflow_dispatch')):
        raise ValueError('Require an owned successful main production run')
    start, end = bd.instant(run['created_at']), bd.instant(run['updated_at'])
    day = start.astimezone(bd.JST).date().isoformat()
    if day != now.astimezone(bd.JST).date().isoformat():
        return []
    rows = []
    for topic, record in sorted(assets.items()):
        if not TOPIC.fullmatch(topic) or topics.get(topic, {}).get('style') != 'v3':
            continue
        stamp = bd.instant(record['published_at'])
        if not start <= stamp <= end or stamp > now:
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', record.get('video_id', '')):
            raise ValueError('Malformed YouTube ID for ' + topic)
        if record.get('privacy') != 'public':
            continue
        rows.append((day, topic, record, WORKFLOWS[wf]))
    return rows


def register(topic, artifact, run):
    if not TOPIC.fullmatch(topic):
        raise ValueError('Invalid asset topic')
    kind = 'asset_' + topic
    filename = 'collespo_asset_' + topic + '.mp4'
    bd.SOURCES[kind] = (topic, artifact, filename, run['path'].rsplit('/', 1)[-1])
    bd.KIND_WORDS[kind] = dict(short='PSの話題', long='PSの話題',
                              lead='試合とシリーズの状況を公式の数字で紹介します',
                              cut='\x00', sport='mlb')
    return kind, filename


def bsky_record(text, title, video_id, now):
    if len(text) > 300:
        raise ValueError('Bluesky caption is longer than 300 characters')
    url = 'https://www.youtube.com/watch?v=' + video_id
    facets = []
    for match in re.finditer(r'https?://[^\s]+', text):
        facets.append({'index': {'byteStart': len(text[:match.start()].encode()),
                                  'byteEnd': len(text[:match.end()].encode())},
                       'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': match[0]}]})
    return {'$type': 'app.bsky.feed.post', 'text': text, 'facets': facets,
            'createdAt': now.isoformat().replace('+00:00', 'Z'),
            'embed': {'$type': 'app.bsky.embed.external', 'external': {
                'uri': url, 'title': title, 'description': 'コレスポのPSの話題です。'}}}


def bsky_once(ledger, key, record, metadata, http=requests):
    """予約・確定rkey・新規のみのCAS。応答不明でも別の投稿を作らない。"""
    old = ledger.data['deliveries'].get(key)
    if old and old.get('state') == 'sent':
        return old
    handle = os.environ.get('BLUESKY_HANDLE', '')
    password = os.environ.get('BLUESKY_APP_PASSWORD', '')
    if handle != 'collespo.bsky.social' or not password:
        raise RuntimeError('Collespo Bluesky credentials are required')
    endpoint = 'https://bsky.social/xrpc/'
    auth = http.post(endpoint + 'com.atproto.server.createSession',
                     json={'identifier': handle, 'password': password}, timeout=30)
    auth.raise_for_status()
    session = auth.json()
    if session.get('handle') != handle:
        raise RuntimeError('Unexpected Bluesky account')
    rkey = 'collespo-' + hashlib.sha256(key.encode()).hexdigest()[:32]
    query = {'repo': session['did'], 'collection': 'app.bsky.feed.post', 'rkey': rkey}
    headers = {'Authorization': 'Bearer ' + session['accessJwt']}
    existing = http.get(endpoint + 'com.atproto.repo.getRecord', params=query,
                        headers=headers, timeout=30)
    if existing.status_code == 200:
        found = existing.json()
        if found['value'].get('text') != record['text'] or found['value'].get('embed') != record['embed']:
            raise RuntimeError('Existing deterministic Bluesky post differs')
        receipt = dict(metadata, state='sent', uri=found['uri'], rkey=rkey)
        ledger.set(key, receipt)
        return receipt
    if existing.status_code != 400 or existing.json().get('error') != 'RecordNotFound':
        existing.raise_for_status()
        raise RuntimeError('Cannot establish absence of Bluesky post')
    if old:
        raise RuntimeError('Uncertain Bluesky reservation needs inspection; no automatic resend')
    ledger.set(key, dict(metadata, state='reserved', rkey=rkey, text=record['text'],
                         reserved_at=datetime.now(timezone.utc).isoformat()))
    result = http.post(endpoint + 'com.atproto.repo.putRecord',
                       json=dict(query, record=record, validate=True, swapRecord=None),
                       headers=headers, timeout=30)
    result.raise_for_status()
    response = result.json()
    receipt = dict(metadata, state='sent', uri=response['uri'], rkey=rkey)
    ledger.set(key, receipt)
    return receipt


def artifacts_of(run):
    available = bd.github('/actions/runs/' + str(run['id']) + '/artifacts')['artifacts']
    name = WORKFLOWS[run['path'].rsplit('/', 1)[-1]]
    selected = [a for a in available if a['name'] == name and not a['expired']]
    if len(selected) != 1 or selected[0]['size_in_bytes'] > bd.MAX_BYTES:
        raise ValueError('Require one unexpired owned video artifact')
    return bd.github('/actions/artifacts/' + str(selected[0]['id']) + '/zip', raw=True)


def write_receipts(directory):
    """制作時点の版と画素を結び付け、後日JSONがv3になっても旧版を配らない。"""
    topics = gt.all_topics(refresh=True)
    for video in Path(directory).glob('collespo_asset_*.mp4'):
        topic = video.stem.removeprefix('collespo_asset_')
        if TOPIC.fullmatch(topic) and topics.get(topic, {}).get('style') == 'v3':
            receipt = dict(topic=topic, style='v3', sha256=hashlib.sha256(video.read_bytes()).hexdigest())
            video.with_suffix('.sns.json').write_text(json.dumps(receipt), encoding='utf-8')


def verify_receipt(archive, filename, topic, digest):
    wanted = filename.removesuffix('.mp4') + '.sns.json'
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        entries = [e for e in zipped.infolist() if e.filename.rsplit('/', 1)[-1] == wanted]
        if not entries:
            return False  # No provenance on old artifacts; do not backfill them.
        if len(entries) != 1 or entries[0].file_size > 4096:
            raise ValueError('Invalid rendering receipt')
        receipt = json.loads(zipped.read(entries[0]))
    if receipt != dict(topic=topic, style='v3', sha256=digest):
        raise ValueError('Rendering receipt differs from the source media')
    return True


def distribute(run, rows, publish=False):
    if not rows:
        print('[info] この実行に当日公開のv3資産動画はありません')
        return
    if publish and os.environ.get('V3_SNS_ENABLED') != 'true':
        raise RuntimeError('V3_SNS_ENABLED must be enabled after review')
    services = bd.selected_services(os.environ.get('BUFFER_CHANNELS'))
    ledger = bd.Ledger() if publish else None
    archive = None
    failed = []
    for day, topic, record, artifact in rows:
        kind, filename = register(topic, artifact, run)
        try:
            keys = {s: day + ':' + kind + ':' + s for s in (*services, 'bluesky')}
            if publish and all(ledger.data['deliveries'].get(k, {}).get('state') == 'sent'
                               for k in keys.values()):
                continue
            try:
                snippet = bd.verify_youtube(record)
            except ValueError as exc:
                if str(exc) == 'YouTube video is not public':
                    print('[info] まだ公開されていません（次の補完で再確認）: ' + topic)
                    continue
                raise
            verified = dict(record, title=snippet['title'], description=snippet.get('description', ''))
            if archive is None:
                archive = artifacts_of(run)
            out = Path('build/asset-sns'); out.mkdir(parents=True, exist_ok=True)
            video = out / filename
            digest = bd.extract_video(archive, video, filename)
            if not verify_receipt(archive, filename, topic, digest):
                print('[info] 制作時のv3証明が無い旧成果物は配信しません: ' + topic)
                continue
            duration = bd.verify_media(video)
            texts = {s: bd.caption(s, day, verified, kind) for s in services}
            texts = {s: text.replace('音声：VOICEVOX:ずんだもん / VOICEVOX:四国めたん',
                                     '音声：VOICEVOX:四国めたん') for s, text in texts.items()}
            # Bluesky uses the compact published title and an external video card.
            btext = bd.caption('twitter', day, verified, kind)
            bpost = bsky_record(btext, verified['title'], record['video_id'], datetime.now(timezone.utc))
            print(json.dumps(dict(topic=topic, video_id=record['video_id'], duration=duration,
                                  sha256=digest, captions=texts, bluesky=bpost), ensure_ascii=False))
            if not publish:
                continue
            channels = bd.graphql('{channels(input:{organizationId:' + json.dumps(bd.ORG)
                                  + '}){id name service}}')['channels']
            for s in services:
                if not any(c['id'] == bd.CHANNELS[s] and c['service'] == s and
                           c['name'] == ('collespo' if s == 'tiktok' else 'collespo_jp') for c in channels):
                    raise ValueError('Owned channel missing: ' + s)
            url = bd.host_video(run, day, video, digest, kind)
            metadata = dict(source_run=run['id'], youtube_id=record['video_id'], sha256=digest,
                            media_url=url, checked_at=datetime.now(timezone.utc).isoformat())
            for s in services:
                try:
                    post = bd.submit_once(ledger, keys[s], bd.create_payload(s, texts[s], url), metadata)
                    print(s, post['status'], post.get('externalLink'))
                except Exception as exc:
                    print('[error] ' + s + ': ' + type(exc).__name__)
                    failed.append(topic + ':' + s)
            try:
                bsky_once(ledger, keys['bluesky'], bpost, metadata)
            except Exception as exc:
                print('[error] bluesky: ' + type(exc).__name__)
                failed.append(topic + ':bluesky')
        except Exception as exc:
            print('[error] ' + topic + ': ' + type(exc).__name__ + ' ' + str(exc)[:120])
            failed.append(topic)
    if failed:
        raise RuntimeError('Asset SNS delivery needs inspection: ' + ', '.join(failed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=int)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--receipt-dir', help='制作時点の版を動画に結び付ける（投稿なし）')
    args = parser.parse_args()
    if args.receipt_dir:
        write_receipts(args.receipt_dir)
        return
    now = datetime.now(timezone.utc)
    assets = json.loads(Path('data/published_assets.json').read_text(encoding='utf-8'))['assets']
    topics = gt.all_topics(refresh=True)
    if args.source_run:
        runs = [bd.github('/actions/runs/' + str(args.source_run))]
    else:
        runs = []
        for workflow in WORKFLOWS:
            runs.extend(bd.github('/actions/workflows/' + workflow +
                                  '/runs?branch=main&status=success&per_page=10')['workflow_runs'])
    for run in sorted(runs, key=lambda r: r['created_at']):
        distribute(run, select(run, assets, topics, now), args.publish)


if __name__ == '__main__':
    main()
