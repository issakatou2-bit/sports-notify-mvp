"""Repair one owned current-edition PS post in place, without reposting."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

from post_bluesky import post_context
from public_short import JST, edition_metadata, public_short

SERVICE = 'https://bsky.social/xrpc/'


def api(method, payload, token=None, write=False):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(
        SERVICE + method + ('' if write else '?' + urllib.parse.urlencode(payload)),
        data=json.dumps(payload).encode() if write else None, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def replacement(old, short, edition):
    body, tags, site = post_context([], short, edition)
    text = body + '\n' + ' '.join('#' + t for t in tags) + '\n' + site + '\n今回のショート動画'
    if len(text) > 280:
        raise ValueError('Caption exceeds safe length')
    facets = []
    for label, feature in [(site, {'$type': 'app.bsky.richtext.facet#link', 'uri': site}),
                           ('今回のショート動画', {'$type': 'app.bsky.richtext.facet#link', 'uri': short['url']})]:
        offset = text.index(label)
        facets.append({'index': {'byteStart': len(text[:offset].encode()),
                                 'byteEnd': len(text[:offset + len(label)].encode())},
                       'features': [feature]})
    for tag in tags:
        label = '#' + tag
        offset = text.index(label)
        facets.append({'index': {'byteStart': len(text[:offset].encode()),
                                 'byteEnd': len(text[:offset + len(label)].encode())},
                       'features': [{'$type': 'app.bsky.richtext.facet#tag', 'tag': tag}]})
    updated = dict(old)
    updated.update(text=text, facets=facets, langs=['ja'], embed={
        '$type': 'app.bsky.embed.external', 'external': {
            'uri': short['url'], 'title': short['title'],
            'description': 'コレスポのPS全試合予告。'}})
    return updated


def repair(uri, video_id, kind='daily', now=None):
    now = now or datetime.now(timezone.utc)
    parts = re.fullmatch(r'at://([^/]+)/app\.bsky\.feed\.post/([A-Za-z0-9]+)', uri)
    if not parts:
        raise ValueError('Exact post URI required')
    edition = edition_metadata(kind, now=now)
    if not edition or not edition.get('program_version') or edition['video_id'] != video_id:
        raise ValueError('Target must match the current due PS edition')
    short = public_short(kind, now=now)
    if not short or short['video_id'] != video_id:
        raise ValueError('Matching public video not confirmed')
    session = api('com.atproto.server.createSession', {
        'identifier': os.environ['BLUESKY_HANDLE'],
        'password': os.environ['BLUESKY_APP_PASSWORD']}, write=True)
    if session['did'] != parts[1]:
        raise ValueError('Post belongs to another account')
    target = dict(repo=session['did'], collection='app.bsky.feed.post', rkey=parts[2])
    found = api('com.atproto.repo.getRecord', target, session['accessJwt'])
    if found['uri'] != uri or found['value'].get('$type') != 'app.bsky.feed.post':
        raise ValueError('Exact existing post not confirmed')
    old = found['value']
    if datetime.fromisoformat(old['createdAt'].replace('Z', '+00:00')).astimezone(JST).date() != now.astimezone(JST).date():
        raise ValueError('Post edition date does not match')
    updated = replacement(old, short, edition)
    if updated != old:
        result = api('com.atproto.repo.putRecord', dict(
            **target, record=updated, swapRecord=found['cid'], validate=True),
            session['accessJwt'], write=True)
        if result['uri'] != uri:
            raise ValueError('Update returned a different record')
    after = api('com.atproto.repo.getRecord', target, session['accessJwt'])
    if after['uri'] != uri or after['value'] != updated:
        raise ValueError('Updated content not confirmed')
    return dict(uri=uri, video_id=video_id, createdAt=old['createdAt'], verified=True)


if __name__ == '__main__':
    try:
        uri, video_id = os.environ.get('TARGET_POST'), os.environ.get('TARGET_VIDEO')
        if not uri and not video_id:
            day = datetime.now(JST).date().isoformat()
            row = json.loads(Path('data/bluesky_delivery.json').read_text(encoding='utf-8'))['editions'].get('daily:' + day)
            if not row or row['state'] == 'linked':
                print('[info] 補完が必要な当日PS投稿はありません')
                raise SystemExit(0)
            uri, video_id = row['uri'], row['video_id']
        print(json.dumps(repair(uri, video_id), ensure_ascii=False))
    except Exception as error:
        # URLs/authentication exceptions may contain secrets; expose type only.
        raise SystemExit('Bluesky同一投稿の補正を停止: ' + type(error).__name__)
