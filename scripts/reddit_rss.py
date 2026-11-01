"""公開RSSだけの少量取得。ログイン・OAuth・JSON API・投稿・制限回避は使わない。"""
import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import topic_hub as hub

NS={'a':'http://www.w3.org/2005/Atom'}
MAX_CALLS_PER_HOUR=3
INTERVAL=10
MAX_BYTES=512_000
MAX_COMMENTS=3
MAX_THREADS=2
JST=timezone(timedelta(hours=9))
BOARDS={'119':'Dodgers','158':'Brewers','139':'tampabayrays','114':'ClevelandGuardians','147':'NYYankees',
        '136':'Mariners','112':'CHICubs','135':'Padres','121':'NewYorkMets','111':'redsox'}


class Content(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.skip=0;self.score=None;self.score_depth=0;self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a':
            author=bool(re.search(r'/(?:u|user)/',attrs.get('href','')))
            self.links.append(author)
            if author:self.skip+=1
        if tag=='blockquote':self.skip+=1
        if tag=='span' and 'score' in attrs.get('class','').split():
            self.score_depth=1
            raw=attrs.get('data-score')
            if raw and re.fullmatch(r'-?\d+',raw):self.score=int(raw)
        if tag in ('p','div','br'):self.parts.append(' ')
    def handle_endtag(self,tag):
        if tag=='a' and self.links:
            if self.links.pop():self.skip-=1
        if tag=='blockquote' and self.skip:self.skip-=1
        if tag=='span':self.score_depth=0
    def handle_data(self,data):
        if self.score_depth:
            m=re.fullmatch(r'\s*(-?\d+)\s+(?:points?|votes?)\s*',data)
            if m:self.score=int(m[1])
            return
        if not self.skip:self.parts.append(data)
    def text(self):
        text=' '.join(''.join(self.parts).split())
        text=re.split(r'(?:submitted by|\[link\]|\[comments\]|\[permalink\])',text,maxsplit=1,flags=re.I)[0].strip()
        return text


def entries(raw):
    if len(raw.encode('utf8'))>MAX_BYTES:raise ValueError('RSSが上限を超えました')
    return ET.fromstring(raw).findall('a:entry',NS)


def rss_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in ('reddit.com','www.reddit.com') or u.username or u.password:
        raise ValueError('公開Reddit HTTPS RSSのみ')
    if not re.fullmatch(r'/r/[A-Za-z0-9_]+/(?:search\.rss|comments/[A-Za-z0-9]+(?:/[A-Za-z0-9_/-]+)?/\.rss)',u.path):
        raise ValueError('検索RSSまたはスレッドRSSのみ')
    return urlunsplit(('https','www.reddit.com',u.path,u.query,''))


def thread_link(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in ('reddit.com','www.reddit.com'):
        raise ValueError('元スレッドが不正')
    m=re.match(r'^(/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+)(?:/|$)',u.path)
    if not m:raise ValueError('元スレッドが不正')
    return 'https://www.reddit.com'+m[1]+'/'


def parse_comments(raw, source_url, now, team_id=None):
    result=[]
    for entry in entries(raw):
        identity=entry.findtext('a:id','',NS)
        # t3はスレッド本文。コメントt1だけ。authorは一切保存しない。
        if not identity.startswith('t1_'):continue
        content=Content();content.feed(entry.findtext('a:content','',NS))
        text=content.text()
        if not 8<=len(text)<=140 or text in ('[deleted]','[removed]') or re.search(r'(?:/u/|u/|@)',text):continue
        at=hub.utc(entry.findtext('a:updated','',NS) or entry.findtext('a:published','',NS))
        if not at or not timedelta(0)<=now-hub.story.stamp(at)<=timedelta(hours=24):continue
        named=[p['name_en'] for p in hub.PLAYERS if p['name_en'] in text or p['name_jp'] in text or
               (p['sport']=='MLB' and re.search(r'\b'+re.escape(p['name_en'].split()[-1])+r'\b',text,re.I))]
        result.append(dict(original=text,title=text,url=thread_link(source_url),at=at,fetched_at=now.isoformat(),
                           source='Redditの試合スレッド',jp_players=named,community_team_id=team_id,
                           score=content.score,score_verified=content.score is not None,
                           order_basis='RSSのtop順を要求（実際の評価順は未確認）',translation_note=hub.FAN_NOTE))
    # 数字が実際に載る場合のみ並べる。無ければRSSの掲載順を保ち、順位とは呼ばない。
    if result and all(r['score_verified'] for r in result):result.sort(key=lambda r:r['score'],reverse=True)
    return result[:MAX_COMMENTS]


def discover(raw, board, match_terms, game_number=None):
    found=[]
    for entry in entries(raw):
        title=entry.findtext('a:title','',NS)
        if not re.search(r'(?:game|post.?game|match|post.?match).*thread',title,re.I):continue
        if match_terms and not all(re.search(re.escape(t),title,re.I) for t in match_terms):continue
        number=re.search(r'Game\s+(\d+)',title,re.I)
        if number and game_number and number[1]!=str(game_number):continue
        link=entry.find('a:link',NS)
        if link is None:continue
        try:url=thread_link(link.get('href',''))
        except ValueError:continue
        if urlsplit(url).path.split('/')[2].casefold()!=board.casefold():continue
        if url not in found:found.append(url)
    return found[:MAX_THREADS]


class Budget:
    def __init__(self,path,now,sleep=time.sleep,clock=None):
        self.path=Path(path);self.now=now;self.sleep=sleep;self.clock=clock or (lambda:now)
        self.state=hub.load(path) or {'calls':[]}
        if self.state.get('_input_state')=='failed':raise ValueError('回数記録が壊れています。制限をリセットして取得しません')
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps(self.state,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def permit(self):
        self.now=max(self.now,self.clock())
        if any(hub.story.stamp(at)>self.now for at in self.state.get('calls',[])):return 'clock_moved_backwards'
        if self.state.get('blocked_jst_date')==self.now.astimezone(JST).date().isoformat():return 'stopped_429'
        calls=[hub.story.stamp(at) for at in self.state.get('calls',[]) if timedelta(0)<=self.now-hub.story.stamp(at)<timedelta(hours=1)]
        if len(calls)>=MAX_CALLS_PER_HOUR:return 'hourly_limit'
        if calls:
            gap=(self.now-max(calls)).total_seconds()
            if gap<INTERVAL:
                self.sleep(INTERVAL-gap);self.now=max(self.now+timedelta(seconds=INTERVAL-gap),self.clock())
        self.state['calls']=[d.isoformat() for d in calls]+[self.now.isoformat()]
        self.save();return None
    def stop_429(self):
        self.state['blocked_jst_date']=self.now.astimezone(JST).date().isoformat();self.save()


def collect(config,state_path,*,now=None,get=None,sleep=time.sleep):
    clock=(lambda:datetime.now(timezone.utc)) if now is None else (lambda:now)
    now=now or datetime.now(timezone.utc)
    if os.environ.get('COLLESPO_REDDIT')!='on':return dict(state='disabled',voices=[])
    # 編集側が公式日程から渡す。RSSの更新時刻を試合時刻にしない。
    try:game_at=hub.story.stamp(config['game_at'])
    except (KeyError,ValueError,TypeError):return dict(state='missing_game_time',voices=[])
    if not -timedelta(hours=2)<=now-game_at<=timedelta(hours=6):return dict(state='outside_game_window',voices=[])
    try:budget=Budget(state_path,now,sleep,clock)
    except ValueError as exc:return dict(state='failed',reason=str(exc),voices=[])
    if get is None:
        import requests
        client=requests.Session();client.trust_env=False  # .netrc等の暗黙の認証を使わない。
        get=client.get
    outputs=[];errors=[]
    def fetch(url):
        url=rss_url(url)
        limit=budget.permit()
        if limit:raise RuntimeError(limit)
        response=get(url,headers={'User-Agent':'collespo-public-rss/1.0 (+https://collespo.com)'},timeout=20,allow_redirects=False,stream=True)
        try:
            if response.status_code==429:budget.stop_429();raise RuntimeError('stopped_429')
            if response.status_code!=200:raise RuntimeError('HTTP '+str(response.status_code))
            data=bytearray()
            for chunk in response.iter_content(8192):
                data.extend(chunk)
                if len(data)>MAX_BYTES:raise ValueError('RSS上限超過')
            # 再検証用の保存材料。取得失敗/候補なしも後から再現できる。
            cache=Path(state_path).parent/'rss-cache';cache.mkdir(parents=True,exist_ok=True)
            (cache/(hub.digest(url)+'.xml')).write_bytes(data)
            return data.decode('utf8')
        finally:response.close()
    try:
        threads=config.get('threads') or []
        if not threads:
            board=config['board']
            if not re.fullmatch(r'[A-Za-z0-9_]+',board):raise ValueError('板の名前が不正')
            query=' '.join(config.get('match_terms') or [])+' game thread'
            url='https://www.reddit.com/r/'+board+'/search.rss?'+urlencode(dict(q=query,restrict_sr='on',sort='top',t='day',limit=5))
            threads=discover(fetch(url),board,config.get('match_terms') or [],config.get('game_number'))
        for thread in threads[:MAX_THREADS]:
            raw=fetch(thread_link(thread)+'.rss?sort=top&limit=10')
            outputs+=parse_comments(raw,thread,budget.now,config.get('team_id'))
    except Exception as exc:
        errors.append(str(exc) if isinstance(exc,(RuntimeError,ValueError)) else type(exc).__name__)
    state='partial' if errors and outputs else errors[0] if errors else 'ready'
    for row in outputs:row['game_date']=config.get('game_date') or game_at.astimezone(JST).date().isoformat()
    return dict(state=state,voices=outputs[:MAX_COMMENTS],updated_at=now.isoformat(),failures=errors,
                score_note='公開RSSに評価数が無い場合は高評価や順位を断定しません')


def plan(archive, now):
    """保存した日程だけ。公開RSSの更新日時で試合時刻を作らない。クラブ板は明示configでも指定可。"""
    from notability_engine import MLB_TEAM_NAME_EN
    candidates=[]
    for file in sorted(Path(archive).glob('*.json'))[-3:]:
        day=datetime.fromisoformat(file.stem)
        for g in hub.load(file).get('games') or []:
            if g.get('league')!='MLB' or not g.get('start_time_jst'):continue
            try:
                at=datetime.strptime(str(day.year)+'/'+g['start_time_jst'],'%Y/%m/%d %H:%M').replace(tzinfo=JST).astimezone(timezone.utc)
                home,away=str(g['home_team_id']),str(g['away_team_id'])
                if not -timedelta(hours=2)<=now-at<=timedelta(hours=6):continue
                opponent=home if g.get('away_has_jp') and not g.get('home_has_jp') else away if g.get('home_has_jp') and not g.get('away_has_jp') else home
                board=BOARDS.get(opponent,'baseball')
                names=[MLB_TEAM_NAME_EN[away].split()[-1],MLB_TEAM_NAME_EN[home].split()[-1]]
                terms=[MLB_TEAM_NAME_EN[away if opponent==home else home].split()[-1]] if board!='baseball' else names
                candidates.append(dict(game_at=at.isoformat(),game_date=at.astimezone(JST).date().isoformat(),board=board,match_terms=terms,team_id=opponent if board!='baseball' else None,
                                       game_source=str(file),matchup=g.get('matchup'),game_id=g.get('game_id')))
            except (ValueError,KeyError):continue
    return min(candidates,key=lambda c:abs(now-hub.story.stamp(c['game_at']))) if candidates else {}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config')
    ap.add_argument('--archive',default='archive')
    ap.add_argument('--state',default='data/reddit_rss_state.json')
    ap.add_argument('--out',default='data/reddit_voices.json')
    args=ap.parse_args()
    lock=Path(args.state+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:result=dict(state='collector_locked',voices=[])
    else:
        os.close(fd)
        try:result=collect(hub.load(args.config) if args.config else plan(args.archive,datetime.now(timezone.utc)),args.state)
        finally:lock.unlink(missing_ok=True)
    p=Path(args.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(state=result['state'],comments=len(result['voices'])),ensure_ascii=False))


if __name__=='__main__':main()
