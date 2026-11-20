"""前の晩の「懸かっている物」ショートを記録し、翌朝の結果ショートで前提として使う。"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import club_display_names

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'data/soccer_stake_history.json'
WINDOW_HOURS = 48
BROKEN = '[omit] 注目試合の記録を読めません'


def _time(value):
    if isinstance(value, datetime):
        at = value
    else:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at


def _points(value):
    return isinstance(value, int) and not isinstance(value, bool)


def record(doc, video_id, as_of):
    """公開したショート1本分の前提を、翌朝まで残せる形にする。"""
    if not video_id:
        raise ValueError('動画IDがありません')
    start = _time(doc['game']['start_time_utc'])
    when = _time(as_of)
    if when >= start:
        raise ValueError('記録の時刻が試合開始以後です')
    stake = doc['stake']
    rows = {}
    for side in ('home', 'away'):
        row = stake[side]
        if not _points(row.get('position')):
            raise ValueError(f'{side}の順位が整数ではありません')
        if not _points(row.get('points')):
            raise ValueError(f'{side}の勝点が整数ではありません')
        rows[side] = dict(team=row['team'], position=row['position'], points=row['points'])
    return dict(event_id=str(doc['event_id']), video_id=video_id, title=doc['title'],
                kind=stake['kind'], gap=stake['gap'], as_of=when.isoformat(),
                start_utc=start.isoformat(), home=rows['home'], away=rows['away'])


def save(doc, video_id, as_of, path=PATH):
    item = record(doc, video_id, as_of)
    history = load(path)
    old = history.get(item['event_id'])
    if old is not None:
        if old.get('video_id') != item['video_id']:
            raise ValueError('同じ試合に別の動画が記録されています')
        return item
    history[item['event_id']] = item
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return item


def load(path=PATH):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('記録の形が違います')
    except (OSError, ValueError):
        print(BROKEN)
        return {}
    return data


def _same_time(record, g):
    return _time(record['start_utc']) == _time(g['start_utc'])


def _in_window(record):
    start = _time(record['start_utc'])
    when = _time(record['as_of'])
    return start - timedelta(hours=WINDOW_HOURS) <= when < start


def _same_clubs(record, g):
    for side in ('home', 'away'):
        mine = (club_display_names.lookup(record[side]['team']) or {}).get('id')
        other = (club_display_names.lookup(g[side]['name_en']) or {}).get('id')
        if mine and other and mine != other:
            return False
    return True


def premise(record, g):
    """「前はこうだった」と「結果こうなった」を、結果ショートの材料から作る。"""
    home, away = g['home']['name_jp'], g['away']['name_jp']
    kind = record['kind']
    lead = ('順位の境目が懸かった試合でした。' if kind == '境目'
            else f'{kind}でした。' if kind.endswith('直接対決') else f'{kind}の直接対決でした。')
    hp, ap = record['home']['points'], record['away']['points']
    hs, as_ = g['score']['home'], g['score']['away']
    nh = hp + (3 if hs > as_ else 1 if hs == as_ else 0)
    na = ap + (3 if as_ > hs else 1 if hs == as_ else 0)
    if hp <= ap and nh > na:
        after = f'{home}が勝点{nh}で、{away}の{na}を上回りました。'
    elif ap <= hp and na > nh:
        after = f'{away}が勝点{na}で、{home}の{nh}を上回りました。'
    elif hp == ap and hs == as_:
        after = f'勝点は{nh}で並んだままです。'
    else:
        after = f'勝点は{home}が{nh}、{away}が{na}になりました。'
    return dict(lead=lead, after=after)


def attach(data, history):
    """結果ショートの材料に、前の晩の前提を同じ試合だけ足す。"""
    out = copy.deepcopy(data)
    found = {}
    for g in out.get('games') or []:
        item = history.get(str(g.get('id')))
        if not item:
            continue
        if not _same_time(item, g) or not _in_window(item) or not _same_clubs(item, g):
            continue
        found[str(g['id'])] = dict(record=copy.deepcopy(item), premise=premise(item, g))
    if found:
        out['stake_followup'] = found
    return out


def validate(data):
    """足した前提が、記録と結果の材料から作り直した物と一致するか。"""
    follow = data.get('stake_followup')
    if not follow:
        return
    games = {str(g.get('id')): g for g in data.get('games') or []}
    for key, item in follow.items():
        g = games.get(str(key))
        if not g:
            raise ValueError('記録に対応する試合がありません')
        if premise(item['record'], g) != item.get('premise'):
            raise ValueError('前提が材料と一致しません')
