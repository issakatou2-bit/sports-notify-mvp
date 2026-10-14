"""Redditの少量受け口。承認のないライブ取得はしない。失敗は他の経路へ伝播させない。"""
from datetime import datetime, timedelta, timezone
import os
import time
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


def collect(threads, player_en, game_at, *, now=None, get=None, sleep=time.sleep, approved=False):
    now=now or datetime.now(timezone.utc)
    if os.environ.get('COLLESPO_REDDIT')=='off': return dict(state='off',voices=[])
    if not hub.enabled(): return dict(state='hub_off',voices=[])
    if not approved or not os.environ.get('REDDIT_OAUTH_TOKEN'):
        return dict(state='approval_required',voices=[],reason='未承認のライブAPI取得を実行しません')
    if abs(now-hub.story.stamp(game_at))>timedelta(hours=WINDOW_HOURS):
        return dict(state='outside_game_window',voices=[])
    if get is None:
        import requests
        get=requests.get
    rows=[]; failures=[]
    for i, url in enumerate(threads[:MAX_THREADS]):
        if i: sleep(INTERVAL)
        try:
            u=urlsplit(url)
            if u.scheme!='https' or u.hostname not in ('www.reddit.com','reddit.com') or '/comments/' not in u.path:
                raise ValueError('スレッドURLが不正')
            response=get('https://oauth.reddit.com'+u.path.rstrip('/')+'.json',
                         params=dict(limit=MAX_COMMENTS,sort='top',depth=1),
                         headers={'Authorization':'Bearer '+os.environ['REDDIT_OAUTH_TOKEN'], 'User-Agent':'collespo-topic-hub/1.0'},timeout=20)
            response.raise_for_status()
            rows+=saved(response.json(),url,player_en,now.isoformat())['voices']
        except Exception as exc:  # 403/429/削除/接続不可。回避や連続再試行をしない。
            failures.append(type(exc).__name__)
    return dict(state='partial' if failures and rows else 'failed' if failures else 'ready',
                voices=rows,failures=failures,updated_at=now.isoformat())
