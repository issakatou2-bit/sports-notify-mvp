"""旧API取得は停止。保存JSONの互換受け口だけを残し、ライブ取得はreddit_rssへ。"""
from datetime import datetime, timezone
import os
from urllib.parse import urlsplit

import topic_hub as hub

MAX_THREADS=2
MAX_COMMENTS=3
INTERVAL=10
WINDOW_HOURS=4


def saved(payload, thread_url, player_en, collected_at):
    u=urlsplit(thread_url)
    if u.scheme!='https' or u.hostname not in ('www.reddit.com','reddit.com') or '/comments/' not in u.path:
        raise ValueError('元のRedditスレッドURLが必要です')
    if os.environ.get('COLLESPO_REDDIT')=='off': return dict(state='off',voices=[])
    children=payload[1].get('data',{}).get('children',[]) if isinstance(payload,list) and len(payload)>1 else []
    rows=[]
    for item in sorted(children,key=lambda i:i.get('data',{}).get('score',0),reverse=True):
        r=item.get('data') or {}; body=r.get('body') or ''
        if item.get('kind')!='t1' or r.get('stickied') or body in ('[deleted]','[removed]') or not 8<=len(body)<=100 or 'u/' in body or '@' in body: continue
        # 生の投稿者名/IDを保存しない。訳は既存の訳工程へ渡すため原文も保持する。
        at=datetime.fromtimestamp(r.get('created_utc',0),timezone.utc).isoformat()
        rows.append(dict(original=body, title=body, jp_players=[player_en], url=thread_url,
                         source='Redditの試合スレッド', at=at, fetched_at=collected_at,
                         score=r.get('score',0), translation_note=hub.FAN_NOTE))
        if len(rows)>=MAX_COMMENTS: break
    return dict(state='ready',updated_at=collected_at,voices=rows)


def collect(threads, player_en, game_at, **kwargs):
    return dict(state='off' if os.environ.get('COLLESPO_REDDIT')=='off' else 'rss_only', voices=[], reason='旧API経路は通信しません。公開RSSのみ使います')
