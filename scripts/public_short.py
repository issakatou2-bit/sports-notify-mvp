"""Resolve today's matching Short only after YouTube confirms public access."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

CHANNEL = 'UCpZ_j8X8uOex5VvKwwTJj3Q'
JST = timezone(timedelta(hours=9))


def candidate(records, kind, now):
    if kind not in ('daily', 'daily_soccer'):
        return None
    day = now.astimezone(JST).date().isoformat()
    row = records.get(kind, {}).get(day)
    if not row or not re.fullmatch(r'[A-Za-z0-9_-]{11}', row.get('video_id', '')):
        return None
    try:
        uploaded = datetime.fromisoformat(row['published_at'].replace('Z', '+00:00'))
        published = datetime.fromisoformat((row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
        if uploaded.tzinfo is None or published.tzinfo is None:
            return None
        if uploaded.astimezone(JST).date().isoformat() != day or uploaded > now or published > now:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return row


def public_short(kind, path='data/published_videos.json', now=None):
    now = now or datetime.now(timezone.utc)
    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        return None
    try:
        row = candidate(json.loads(Path(path).read_text(encoding='utf-8')), kind, now)
        if not row:
            return None
        query = urllib.parse.urlencode({'part': 'status,snippet', 'id': row['video_id'], 'key': key})
        with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/videos?' + query, timeout=12) as response:
            items = json.load(response).get('items', [])
        if not items:
            return None
        video = items[0]
        if video['status'].get('privacyStatus') != 'public' or not video['status'].get('embeddable'):
            return None
        if video['snippet']['channelId'] != CHANNEL:
            return None
        return {'video_id': row['video_id'], 'url': 'https://www.youtube.com/watch?v=' + row['video_id'],
                'title': video['snippet']['title']}
    except Exception:
        # URLs in network exceptions can contain the API key. Do not print them.
        return None
