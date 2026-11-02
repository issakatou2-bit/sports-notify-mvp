"""日本代表の確認済み全大会一覧。大会別ESPNから網羅性を推定しない。"""
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/'data/soccer_national_results.json'
JST=timezone(timedelta(hours=9))
MAX_AGE_DAYS=21


def load():
    return json.loads(PATH.read_text(encoding='utf8'))


def row(value, sources, opponent=None):
    r=copy.deepcopy(value)
    r.update(id='verified:'+r['date']+':'+(opponent or r['opponent']),date_jst=r['date'],
        start_utc=r['date']+'T00:00:00+09:00',team='日本',opponent=opponent or r['opponent'],
        source_url=sources[0])
    if type(r['gf']) is not int or type(r['ga']) is not int or min(r['gf'],r['ga'])<0:
        raise ValueError('確認一覧の得失点が不正です')
    expected='win' if r['gf']>r['ga'] else 'loss' if r['gf']<r['ga'] else 'draw'
    if r.get('result')!=expected:raise ValueError('確認一覧の勝敗とスコアが不一致です')
    return r


def context(as_of, opponent, observed=(), current=None):
    source=load();at=datetime.fromisoformat(as_of.replace('Z','+00:00')).astimezone(JST)
    # 結果見本の集計上限はその試合の日。次の試合は別用途でのみ参照。
    cutoff=current['date_jst'] if current else at.date().isoformat()
    all_rows=[row(v,source['sources']) for v in source['matches']]
    by_key={}
    for r in all_rows:
        key=(r['date_jst'],r['opponent'])
        if key in by_key:raise ValueError('確認一覧の試合が重複しています')
        by_key[key]=r
    rows=[r for r in all_rows if r['date_jst']<=cutoff]
    if current:
        key=(current['date_jst'],current['opponent'])
        if key in by_key:
            if any(current[k]!=by_key[key][k] for k in ('gf','ga')):
                raise ValueError('当該ESPN確定結果と確認一覧が不一致です')
        else:
            rows.append(copy.deepcopy(current))
    warnings=[]
    age=(at.date()-datetime.fromisoformat(source['checked_at']).date()).days
    if age>MAX_AGE_DAYS:warnings.append(f'確認済み一覧の更新から{age}日経過（上限{MAX_AGE_DAYS}日）。日本の履歴の断定を省略')
    latest=max(r['date_jst'] for r in all_rows)
    for r in observed:
        key=(r['date_jst'],r['opponent'])
        if r['date_jst']>cutoff:continue
        if key in by_key:
            if any(r[k]!=by_key[key][k] for k in ('gf','ga')):
                warnings.append('ESPNと確認一覧の結果が不一致: '+str(key))
        elif current and key==(current['date_jst'],current['opponent']):
            if any(r[k]!=current[k] for k in ('gf','ga')):raise ValueError('追加結果とESPN一覧が不一致です')
        elif r['date_jst']>latest:
            warnings.append('一覧より新しい終了済み試合が未収載: '+str(key))
    meetings=[row(v,source['sources'],opponent) for v in source.get('previous_meetings',{}).get(opponent,[])]
    meetings += [r for r in rows if r['opponent']==opponent]
    # 当該試合自体を「前回」にしない。
    meetings={ (r['date_jst'],r['opponent']):r for r in meetings if r['date_jst']< (current['date_jst'] if current else at.date().isoformat())}
    meetings=sorted(meetings.values(),key=lambda r:r['date_jst'],reverse=True)
    rows=sorted(rows,key=lambda r:r['date_jst'],reverse=True)
    prior=[r for r in rows if not current or (r['date_jst'],r['opponent'])!=(current['date_jst'],current['opponent'])]
    next_known=min((r for r in all_rows if r['date_jst']>cutoff),key=lambda r:r['date_jst'],default=None)
    trusted=not warnings
    return dict(history_version=3,history_digest=hashlib.sha256(PATH.read_bytes()).hexdigest(),
        history_checked_at=source['checked_at'],history_sources=source['sources'],history_warnings=warnings,
        history_trusted=trusted,japan_history=rows if trusted else [],
        japan_recent=prior[0] if trusted and prior else None,
        japan_previous=prior[1] if trusted and len(prior)>1 else None,
        previous=meetings[0] if trusted and meetings else None,
        previous_earlier=meetings[1] if trusted and len(meetings)>1 else None,
        next_known=next_known)
