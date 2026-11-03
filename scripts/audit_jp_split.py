"""保存した生応答と縮約・旧データ・新原稿の数字を独立照合する。"""
from collections import Counter
import json
import hashlib
from pathlib import Path
import subprocess
import sys

import jp_stock as jp


def main(raw_path, schedule_path):
    raw = json.loads(Path(raw_path).read_text(encoding='utf8'))
    schedule = json.loads(Path(schedule_path).read_text(encoding='utf8'))
    games = {g['gamePk']: g for d in schedule['dates'] for g in d['games'] if g.get('status', {}).get('codedGameState') == 'F'}
    saved = jp.stock.read(jp.ROOT/jp.SOURCE_PATH)
    old = json.loads(subprocess.check_output(['git', 'show', 'HEAD:'+jp.SOURCE_PATH], cwd=jp.ROOT))
    assert saved['schedule_sha256'] == hashlib.sha256(Path(schedule_path).read_bytes()).hexdigest()
    stripped = json.loads(json.dumps(saved))
    stripped.pop('schedule_sha256')
    stripped.pop('schedule_source')
    day_counts = Counter()
    count, fields = 0, 0
    for pid, player in raw.items():
        for group in ('hitting', 'pitching'):
            source = {r['game']['gamePk']: r for r in player.get(group+'_gameLog', [])}
            assert len(source) == len(saved['players'][pid][group])
            for row in stripped['players'][pid][group]:
                r = source[row['game_pk']]
                assert row['date'] == r['date']
                for k, value in row['stat'].items():
                    assert value == r['stat'][k]
                    fields += 1
                for key in ('isHome', 'isWin'):
                    assert row.pop(key) is r[key]
                assert row.pop('team_id') == r['team']['id']
                scheduled = games[row['game_pk']]
                value = row.pop('dayNight')
                assert value == scheduled['dayNight']
                day_counts[value] += 1
                side = 'home' if scheduled['teams']['home']['team']['id'] == r['team']['id'] else 'away'
                assert scheduled['teams'][side]['team']['id'] == r['team']['id']
                assert r['isHome'] == (side == 'home')
                assert r['isWin'] == scheduled['teams'][side]['isWinner']
                count += 1
    for key in ('acquired', 'raw_sha256'):
        stripped[key] = old[key]
    assert stripped == old, '追加3属性と取得情報以外に旧データの差がある'

    def total(rows):
        result = Counter()
        for r in rows:
            result.update({k: v for k, v in r['stat'].items() if type(v) is int})
        return result

    def detail(rows, group):
        s = total(rows)
        if group == 'hitting':
            return f"{s['atBats']}打数{s['hits']}安打、{s['homeRuns']}本塁打、{s['rbi']}打点"
        # 元の投球回文字列からアウト数を独立に算出。
        outs = sum(int(r['stat']['inningsPitched'].split('.')[0])*3+int(r['stat']['inningsPitched'].split('.')[1]) for r in rows)
        innings = f'{outs//3}回'+(f'{outs%3}/3' if outs%3 else '')
        return f"{innings}、{s['strikeOuts']}奪三振、失点{s['runs']}、自責点{s['earnedRuns']}"

    def concise(rows, group):
        s = total(rows)
        if group == 'hitting':
            n, d = s['hits']*1000, s['atBats']
        else:
            n, d = s['earnedRuns']*2700, s['outs']
        rounded = (2*n+d)//(2*d) if d else None
        value = ('算出なし' if rounded is None else
                 f'{rounded//1000}.{rounded%1000:03d}'.removeprefix('0') if group == 'hitting' else
                 f'{rounded//100}.{rounded%100:02d}')
        if group == 'hitting':
            return f"打率{value}、{s['homeRuns']}本塁打、{s['rbi']}打点"
        outs = sum(int(r['stat']['inningsPitched'].split('.')[0])*3+int(r['stat']['inningsPitched'].split('.')[1]) for r in rows)
        innings = f'{outs//3}回'+(f'{outs%3}/3' if outs%3 else '')
        return f"防御率{value}、{innings}、{s['strikeOuts']}奪三振"

    audited = []
    for spec in jp.build()['topics']:
        if spec['stock_kind'] not in ('home', 'win', 'daynight'):
            continue
        pid, group = spec['player_ids'][0], spec['comparison_group']
        rows = raw[pid][group+'_gameLog']
        if spec['stock_kind'] == 'win':
            selected = [r for r in rows if r['stat'].get('homeRuns', 0) > 0] if group == 'hitting' else [r for r in rows if r['stat'].get('gamesStarted') == 1]
            wins = [r for r in selected if r['isWin']]
            losses = [r for r in selected if not r['isWin']]
            assert f'{len(wins)}勝{len(losses)}敗' in spec['title']
            assert spec['items'][0][1] == concise(selected, group)
            assert spec['items'][1][1] == concise(wins, group)
            assert spec['items'][2][1] == concise(losses, group)
        else:
            selected = rows
            for i, value in enumerate((True, False) if spec['stock_kind'] == 'home' else ('day', 'night')):
                subset = [r for r in rows if (r['isHome'] if spec['stock_kind'] == 'home' else games[r['game']['gamePk']]['dayNight']) == value]
                assert spec['items'][i][1] == (detail(subset, group) if spec['stock_kind'] == 'home' else concise(subset, group))
                s = total(subset)
                numerator, denominator = (s['hits']*1000, s['atBats']) if group == 'hitting' else (s['earnedRuns']*2700, s['outs'])
                rounded = (2*numerator+denominator)//(2*denominator)
                value = f'{rounded//1000}.{rounded%1000:03d}'.removeprefix('0') if group == 'hitting' else f'{rounded//100}.{rounded%100:02d}'
                assert value in spec['title']
        assert set(spec['game_ids']) == {str(r['game']['gamePk']) for r in selected}
        audited.append(spec['key'])
    result = dict(schedule_games=len(games), schedule_days=dict(day_counts), schedule_sha256=saved['schedule_sha256'], rows=count, stat_fields=fields, legacy_unchanged=True, audited_new=audited,
                  source=str(raw_path), acquired=saved['acquired'])
    jp.write(jp.ROOT/'build/jp_split_check/numeric_audit.json', result)
    print(count, fields, len(audited))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
