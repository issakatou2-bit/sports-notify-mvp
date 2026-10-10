"""前日JSTに終了した欧州5大リーグの日本人選手本人の結果。"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import notability_engine as ne

JST=timezone(timedelta(hours=9))
LEAGUES={'PL':'eng.1','PD':'esp.1','BL1':'ger.1','SA':'ita.1','FL1':'fra.1'}
LEAGUE_NAMES={'PL':'プレミアリーグ','PD':'ラ・リーガ','BL1':'ブンデスリーガ','SA':'セリエA','FL1':'リーグ・アン'}
ESPN='https://site.api.espn.com/apis/site/v2/sports/soccer'
SOURCE='ESPN・football-data.org'
STATUS={'starter':'先発','substitute':'途中出場','none':'出場なし'}
LIMIT=40.0


def utc(text):
    value=datetime.fromisoformat(str(text).replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('時刻にUTC/JSTの指定がありません')
    return value


def fetch_json(url):
    request=urllib.request.Request(url,headers={'User-Agent':'collespo/1.0'})
    with urllib.request.urlopen(request,timeout=25) as response:return json.load(response)


def completion_time(comp,summary):
    """終了の実時刻だけ。開始＋90分などの推測はしない。"""
    times=[]
    for value in (comp.get('endDate'),summary.get('header',{}).get('endDate')):
        if value:times.append(utc(value))
    for event in summary.get('keyEvents',[]):
        kind=event.get('type') or {}
        if (str(kind.get('id'))=='83' or kind.get('type')=='end-regular-time') and event.get('wallclock'):
            if (event.get('period') or {}).get('number',2)>=2:times.append(utc(event['wallclock']))
    return max(times).isoformat() if times else None


def resolve_player(rows,name_en):
    """姓と名の頭を両方照合し、1人に決まる場合だけ使う。"""
    parts=name_en.split();surname=ne.normalize_club(parts[-1]);initial=parts[0][0].lower()
    matches=[]
    for row in rows:
        athlete=row.get('athlete') or {}
        full=(athlete.get('fullName') or athlete.get('displayName') or '').split()
        last=athlete.get('lastName') or (full[-1] if full else '')
        given=next((x for x in full if ne.normalize_club(x)!=ne.normalize_club(last)),'')
        if ne.normalize_club(last)==surname and given.lower().startswith(initial):matches.append(row)
    return matches[0] if len(matches)==1 else None


def integer(value):
    if value is None:return None
    try:
        number=float(value)
        return int(number) if number>=0 and number.is_integer() else None
    except (ValueError,TypeError):return None


def clock_label(value):
    match=re.fullmatch(r"(\d+)'?(?:\+(\d+)'?)?",str(value).strip())
    if not match:raise ValueError('得点の分を読めません: '+str(value))
    return match[1]+('+'+match[2] if match[2] else '')


def player_result(player,rows,side,event_id):
    row=resolve_player(rows,player['name_en'])
    result={'name':player['name_jp'],'name_en':player['name_en'],'club':player['team_jp'],
            'side':side,'event_id':event_id,'athlete_id':None,'status':'none',
            'goals':None,'assists':None,'yellow_cards':None,'red_cards':None,'plays':[]}
    if row is None:
        raise ValueError('選手名を一意に照合できません（出場なしと推測しない）')
    if 'starter' not in row or 'subbedIn' not in row:raise ValueError('出場区分が不明')
    result['athlete_id']=str(row['athlete']['id'])
    result['status']='starter' if row['starter'] else 'substitute' if row['subbedIn'] else 'none'
    stats={s['name']:integer(s.get('value',s.get('displayValue'))) for s in row.get('stats',[])}
    if stats.get('appearances')==0 and result['status']!='none':raise ValueError('出場区分と出場数が不一致')
    for dest,key in (('goals','totalGoals'),('assists','goalAssists'),('yellow_cards','yellowCards'),('red_cards','redCards')):
        result[dest]=stats.get(key)
    if result['status']=='none' and (result['goals'] or result['assists']):raise ValueError('出場なしに得点/アシスト')
    result['subbed_out']=bool(row.get('subbedOut'))
    result['appearance_evidence']='ESPN starter/subbedIn'
    result['plays']=[{'minute':clock_label((p.get('clock') or {}).get('displayValue')),'goal':bool(p.get('didScore')),'assist':bool(p.get('didAssist'))}
                     for p in row.get('plays',[]) if p.get('didScore') or p.get('didAssist')]
    return result


def rank_key(player):
    # Strict category order: any goal > any assist > starter > substitute > none.
    tier=4 if player.get('goals') else 3 if player.get('assists') else 2 if player['status']=='starter' else 1 if player['status']=='substitute' else 0
    return (-tier,-(player.get('goals') or 0),-(player.get('assists') or 0),player['name'])


def club_key(name):
    return ne.normalize_club(ne.club_name_jp(name))


def football_check(game,matches):
    if game['league'] not in matches:return 'unavailable'
    found=[]
    for match in matches[game['league']]:
        if match.get('status')!='FINISHED':continue
        if (club_key((match.get('homeTeam') or {}).get('name',''))!=club_key(game['home']['name_en']) or
            club_key((match.get('awayTeam') or {}).get('name',''))!=club_key(game['away']['name_en'])):continue
        if abs((utc(match['utcDate'])-utc(game['start_utc'])).total_seconds())>600:continue
        found.append(match)
    if not found:return 'not_found'
    if len(found)!=1:return 'mismatch'
    score=(found[0].get('score') or {}).get('fullTime') or {}
    return 'matched' if score==game['score'] else 'mismatch'


def in_window(ended,target):
    """その日の夜の試合＝日本時間の target 8時〜翌朝8時に終わった試合（10/10 本人「8時には出揃う？」）。
    土曜の夜の試合は日曜の朝4〜6時に終わるので、暦の日で切ると1日遅れる。"""
    start=datetime(target.year,target.month,target.day,8,tzinfo=JST)
    return start<=ended.astimezone(JST)<start+timedelta(days=1)


def build(boards,summaries,target_date,football=None,roster=None):
    target=date.fromisoformat(str(target_date));football=football or {};games=[];rejected=[];seen=set()
    roster=ne.JP_PLAYERS_SOCCER if roster is None else roster
    for key,board in boards.items():
        code=key.split('_')[0]
        if code not in LEAGUES:continue
        for event in board.get('events',[]):
            id=str(event['id'])
            if id in seen:continue
            comp=event['competitions'][0]
            if not (comp.get('status',{}).get('type') or {}).get('completed'):continue
            seen.add(id)
            sides={c['homeAway']:c for c in comp.get('competitors',[])}
            if not all(s in sides for s in ('home','away')):continue
            candidates={s:[p for p in roster if p['league']==code and p['match'] in ne.normalize_club(sides[s]['team']['displayName'])] for s in sides}
            # Club membership in the identity roster can lag transfers. The final
            # ESPN squad establishes the actual club; search Japanese identities on both sides.
            if not any(candidates.values()) and id not in summaries:continue
            try:
                saved=summaries.get(id)
                if saved is None:raise ValueError('summary取得なし')
                summary=saved.get('summary',saved)
                ended=completion_time(comp,summary)
                if not ended:raise ValueError('終了実時刻なし')
                if not in_window(utc(ended),target):continue
                header=(summary.get('header') or {}).get('competitions') or []
                if len(header)!=1 or str(header[0].get('id'))!=id:raise ValueError('summaryの試合ID不一致')
                if utc(header[0]['date'])!=utc(event['date']):raise ValueError('summaryの開始時刻不一致')
                if not (header[0].get('status',{}).get('type') or {}).get('completed'):raise ValueError('summaryは終了前')
                score={s:integer(sides[s].get('score')) for s in ('home','away')}
                if None in score.values():raise ValueError('スコア不明')
                check_sides={c['homeAway']:c for c in header[0].get('competitors',[])}
                if any(str(check_sides.get(s,{}).get('id'))!=str(sides[s]['id']) or integer(check_sides.get(s,{}).get('score'))!=score[s] for s in score):raise ValueError('ESPN内のクラブ/スコア不一致')
                game={'id':id,'league':code,'league_jp':LEAGUE_NAMES[code],'start_utc':event['date'],'finished_utc':ended,
                      'date_jst':target.isoformat(),'score':score,'players':[], 'goals':[], 'unresolved':[]}
                for side in ('home','away'):
                    team=sides[side]['team']
                    game[side]={'id':str(team['id']),'name_en':team['displayName'],'name_jp':ne.club_name_jp(team['displayName']),
                                'abbr':team.get('abbreviation') or team['displayName'][:3].upper()}
                    groups=[g for g in summary.get('rosters',[]) if str(g.get('team',{}).get('id'))==str(team['id'])]
                    if len(groups)!=1:raise ValueError('クラブの名簿なし/重複')
                    rows=groups[0].get('roster') or []
                    if sum(bool(r.get('starter')) for r in rows)!=11:raise ValueError('先発11人の完全名簿なし')
                    for player in roster:
                        if resolve_player(rows,player['name_en']) is not None:
                            actual=dict(player,team_jp=game[side]['name_jp'])
                            game['players'].append(player_result(actual,rows,side,id))
                    game['unresolved'].extend(p['name_jp'] for p in candidates[side]
                                              if resolve_player(rows,p['name_en']) is None)
                matched={p['name'] for p in game['players']}
                game['unresolved']=[name for name in game['unresolved'] if name not in matched]
                if not game['players']:raise ValueError('日本人選手を当日の登録名簿で照合できず')
                people={p['athlete_id']:p for p in game['players'] if p['athlete_id']}
                side_by_id={game[s]['id']:s for s in ('home','away')}
                for detail in comp.get('details',[]):
                    if not detail.get('scoringPlay') or detail.get('shootout'):continue
                    side=side_by_id.get(str((detail.get('team') or {}).get('id')))
                    if not side:raise ValueError('得点先クラブ不明')
                    athlete=(detail.get('athletesInvolved') or [{}])[0];pid=str(athlete.get('id',''))
                    jp=people.get(pid);own=bool(detail.get('ownGoal') or (detail.get('type') or {}).get('text')=='Own Goal')
                    minute=clock_label((detail.get('clock') or {}).get('displayValue'))
                    assists=[p['name'] for p in game['players'] if p['side']==side and any(x['assist'] and x['minute']==minute for x in p['plays'])]
                    game['goals'].append({'minute':minute,'scorer':jp['name'] if jp else athlete.get('displayName') or '得点者不明',
                        'athlete_id':pid,'side':side,'own_goal':own,'japanese_goal':bool(jp and not own),
                        'japanese_assists':assists})
                game['goals_complete']=all(sum(g['side']==s for g in game['goals'])==score[s] for s in score)
                if game['goals_complete']:
                    for p in game['players']:
                        if p['goals'] is not None and p['goals']!=sum(g['athlete_id']==p['athlete_id'] and not g['own_goal'] for g in game['goals']):raise ValueError('個人成績と得点経過の不一致')
                game['score_crosscheck']=football_check(game,football)
                if game['score_crosscheck']=='mismatch':raise ValueError('football-dataとのスコア不一致')
                games.append(game)
            except (ValueError,KeyError,TypeError) as e:rejected.append({'event_id':id,'reason':str(e)})
    players=sorted([p for game in games for p in game['players']],key=rank_key)
    return {'schema_version':1,'date_jst':target.isoformat(),'generated_at':datetime.now(timezone.utc).isoformat(),
            'source':SOURCE,'games':games,'players':players,'can_make':any(p['status']!='none' for p in players),'rejected':rejected}


def action(player):
    if player.get('goals'):return 'がゴール' if player['goals']==1 else f"が{player['goals']}ゴール"
    if player.get('assists'):return f"が{player['assists']}アシスト"
    return 'が先発' if player['status']=='starter' else 'が途中出場' if player['status']=='substitute' else 'は出場なし'


def validate_data(data):
    """正規化後の材料でも、クラブと本人の数字・出場区分を照合する。"""
    day=date.fromisoformat(data['date_jst'])
    flattened=[]
    for game in data['games']:
        if not in_window(utc(game['finished_utc']),day):raise ValueError('終了時刻が対象の夜（8時〜翌8時）の外')
        if game['home']['id']==game['away']['id']:raise ValueError('対戦クラブが同じ')
        if any(type(v) is not int or v<0 for v in game['score'].values()):raise ValueError('スコアが不正')
        if game['goals_complete']!=all(sum(g['side']==s for g in game['goals'])==game['score'][s] for s in ('home','away')):raise ValueError('得点経過の完全性が不一致')
        for p in game['players']:
            if p['event_id']!=game['id'] or p['side'] not in ('home','away') or p['club']!=game[p['side']]['name_jp']:raise ValueError('選手の試合/クラブが不一致')
            if p['status'] not in STATUS:raise ValueError('出場区分が不明')
            if p['status']=='none' and (p.get('goals') or p.get('assists')):raise ValueError('出場なしを活躍にしない')
            for key in ('goals','assists','yellow_cards','red_cards'):
                if p[key] is not None and (type(p[key]) is not int or p[key]<0):raise ValueError('個人成績が不正')
            if game['goals_complete'] and p['goals'] is not None and p['goals']!=sum(g['athlete_id']==p['athlete_id'] and not g['own_goal'] for g in game['goals']):raise ValueError('得点数と経過が不一致')
            flattened.append(p)
        people={p['athlete_id']:p for p in game['players']}
        for g in game['goals']:
            clock_label(g['minute'])
            if g['side'] not in ('home','away'):raise ValueError('得点先が不明')
            jp=people.get(g['athlete_id'])
            if g['japanese_goal']!=bool(jp and not g['own_goal']):raise ValueError('日本人の得点表示が不正')
            if jp and not g['own_goal'] and jp['side']!=g['side']:raise ValueError('得点先と選手のクラブが不一致')
    if sorted(flattened,key=rank_key)!=data['players']:raise ValueError('一覧の順位/数字が試合の材料と違う')
    if bool(data['can_make'])!=any(p['status']!='none' for p in flattened):raise ValueError('出場ゼロの生成条件が不正')


def title(data):
    if not data.get('can_make'):return ''
    lead=next(p for p in data['players'] if p['status']!='none');game=next(g for g in data['games'] if g['id']==lead['event_id'])
    score=f"{game['home']['name_jp']} {game['score']['home']}-{game['score']['away']} {game['away']['name_jp']}"
    others=' ほか' if len(data['games'])>1 else ''
    return f"【欧州サッカー】{lead['name']}{action(lead)}｜{score}{others} 日本人選手の結果 #Shorts"


def description_lines(data):
    lines=[f"{data['date_jst']}の夜〜翌朝（日本時間）に終わった欧州5大リーグの試合から、日本人選手本人の結果です。"]
    lines += [f"・{p['name']}（{p['club']}）{STATUS[p['status']]}"+ ''.join(f" / {p[k]}{unit}" for k,unit in (('goals','得点'),('assists','アシスト'),('yellow_cards','警告'),('red_cards','退場')) if p.get(k) is not None) for p in data['players']]
    lines += ['', '出典: '+SOURCE+'。終了時刻・出場区分・個人成績・得点経過はESPN。football-data.orgのスコアを取得できた試合は照合し、不一致は除外します。',
              '出場なしは一覧のみ。クラブの勝敗を選手本人の活躍とは扱っていません。']
    return lines


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date',default=(datetime.now(JST).date()-timedelta(days=1)).isoformat(),help='終了した日本時間の日')
    ap.add_argument('--scoreboards',type=Path)
    ap.add_argument('--summaries',type=Path)
    ap.add_argument('--football',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'data/soccer_results.json')
    args=ap.parse_args();target=date.fromisoformat(args.date)
    if bool(args.scoreboards)!=bool(args.summaries):ap.error('保存scoreboardsとsummariesは両方指定')
    if args.scoreboards:
        boards=json.loads(args.scoreboards.read_text(encoding='utf-8'));summaries=json.loads(args.summaries.read_text(encoding='utf-8'))
    else:
        boards={};summaries={}
        for code,slug in LEAGUES.items():
            for day in (target-timedelta(days=1),target,target+timedelta(days=1)):
                key=code+'_'+day.strftime('%Y%m%d')
                boards[key]=fetch_json(f'{ESPN}/{slug}/scoreboard?dates={day:%Y%m%d}')
                for event in boards[key].get('events',[]):
                    comp=event['competitions'][0]
                    if not (comp.get('status',{}).get('type') or {}).get('completed'):continue
                    # Search the actual final squads rather than trusting stale club membership.
                    id=str(event['id'])
                    if id not in summaries:summaries[id]=fetch_json(f'{ESPN}/{slug}/summary?event={id}')
    football=json.loads(args.football.read_text(encoding='utf-8')) if args.football else {}
    if not args.scoreboards and os.environ.get('FOOTBALL_DATA_API_KEY'):
        import soccer_jp_week
        football=soccer_jp_week.fetch_matches(os.environ['FOOTBALL_DATA_API_KEY'],target+timedelta(days=1))
    data=build(boards,summaries,target.isoformat(),football)
    validate_data(data)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'date':args.date,'games':len(data['games']),'players':len(data['players']),'can_make':data['can_make'],'rejected':data['rejected']},ensure_ascii=False))


if __name__=='__main__':main()
