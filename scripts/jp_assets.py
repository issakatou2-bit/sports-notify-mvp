"""保存済みMLB公式RS材料から、指定された比較5組・所属球団4案だけを作る。"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import season_stock as stock

ROOT = Path(__file__).resolve().parents[1]
# 組を増殖させない。最後は題で先に出す指標（材料から値を取得）。
PAIRS = ((808967, 684007, '防御率'), (579328, 608372, '登板'),
         (808963, 837227, '奪三振'), (660271, 673548, '本塁打'),
         (808959, 672960, '打点'))
CLUBS = {'115': ('608372',), '119': ('808963', '660271', '808967'),
         '135': ('673513',), '121': ('673540',)}
RUN_KEYS = frozenset({'season_momentum_rs2026_115_824309_824308',
                     'season_momentum_rs2026_119_823907_823817',
                     'season_momentum_rs2026_135_823253_824308'})


def comparisons(root=ROOT):
    saved = stock.read(root/'data/season_topics.json')
    if saved.get('source') != 'MLB Stats API（レギュラーシーズン）':
        return []
    rows = {str(t.get('player_id')): t for t in saved.get('topics', []) if t.get('jp')}
    out = []
    for aid, bid, focus in PAIRS:
        a, b = rows.get(str(aid), {}), rows.get(str(bid), {})
        if not a or not b or any(t.get('game_type', 'R') != 'R' or '2026年' not in t.get('title', '') for t in (a, b)):
            continue
        lines = [dict(t['items']).get('今季の成績', '') for t in (a, b)]
        pitcher = ['登板' in line for line in lines]
        if pitcher[0] != pitcher[1]:
            continue
        metrics = (('登板', r'(\d+)登板'), ('防御率', r'防御率(\d+\.\d+)'),
                   ('奪三振', r'(\d+)奪三振')) if pitcher[0] else (
                   ('本塁打', r'(\d+)本塁打'), ('打点', r'(\d+)打点'), ('OPS', r'OPS(\.\d+)'))
        values = {head: [re.search(pattern, line) for line in lines] for head, pattern in metrics}
        if any(not m for matches in values.values() for m in matches):
            continue
        values = {h: [m[1] for m in matches] for h, matches in values.items()}
        names = [a['jp'], b['jp']]
        items = [(h, f'{names[0]} {v[0]} ／ {names[1]} {v[1]}') for h, v in values.items()]
        unit = {'本塁打': '本', '打点': '打点', '登板': '登板', '奪三振': '奪三振', '防御率': ''}[focus]
        v = values[focus]
        # 題も冒頭も、同じ指標の保存値を二人分そのまま示す。優劣や寄与を推定しない。
        head = f'{names[0]}{v[0]}{unit}と{names[1]}{v[1]}{unit}'
        if focus == '防御率':
            head = f'{names[0]}の防御率{v[0]}と{names[1]}の防御率{v[1]}'
        spec = stock.base(f'season_compare_2026_{aid}_{bid}', head,
                          f'2026年レギュラーシーズン。{head}。', items,
                          game_type='R', stock_kind='compare', player_ids=[str(aid), str(bid)],
                          source_paths=['data/season_topics.json'], comparison_group='pitching' if pitcher[0] else 'hitting',
                          comparison_values=values)
        if focus == '防御率':
            # 数字だけが次行へ残らないよう、二人分を同じまとまりで改行する。
            spec['heading'] = f'{names[0]}の防御率{v[0]}\n{names[1]}の防御率{v[1]}'
            spec['hook'] = spec['heading']
        else:
            spec['hook'] = f'{names[0]}{v[0]}{unit}\n{names[1]}{v[1]}{unit}'
            if focus == '奪三振':
                spec['heading'] = spec['hook']
        out.append(spec)
    return out


def club_topics(root=ROOT):
    from notability_engine import JP_PLAYERS_MLB
    games, _ = stock.archived_games(root)
    rows = [t for t in stock.momentum_topics(games) if t['key'] in RUN_KEYS]
    rows += [t for t in stock.game_topics(games) if t['game_pk'] == 823818]
    roster = stock.read(root/'data/roster_snapshot.json').get('players', {})
    names = {p['name_en']: p['name_jp'] for p in JP_PLAYERS_MLB}
    players = {str(t.get('player_id')): t for t in stock.read(root/'data/season_topics.json').get('topics', []) if t.get('jp')}
    out = []
    for t in rows:
        tid = str(t.get('team_id') or '121')
        ids = CLUBS.get(tid)
        if not ids or any(str(roster.get(pid, {}).get('team_id')) != tid or not players.get(pid) for pid in ids):
            continue
        if any(names.get(roster[pid].get('name')) != players[pid]['jp'] for pid in ids):
            continue
        affiliation = '・'.join(players[pid]['jp'] for pid in ids)+'が所属する'
        club_heading = t['heading']
        head = affiliation+club_heading
        t.update(title=f'【MLB】{head}｜2026年レギュラーシーズン #Shorts',
                 label=head, heading=club_heading, hook=club_heading, player_ids=list(ids), game_type='R',
                 affiliation_only=True, source_paths=t['source_paths']+['data/roster_snapshot.json'])
        # 所属を一度だけ説明。出場、登板、個人の勝利への貢献は生成しない。
        t['intro'] = t['intro'].replace('2026年レギュラーシーズン。', '2026年レギュラーシーズン。'+affiliation, 1)
        if t['stock_kind'] == 'game':
            t['intro'] = t['intro'].replace('のメッツ対', 'の'+affiliation+'メッツ対', 1)
        out.append(t)
    return out


def ids(topic, spec=None):
    """鍵に全IDが入る比較と、所属を含む複数選手回。"""
    match = re.fullmatch(r'season_compare_2026_(\d+)_(\d+)', topic or '')
    if match:
        return set(match.groups())
    if (spec or {}).get('player_ids'):
        return {str(x) for x in spec['player_ids']}
    import player_publications as pp
    pid = pp.topic_id(topic)
    return {pid} if pid else set()


def available(topic, spec, ledgers, as_of=None):
    import player_publications as pp
    done = {**ledgers[0].get('asset', {}), **ledgers[1].get('assets', {})}
    if topic in done:
        return False
    if spec.get('stock_kind') == 'momentum':
        for key in done:
            match = re.fullmatch(r'season_momentum_rs2026_(\d+)_(\d+)_(\d+)', key)
            if match and match[1] == str(spec['team_id']) and set(match.groups()[1:]) & set(spec['game_ids']):
                return False
    return not any(pp.recent(pid, 'season_player', as_of, ledgers) for pid in ids(topic, spec))


def publication_available(topic, spec, ledgers, as_of):
    """日付をまたぐ予約は実際の公開予定日で型と上限も再照合する。"""
    import asset_policy as policy
    import player_publications as pp
    if not available(topic, spec, ledgers, as_of):
        return False
    day = as_of.astimezone(pp.JST).date()
    rows = policy.merge_records(ledgers[0].get('asset', {}), ledgers[1].get('assets', {}))
    count = 0
    for key, row in rows.items():
        if not key.startswith('season_'):
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
        except (ValueError, KeyError):
            continue
        if stamp.astimezone(pp.JST).date() == day:
            count += 1
            if policy.season_kind(key) == policy.season_kind(topic):
                return False
    return count < 3


def publication_ledgers():
    """最新の公開台帳に、この実行内で成功した未pushの記録も合わせる。"""
    import asset_policy as policy
    import player_publications as pp
    fresh, local = pp.load(refresh=True), pp.load()
    videos = dict(fresh[0])
    for group in ('asset', 'player_story'):
        videos[group] = policy.merge_records(local[0].get(group, {}), fresh[0].get(group, {}))
    assets = {'assets': policy.merge_records(local[1].get('assets', {}), fresh[1].get('assets', {}))}
    return videos, assets


def build(root=ROOT):
    import asset_policy
    topics = comparisons(root)+club_topics(root)
    names = {t['jp'] for t in stock.read(root/'data/season_topics.json').get('topics', []) if t.get('jp')}
    topics = [t for t in topics if asset_policy.selectable(t['key'], t, names)]
    return dict(season='2026', source='MLB Stats API / 保存済みRS材料', topics=topics)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('build/jp_asset_topics.json'))
    args = ap.parse_args()
    doc = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(f"日本人資産の材料: {len(doc['topics'])}本（公開間隔は選択時に再照合）")


if __name__ == '__main__':
    main()
