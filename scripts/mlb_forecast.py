"""19時の数字つき期待を保存し、同じ試合の17時成績と照合する。"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/'data/mlb_forecast_history.json'
JST=timezone(timedelta(hours=9))


def enabled():return os.environ.get('COLLESPO_MLB_FORECAST')=='check'


def read(path):
    path=Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def binding(narration):return dict(mlb_narration_sha256=digest(narration))


def past(created, directory=None):
    directory=Path(directory or ROOT/'data/recap_history')
    cutoff=datetime.fromisoformat(created.replace('Z','+00:00'))
    if cutoff.tzinfo is None:raise ValueError('予告の作成時刻に時差がありません')
    out=[]
    for path in sorted(directory.glob('*.json')):
        data=read(path)
        stamp=data.get('updated_at')
        if not stamp:continue
        observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if observed.tzinfo is None or observed>cutoff:continue
        if str(data.get('date_jst') or '')>cutoff.astimezone(JST).date().isoformat():continue
        for p in data.get('players',[]):
            out.append(dict(p,day=data.get('date_jst'),source=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)))
    return out


def expectation(games, created, directory=None):
    import sys
    sys.path.insert(0,str(ROOT))
    import notability_engine as ne
    known={p['name_en']:p for p in ne.JP_PLAYERS_MLB}
    samples=past(created,directory)
    tomorrow=(datetime.fromisoformat(created.replace('Z','+00:00')).astimezone(JST).date()+timedelta(days=1)).isoformat()
    for game in games:
        start=game.get('start_time_jst')
        if not start or not game.get('game_id'):continue
        try:
            when=datetime.fromisoformat(start.replace('Z','+00:00'))
            if when.tzinfo is None:continue
        except ValueError:
            try:when=datetime.strptime(tomorrow[:4]+'/'+start,'%Y/%m/%d %H:%M').replace(tzinfo=JST)
            except ValueError:continue
        target=when.astimezone(JST).date().isoformat()
        if target!=tomorrow:continue
        candidates=[]
        for side in ('home','away'):
            probable=game.get(side+'_probable') or {}
            name=probable.get('name_en') or probable.get('name')
            player=known.get(name) or next((p for p in known.values() if p['name_jp']==probable.get('name')),None)
            if player and probable.get('player_id'):
                candidates.append((player, str(probable['player_id']), 'pitcher'))
        for name in game.get('jp_players',[]):
            player=next((p for p in known.values() if p['name_jp']==name and p['type']=='batter'),None)
            if player:
                ids={str(p['player_id']) for p in samples if p.get('name')==name and p.get('type')=='batter'}
                if len(ids)==1:candidates.append((player,ids.pop(),'batter'))
        for player,pid,typ in candidates:
            recent=[p for p in samples if str(p.get('player_id'))==pid and p.get('type')==typ
                    and (typ!='pitcher' or p.get('gs')==1)]
            recent=[p for p in recent if str(p['day'])[:4]==tomorrow[:4]][-5:]
            field='so' if typ=='pitcher' else 'hits'
            recent=[p for p in recent if type(p.get(field)) is int]
            if len(recent)<3:continue
            if typ=='pitcher':
                mean=sum(p[field] for p in recent)/len(recent)
                target_value=max(1,math.floor(mean+.5));unit='奪三振'
                basis=f'番組で集計した先発{len(recent)}日分は平均{mean:.1f}奪三振'
            else:
                target_value=1;unit='安打'
                basis=f'番組で集計した{len(recent)}日分で安打が出たのは{sum(p[field]>0 for p in recent)}日'
            name=player['name_jp']
            spoken=f'{name}は{basis}。明日は{target_value}{unit}以上に注目です。'
            return dict(created_at=created,target_day=tomorrow,game_id=str(game['game_id']),
                        start_time_jst=start,player_id=pid,name=name,type=typ,field=field,threshold=target_value,
                        basis=basis,spoken=spoken,samples=[{k:p[k] for k in ('day','source',field)} for p in recent],
                        period=dict(start=recent[0]['day'],end=recent[-1]['day']),
                        source='MLB公式 Stats API の保存成績。直近は取得できた材料の範囲')
    return None


def decorate(narration,games,created,directory=None):
    if not enabled():return narration
    out=copy.deepcopy(narration)
    prediction=expectation(games,created,directory)
    if not prediction:return out
    for seg in out.get('segments',[]):
        meta=seg.get('meta') or {}
        index=meta.get('game_index')
        ids=meta.get('game_ids') or []
        match=(type(index) is int and 0<=index<len(games) and str(games[index].get('game_id'))==prediction['game_id'])
        if seg.get('kind') in ('game','preview','ps_program') and (match or [prediction['game_id']]==[str(x) for x in ids]):
            seg['text']+=prediction['spoken'];seg.setdefault('meta',{})['mlb_forecast']=prediction
            out['mlb_forecast']=prediction
            return out
    return out


def official_games(evidence):
    games=[]
    for day in evidence.get('schedule',{}).get('dates',[]):
        for g in day.get('games',[]):
            row=dict(game_id=g['gamePk'],start_time_jst=g.get('gameDate'),jp_players=[])
            for side in ('home','away'):
                p=(g.get('teams',{}).get(side) or {}).get('probablePitcher') or {}
                row[side+'_probable']=dict(player_id=p.get('id'),name_en=p.get('fullName'))
            games.append(row)
    return games


def decorate_program(program,evidence,created,key_fn):
    if not enabled() or program.get('kind')!='daily':return program
    out=decorate(dict(segments=program['segments']),official_games(evidence),created)
    if not out.get('mlb_forecast'):return program
    program=copy.deepcopy(program);program['segments']=out['segments'];program['mlb_forecast']=out['mlb_forecast']
    program['edition_key']=key_fn(program)
    return program


def snapshot(narration,published):
    prediction=narration.get('mlb_forecast')
    if not prediction:return None
    day=datetime.fromisoformat(prediction['created_at'].replace('Z','+00:00')).astimezone(JST).date().isoformat()
    entry=(published.get('daily') or {}).get(day) or {}
    if not entry.get('video_id') or entry.get('preview_binding')!=binding(narration):
        raise ValueError('実際の予告と原稿hashを照合できません')
    return dict(prediction,video_id=entry['video_id'],preview_day=day,binding=binding(narration))


def answer(data, history=None):
    if not enabled():return None
    records=history if history is not None else read(HISTORY)
    forecast=records.get(data.get('date_jst'))
    if not forecast or not forecast.get('video_id'):return None
    if (datetime.fromisoformat(forecast['preview_day']).date()+timedelta(days=1)).isoformat()!=data.get('date_jst'):return None
    players=[p for p in data.get('players',[]) if str(p.get('player_id'))==forecast['player_id']
             and p.get('type')==forecast['type']]
    if len(players)!=1:return None
    p=players[0]
    # ダブルヘッダーの日合計や別の試合を混ぜない。
    if p.get('game_ids')!=[forecast['game_id']]:return None
    value=p.get(forecast['field'])
    if type(value) is not int:return None
    if forecast['type']=='pitcher' and float(p.get('ip') or 0)<=0 and not any(
        (p.get(key) or 0)>0 for key in ('gs','hits','er','bb','so')):return None
    if forecast['type']=='batter' and (p.get('pa') or 0)<=0:return None
    unit='奪三振' if forecast['field']=='so' else '安打'
    result='届きました' if value>=forecast['threshold'] else '届きませんでした'
    return dict(kind='forecast_check',speaker=2,min_duration=.5,
                text=f'昨夜は{forecast["name"]}の{forecast["threshold"]}{unit}以上に注目しました。結果は{value}{unit}で{result}。',
                meta=dict(forecast=forecast,actual=value,met=value>=forecast['threshold']))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--narration',default='public/narration.json')
    ap.add_argument('--published',default='data/published_videos.json')
    ap.add_argument('--out',type=Path,default=HISTORY)
    args=ap.parse_args()
    if not enabled():return
    record=snapshot(read(args.narration),read(args.published))
    if not record:return
    history=read(args.out);history[record['target_day']]=record
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('MLBの予告を保存:',record['target_day'],record['name'])


if __name__=='__main__':main()
