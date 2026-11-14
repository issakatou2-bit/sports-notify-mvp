"""日本代表の親善試合。取得・選定と台本を分け、既定offで公開を止める。"""

import short_common
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import warnings
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
API = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.friendly/'
ALL_API = 'https://site.api.espn.com/apis/site/v2/sports/soccer/all/'
JAPAN = '627'
TEAM_NAMES = {'Japan':'日本', 'Brazil':'ブラジル', 'Paraguay':'パラグアイ',
    'Venezuela':'ベネズエラ', 'Uruguay':'ウルグアイ', 'Iceland':'アイスランド',
    'India':'インド', 'Australia':'オーストラリア', 'Egypt':'エジプト',
    'Panama':'パナマ', 'Croatia':'クロアチア', 'France':'フランス',
    'England':'イングランド', 'Scotland':'スコットランド', 'Bolivia':'ボリビア',
    'Colombia':'コロンビア', 'Greece':'ギリシャ', 'Morocco':'モロッコ', 'Nicaragua':'ニカラグア',
    'Ghana':'ガーナ', 'Chile':'チリ', 'Mexico':'メキシコ', 'United States':'アメリカ'}
TEAM_NAMES.update({'Netherlands':'オランダ','Tunisia':'チュニジア','Sweden':'スウェーデン',
    'Ecuador':'エクアドル','New Zealand':'ニュージーランド','Argentina':'アルゼンチン',
    'Bahrain':'バーレーン','China':'中国','Germany':'ドイツ','Haiti':'ハイチ','Indonesia':'インドネシア',
    'Norway':'ノルウェー','Peru':'ペルー','Saudi Arabia':'サウジアラビア','Senegal':'セネガル',
    'South Korea':'韓国','Türkiye':'トルコ','TÃ¼rkiye':'トルコ'})


def enabled():
    import os
    return os.environ.get('COLLESPO_SOCCER_NATIONAL', 'off') == 'on'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')


def instant(value):
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('日時のタイムゾーンがありません')
    return at


def number(value):
    if isinstance(value, dict):
        value = value.get('value', value.get('displayValue'))
    if isinstance(value, bool) or value is None:
        raise ValueError('スコアがありません')
    n = float(value)
    if not n.is_integer() or not 0 <= n <= 30:
        raise ValueError('スコアが不正です')
    return int(n)


def team_name(value):
    name = TEAM_NAMES.get(value)
    if not name:
        raise ValueError('国名の日本語辞書がありません: '+value)
    return name


def player_name(english, japanese=False):
    table = read(ROOT/'data/player_kana.json')
    confirmed = read(ROOT/'data/soccer_player_names.json')['players']
    names = {p['name_en']:p['name_jp'] for p in confirmed if p.get('status') == 'confirmed'}
    jp = names.get(english) if japanese else table['names'].get(english)
    if japanese and (not jp or not next((p for p in confirmed if p['name_en']==english and p.get('reading')), None)):
        # 11/14 ブラジル戦の結果の回が中村敬斗（追跡の42人の外）で止まった。公式招集名簿（JFA発表）の選手はそこから引く。
        official=official_squad_player(english)
        if not official:
            raise ValueError('日本代表選手の名前・読みが未登録です: '+english)
        jp=official['name']
    if jp and re.search(r'[A-Za-z]', jp):
        raise ValueError('日本語名にローマ字があります')
    return jp or None


def match(event, venue=None):
    c = event['competitions'][0]
    competitors = c['competitors']
    if len(competitors)!=2 or sum(str(t['team']['id'])==JAPAN for t in competitors)!=1:
        raise ValueError('日本代表の1試合に限定します')
    jp = next(t for t in competitors if str(t['team']['id'])==JAPAN)
    opp = next(t for t in competitors if str(t['team']['id'])!=JAPAN)
    v = c.get('venue') or venue or {}
    name = v.get('fullName')
    venue_jp = {'Singapore National Stadium':'シンガポール・ナショナル・スタジアム',
        'Edion Peace Wing Hiroshima':'エディオンピースウイング広島',
        'Miyagi Stadium':'宮城スタジアム', 'Japan National Stadium':'国立競技場'}.get(name)
    state = c.get('status') or event.get('status') or {}
    completed = state.get('type', {}).get('completed') is True
    row = dict(id=str(event['id']), start_utc=event['date'],
        kickoff_jst=instant(event['date']).astimezone(JST).isoformat(),
        opponent_id=str(opp['team']['id']), opponent=team_name(opp['team']['displayName']),
        opponent_abbr=opp['team'].get('abbreviation') or '?',
        venue=venue_jp, venue_raw=name, completed=completed,
        source_url='https://www.espn.com/soccer/match/_/gameId/'+str(event['id']))
    if completed:
        row['score'] = dict(japan=number(jp.get('score')), opponent=number(opp.get('score')))
    return row


def japan_matches(scoreboards):
    rows = {}
    for board in scoreboards:
        for e in board.get('events') or []:
            if any(str(t['team']['id'])==JAPAN for t in e['competitions'][0]['competitors']):
                row = match(e)
                if not row['venue']:
                    raise ValueError('日本語会場名が未登録です')
                rows[row['id']] = row
    return sorted(rows.values(), key=lambda r:r['start_utc'])


def recent(schedule, team_id, before):
    rows = []
    for e in schedule.get('events') or []:
        if instant(e['date']) >= before:
            continue
        c=e['competitions'][0]
        if not c.get('status', {}).get('type', {}).get('completed'):
            continue
        sides = c['competitors']
        a = next((t for t in sides if str(t['team']['id'])==str(team_id)), None)
        if not a or len(sides)!=2:
            continue
        b = next(t for t in sides if t is not a)
        rows.append(dict(id=str(e['id']), date_jst=instant(e['date']).astimezone(JST).date().isoformat(),
            start_utc=e['date'], team=team_name(a['team']['displayName']),
            team_abbr=a['team'].get('abbreviation') or '?',opponent_abbr=b['team'].get('abbreviation') or '?',
            opponent=team_name(b['team']['displayName']), gf=number(a['score']), ga=number(b['score']),
            source_url='https://www.espn.com/soccer/match/_/gameId/'+str(e['id'])))
    return sorted(rows, key=lambda r:r['start_utc'], reverse=True)


def preview(game, japan_schedule, opponent_schedule, previous, as_of):
    at=instant(as_of)
    if at >= instant(game['start_utc']):
        raise ValueError('開始後は予告を作りません')
    op=recent(opponent_schedule,game['opponent_id'],at)
    observed=recent(japan_schedule,JAPAN,at)
    import soccer_national_history as history
    context=history.context(as_of,game['opponent'],observed)
    for message in context['history_warnings']:warnings.warn(message)
    return dict(version=1, story_version=3, mode='preview', game=game, as_of=as_of,
        japan_observed=observed,opponent_history=op,
        opponent_recent=op[0] if op else None,opponent_previous=None,**context)


def result(summary, upcoming, japan_schedule, as_of):
    c=summary['header']['competitions'][0]
    game=match(dict(id=summary['header']['id'], date=c['date'], competitions=[c]),summary.get('gameInfo',{}).get('venue'))
    if not game['completed'] or instant(game['start_utc'])>=instant(as_of):
        raise ValueError('試合終了を確認できません')
    counts={JAPAN:0,game['opponent_id']:0}
    goals=[];seen=set()
    for e in summary.get('keyEvents') or []:
        if not e.get('scoringPlay') or e.get('shootout'):
            continue
        if not e.get('id') or e['id'] in seen:
            raise ValueError('得点イベントIDの欠測・重複')
        seen.add(e['id'])
        team=str(e.get('team',{}).get('id'))
        if team not in counts:
            raise ValueError('得点チームを特定できません')
        # ESPNのteamは得点を得た側。オウンゴールの選手の国籍とは分ける。
        counts[team]+=1
        people=e.get('participants') or []
        name=(people[0].get('athlete') or {}).get('displayName') if people else None
        own=e.get('type',{}).get('id')=='97' or 'own' in e.get('type',{}).get('text','').lower()
        if team==JAPAN and not own and not name:raise ValueError('日本代表の得点者名がありません')
        jp_name=player_name(name,team==JAPAN and not own) if name and not own else None
        goals.append(dict(team_id=team, name=jp_name, name_en=name, own_goal=own,
            athlete_id=str((people[0].get('athlete') or {}).get('id') or '') if people else '',
            minute=e.get('clock',{}).get('displayValue','').replace("'",''), id=e['id']))
    complete=counts=={JAPAN:game['score']['japan'],game['opponent_id']:game['score']['opponent']}
    halves={}
    for t in c['competitors']:
        values=[number(x) for x in t.get('linescores',[])]
        side='japan' if str(t['team']['id'])==JAPAN else 'opponent'
        if len(values)==2 and sum(values)==game['score'][side]:halves[side]=values
    if len(halves)!=2:halves=None
    known={g['id']:g for g in upcoming}
    for e in japan_schedule.get('events') or []:
        if instant(e['date'])>instant(game['start_utc']):
            known[str(e['id'])]=match(e)
    future=[g for g in known.values() if instant(g['start_utc'])>instant(game['start_utc'])]
    current=dict(id=game['id'],date_jst=game['kickoff_jst'][:10],start_utc=game['start_utc'],team='日本',
        opponent=game['opponent'],competition='親善試合',gf=game['score']['japan'],ga=game['score']['opponent'],source_url=game['source_url'])
    observed=recent(japan_schedule,JAPAN,instant(as_of))
    import soccer_national_history as history
    context=history.context(as_of,game['opponent'],observed,current)
    for message in context['history_warnings']:warnings.warn(message)
    next_game=min(future,key=lambda g:g['start_utc']) if future else None
    if context['next_known'] and (not next_game or context['next_known']['date_jst']<next_game['kickoff_jst'][:10]):next_game=None
    return dict(version=1,story_version=3,length_policy=3,mode='result',game=game,as_of=as_of,goals_complete=complete,
        japan_observed=observed,current_result=current,**context,
        goal_counts=counts, goals=goals if complete else [],halves=halves,
        next_game=next_game)


def season_rows(material, club, english, as_of, season, *, name_jp=None):
    """既存予告のseason_players。氏名・所属・季・取得時刻が揃う時だけ。"""
    import club_display_names as clubs
    name=name_jp if name_jp is not None else player_name(english,True)
    target=clubs.lookup(club)
    found=[]
    for g in material.get('games') or []:
        for p in g.get('season_players') or []:
            other=clubs.lookup(p.get('club'))
            same_club=p.get('club')==club or (target and other and target['id']==other['id'])
            if p.get('name')!=name or not same_club or p.get('scope')!='season':
                continue
            if not p.get('as_of') or not p.get('source'):
                continue
            stored=p.get('season')
            if stored is None:
                # 既存season_playersは現在季の値。欧州の年またぎ季だけを日時で限定する。
                at=instant(p['as_of']).astimezone(JST)
                start=at.year if at.month>=7 else at.year-1
                stored=f'{start}/{str(start+1)[-2:]}'
            if str(stored)!=str(season):continue
            if not instant(as_of)-timedelta(days=7)<=instant(p['as_of'])<=instant(as_of):
                continue
            values={k:p[k] for k in ('goals','assists','minutes','appearances') if p.get(k) is not None}
            if not values or any(type(v) is not int or v<0 for v in values.values()):
                continue
            found.append(dict(values=values,season=str(season),league=g.get('league'),as_of=p['as_of'],source=p['source']))
    unique={json.dumps(p,sort_keys=True,ensure_ascii=False):p for p in found}
    return next(iter(unique.values())) if len(unique)==1 else None


def squad_source(data):
    if data.get('sample') or urlparse(data.get('source_url','')).hostname!='www.jfa.jp':
        raise ValueError('本物のJFA公式発表だけを使います')


def official_squad_player(english):
    """公式招集名簿（JFA発表、data/soccer_national_squad.json）にいる選手。なければ None。"""
    path=ROOT/'data/soccer_national_squad.json'
    if not english or not path.exists():
        return None
    data=read(path)
    try:
        squad_source(data)
    except ValueError:
        return None
    p=next((p for p in data.get('players') or [] if p.get('name_en')==english),None)
    return squad_player(p) if p else None


def squad_player(p):
    """発表の氏名と読みが正。既存確定名簿と衝突したら止める。"""
    english=p.get('name_en');name=p.get('name_jp');reading=p.get('reading')
    if (not isinstance(english,str) or not english.strip() or not isinstance(name,str)
            or not re.fullmatch(r'[一-龯﨑々ァ-ヶー]+',name)
            or not isinstance(reading,str) or not re.fullmatch(r'[ァ-ヶー]+',reading)):
        raise ValueError('招集名簿の氏名・カタカナ読みがありません')
    known=next((r for r in read(ROOT/'data/soccer_player_names.json')['players'] if r['name_en']==english),None)
    if known and (known.get('name_jp')!=name or known.get('reading')!=reading):
        raise ValueError('招集名簿の氏名・読みが既存辞書と一致しません: '+english)
    if not p.get('club') or p.get('position') not in ('GK','DF','MF','FW','MF/FW'):
        raise ValueError('招集名簿の所属・位置を確認してください')
    if type(p.get('first_call',False)) is not bool:
        raise ValueError('初招集の印が不正です')
    return dict(name=name,name_en=english,reading=reading,club=p['club'],position=p['position'],first_call=p.get('first_call',False))


def squad(data, material, as_of, page=0, upcoming=None):
    if not data or not data.get('announced_at'):
        return None
    if data.get('window')!=instant(as_of).astimezone(JST).strftime('%Y-%m'):
        return None
    squad_source(data)
    if instant(data['announced_at'])>instant(as_of) or not data.get('players'):
        return None
    players=[];seen=set();english_seen=set()
    for p in data['players']:
        row=squad_player(p);name=row['name']
        if name in seen or row['name_en'] in english_seen:
            raise ValueError('招集名簿の重複・所属・位置を確認してください')
        seen.add(name)
        english_seen.add(row['name_en'])
        row['stats']=season_rows(material,p['club'],p['name_en'],as_of,data['season'],name_jp=name)
        players.append(row)
    pages=[players[i:i+3] for i in range(0,len(players),3)]
    # 1人だけ余ったら前のページへ足す（4人）。2人ずつに割ると1ページ増え、28人で
    # 試合前の空き日（11/5〜12・15）に収まらず、初招集の選手が出せなかった。
    if len(pages)>1 and len(pages[-1])==1:
        pages[-2].extend(pages.pop())
    selected=pages[page] if 0<=page<len(pages) else []
    if not selected:
        return None
    import soccer_national_pitch as pitch
    for p in selected:p['league']=pitch.league_for(p['club'])
    return dict(version=1,mode='squad',as_of=as_of,source_url=data['source_url'],
        announced_at=data['announced_at'],page=page,total_pages=len(pages),
        players=selected,window=data['window'],squad_size=len(players),squad_style=pitch.STYLE,
        featured_count=len(selected),squad_roster=[squad_player(p) for p in data['players']],
        next_game=next((g for g in sorted(upcoming or [],key=lambda g:g['start_utc']) if instant(g['start_utc'])>instant(as_of)),None))


def outcome(row):
    return ('勝ちました' if row['gf']>row['ga'] else '敗れました' if row['gf']<row['ga'] else '引き分けました')


def result_sentence(row, label):
    d=datetime.fromisoformat(row['date_jst'])
    year=str(d.year)+'年' if label=='前回の対戦で日本' else ''
    particle='と' if row['gf']==row['ga'] else 'に'
    return f"{label}は{year}{d.month}月{d.day}日、{row['opponent']}{particle}{row['gf']}対{row['ga']}で{outcome(row)}。"


def history_record(rows, year):
    """確認済みの全大会を集計。PK戦は引き分け、PK得点は含めない。"""
    unique={}
    for r in rows:
        if datetime.fromisoformat(r['date_jst']).year!=year:continue
        if r['id'] in unique and any(r[k]!=unique[r['id']][k] for k in ('gf','ga','opponent','date_jst')):
            raise ValueError('親善試合の同じIDに異なる結果があります')
        unique[r['id']]=r
    games=sorted(unique.values(),key=lambda r:instant(r['start_utc']),reverse=True)
    wins=sum(r['gf']>r['ga'] for r in games);losses=sum(r['gf']<r['ga'] for r in games)
    streak=unbeaten=0
    for r in games:
        if r['gf']<=r['ga']:break
        streak+=1
    for r in games:
        if r['gf']<r['ga']:break
        unbeaten+=1
    return dict(year=year,games=len(games),wins=wins,losses=losses,draws=len(games)-wins-losses,
        gf=sum(r['gf'] for r in games),ga=sum(r['ga'] for r in games),winning_streak=streak,
        unbeaten=unbeaten,ids=[r['id'] for r in games])


def recent_pair(data, side):
    return [r for r in (data.get(side+'_previous'),data.get(side+'_recent')) if r]


def recent_sentence(data, side):
    if side=='opponent':
        r=data.get('opponent_recent')
        if not r:return ''
        d=datetime.fromisoformat(r['date_jst']);particle='と' if r['gf']==r['ga'] else 'に'
        verb='勝っています' if r['gf']>r['ga'] else '敗れています' if r['gf']<r['ga'] else '引き分けています'
        return f"{r['team']}は{d.month}月{d.day}日に{r['opponent']}{particle}{r['gf']}対{r['ga']}で{verb}。"
    if data.get('history_version')==3:
        if not data.get('history_trusted'):return ''
        r=data.get('japan_recent')
        if not r:return ''
        if r.get('competition')=='キリンカップ' and r.get('stage')=='決勝' and r['gf']>r['ga']:
            d=datetime.fromisoformat(r['date_jst'])
            return f"日本は{d.month}月のキリンカップで優勝しました。決勝は{r['opponent']}に{r['gf']}対{r['ga']}でした。"
        if r.get('competition')=='キリンカップ' and 'PK戦で勝利' in r.get('note',''):
            return 'エクアドルとは0対0からPK戦で勝ちました。'
        return result_sentence(r,'日本')
    rows=recent_pair(data,side)
    if not rows:return ''
    team=rows[-1]['team']
    if len(rows)==1:return result_sentence(rows[0],team)
    record=history_record(rows,datetime.fromisoformat(rows[-1]['date_jst']).year)
    months={r['date_jst'][:7] for r in rows}
    period=(str(datetime.fromisoformat(rows[-1]['date_jst']).month)+'月の親善試合で' if len(months)==1 else '直近2試合の親善試合で')
    if record['winning_streak']==2:
        clauses='、'.join(f"{r['opponent']}に{r['gf']}対{r['ga']}" for r in rows)
        return f'{team}は{period}、{clauses}と連勝しています。'
    clauses=[]
    for i,r in enumerate(rows):
        particle='と' if r['gf']==r['ga'] else 'に'
        forms=('勝ち','勝っています') if r['gf']>r['ga'] else ('敗れ','敗れています') if r['gf']<r['ga'] else ('引き分け','引き分けています')
        verb=forms[i==len(rows)-1]
        clauses.append(f"{r['opponent']}{particle}{r['gf']}対{r['ga']}で{verb}")
    return f"{team}は{period}、"+'、'.join(clauses)+'。'


def previous_sentence(row):
    d=datetime.fromisoformat(row['date_jst']);score=f"{row['gf']}対{row['ga']}"
    verb='勝っています' if row['gf']>row['ga'] else '敗れています' if row['gf']<row['ga'] else '引き分けています'
    return f"前回は{d.year}年{d.month}月の{row['competition']}で{score}でした。"


def minute_words(value):
    m=re.fullmatch(r'(\d+)(?:\+(\d+))?',value)
    if not m:raise ValueError('得点時刻を確認できません')
    if m[2]:return ('前半' if int(m[1])<=45 else '後半')+'追加時間'+m[2]+'分'
    return m[1]+'分'


def match_story(data):
    """完備した得点経過だけで人数集計・逆転・決勝点を計算する。"""
    empty=dict(scorers=[],comeback=False,conceded_first=False,decisive=None)
    if not data.get('goals_complete'):return empty
    game=data['game'];goals=data.get('goals') or [];ids=(JAPAN,game['opponent_id'])
    if any(sum(g['team_id']==ident for g in goals)!=game['score'][side] for ident,side in zip(ids,('japan','opponent'))):
        return empty
    def clock(g):
        minute_words(g['minute']);parts=g['minute'].split('+');return int(parts[0]),int(parts[1]) if len(parts)>1 else 0
    ordered=sorted(goals,key=clock);groups={};score={ident:0 for ident in ids};trail=False
    for goal in ordered:
        key=(goal['team_id'],'own' if goal['own_goal'] else 'unknown' if not goal['name'] else goal.get('athlete_id') or goal.get('name_en'))
        if key not in groups:groups[key]=dict(team_id=goal['team_id'],name=goal['name'],own_goal=goal['own_goal'],goals=0)
        groups[key]['goals']+=1
        score[goal['team_id']]+=1
        trail=trail or score[JAPAN]<score[ids[1]]
    jp,op=game['score']['japan'],game['score']['opponent']
    decisive=None
    if jp!=op:
        winner=JAPAN if jp>op else ids[1];threshold=min(jp,op)+1
        winner_goals=[g for g in ordered if g['team_id']==winner]
        decisive=copy.deepcopy(winner_goals[threshold-1])
    return dict(scorers=list(groups.values()),comeback=bool(jp>op and trail),
        conceded_first=bool(ordered and ordered[0]['team_id']!=JAPAN),decisive=decisive)


def scorer_sentence(data):
    story=match_story(data)
    named=[g for g in story['scorers'] if g['name'] and not g['own_goal']]
    japan=[g for g in named if g['team_id']==JAPAN]
    selected=japan or named
    if selected:
        return '、'.join(g['name']+'が'+str(g['goals'])+'点' for g in selected)+'を取りました。'
    rows=[g for g in story['scorers'] if not g['own_goal']]
    return '、'.join(('日本' if g['team_id']==JAPAN else data['game']['opponent'])+'が'+str(g['goals'])+'点' for g in rows)+'を取りました。' if rows else ''


def record_sentence(data, totals=False):
    if not data.get('history_trusted'):return ''
    year=instant(data['game']['kickoff_jst']).year
    r=history_record(data.get('japan_history') or [],year)
    if not r['games']:return ''
    text=f"{year}年は{r['games']}試合で{r['wins']}勝{r['draws']}分{r['losses']}敗です。"
    if totals:text+=f"この{r['games']}試合の合計は{r['gf']}得点、{r['ga']}失点です。"
    return text


def kickoff_sentence(g, lead):
    at=instant(g['kickoff_jst'])
    return f"{lead}は{g['opponent']}戦です。日本時間{at.month}月{at.day}日{at.hour}時{at.minute}分に始まります。"


def cup_route(data):
    if not data.get('history_trusted') or (data.get('japan_recent') or {}).get('note')!='優勝':return None
    return next((r for r in data['japan_history'] if r.get('competition')=='キリンカップ' and 'PK戦で勝利' in r.get('note','')),None)


def segments_for(data):
    mode=data['mode'];g=data.get('game');rows=[]
    def add(panel,text,**meta):
        rows.append(dict(kind='national',text=text,speaker=2,meta=dict(panel=panel,**meta)))
    if mode=='preview':
        at=instant(g['kickoff_jst']);place='シンガポールで' if g['venue_raw']=='Singapore National Stadium' else ''
        first=f'{at.month}月{at.day}日{at.hour}時{at.minute}分、日本が{place}{g["opponent"]}と戦います。'
        p=data.get('previous')
        world_rematch=p and p.get('competition')=='ワールドカップ' and p['gf']<p['ga']
        if world_rematch:
            d=datetime.fromisoformat(p['date_jst'])
            first+=f'{d.month}月のワールドカップで敗れた相手との再戦です。'
        elif p:first+=previous_sentence(p)
        add('match',first)
        if world_rematch:
            text=f"ワールドカップの{p['stage']}では{p['gf']}対{p['ga']}でした。"
            earlier=data.get('previous_earlier')
            if earlier:
                d=datetime.fromisoformat(earlier['date_jst'])
                text+=f"その前の{d.year}年{d.month}月の{earlier['competition']}では{earlier['gf']}対{earlier['ga']}で"+('勝っています。' if earlier['gf']>earlier['ga'] else '敗れています。' if earlier['gf']<earlier['ga'] else '引き分けています。')
            add('previous',text)
        add('venue','会場は'+g['venue']+'です。')
        if recent_sentence(data,'japan'):add('recent',recent_sentence(data,'japan'))
        if recent_sentence(data,'opponent'):add('opponent-recent',recent_sentence(data,'opponent'))
    elif mode=='result':
        s=g['score'];score=f"{s['japan']}対{s['opponent']}"
        if s['japan']>s['opponent']:text=f"日本が{g['opponent']}に{score}で勝ちました。"
        elif s['japan']<s['opponent']:text=f"日本は{g['opponent']}に{score}で敗れました。"
        else:text=f"日本は{g['opponent']}と{score}で引き分けました。"
        add('score',text)
        story=match_story(data)
        if story['scorers']:
            text=scorer_sentence(data)
            if story['comeback']:text+=('先に失点してからの逆転勝ちです。' if story['conceded_first'] else '一度リードを許してからの逆転勝ちです。')
            if story['decisive']:
                text+='決勝点は'+minute_words(story['decisive']['minute'])+('のオウンゴールです。' if story['decisive']['own_goal'] else 'のゴールです。')
            add('goals',text)
        elif data.get('halves') and s['japan']>s['opponent']:
            h=data['halves']
            if h['japan'][1]>0:add('halves',f"前半を{h['japan'][0]}対{h['opponent'][0]}で折り返し、後半に{h['japan'][1]}点を加えました。")
        n=data.get('next_game')
        if n:
            add('next',kickoff_sentence(n,'日本代表の次の試合')+('会場は'+n['venue']+'です。' if n.get('venue') else ''))
        elif data.get('next_known'):
            r=data['next_known'];d=datetime.fromisoformat(r['date_jst'])
            add('next-known',f"日本代表の次の試合は、{d.month}月{d.day}日の{r['competition']}、{r['opponent']}戦です。")
    elif mode=='squad':
        if data.get('squad_style')=='pitch-v1':
            import soccer_national_pitch
            return soccer_national_pitch.segments(data)
        d=instant(data['announced_at']).astimezone(JST)
        add('squad',f"{d.month}月{d.day}日に発表された日本代表の招集メンバーを、所属クラブとともに紹介します。",intro=True)
        for i,p in enumerate(data['players']):
            position={'GK':'ゴールキーパー','DF':'ディフェンダー','MF':'ミッドフィルダー','FW':'フォワード',
                'MF/FW':'ミッドフィルダー、フォワード'}.get(p['position'])
            if not position:raise ValueError('発表のポジションを確認できません')
            text=p['name']+'は'+p['club']+'所属です。発表されたポジションは'+position+'です。'
            if p.get('first_call'):text+='初めての招集です。'
            stats=p.get('stats')
            if stats:
                units={'goals':'得点','assists':'アシスト','minutes':'分出場','appearances':'試合出場'}
                a=instant(stats['as_of']).astimezone(JST)
                text+=f"今季の{stats['league']}では、"+'、'.join(str(v)+units[k] for k,v in stats['values'].items())+f"。{a.month}月{a.day}日時点です。"
            add('squad',text,player=i)
        # 27秒に届かない回（成績のないGKの3人など）だけ、発表と次の試合の確定事実を足す。
        level=data.get('length_level',0)
        if level>=2 and data.get('squad_size'):add('squad-count',f"今回の招集メンバーは{data['squad_size']}人です。")
        if data.get('next_game'):add('next',kickoff_sentence(data['next_game'],'日本代表の次の試合'))
        if level>=1 and (data.get('next_game') or {}).get('venue'):add('venue',f"次の試合の会場は{data['next_game']['venue']}です。")
    else:
        raise ValueError('未知の代表番組')
    level=data.get('length_level',0)
    has_next=bool(data.get('next_game') or data.get('next_known'))
    if mode in ('preview','result') and (level>=1 or mode=='preview') and record_sentence(data):
        rows.insert(-1 if mode=='result' and has_next else len(rows),
            dict(kind='national',text=record_sentence(data,totals=level>=2),speaker=2,meta=dict(panel='year-record')))
    if mode=='preview' and level>=3 and cup_route(data):
        r=cup_route(data)
        rows.append(dict(kind='national',text=f"キリンカップの{r['stage']}は{r['opponent']}と0対0からPK戦で勝ちました。",speaker=2,meta=dict(panel='cup-route')))
    if mode=='result' and level>=3 and g.get('venue'):
        at=instant(g['kickoff_jst'])
        rows.insert(-1 if has_next else len(rows),dict(kind='national',
            text=f"{at.month}月{at.day}日の親善試合で、会場は{g['venue']}でした。",speaker=2,meta=dict(panel='match-venue')))
    if mode=='result' and level>=4 and data.get('japan_recent'):
        rows.insert(-1 if has_next else len(rows),dict(kind='national',
            text=result_sentence(data['japan_recent'],'ひとつ前の試合で日本'),speaker=2,meta=dict(panel='recent-single')))
    return rows


def title(data):
    import soccer_title_v2 as titles
    if data['mode']=='squad':
        # 番号だけの題では誰の回か分からない。紹介する選手の名前を並べる。
        head='日本代表の招集メンバー '+'・'.join(p['name'] for p in data['players'])
    else:
        g=data['game'];at=instant(g['kickoff_jst'])
        if data['mode']=='preview':
            head=f"日本対{g['opponent']} {at.month}/{at.day} {at.hour:02d}:{at.minute:02d}"
        else:
            s=g['score'];head=f"日本{s['japan']}-{s['opponent']}{g['opponent']}"
            scorers=[r for r in match_story(data)['scorers'] if r['team_id']==JAPAN and r['name'] and not r['own_goal']]
            if scorers:head+=' '+'・'.join(r['name']+str(r['goals'])+'得点' for r in scorers)
    return titles.title(head)


@short_common.narration
def narration(data):
    d=copy.deepcopy(data)
    return dict(program='soccer_national',label=instant(d['as_of']).astimezone(JST).date().isoformat(),
        date_jst=instant(d['as_of']).astimezone(JST).date().isoformat(),title=title(d),
        segments=segments_for(d),national_material=d,duration_budget=dict(limit=60,grace=0),
        sanity_materials=[dict(source='ESPN / JFA 保存材料',sport='soccer',facts=d)])


def check(document):
    if document.get('program')!='soccer_national':
        return []
    data=document.get('national_material') or {}
    try:
        if data.get('mode')=='squad':
            squad_source(data)
            if data.get('squad_style')=='pitch-v1':
                import soccer_national_pitch
                soccer_national_pitch.validate(data)
                import soccer_national_numbers
                soccer_national_numbers.check_attached(data)
            seen=set();english_seen=set()
            for p in data['players']:
                squad_player(dict(p,name_jp=p['name']))
                if p['name'] in seen or p['name_en'] in english_seen:raise ValueError('招集名簿の重複')
                seen.add(p['name']);english_seen.add(p['name_en'])
        if data.get('mode') in ('preview','result'):
            import soccer_national_history as history
            if data.get('history_version')!=3:return ['日本の全大会の確認済み一覧による再照合が必要です']
            current=None
            if data['mode']=='result':
                g=data['game']
                current=dict(id=g['id'],date_jst=g['kickoff_jst'][:10],start_utc=g['start_utc'],team='日本',
                    opponent=g['opponent'],competition='親善試合',gf=g['score']['japan'],ga=g['score']['opponent'],source_url=g['source_url'])
                if data.get('current_result')!=current:return ['当該結果の追加材料が最終スコアと一致しません']
            verified=history.context(data['as_of'],data['game']['opponent'],data['japan_observed'],current)
            if any(data.get(k)!=v for k,v in verified.items()):
                return ['前回・直近・年間成績が確認済み全大会一覧の再計算と一致しません']
        expected=[{k:s[k] for k in ('kind','text','speaker','meta')} for s in short_common.prepare(dict(segments=segments_for(data)))['segments']]
        actual=[{k:s[k] for k in ('kind','text','speaker','meta')} for s in document.get('segments') or []]
        if actual!=expected or document.get('title')!=title(data):
            return ['日本代表の原稿・数字・得点者が保存材料と一致しません']
        if data.get('mode')=='result':
            score=data['game']['score'];counts=data['goal_counts']
            complete=counts=={JAPAN:score['japan'],data['game']['opponent_id']:score['opponent']}
            if complete!=data['goals_complete'] or (not complete and data.get('goals')):
                return ['得点イベントと最終スコアが不一致です。得点者の紹介を停止します']
            if complete and any(sum(g['team_id']==ident for g in data.get('goals',[]))!=value for ident,value in counts.items()):
                return ['紹介する得点イベントの数が一致しません']
            for goal in data.get('goals',[]):
                if not re.fullmatch(r'\d+(?:\+\d+)?',goal['minute']):return ['得点時刻を確認できません']
                expected_name=None if goal['own_goal'] else player_name(goal['name_en'],goal['team_id']==JAPAN)
                if expected_name!=goal.get('name'):return ['得点者の日本語名が既存辞書と一致しません']
            if data.get('halves') and any(sum(data['halves'][s])!=score[s] for s in ('japan','opponent')):
                return ['前後半のスコアと最終スコアが一致しません']
    except (KeyError,ValueError,TypeError):
        return ['日本代表の材料を確認できません']
    return []


def speech_readings(document):
    """公式招集台本だけへ読みを渡し、実queryの氏名検査・句結合を保つ。"""
    data=document['national_material']
    import name_reading_guard as guard
    if data['mode']=='result':
        # 結果の回：日本の得点者のうち、公式招集名簿にいる選手の読みだけを渡す。
        out={}
        for g in data.get('goals') or []:
            p=official_squad_player(g.get('name_en')) if g.get('team_id')==JAPAN and not g.get('own_goal') else None
            if not p or p['name']!=g.get('name'):
                continue
            existing=guard.player_data().get('readings',{}).get(p['name'])
            if existing and existing!=p['reading']:raise ValueError('名前の読みの守りと招集名簿が不一致です')
            out[p['name']]=('player',p['reading'])
        return out
    squad_source(data)
    if data['mode']!='squad':raise ValueError('招集回だけの読みです')
    clubs=read(ROOT/'data/soccer_national_club_readings.json')
    out={}
    for p in data['players']:
        existing=guard.player_data().get('readings',{}).get(p['name'])
        if existing and existing!=p['reading']:raise ValueError('名前の読みの守りと招集名簿が不一致です')
        out[p['name']]=('player',p['reading'])
        reading=clubs.get(p['club'])
        if not reading or not re.fullmatch(r'[ァ-ヶー]+',reading):
            raise ValueError('招集クラブの読みが未登録です: '+p['club'])
        out[p['club']]=('club',reading)
    if check(document):raise ValueError('招集台本の照合が必要です')
    return out


def information(document):
    if check(document):
        raise ValueError('日本代表の情報数を照合できません')
    d=document['national_material'];g=d.get('game');units=[]
    def add(subject,fact,value,source):
        units.append(dict(subject=subject,fact=fact,value=value,source=source,segments=[]))
    if g:
        add(g['id'],'対戦と開始予定' if d['mode']=='preview' else '試合日と対戦',
            [g['opponent'],g['kickoff_jst'] if d['mode']=='preview' else g['kickoff_jst'][:10]],g['source_url'])
        if d['mode']=='preview':
            add(g['id'],'会場',g['venue'],g['source_url'])
        else:
            add(g['id'],'最終スコア',g['score'],g['source_url'])
        panels={s['meta'].get('panel') for s in document['segments']}
        keys=('japan_recent','opponent_recent','previous','previous_earlier') if d['mode']=='preview' else ('japan_recent',) if 'recent-single' in panels else ()
        for key in keys:
            r=d.get(key)
            if r:
                add(r['id'],'過去の試合結果',[r['date_jst'],r['gf'],r['ga']],r['source_url'])
        if d.get('next_game'):
            n=d['next_game'];add(n['id'],'次の対戦と開始予定',[n['opponent'],n['kickoff_jst']],n['source_url'])
        elif d.get('next_known'):
            n=d['next_known'];add(n['id'],'次の対戦と日付',[n['opponent'],n['date_jst']],n['source_url'])
        if d.get('goals_complete') and d.get('goals'):
            add(g['id'],'得点経過',d['goals'],g['source_url'])
        if d.get('halves') and 'halves' in panels:add(g['id'],'前半終了と試合終了',d['halves'],g['source_url'])
        if 'match-venue' in panels:add(g['id'],'会場',g['venue'],g['source_url'])
        if 'year-record' in panels:
            record=history_record(d.get('japan_history') or [],instant(g['kickoff_jst']).year)
            add('日本','確認済み当年全大会成績',record,d['history_sources'])
        if 'cup-route' in panels:
            r=cup_route(d);add(r['id'],'キリンカップのPK勝利',[r['gf'],r['ga'],'PK戦勝利'],r['source_url'])
    else:
        for p in d['players']:
            add(p['name'],'招集と所属クラブ',p['club'],d['source_url'])
            if p.get('first_call'):add(p['name'],'日本代表初招集',True,d['source_url'])
        if d.get('next_game'):
            g=d['next_game'];add(g['id'],'次の対戦と開始予定',[g['opponent'],g['kickoff_jst']],g['source_url'])
    return units


def squad_description(d):
    """招集の回の概要欄。台本の流し込みをやめ、材料にある名前・所属・数字だけで組む。"""
    players=d.get('players') or []
    names='・'.join(p['name'] for p in players)
    try:
        day=instant(d['announced_at']).astimezone(JST);head=f"{day.month}月{day.day}日にJFAが発表した"
    except (KeyError,TypeError,ValueError):head='JFAが発表した'
    lines=[f"{head}日本代表の招集メンバーから、{names}を紹介します。",'']
    units={'goals':'得点','assists':'アシスト','minutes':'分出場','appearances':'試合出場'}
    for p in players:
        row=f"・{p['name']}（{p['club']}）"
        src=p.get('season_numbers') or p.get('stats') or {}
        vals=[str(v)+units[k] for k,v in (src.get('values') or {}).items() if k in units]
        if vals:row+=' 今季'+'・'.join(vals)
        lines.append(row)
    g=d.get('next_game')
    if g and g.get('kickoff_jst') and g.get('opponent'):
        at=instant(g['kickoff_jst'])
        lines+=['',f"次の代表戦：{g['opponent']}戦 日本時間{at.month}月{at.day}日{at.hour}時{at.minute:02d}分"]
    return '\n'.join(lines)


def metadata(document):
    if check(document):
        raise ValueError('代表番組の原稿検査に失敗しました')
    d=document['national_material'];g=d.get('game')
    links=[g['source_url']] if g else [d['source_url']]
    links += [d[k]['source_url'] for k in ('japan_recent','opponent_recent','japan_previous','opponent_previous','previous','previous_earlier','next_game','next_known') if d.get(k)]
    links += d.get('history_sources',[])
    links += [p['stats']['source'] for p in d.get('players',[]) if p.get('stats')]
    if d.get('length_level',0)>=1:links += [r['source_url'] for r in d.get('japan_history') or []]
    text='\n'.join(s['text'] for s in document['segments'])
    if d.get('mode')=='squad':
        text=squad_description(d)
        text+='\n\n図はJFAが発表したポジションの名簿順です。先発やフォーメーションの予想ではありません。MF/FWは一括発表です。'
        links += [p['season_numbers']['source'] for p in d.get('players',[]) if p.get('season_numbers')]
        if d.get('national_numbers'):text+='\n今季成績の取得日: '+instant(d['national_numbers']['as_of']).astimezone(JST).strftime('%Y/%m/%d')
    # ESPNの成績APIのURLは読み手に意味が無いので外し、名前だけ書く。試合ページ(www.espn.com)は残す。
    shown=[u for u in dict.fromkeys(links) if urlparse(u).hostname!='sports.core.api.espn.com']
    dropped=len(shown)<len(set(links))
    names=[p['name'] for p in d.get('players',[])][:3]
    tagline=' '.join(['#サッカー日本代表',*['#'+n for n in names],'#Shorts'])
    return dict(snippet=dict(title=document['title'],description=text+'\n\n'+tagline+'\n\n出典\n'+'\n'.join(shown)+
        ('\n今季成績: ESPN' if dropped else '')+
        '\n音声: VOICEVOX:四国めたん',tags=['サッカー','日本代表','コレスポ',*names],categoryId='17',
        defaultLanguage='ja',defaultAudioLanguage='ja'))


def fetch_snapshot(directory, now, days=12):
    """1日ずつ取得。生応答はbuild内だけに保存。キー・有料API不要。"""
    import requests
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    def get(endpoint,params,filename,base=API):
        response=requests.get(base+endpoint,params=params,timeout=30)
        response.raise_for_status();d=response.json();save(directory/filename,d);return d
    boards=[]
    for i in range(-2,days+1):
        day=(now.astimezone(JST).date()+timedelta(days=i)).strftime('%Y%m%d')
        boards.append(get('scoreboard',{'dates':day},'scoreboard_'+day+'.json'))
    games=japan_matches(boards)
    schedules={}
    for ident in {JAPAN,*[g['opponent_id'] for g in games]}:
        schedules[ident]=get('teams/'+ident+'/schedule',{'season':now.year},'schedule_all_'+ident+'.json',ALL_API)
    # 日本の履歴はローカルの確認済み一覧。ESPNは未収載試合の検知だけに使う。
    return games,schedules,{}


def choose(games, schedules, previous, now, ledger, summary_loader, squad_data=None, club_material=None):
    """1日1本の台帳。結果→前日予告→招集分冊の順。遅延した古い回は出さない。"""
    local=now.astimezone(JST);day=local.date().isoformat()
    if ledger.get('soccer_national',{}).get(day):
        return None
    for g in games:
        kick=instant(g['start_utc']).astimezone(JST)
        entries=ledger.get('soccer_national',{}).values()
        result_done=any(e.get('national_mode')=='result' and e.get('national_event_id')==g['id'] for e in entries)
        target=kick.replace(hour=22,minute=0) if kick.hour<20 else (kick+timedelta(days=1)).replace(hour=8,minute=0)
        target=target.replace(second=0,microsecond=0)
        # 結果は定時の回ではない（11/14 本人「0時超えても普通に投稿していい」）。22時の回は翌日12時まで
        # 途切れずに出す。0時〜7時はすぐ、7時〜12時は8:00（これまでの朝の枠）に予約する。
        end=target.replace(hour=12) if target.hour==8 else (target+timedelta(days=1)).replace(hour=12)
        due=target-timedelta(minutes=45)<=local<end
        fallback=kick.hour<20 and local.date()==target.date()+timedelta(days=1) and 7<=local.hour<12
        if not result_done and (due or fallback):
            summary=summary_loader(g['id'])
            if summary['header']['competitions'][0].get('status',{}).get('type',{}).get('completed'):
                d=result(summary,games,schedules[JAPAN],now.isoformat())
                if fallback:target=local.replace(hour=8,minute=0,second=0,microsecond=0)
                d['publish_at']=max(target,(local+timedelta(minutes=21)).replace(second=0,microsecond=0)).isoformat()
                return d
        target=(kick-timedelta(days=1)).replace(hour=19,minute=30,second=0,microsecond=0)
        if local.date()==target.date() and target-timedelta(hours=7)<=local<target.replace(hour=22,minute=0):
            d=preview(g,schedules[JAPAN],schedules[g['opponent_id']],previous,now.isoformat())
            d['publish_at']=max(target,(local+timedelta(minutes=21)).replace(second=0,microsecond=0)).isoformat()
            return d
    occupied={instant(g['kickoff_jst']).date() for g in games}
    occupied|={instant(g['kickoff_jst']).date()-timedelta(days=1) for g in games}
    occupied|={instant(g['kickoff_jst']).date()+timedelta(days=1) for g in games if instant(g['kickoff_jst']).hour>=20}
    # 10:15 の定時起動は実際には 12:34〜13:00 に動いていた（11/2〜4）。12時までに限ると
    # 招集の回が1本も出ないので、夕方の予告の時間帯の前（20時）まで受け付ける。
    if squad_data and local.date() not in occupied and 10<=local.hour<20:
        finished={e.get('national_squad_page') for e in ledger.get('soccer_national',{}).values() if e.get('national_squad_page') is not None}
        page=next(i for i in range(100) if i not in finished)
        d=squad(squad_data,club_material or {},now.isoformat(),page,upcoming=games)
        # 試合が全部終わった後の招集紹介は出さない（模擬で最後の1ページが 11/19 になった）。
        if d and d.get('next_game'):
            d['publish_at']=max(local.replace(hour=12,minute=0,second=0,microsecond=0),
                                (local+timedelta(minutes=21)).replace(second=0,microsecond=0)).isoformat()
            return d
    return None


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_national')
    ap.add_argument('--squad',type=Path,default=ROOT/'data/soccer_national_squad.json')
    args=ap.parse_args(argv)
    args.out.mkdir(parents=True,exist_ok=True)
    marker=args.out/'gate.json'
    save(marker,dict(can_make=False,reason='既定off'))
    if not enabled() and not __import__('sample_only').enabled():
        print('日本代表の生成・公開は既定offです');return
    now=datetime.now(timezone.utc)
    games,schedules,previous=fetch_snapshot(args.out/'raw',now)
    def summary(ident):
        import requests
        r=requests.get(API+'summary',params={'event':ident},timeout=30);r.raise_for_status()
        d=r.json();save(args.out/'raw'/('summary_'+ident+'.json'),d);return d
    data=choose(games,schedules,previous,now,{} if __import__('sample_only').enabled() else read(ROOT/'data/published_videos.json'),summary,
        read(args.squad) if args.squad.exists() else None,read(ROOT/'data/soccer_games.json'))
    if not data:
        save(marker,dict(can_make=False,reason='対象枠・終了結果・発表済みメンバーなし'));return
    if data['mode']=='squad':
        import soccer_national_numbers as numbers
        roster=read(args.squad)
        selected={p['name'] for p in data['players']}
        requested=dict(roster,players=[p for p in roster['players'] if p['name_jp'] in selected])
        sheet=numbers.collect(requested,now.isoformat(),args.out/'raw'/'numbers')
        save(args.out/'numbers.json',sheet)
        data=numbers.attach(data,sheet)
    narr=narration(data)
    if check(narr):
        raise ValueError(check(narr))
    save(args.out/'material.json',data);save(args.out/'narration.json',narr)
    save(marker,dict(can_make=True,publish_at=data['publish_at'],date_jst=narr['date_jst'],warnings=data.get('history_warnings',[])))


if __name__=='__main__':
    main()
