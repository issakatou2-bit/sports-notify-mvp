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
        texts=[str((comp.get('type') or {}).get('text',''))]+[str(n.get('headline','')) for n in comp.get('notes',[])]
        text=' / '.join(texts)
        if re.search(r'\b(round of \d+|quarter.?finals?|semi.?finals?|final|knockout|leg [12])\b',text,re.I):
            game.update(phase='knockout',phase_source=text)
        game['jp_by_side']=selection.members(game)
        game['home_has_jp']=bool(game['jp_by_side']['home']);game['away_has_jp']=bool(game['jp_by_side']['away'])
        out.append(game)
    return out


def supplement(data,boards):
    data=dict(data,games=list(data['games']),source_errors=list(data.get('source_errors',[])),fixture_coverage=[])
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
            data['source_errors'].append(dict(competition=code,reason=type(boards[code]).__name__))
            data['fixture_coverage'].append(dict(competition=code,status='failed'));continue
        try:games=parse(boards[code],competition)
        except (ValueError,KeyError,TypeError) as error:
            data['source_errors'].append(dict(competition=code,reason=str(error)));continue
        data['fixture_coverage'].append(dict(competition=code,status='success',events=len(boards[code]['events'])))
        for g in games:
            old=seen.get(key(g))
            if old:
                old['fixture_sources']=sorted(set(old.get('fixture_sources') or ['football-data.org'])|{'ESPN'})
                for name in ('espn_event_id','phase','phase_source','competition_code'):
                    if name in g:old[name]=g[name]
            else:data['games'].append(g);seen[key(g)]=g
    return data


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--games',type=Path,default=selection.ROOT/'data/soccer_games.json');ap.add_argument('--boards',type=Path)
    args=ap.parse_args();data=json.loads(args.games.read_text(encoding='utf8'));day=datetime.now(timezone.utc).date()
    if args.boards:boards=json.loads(args.boards.read_text(encoding='utf8'))
    else:
        boards={}
        # EL/カンファレンスを先に確認。翌日の夜のカードを混ぜないよう選定側でも時刻を照合。
        competitions=sorted(selection.competitions(),key=lambda c:c['code'] not in ('EL','UECL'))
        for c in competitions:
            try:boards[c['code']]=results.fetch_json(f"{API}/{c['espn']}/scoreboard?dates={day:%Y%m%d}-{day+timedelta(days=1):%Y%m%d}&limit=100")
            except Exception as error:boards[c['code']]=error
    data=supplement(data,boards);args.games.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(coverage=data['fixture_coverage'],errors=data['source_errors']),ensure_ascii=False))
if __name__=='__main__':main()
