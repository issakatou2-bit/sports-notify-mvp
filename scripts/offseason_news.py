"""オフの公式材料を既存の資産動画へ。通信失敗・不足を空の成功にしない。"""
import argparse
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
from offseason_switches import enabled, available

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
API = 'https://statsapi.mlb.com/api/v1'
JST = timezone(timedelta(hours=9))
CALENDAR = Path(__file__).resolve().parents[1] / 'data/offseason_calendar_2026.json'
AWARDS = {'ALMVP': 'ア・リーグMVP', 'NLMVP': 'ナ・リーグMVP',
          'ALCY': 'ア・リーグのサイ・ヤング賞', 'NLCY': 'ナ・リーグのサイ・ヤング賞',
          'ALROY': 'ア・リーグ新人王', 'NLROY': 'ナ・リーグ新人王',
          'ALGG': 'ア・リーグのゴールドグラブ', 'NLGG': 'ナ・リーグのゴールドグラブ',
          'ALSS': 'ア・リーグのシルバースラッガー', 'NLSS': 'ナ・リーグのシルバースラッガー'}
MOVES = {'DFA': 'FAを宣言しました', 'SFA': 'FA契約を結びました',
         'SGN': '契約が公式に記録されました',
         'TR': 'トレードが公式に記録されました'}
OUTRO_TEXT = 'コレスポでは、オフの動きを公式の記録で追っています。チャンネル登録して、また見に来てくださいね。'


def item_speech(head, body):
    return body.rstrip('。') + '。'


def get(path, **params):
    import requests
    response = requests.get(API + '/' + path, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def recipients(ident, season, fetch):
    # 発表前の年は MLB が 404 を返す（11/1 本番で全体が落ちた）。まだ受賞者がいないだけ。
    import requests
    try:
        return fetch(f'awards/{ident}/recipients', season=season)
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return {'awards': []}
        raise


def names():
    import notability_engine as ne
    jp = {p['name_en']: p['name_jp'] for p in ne.JP_PLAYERS_MLB}
    table = json.loads(Path('data/player_kana.json').read_text(encoding='utf-8')).get('names', {})
    # MLB未所属の移籍候補は在籍名簿に混ぜず、確認済みの別表から登録する。
    candidates = json.loads((CALENDAR.parent / 'offseason_players.json').read_text(encoding='utf-8'))['players']
    jp.update({p['name_en']: p['name_jp'] for p in candidates})
    return jp, {**table, **jp}


def schedule(day, calendar=None):
    """今後7日。表の確定した絶対日付だけ。米東部の日付をJSTへ推測しない。"""
    calendar = calendar or json.loads(CALENDAR.read_text(encoding='utf-8'))
    rows = []
    for row in calendar['events']:
        when = date.fromisoformat(row['date_et'])
        if day <= when < day + timedelta(days=7):
            rows.append(dict(row, event_id='calendar:' + row['id'],
                head=f'{when.month}月{when.day}日｜{row["label"]}',
                body=f'{when.month}月{when.day}日、{row["text"]}', japanese=False))
    return rows


def award_rows(payloads, season, jp, table):
    rows = []
    for award_id, payload in payloads.items():
        if award_id not in AWARDS:
            continue
        if award_id.endswith(('GG', 'SS')) and any(
                not table.get((r.get('player') or {}).get('nameFirstLast') or
                              (r.get('player') or {}).get('name') or (r.get('player') or {}).get('fullName'))
                for r in payload['awards'] if str(r.get('season')) == str(season)):
            continue  # 未登録名を飛ばして一部の部門だけを選ばない。辞書確認後に全体を扱う。
        # recipientsは受賞記録。最終候補はこのAPIから取得しない。
        for row in payload['awards']:
            if row.get('id') not in (None, award_id):
                continue
            person = row.get('player') or {}
            original = person.get('nameFirstLast') or person.get('name') or person.get('fullName')
            name = table.get(original)
            if str(row.get('season')) != str(season) or not name or not person.get('id'):
                continue
            rank = str(row.get('rank', ''))
            if row.get('notes') or rank not in ('', '1'):
                continue
            # このendpointは受賞記録。投票数だけの行を受賞へ変換しない。
            label = AWARDS[award_id]
            position = (person.get('primaryPosition') or {}).get('abbreviation', '')
            body = f'{name}は{season}年の{label}を受賞しました'
            rows.append(dict(event_id=f'award:{season}:{award_id}:{person["id"]}:winner',
                head=f'{name}｜{label}' + (f'・{POSITION_LABEL[position]}' if position in POSITION_LABEL else ''), body=body, name=name, japanese=original in jp,
                source=f'{API}/awards/{award_id}/recipients?season={season}', raw=copy.deepcopy(row)))
    return sorted(rows, key=lambda r: (not r['japanese'], r['event_id']))


def notable(season, fetch=get):
    """大型の対象を公式実績で固定。契約額や報道の評価は使わない。"""
    result = set()
    for ident in ('ALMVP', 'NLMVP', 'ALCY', 'NLCY'):
        payload = fetch(f'awards/{ident}/recipients', season=season - 1)
        for row in payload['awards']:
            if str(row.get('season')) == str(season - 1) and str(row.get('rank', '1')) == '1':
                if (row.get('player') or {}).get('id'):
                    result.add(row['player']['id'])
    # 当季30本塁打／200奪三振も対象。規模の編集基準であり契約額の主張ではない。
    for group, stat, threshold in (('hitting', 'homeRuns', 30), ('pitching', 'strikeOuts', 200)):
        payload = fetch('stats', stats='season', group=group, season=season,
                        sportIds=1, playerPool='ALL', gameType='R', limit=10000)
        for block in payload['stats']:
            for row in block['splits']:
                if str(row.get('season')) == str(season) and int(row['stat'].get(stat, 0)) >= threshold:
                    result.add(row['player']['id'])
    return result


def season_line(payload, season, person_id):
    """person seasonのMLB通算1行だけ。チーム別分割や欠測を足し算しない。"""
    for group in ('pitching', 'hitting'):
        for block in payload.get('stats', []):
            if block.get('group', {}).get('displayName') != group or block.get('type', {}).get('displayName') != 'season':
                continue
            rows = [r for r in block.get('splits', []) if str(r.get('season')) == str(season)
                    and (r.get('player') or {}).get('id', person_id) == person_id
                    and (r.get('sport') or {}).get('id', 1) == 1]
            totals = [r for r in rows if r.get('numTeams', 0) > 1 or not r.get('team')]
            rows = totals if len(totals) == 1 else rows
            if len(rows) != 1:
                continue
            stat = rows[0].get('stat', {})
            fields = ('gamesPitched', 'era', 'strikeOuts') if group == 'pitching' else ('gamesPlayed', 'homeRuns', 'avg')
            values = [str(stat.get(k, '')) for k in fields]
            patterns = (r'\d+', r'\d+\.\d{2}', r'\d+') if group == 'pitching' else (r'\d+', r'\d+', r'(?:0?\.\d{3}|1\.000)')
            if not all(re.fullmatch(p, v) for p, v in zip(patterns, values)) or int(values[0]) == 0:
                continue
            if group == 'pitching':
                return f'{season}年は{values[0]}登板、防御率{values[1]}、{values[2]}奪三振'
            return f'{season}年は{values[0]}試合、{values[1]}本塁打、打率{values[2]}'
    return ''


def enrich_transactions(rows, fetch=get):
    """任意の成績補足。通信失敗は当該補足だけ省略する。"""
    result, cache = [], {}
    for original in rows:
        row = copy.deepcopy(original)
        raw = row['raw']
        if raw.get('typeCode') in ('DFA', 'SFA'):
            when = date.fromisoformat(raw['date'][:10])
            season = when.year - (when.month < 4)
            ident = raw['person'].get('id')
            if ident:
                key = (ident, season)
                if key not in cache:
                    try:
                        cache[key] = fetch(f'people/{ident}/stats', stats='season', group='hitting,pitching',
                                           season=season, gameType='R', sportIds=1)
                    except Exception:
                        cache[key] = {}
                payload = cache[key]
                try:
                    line = season_line(payload, season, ident)
                except (AttributeError, TypeError, ValueError, KeyError):
                    line = ''
                if line:
                    row['season_stats'] = dict(season=season, person_id=ident, payload=copy.deepcopy(payload),
                        source=f'{API}/people/{ident}/stats?stats=season&group=hitting,pitching&season={season}&gameType=R&sportIds=1')
                    row['body'] += '。' + line
        result.append(row)
    return result


def transaction_rows(payload, start, end, jp, table, stars):
    import notability_engine as ne
    rows = []
    for row in payload['transactions']:
        person = row.get('person') or {}
        original = person.get('fullName') or person.get('name')
        name = table.get(original)
        stamp = row.get('date', '')[:10]
        try:
            when = date.fromisoformat(stamp)
        except ValueError:
            continue
        if not (start <= when <= end) or not row.get('id') or not name:
            continue
        if original not in jp and person.get('id') not in stars:
            continue
        code = row.get('typeCode')
        # コードを推測しない。公式取引本文が本人のpostedを明記する場合だけ。
        description = row.get('description', '')
        posting_teams = [(row.get(k) or {}).get('name') for k in ('fromTeam', 'toTeam')]
        posted = bool(original and any(team and re.fullmatch(
            re.escape(team) + r' posted ' + re.escape(original) + r'(?: for .+)?\.',
            description, re.IGNORECASE) for team in posting_teams))
        if posted:
            rows.append(dict(event_id=f'transaction:{row["id"]}', head=f'{name}｜ポスティング',
                body=f'{name}のポスティングがMLB公式の取引記録に載りました',
                name=name, japanese=original in jp, raw=copy.deepcopy(row),
                source=f'{API}/transactions?playerId={person.get("id")}&startDate={start}&endDate={end}'))
            continue
        if code not in MOVES:
            continue  # DES・OUT・REL・SC等は取り上げない。
        action = MOVES[code]
        origin = ne.MLB_TEAM_NAME_JP.get(str((row.get('fromTeam') or {}).get('id')))
        target = ne.MLB_TEAM_NAME_JP.get(str((row.get('toTeam') or {}).get('id')))
        if code == 'DFA':
            # Declared Free AgencyのtoTeamは元所属。行先には使わない。
            action = (f'{target}から' if target else '') + 'FAを宣言しました'
        if code == 'SFA':
            if not target:
                continue
            action = f'{target}とFA契約を結びました'
        if code == 'SGN' and target:
            action = f'{target}との契約が公式に記録されました'
        if code == 'TR' and target:
            action = (f'{origin}から' if origin else '') + f'{target}へのトレードが公式に記録されました'
        label = {'DFA': 'FA宣言', 'SFA': 'FA契約', 'SGN': '契約', 'TR': 'トレード'}[code]
        rows.append(dict(event_id=f'transaction:{row["id"]}', head=f'{name}｜{label}',
            body=f'{name}は{action}',
            name=name, japanese=original in jp, raw=copy.deepcopy(row),
            source=f'{API}/transactions?playerId={person.get("id")}&startDate={start}&endDate={end}'))
    return sorted(rows, key=lambda r: (not r['japanese'], r['event_id']))


def topic(kind, rows, day, season=2026):
    # 同じ発表を画面分割して情報数にしない。少なければ既存short_contentで見送り。
    unique = {r['event_id']: r for r in rows}
    # 検証済み見本は4件で約48〜54秒。長い移籍先を読む取引は3件まで。
    # 6件を毎回選んで上限超過→同じ未投稿6件を再選択する状態を避ける。
    rows = list(unique.values())[:3 if kind == 'transactions' else 4]
    if not rows:
        return None
    digest = hashlib.sha256('|'.join(sorted(r['event_id'] for r in rows)).encode()).hexdigest()[:12]
    title = {'schedule': 'MLBオフの1週間の予定', 'awards': f'{season}年のMLB公式表彰',
             'transactions': 'MLB公式に記録された選手の動き'}[kind]
    lead = next((r.get('name') for r in rows if r.get('japanese')), None)
    if lead:
        title = lead + 'と' + title
    intro = {'schedule': 'この先1週間のMLBオフの予定です。日付はすべてアメリカ東部の日付でお伝えします。',
             'awards': f'{season}年のMLBの表彰です。MLB公式の受賞記録からお伝えします。',
             'transactions': 'MLB公式の取引記録に載った選手の動きです。FA宣言とFA契約、トレードを分けてお伝えします。'}[kind]
    return dict(key=f'offseason_{kind}_{season}_{digest}', label=title, heading=title,
        kind_label='MLB', data_credit='MLB.com' if kind == 'schedule' else 'MLB Stats API',
        v3=dict(source='出典: MLB.com / 日付は米東部' if kind == 'schedule' else '出典: MLB公式 / 受賞・取引記録'),
        hook=title, intro=intro, intro_as_is=True, style='v3',
        source='MLB公式｜日付は米東部' if kind == 'schedule' else 'MLB公式 / 受賞・取引記録', source_url=rows[0]['source'],
        items=[(r['head'], r['body']) for r in rows],
        offseason=dict(kind=kind, day=str(day), season=season, events=rows))


POSITION_ORDER = {v: i for i, v in enumerate(('P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'OF', 'DH', 'UT'))}
POSITION_LABEL = dict(zip(POSITION_ORDER, ('投手', '捕手', '一塁手', '二塁手', '三塁手', '遊撃手',
                                         '左翼手', '中堅手', '右翼手', '外野手', '指名打者', 'ユーティリティ')))


def award_topics(rows, day, season):
    """複数部門賞はリーグ・賞別、守備位置順。端数1〜2件を残さず3〜4件に分ける。"""
    groups, singles = {}, []
    for row in rows:
        ident = row['event_id'].split(':')[2]
        if ident.endswith(('GG', 'SS')):
            groups.setdefault(ident, []).append(row)
        else:
            singles.append(row)
    result = []
    if singles:
        result.append(topic('awards', singles, day, season))
    for ident, events in sorted(groups.items()):
        events.sort(key=lambda r: (POSITION_ORDER.get((r['raw']['player'].get('primaryPosition') or {}).get('abbreviation'), 99),
                                   r['raw']['player'].get('nameFirstLast', ''), r['event_id']))
        count = (len(events) + 3) // 4
        size, extra = divmod(len(events), count)
        if size < 3:
            continue  # 全部門を3〜4件で分けられない時は賞全体を保留。
        offset = 0
        for index in range(count):
            batch = events[offset:offset + size + (index < extra)]
            offset += len(batch)
            spec = topic('awards', batch, day, season)
            spec['label'] = spec['heading'] = spec['hook'] = f'{season}年の{AWARDS[ident]}（{index+1}/{count}）'
            result.append(spec)
    return result


def sample_intro(kind, season):
    if kind == 'awards':
        return f'これは{season}年のMLB表彰を使った動作見本です。2026年の受賞結果ではありません。'
    return f'これは{season}年のMLB公式取引記録を使った過年度見本です。今年の移籍情報ではありません。'


def collect(day, season, fetch=get):
    jp, table = names()
    awards = {ident: recipients(ident, season, fetch) for ident in AWARDS}
    start = day - timedelta(days=6)
    moves = fetch('transactions', sportId=1, startDate=str(start), endDate=str(day))
    return {'schedule': schedule(day), 'awards': award_rows(awards, season, jp, table),
            'transactions': enrich_transactions(transaction_rows(moves, start, day, jp, table, notable(season, fetch)), fetch)}


def attach(document, spec):
    evidence = spec.get('offseason')
    if evidence:
        document['offseason'] = copy.deepcopy(evidence)
        if spec.get('offseason_sample'):
            document['offseason_sample'] = True
        document['sanity_date_jst'] = evidence['day']
        document.setdefault('sanity_materials', []).append(dict(source='MLB公式・オフ',
            source_url=spec.get('source_url'), offseason=copy.deepcopy(evidence),
            facts=[dict(label=r['head'], text=r['body'], source_url=r['source'], raw=r.get('raw'))
                   for r in evidence['events']]))
    return document


def check(document):
    """保存した公式入力から作った各行を再照合。数字だけの変更も止める。"""
    evidence = document.get('offseason')
    if not evidence:
        return []
    sources = [s['offseason'] for s in document.get('sanity_materials', []) if s.get('offseason')]
    if sources != [evidence]:
        return ['オフの公式材料と原稿添付が不一致']
    # 読上げ用の文だけを根拠にしない。受信した公式レコード／固定日程から再構築。
    jp, table = names()
    day = date.fromisoformat(evidence['day'])
    for event in evidence['events']:
        if evidence['kind'] == 'schedule':
            rebuilt = schedule(day)
        elif evidence['kind'] == 'awards':
            ident = event['event_id'].split(':')[2]
            rebuilt = award_rows({ident: {'awards': [event.get('raw', {})]}}, evidence['season'], jp, table)
        elif evidence['kind'] == 'transactions':
            raw = event.get('raw', {})
            start = date.fromisoformat(evidence['window_start']) if document.get('offseason_sample') and evidence.get('window_start') else day-timedelta(days=6)
            rebuilt = transaction_rows({'transactions': [raw]}, start, day,
                                       jp, table, {(raw.get('person') or {}).get('id')})
            if event.get('season_stats'):
                saved = event['season_stats']
                rebuilt = enrich_transactions(rebuilt, lambda *a, **k: saved['payload'])
        else:
            return ['オフの材料の種類が不明']
        if event not in rebuilt:
            return ['オフの文面・名前・区分が受信した公式記録と不一致']
    spec = (__import__('jp_future_series').topic(evidence['events'], day, evidence['season'], episode=evidence['series_number'])
            if evidence.get('series_number') else topic(evidence['kind'], evidence['events'], day, evidence['season']))
    intros = [s.get('text') for s in document.get('segments', []) if s.get('kind') == 'intro']
    expected_intro = spec['intro']
    if document.get('offseason_sample'):
        expected_intro = sample_intro(evidence['kind'], evidence['season'])
    if intros != [expected_intro] or any(s.get('kind') not in ('intro', 'list', 'outro') for s in document.get('segments', [])):
        return ['オフの冒頭または未対応の追加文が公式材料と不一致']
    # 既存話者の敬語・字幕変換後も、材料由来の本体を全文で照合する。
    expected = []
    items = spec['items']
    for index in range(0, len(items), 2):
        text = ''.join(item_speech(head, body) for head, body in items[index:index+2])
        expected.append(text)
    actual = [s['text'] for s in document.get('segments', []) if s.get('kind') == 'list']
    if actual != expected:
        return ['オフの予定・表彰・移籍の本文が公式材料と不一致']
    if [s.get('text') for s in document.get('segments', []) if s.get('kind') == 'outro'] != [OUTRO_TEXT]:
        return ['オフの締めが専用文と不一致']
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', default=str(datetime.now(JST).date()))
    parser.add_argument('--season', type=int, default=2026)
    parser.add_argument('--out', default='data/offseason_topics.json')
    parser.add_argument('--pick', action='store_true')
    parser.add_argument('--record', help='公開成功後のみ、イベントの重複防止記録を追記')
    args = parser.parse_args()
    path = Path(args.out)
    if args.record:
        catalog = json.loads(path.read_text(encoding='utf-8'))
        published = json.loads(Path('data/published_assets.json').read_text(encoding='utf-8'))['assets']
        if args.record not in published:
            raise ValueError('公開成功記録がないためイベントを確定できません')
        spec = next(t for t in catalog['topics'] if t['key'] == args.record)
        record = Path('data/offseason_published.json')
        state = json.loads(record.read_text(encoding='utf-8')) if record.exists() else {'events': []}
        state['events'] = sorted(set(state['events']) | {r['event_id'] for r in spec['offseason']['events']})
        # 当日中に材料を再取得しても、予約公開待ちのSNS用の版情報を失わない。
        existing = state.setdefault('topics', {}).get(spec['key'])
        episode = spec['offseason'].get('series_number')
        if episode and not existing and episode != __import__('jp_future_series').number(state):
            raise ValueError('連載番号が公開成功記録と一致しません。再選定が必要です')
        state['topics'][spec['key']] = {'style': spec['style'], **({'series_number': episode} if episode else {})}
        record.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return
    if args.pick:
        if not enabled():
            return
        state = Path('data/offseason_published.json')
        seen = set(json.loads(state.read_text(encoding='utf-8'))['events']) if state.exists() else set()
        catalog = json.loads(path.read_text(encoding='utf-8'))
        for spec in catalog['topics']:
            if available(spec, date.fromisoformat(args.day)) and len(spec['items']) >= 3 and not any(
                    r['event_id'] in seen for r in spec['offseason']['events']):
                print(spec['key'])
        return
    day = date.fromisoformat(args.day)
    # 前回の成功を失敗した日の新材料として残さない。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(day=str(day), topics=[], state='collecting')), encoding='utf-8')
    materials = collect(day, args.season)
    state = Path('data/offseason_published.json')
    history = json.loads(state.read_text(encoding='utf-8')) if state.exists() else {'events': []}
    seen = set(history['events'])
    topics = []
    for kind, rows in materials.items():
        pending = [r for r in rows if r['event_id'] not in seen]
        topics.extend([spec for spec in award_topics(rows, day, args.season)
                       if not any(r['event_id'] in seen for r in spec['offseason']['events'])] if kind == 'awards'
                      else [__import__('jp_future_series').topic(pending, day, args.season, state=history)] if kind == 'transactions'
                      else [topic(kind, pending, day, args.season)])
    path.write_text(json.dumps(dict(day=str(day), state='ready', topics=[t for t in topics if t]),
                               ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
