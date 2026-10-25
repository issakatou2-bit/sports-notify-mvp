"""取得済みの値だけで予告の注目理由/期待選手を決める。LLM・通信・欠測の推論なし。"""
import copy
from datetime import datetime
import functools
import json
import math
from pathlib import Path

import club_display_names as clubs
import name_reading_guard as readings

ROOT=Path(__file__).resolve().parents[1]


def number(value,minimum=0):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=minimum


@functools.lru_cache(maxsize=1)
def derbies():
    return json.loads((ROOT/'data/soccer_derbies.json').read_text(encoding='utf8'))['pairs']


def club_id(name):
    return (clubs.lookup(name) or {}).get('id')


def point_gap(home,away):
    for key in ('points','points_back'):
        a,b=home.get(key),away.get(key)
        if number(a) and number(b) and a==int(a) and b==int(b):return abs(a-b)
    return None


def timestamp(text):
    try:
        value=datetime.fromisoformat(str(text).replace('Z','+00:00'))
        return value if value.tzinfo else None
    except ValueError:return None


def expectation(game):
    """今季3得点/3アシスト以上。総合順位のない材料を上位と呼ばない。"""
    pool=[]
    for row in game.get('season_players') or []:
        if not isinstance(row,dict):continue
        if row.get('scope')!='season' or row.get('out') is True:continue
        if row.get('minutes') is not None and not number(row['minutes'],1):continue
        identity=club_id(row.get('club'))
        if identity is None or identity not in {club_id(game.get(s+'_team_name')) for s in ('home','away')}:continue
        if not row.get('source'):continue
        at=timestamp(row.get('as_of'));kick=timestamp(game.get('start_time_utc'))
        if not at or not kick or not 0<=(kick-at).total_seconds()<=48*3600:continue
        goals,assists=row.get('goals'),row.get('assists')
        if any(v is not None and (not number(v) or v!=int(v)) for v in (goals,assists)):continue
        if not (number(goals) or number(assists)):continue
        if not any(number(v) and v>=3 for v in (goals,assists)):continue
        raw=row.get('name') or row.get('name_en')
        if not isinstance(raw,str):continue
        canonical=readings.player_data().get('reading_aliases',{}).get(raw,raw)
        if canonical in (game.get('preview_out_names') or []):continue
        if not canonical or not readings.player_reading(canonical):
            print('[omit] 期待選手の表示/読みが未登録: '+str(raw))
            continue
        pool.append(dict(name=canonical,club=row['club'],goals=goals,assists=assists,
                         japanese=canonical in readings.player_data()['japanese_players'],
                         source=row['source'],as_of=row['as_of']))
    return max(pool,key=lambda p:(p['japanese'],max(p.get('goals') or 0,p.get('assists') or 0),
                                 (p.get('goals') or 0)+(p.get('assists') or 0),p['name'])) if pool else None


def attach_season_stats(data,availability=None):
    """既存FPL保存分の今季集計。別試合の数字や古いsnapshotを今の数字にしない。"""
    data=copy.deepcopy(data)
    if availability is None:
        try:availability=json.loads((ROOT/'data/soccer_availability.json').read_text(encoding='utf8'))
        except (OSError,ValueError):return data
    if availability.get('source')!='https://fantasy.premierleague.com/api/bootstrap-static/':return data
    for game in data.get('games',[]):
        if 'season_players' in game:continue  # 上流で集計した値を上書きしない。
        if not game.get('start_time_utc'):
            import soccer_slots_v4
            game['start_time_utc']=soccer_slots_v4.kickoff(game,data['generated_at']).isoformat()
        game['season_players']=[]
        for name,row in availability.get('players',{}).items():
            identity=club_id(row.get('club_jp'))
            if identity is None or identity not in {club_id(game.get(s+'_team_name')) for s in ('home','away')}:continue
            game['season_players'].append(dict(name=name,club=row['club_jp'],scope='season',
                 goals=row.get('goals'),assists=row.get('assists'),minutes=row.get('minutes'),out=row.get('out'),
                 as_of=availability.get('updated_at'),source=availability['source']))
    return data


def decide(game,limit=2):
    reasons=[]
    pair={club_id(game.get(s+'_team_name')) for s in ('home','away')}
    if None not in pair:
        for derby in derbies():
            if pair==set(derby['clubs']):reasons.append(dict(kind='derby',text=derby['name'],source=derby['source']));break
    home=game.get('home_standing');home=home if isinstance(home,dict) else {}
    away=game.get('away_standing');away=away if isinstance(away,dict) else {}
    ranks=[home.get('rank'),away.get('rank')];gap=point_gap(home,away)
    valid_ranks=all(type(r) is int and r>0 for r in ranks) and ranks[0]!=ranks[1]
    if valid_ranks:
        named='対'.join(('首位' if rank==1 else f'{rank}位')+(clubs.lookup(game.get(side+'_team_name')) or {}).get('display',game.get(side+'_team_name','')) for side,rank in zip(('home','away'),ranks))
        a,b=sorted(ranks);cut=game.get('cl_line');drop=game.get('relegation_line')
        if a==1 and b<=3 and gap is not None and gap<=3:
            reasons.append(dict(kind='title',text=named+'の首位争い',ranks=ranks,gap=gap))
        elif type(cut) is int and cut>0 and a<=cut<b and b-a<=2 and gap is not None and gap<=3:
            reasons.append(dict(kind='cl',text='CL圏の境目 '+named,line=cut,ranks=ranks,gap=gap))
        elif type(drop) is int and drop>0 and a>=drop-2 and gap is not None and gap<=3:
            reasons.append(dict(kind='relegation',text='残留争い '+named,line=drop,ranks=ranks,gap=gap))
        elif b-a<=3:reasons.append(dict(kind='rank',text=named+f'、順位差{b-a}の直接対決',ranks=ranks,rank_difference=b-a))
        elif a==1:reasons.append(dict(kind='leader',text=named,ranks=ranks))
    if gap is not None:reasons.append(dict(kind='points',text=f'勝点差{gap:g}',gap=gap))
    for side,label,standing in [('home','ホーム側',home),('away','アウェー側',away)]:
        form=standing.get('last_five')
        if not isinstance(form,list) or len(form)!=5 or not all(v in ('W','D','L') for v in form):continue
        count=0
        for v in reversed(form):
            if v!=form[-1]:break
            count+=1
        tail=f'{count}連勝' if form[-1]=='W' and count>=3 else f'{count}連敗' if form[-1]=='L' and count>=3 else ''
        value=tail or f'直近5試合 {form.count("W")}勝{form.count("D")}分{form.count("L")}敗'
        reasons.append(dict(kind='form',text=label+' '+value,side=side,form=form))
    previous=game.get('previous_season_h2h')
    if isinstance(previous,dict) and previous.get('season') is not None and game.get('season') is not None:
        if type(previous['season']) is int and type(game['season']) is int and previous['season']==game['season']-1:
            prev_pair={club_id(previous.get(s+'_team_name')) for s in ('home','away')}
            scores=previous.get('score') or {}
            if pair==prev_pair and None not in pair and all(type(scores.get(s)) is int and scores[s]>=0 for s in ('home','away')):
                side='home' if club_id(previous['home_team_name'])==club_id(game['home_team_name']) else 'away'
                other='away' if side=='home' else 'home'
                reasons.append(dict(kind='h2h',text=f'昨季対戦 今回のホーム側が{scores[side]}対{scores[other]}',source=previous))
    # 補足がどれも同じ勝点差だけになる場合を避ける。取れた試合固有の要素を先に。
    order={'derby':0,'title':1,'cl':1,'relegation':1,'form':2,'h2h':3,'leader':4,'rank':4,'points':5}
    reasons=sorted(reasons,key=lambda r:order[r['kind']])[:limit]
    return dict(reasons=reasons,player=expectation(game))


def player_numbers(player):
    return ' '.join(f'{player[k]:g}{unit}' for k,unit in [('goals','得点'),('assists','アシスト')] if number(player.get(k)))


def stats_label(player):
    return '今季FPL集計' if player.get('source')=='https://fantasy.premierleague.com/api/bootstrap-static/' else '今季'


def same_slot(game,meta,generated):
    if any(game.get(key+'_team_name')!=meta.get(key) for key in ('home','away')):return False
    if game.get('league')!=meta.get('league'):return False
    import soccer_slots_v4
    try:at=soccer_slots_v4.kickoff(game,generated)
    except (ValueError,KeyError,TypeError):return False
    day=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）'
    return meta.get('date')==day and meta.get('time')==at.strftime('%H:%M')


def enrich_plan(plan):
    plan=copy.deepcopy(plan);facts={}
    games={str(g['game_id']):g for g in plan['data'].get('games',[])}
    for seg in plan['narration']['segments']:
        if seg['kind']!='preview':continue
        meta=seg['meta'];matches=[g for g in games.values() if same_slot(g,meta,plan['data']['generated_at'])]
        if len(matches)!=1:
            print('[omit] 注目理由: 試合と材料の日時を一意に照合できません')
            continue
        game=matches[0];meta['game_id']=str(game['game_id'])
        interest=decide(game);meta['interest']=interest;facts[str(game['game_id'])]=interest
        if interest['reasons']:seg['text']+='。'.join(r['text'] for r in interest['reasons'])+'。'
        player=interest['player']
        if player:
            meta['expectation_name']=player['name']
            seg['text']+=f'期待選手は{player["name"]}。{stats_label(player)}で{player_numbers(player)}です。'
    plan['data']['match_interest']=facts
    if any((row.get('player') or {}).get('source')=='https://fantasy.premierleague.com/api/bootstrap-static/' for row in facts.values()):
        credit=plan['shared']['source']+'・FPL'
        plan['shared']['source']=credit
        for seg in plan['narration']['segments']:seg['meta']['source']=credit
    return plan
