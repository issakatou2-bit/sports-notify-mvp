"""Resolve today's matching Short only after YouTube confirms public access."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
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
        print('[info] Short link: API key unavailable; use channel link')
        return None
    try:
        row = candidate(json.loads(Path(path).read_text(encoding='utf-8')), kind, now)
        if not row:
            print('[info] Short link: no eligible current-edition record; use channel link')
            return None
        query = urllib.parse.urlencode({'part': 'status,snippet', 'id': row['video_id'], 'key': key})
        # The daily post runs at the scheduled release instant. YouTube may
        # still report the pre-release state. Retry only within this short
        # transition window; never use a stale or unconfirmed video as fallback.
        scheduled = row.get('publish_at')
        recent_release = scheduled and 0 <= (now - datetime.fromisoformat(
            scheduled.replace('Z', '+00:00'))).total_seconds() <= 120
        attempts = 3 if recent_release else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/videos?' + query, timeout=8) as response:
                    items = json.load(response).get('items', [])
                video = items[0] if items else None
                if video:
                    if video['id'] != row['video_id'] or video['snippet']['channelId'] != CHANNEL:
                        print('[info] Short link: video/channel mismatch; use channel link')
                        return None
                    if video['status'].get('privacyStatus') == 'public' and video['status'].get('embeddable'):
                        return {'video_id': row['video_id'], 'url': 'https://www.youtube.com/watch?v=' + row['video_id'],
                                'title': video['snippet']['title']}
                reason = 'public embeddable video not yet confirmed'
            except Exception:
                # Network exceptions may include the key-bearing URL.
                reason = 'verification request failed'
            print(f'[info] Short link: {reason} ({attempt + 1}/{attempts})')
            if attempt + 1 < attempts:
                time.sleep(5)
        print('[info] Short link: confirmation unavailable; use channel link')
        return None
    except Exception:
        # URLs in network exceptions can contain the API key. Do not print them.
        print('[info] Short link: invalid record or verification data; use channel link')
        return None
