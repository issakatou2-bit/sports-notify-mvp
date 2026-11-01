"""ESPNの大会別日程を補う。取得失敗を試合なしへ置き換えない。"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import soccer_selection as selection
import soccer_results as results
import club_display_names as clubs
API=results.ESPN


def parse(board,competition):
    if not isinstance(board.get('events'),list):raise ValueError('ESPN events配列なし')
    out=[]
    for event in board['events']:
        comps=event.get('competitions') or []
        if len(comps)!=1:continue
        comp=comps[0];sides={c.get('homeAway'):c for c in comp.get('competitors',[])}
        if not all(s in sides for s in ('home','away')):raise ValueError('ESPNのホーム/アウェー不明')
        at=results.utc(event['date']);status=(comp.get('status',{}).get('type') or {})
        if status.get('completed'):continue
        if status.get('name') in ('STATUS_POSTPONED','STATUS_CANCELED','STATUS_ABANDONED'):continue
        game=dict(game_id='espn-'+str(event['id']),espn_event_id=str(event['id']),competition_code=competition['code'],league=competition['name'],
                  start_time_utc=at.isoformat(),start_time_jst=at.astimezone(selection.JST).strftime('%m/%d %H:%M'),is_notable=False,
                  fixture_source=API+'/'+competition['espn']+'/scoreboard',home_standing=None,away_standing=None)
        game['fixture_sources']=['ESPN']
        for side in ('home','away'):
            team=sides[side]['team'];row=clubs.lookup(team.get('displayName')) or clubs.lookup(team.get('name'))
            game[side+'_team_name']=row['id'] if row else team['displayName']
            game[side+'_team_id']='espn-'+str(team['id'])
        # 試合材料の明示したラウンドだけを読む。月/日付から段階を推測しない。
        # 杯戦のラウンドは type/notes ではなく season.slug（second-round 等）に入る（10/28 DFB・国王杯で確認）。
        texts=[str((comp.get('type') or {}).get('text',''))]+[str(n.get('headline','')) for n in comp.get('notes',[])]
        texts.append(str((event.get('season') or {}).get('slug','')).replace('-',' '))
        text=' / '.join(t for t in texts if t)
        cup=not competition['football_free'] and competition['code'] not in ('CL','EL','UECL')
        if re.search(r'\b(round of \d+|quarter.?finals?|semi.?finals?|final|knockout|leg [12])\b',text,re.I) or \
           (cup and re.search(r'\b(first|second|third|fourth|fifth|[1-5](st|nd|rd|th)) round\b',text,re.I)):
            game.update(phase='knockout',phase_source=text)
        game['jp_by_side']=selection.members(game)
        game['home_has_jp']=bool(game['jp_by_side']['home']);game['away_has_jp']=bool(game['jp_by_side']['away'])
        out.append(game)
    return out


def supplement(data,boards):
    data=dict(data,games=list(data['games']),source_errors=[e for e in data.get('source_errors',[]) if e.get('competition') not in boards],fixture_coverage=[])
    seen={}
    def key(g):
        return (selection.competition(g)['code'] if selection.competition(g) else g.get('league'),
                clubs.normalize(clubs.display(g.get('home_team_name'))),clubs.normalize(clubs.display(g.get('away_team_name'))),
                selection.kickoff(g,data['generated_at']).isoformat())
    for g in data['games']:
        try:seen[key(g)]=g
        except (ValueError,KeyError,TypeError):continue
    for competition in selection.competitions():
        code=competition['code']
        if code not in boards:continue
        if isinstance(boards[code],Exception):
            data['source_errors'].append(dict(competition=code,reason=error_reason(boards[code])))
            data['fixture_coverage'].append(dict(competition=code,status='failed',reason=error_reason(boards[code])));continue
        try:games=parse(boards[code],competition)
        except (ValueError,KeyError,TypeError) as error:
            data['source_errors'].append(dict(competition=code,reason=str(error)))
            data['fixture_coverage'].append(dict(competition=code,status='failed',reason=str(error)));continue
        errors=boards[code].get('source_errors',[])
        data['source_errors'].extend(dict(competition=code,**e) for e in errors)
        data['fixture_coverage'].append(dict(competition=code,status='partial' if errors else 'success' if boards[code]['events'] else 'no_games',events=len(boards[code]['events']),label='一部取得失敗' if errors else '取得成功' if boards[code]['events'] else '試合なし'))
        for g in games:
            old=seen.get(key(g))
            if old:
                old['fixture_sources']=sorted(set(old.get('fixture_sources') or ['football-data.org'])|{'ESPN'})
                for name in ('espn_event_id','phase','phase_source','competition_code'):
                    if name in g:old[name]=g[name]
            else:data['games'].append(g);seen[key(g)]=g
    return data


def error_reason(error):
    code=getattr(error,'code',None)
    return type(error).__name__+(f' HTTP {code}' if code is not None else '')+' '+str(getattr(error,'reason',error))


def fetch_board(competition,day,days=2):
    # 範囲指定で全大会が失敗したため、既存の結果取得と同じ単日指定にする。
    events={};errors=[]
    for at in (day+timedelta(days=i) for i in range(days)):
        url=f"{API}/{competition['espn']}/scoreboard?dates={at:%Y%m%d}&limit=100"
        try:
            board=results.fetch_json(url)
            if not isinstance(board.get('events'),list):raise ValueError('ESPN events配列なし')
        except Exception as error:
            if days<=2:raise
            errors.append(dict(day=at.isoformat(),reason=error_reason(error)));continue
        for event in board['events']:events[str(event['id'])]=event
    return dict(events=list(events.values()),**({'source_errors':errors} if errors else {}))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--games',type=Path,default=selection.ROOT/'data/soccer_games.json');ap.add_argument('--boards',type=Path)
    args=ap.parse_args();data=json.loads(args.games.read_text(encoding='utf8'));day=datetime.now(timezone.utc).date()
    if args.boards:boards=json.loads(args.boards.read_text(encoding='utf8'))
    else:
        boards={}
        # EL/カンファレンスを先に確認。翌日の夜のカードを混ぜないよう選定側でも時刻を照合。
        competitions=sorted(selection.competitions(),key=lambda c:c['code'] not in ('EL','UECL'))
        for c in competitions:
            # UTC単日8日分でJSTの今後7日を覆い、選定前の辞書検査へ渡す。
            try:boards[c['code']]=fetch_board(c,day,days=8)
            except Exception as error:boards[c['code']]=error
    data=supplement(data,boards);args.games.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(coverage=data['fixture_coverage'],errors=data['source_errors']),ensure_ascii=False))
if __name__=='__main__':main()
