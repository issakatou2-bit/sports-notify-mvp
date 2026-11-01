"""Optional score-only second opinion. Never edits or rejects primary results."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://www.thesportsdb.com/api/v1/json/123/eventsday.php'
LEAGUES = {'PL':'4328','PD':'4335','BL1':'4331','SA':'4332','FL1':'4334'}
# Only known spellings, never fuzzy-match youth/women/reserve teams.
ALIASES = {'tottenham':'tottenham hotspur','brighton and hove albion':'brighton',
           'psg':'paris saint germain','bayern munich':'bayern munchen'}


def name(value):
    text = unicodedata.normalize('NFKD',str(value or '')).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9]+',' ',text).strip()
    return ALIASES.get(text,text)


def number(value):
    return int(value) if not isinstance(value,bool) and re.fullmatch(r'\d+',str(value)) else None


def group(game):
    league = LEAGUES.get(game.get('league'))
    try:
        start = datetime.fromisoformat(game['start_utc'].replace('Z','+00:00'))
        if start.tzinfo is None: return None
        day = start.astimezone(timezone.utc).date().isoformat()
    except (KeyError,ValueError,TypeError): return None
    return (league,day) if league else None


def compare(game, events):
    key = group(game)
    record = dict(primary_id=game.get('id'),status='not_found')
    if key is None: return dict(record,status='unsupported')
    if not all(name(game.get(s,{}).get('name_en')) for s in ('home','away')):
        return dict(record,status='primary_invalid')
    matched = [e for e in events if str(e.get('idLeague'))==key[0] and e.get('dateEvent')==key[1]
               and name(e.get('strHomeTeam'))==name(game.get('home',{}).get('name_en'))
               and name(e.get('strAwayTeam'))==name(game.get('away',{}).get('name_en'))]
    if len(matched)!=1: return dict(record,status='ambiguous' if matched else 'not_found')
    event = matched[0]
    score = {s:number(event.get('int'+s.title()+'Score')) for s in ('home','away')}
    if None in score.values() or event.get('strStatus') not in ('FT','Match Finished','AET','AP'):
        return dict(record,status='not_final',secondary_id=event.get('idEvent'))
    primary = game.get('score') or {}
    if set(primary)!=set(score) or any(number(primary[s]) is None for s in score):
        return dict(record,status='primary_invalid')
    return dict(record,status='matched' if score==primary else 'mismatch',secondary_id=event.get('idEvent'),
                primary_score=primary,secondary_score=score)


class Fetcher:
    """Max 10 calls, spaced >=2.1s (free limit 30/min); no automatic retry."""
    def __init__(self, cache):
        self.cache = Path(cache); self.count = 0; self.last = None; self.stopped = False

    def get(self, key):
        self.cache.mkdir(parents=True,exist_ok=True)
        path = self.cache/(key[0]+'-'+key[1]+'.json')
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                if 0 <= time.time()-saved['fetched_at'] < 3600:
                    return saved['events'],'cached'
            except (OSError,ValueError,KeyError,TypeError): pass
        if self.stopped: return [],'rate_limited'
        if self.count>=10: return [],'request_cap'
        if self.last is not None: time.sleep(max(0,2.1-(time.monotonic()-self.last)))
        self.last = time.monotonic(); self.count += 1
        url = BASE+'?'+urllib.parse.urlencode({'l':key[0],'d':key[1]})
        try:
            req = urllib.request.Request(url,headers={'User-Agent':'Collespo-score-check/1.0'})
            with urllib.request.urlopen(req,timeout=15) as r: data = json.load(r)
            events = data.get('events') or []
            if not isinstance(events,list) or any(not isinstance(e,dict) for e in events):return [],'invalid_response'
            # No artwork, player/person data or API key is stored.
            fields = ('idEvent','idLeague','dateEvent','strHomeTeam','strAwayTeam','intHomeScore','intAwayScore','strStatus')
            events = [{k:e.get(k) for k in fields} for e in events]
            path.write_text(json.dumps(dict(fetched_at=time.time(),events=events),ensure_ascii=False),encoding='utf-8')
            return events,'fetched'
        except urllib.error.HTTPError as e:
            code = e.code; e.close()
            if code==429:self.stopped = True
            return [],'rate_limited' if code==429 else 'http_'+str(code)
        except Exception as e:  # optional checker must never stop the source pipeline
            return [],'fetch_failed_'+type(e).__name__


def check(data, fetch):
    groups = {}; records = []
    for game in data.get('games') or []:
        key = group(game)
        if key is None:
            records.append(compare(game,[]));continue
        if key not in groups:groups[key] = fetch(key)
        events,status = groups[key]
        record = compare(game,events) if status in ('fetched','cached','fixture') else dict(primary_id=game.get('id'),status=status)
        record['lookup'] = dict(league=key[0],day=key[1],status=status,returned=len(events),free_limit=3)
        records.append(record)
    return dict(source='TheSportsDB',source_url='https://www.thesportsdb.com',checked_at=datetime.now(timezone.utc).isoformat(),
                records=records,mismatches=sum(r['status']=='mismatch' for r in records),requests=len(groups),
                note='無料の日別返却上限3件。未掲載は一致でも不一致でもない。一次結果は変更しない。')


def report(result):
    mismatches = [r for r in result['records'] if r['status']=='mismatch']
    for r in mismatches:
        print('::warning::TheSportsDB score mismatch: '+str(r['primary_id'])+' '+str(r['primary_score'])+' / '+str(r['secondary_score']))
    message = '\n### TheSportsDB スコア照合（通知のみ）\n\n'
    message += f"- 不一致 {len(mismatches)}件 / 照合対象 {len(result['records'])}件。一次結果は変更しません。\n"
    message += '- 出典: [TheSportsDB](https://www.thesportsdb.com)。未掲載・未終了・取得失敗は未照合です。\n'
    for r in result['records']:
        message += f"- 試合 {r['primary_id']}: {r['status']}"
        if r['status']=='mismatch':message += f"（一次 {r['primary_score']} / 二次 {r['secondary_score']}）"
        message += '\n'
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path,'a',encoding='utf-8') as f:f.write(message)
    print(f"TheSportsDB: {len(result['records'])}件 / 不一致{len(mismatches)}件（通知のみ）")


def main():
    if os.environ.get('COLLESPO_THESPORTSDB_CHECK')!='on':
        print('TheSportsDB check: off');return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,default=ROOT/'data/soccer_results.json')
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_results/thesportsdb-check.json')
    ap.add_argument('--cache',type=Path,default=ROOT/'build/soccer_results/thesportsdb-cache')
    args = ap.parse_args()
    try:
        data = json.loads(args.source.read_text(encoding='utf-8'))
        fetch = Fetcher(args.cache)
        result = check(data,fetch.get); result['network_requests'] = fetch.count
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        report(result)
    except Exception as e:
        print('::warning::TheSportsDB check unavailable: '+type(e).__name__)
    return 0


if __name__=='__main__':raise SystemExit(main())
