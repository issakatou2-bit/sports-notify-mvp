"""同じ大会の順位の前後と次戦を取得。取れない項目だけ省く。"""
import copy
from datetime import datetime,timedelta,timezone
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import notability_engine as ne
import club_display_names as clubs
import soccer_results as results
ROOT=Path(__file__).resolve().parents[1]


def tables(payload,code,at):
    season=(payload.get('season') or {}).get('id')
    rows={};duplicates=set()
    for group in payload.get('standings',[]):
        if group.get('type')!='TOTAL':continue
        for row in group.get('table',[]):
            club=clubs.lookup(row['team']['name'])
            if not club or type(row.get('position')) is not int or row['position']<=0:continue
            ident=club['id']
            if ident in rows:duplicates.add(ident)
            rows[ident]=dict(rank=row['position'],played=row.get('playedGames'),competition=code,season=season,as_of=at,
                             source=ne.FOOTBALL_DATA_BASE+'/competitions/'+code+'/standings')
    return {k:v for k,v in rows.items() if k not in duplicates}


def fetch_table(code,key):
    payload=ne._football_data_get(ne.FOOTBALL_DATA_BASE+'/competitions/'+code+'/standings',{'X-Auth-Token':key}).json()
    return tables(payload,code,datetime.now(timezone.utc).isoformat())


def capture_before(record):
    record=copy.deepcopy(record);key=os.environ.get('FOOTBALL_DATA_API_KEY')
    if not key:return record
    cache={}
    for g in record['games']:
        code=g.get('competition_code')
        if code not in ne.SOCCER_COMPETITIONS:continue  # 無料で取得する既存の大会だけ。
        if code not in cache:
            try:cache[code]=fetch_table(code,key)
            except Exception as error:
                print('[omit] 予告時の順位:',code,type(error).__name__);cache[code]={}
        for side in ('home','away'):
            row=cache[code].get((clubs.lookup(g[side]) or {}).get('id'))
            if row and results.utc(row['as_of'])<results.utc(g['start_utc']):g['standings'][side]=row
    return record


def after_context(data,preview):
    before={};after={};upcoming=[];key=os.environ.get('FOOTBALL_DATA_API_KEY');day=results.date.fromisoformat(data['date_jst'])+timedelta(days=1)
    if not preview:return before,after,upcoming
    codes=set()
    for g in preview['games']:
        codes.add(g.get('competition_code'))
        for side in ('home','away'):
            ident=(clubs.lookup(g[side]) or {}).get('id')
            if ident and (g.get('standings') or {}).get(side):before[ident]=g['standings'][side]
    for code in sorted(c for c in codes if c):
        if key and code in ne.SOCCER_COMPETITIONS:
            try:after.update(fetch_table(code,key))
            except Exception as error:print('[omit] 結果時の順位:',code,type(error).__name__)
            try:
                url=ne.FOOTBALL_DATA_BASE+'/competitions/'+code+'/matches'
                payload=ne._football_data_get(url,{'X-Auth-Token':key},params={'dateFrom':day.isoformat(),'dateTo':(day+timedelta(days=14)).isoformat()}).json()
                for g in payload.get('matches',[]):
                    if g.get('status') not in ('SCHEDULED','TIMED'):continue
                    if not g.get('utcDate'):continue
                    upcoming.append(dict(home=g['homeTeam']['name'],away=g['awayTeam']['name'],start_utc=g['utcDate'],source=url,competition=code))
            except Exception as error:print('[omit] 次の試合:',code,type(error).__name__)
        else:
            registry=ROOT/'data/soccer_competitions.json'
            competitions=json.loads(registry.read_text(encoding='utf8'))['competitions'] if registry.exists() else []
            comp=next((c for c in competitions if c['code']==code),None)
            if not comp:continue
            url=results.ESPN+'/'+comp['espn']+'/scoreboard'
            try:
                payload=results.fetch_json(f'{url}?dates={day:%Y%m%d}-{day+timedelta(days=7):%Y%m%d}&limit=100')
                for event in payload.get('events',[]):
                    g=event['competitions'][0];status=(g.get('status',{}).get('type') or {})
                    if status.get('completed') or status.get('state')!='pre':continue
                    sides={c['homeAway']:c for c in g['competitors']}
                    upcoming.append(dict(home=sides['home']['team']['displayName'],away=sides['away']['team']['displayName'],start_utc=event['date'],source=url,competition=code))
            except Exception as error:print('[omit] 次の試合:',code,type(error).__name__)
    return before,after,upcoming
