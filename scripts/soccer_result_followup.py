"""予告と結果をクラブ・開始時刻で照合。数字がない項目は省く。"""
import copy
import json
from pathlib import Path
import club_display_names as clubs
import soccer_results as results
ROOT=Path(__file__).resolve().parents[1]


def load_preview(day,path=None):
    path=Path(path or ROOT/'data/soccer_preview_history.json')
    if not path.exists():return None
    try:
        history=json.loads(path.read_text(encoding='utf8'))
        value=history.get(day) if isinstance(history,dict) else None
    except (OSError,ValueError) as error:
        print('[omit] 前夜予告の保存記録を確認できません:',type(error).__name__);return None
    return value if value and value.get('video_id') else None


def match(preview,home,away,start):
    if not preview:return None
    identity=lambda name:(clubs.lookup(name) or {}).get('id')
    pair=(identity(home),identity(away))
    if None in pair:return None
    candidates=[p for p in preview['games'] if (identity(p['home']),identity(p['away']))==pair and results.utc(p['start_utc'])==results.utc(start)]
    return candidates[0] if len(candidates)==1 else None


def attach(data,preview,extras=None,standings_before=None,standings_after=None,next_games=None):
    data=copy.deepcopy(data)
    if not preview:return data
    ordered=[];extras=extras or {};before=standings_before or {};after=standings_after or {}
    data['preview_expectation_results']=copy.deepcopy(extras)
    data['preview_next_fixtures']=copy.deepcopy(next_games or [])
    for announced in preview.get('games',[]):
        games=[g for g in data['games'] if match(dict(games=[announced]),g['home']['name_en'],g['away']['name_en'],g['start_utc'])]
        if len(games)!=1:continue  # 延期・未終了・取得不足は勝敗を作らない。
        game=games[0];expectation=announced.get('expectation');answer=None
        if expectation:
            candidates=[p for p in game['players']+extras.get(game['id'],[]) if p['name']==expectation['name']]
            if len(candidates)==1:answer=copy.deepcopy(candidates[0])
        changes=[]
        for side in ('home','away'):
            club=(clubs.lookup(game[side]['name_en']) or {}).get('id');b=before.get(club) or {};a=after.get(club) or {}
            # 同じ大会/シーズンの前後、同じクラブの順位が明示されている時だけ。
            if b.get('competition')!=a.get('competition') or b.get('season')!=a.get('season') or not b.get('competition') or not b.get('season'):continue
            if not b.get('source') or b.get('source')!=a.get('source'):continue
            if not b.get('as_of') or not a.get('as_of'):continue
            if results.utc(b['as_of'])>=results.utc(game['start_utc']) or results.utc(a['as_of'])<results.utc(game['finished_utc']):continue
            if all(type(v) is int and v>0 for v in (b.get('rank'),a.get('rank'))) and b['rank']!=a['rank']:
                changes.append(dict(club=game[side]['name_jp'],before=b['rank'],after=a['rank'],evidence=dict(before=b,after=a)))
        upcoming=[]
        for row in next_games or []:
            ids={(clubs.lookup(row.get(s)) or {}).get('id') for s in ('home','away')}
            if not row.get('source') or None in ids:continue
            if not ids.intersection((clubs.lookup(game[s]['name_en']) or {}).get('id') for s in ('home','away')):continue
            if not row.get('start_utc') or results.utc(row['start_utc'])<=results.utc(game['finished_utc']):continue
            upcoming.append(row)
        upcoming.sort(key=lambda r:results.utc(r['start_utc']))
        ordered.append(dict(event_id=game['id'],forecast=announced,answer=answer,rank_changes=changes,next_game=upcoming[0] if upcoming else None))
    if ordered:
        ids=[r['event_id'] for r in ordered];data['games'].sort(key=lambda g:ids.index(g['id']) if g['id'] in ids else len(ids))
        data['preview_followup']=dict(day=preview['day'],video_id=preview['video_id'],games=ordered)
        data['can_make']=True
    return data


def validate(data):
    followup=data.get('preview_followup')
    if not followup:return
    if followup['day']!=data['date_jst'] or not followup.get('video_id'):raise ValueError('予告の対象日/公開記録が不一致')
    for row in followup['games']:
        games=[g for g in data['games'] if g['id']==row['event_id']]
        if len(games)!=1:raise ValueError('予告の結果IDを照合できません')
        g=games[0]
        if not match(dict(games=[row['forecast']]),g['home']['name_en'],g['away']['name_en'],g['start_utc']):raise ValueError('予告と結果のクラブ/日時が不一致')
        answer=row.get('answer')
        if answer:
            if answer['name']!=row['forecast']['expectation']['name'] or answer['event_id']!=g['id'] or answer['club'] not in (g['home']['name_jp'],g['away']['name_jp']):raise ValueError('期待選手の結果が別の試合/クラブです')
            if answer['status'] not in results.STATUS:raise ValueError('期待選手の出場区分が不明')
            if answer['status']=='none' and (answer.get('goals') or answer.get('assists')):raise ValueError('出場なしなのに得点/アシスト')
            candidates=g['players']+data.get('preview_expectation_results',{}).get(g['id'],[])
            if answer not in candidates:raise ValueError('期待選手の数字が取得材料と一致しません')
            for key in ('goals','assists'):
                if answer.get(key) is not None and (type(answer[key]) is not int or answer[key]<0):raise ValueError('期待選手の数字が不正')
        for change in row['rank_changes']:
            before=change['evidence']['before'];after=change['evidence']['after']
            if change['before']!=before['rank'] or change['after']!=after['rank']:raise ValueError('順位と照合材料が不一致')
            if before['competition']!=after['competition'] or before['season']!=after['season'] or before['source']!=after['source']:raise ValueError('順位の大会/集計範囲が不一致')
            if results.utc(before['as_of'])>=results.utc(g['start_utc']) or results.utc(after['as_of'])<results.utc(g['finished_utc']):raise ValueError('順位の前後時刻が不正')
        if row.get('next_game') and row['next_game'] not in data.get('preview_next_fixtures',[]):raise ValueError('次の試合が取得材料と不一致')
