"""レギュラーシーズンの保存結果から、オフにも使える題材を作る。

当日向けPSの期限を延ばさない。公開済みの鍵・選手ID・試合IDを保持する。
archiveは全日程ではないため、勝敗の連続性を順位表の累積勝敗でも照合する。
台詞は既存のitems読み上げ。外部通信・辞書への自動登録は行わない。
"""
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KINDS = ('momentum', 'player', 'game', 'odds', 'story')


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def base(key, heading, intro, items, **extra):
    return dict(key=key, label=heading, heading=heading, hook=heading,
                intro=intro, intro_as_is=True, style='v3',
                title=f'【MLB】{heading}｜2026年レギュラーシーズン #Shorts',
                source='MLB Stats API / 保存した2026年レギュラーシーズン材料',
                items=items, season_stock=True, **extra)


def archived_games(root=ROOT):
    """同じ試合の異なるスコア・勝者は採用しない。R・2026・勝者ありのみ。"""
    rows, conflicts = {}, set()
    for path in sorted((root/'archive').glob('2026-*.json')):
        for g in read(path).get('games', []):
            s = g.get('final_score') or {}
            if g.get('league') != 'MLB' or g.get('game_type') != 'R':
                continue
            if (not g.get('game_id') or s.get('winner') not in ('home', 'away')
                    or any(type(s.get(x)) is not int or s[x] < 0 for x in ('home', 'away'))
                    or s['home'] == s['away']
                    or s['winner'] != ('home' if s['home'] > s['away'] else 'away')):
                continue
            key = str(g['game_id'])
            if key in rows and rows[key]['final_score'] != s:
                conflicts.add(key)
            # JSTの開始時刻は現地日付と同一視しない。表示は保存日の範囲と明記。
            row = dict(g, archive_day=path.stem, source_path=str(path.relative_to(root)))
            rows.setdefault(key, row)
    return [v for k, v in rows.items() if k not in conflicts], sorted(conflicts)


def record(g, side):
    st = g.get(side+'_standing') or {}
    if any(type(st.get(k)) is not int or st[k] < 0 for k in ('wins', 'losses')):
        return None
    return st['wins'], st['losses']


def side_of(g, tid):
    return 'home' if str(g['home_team_id']) == str(tid) else 'away'


def date_label(g):
    text = g.get('start_time_jst', '')
    return text.split()[0].replace('/', '月')+'日' if re.fullmatch(r'\d{2}/\d{2} \d{2}:\d{2}', text) else ''


def result_text(g, tid):
    side = side_of(g, tid)
    other = 'away' if side == 'home' else 'home'
    s = g['final_score']
    return f"{g[other+'_team_name']}に{s[side]}対{s[other]}"


def momentum_topics(games, audit=None):
    """7連勝/7連敗以上を一つの期間につき1本。欠けた試合は接続しない。"""
    teams = defaultdict(list)
    for g in games:
        for side in ('home', 'away'):
            teams[str(g[side+'_team_id'])].append(g)
    out = []
    for tid, rows in sorted(teams.items()):
        rows.sort(key=lambda g: (g.get('start_time_jst') or '', g['game_id']))
        run, previous, previous_outcome = [], None, None
        def emit():
            if audit is not None and run:
                audit[str(len(run))] = audit.get(str(len(run)), 0)+1
            if len(run) < 7:
                return
            first, last = run[0], run[-1]
            if not all(date_label(g) for g in run):
                return
            side = side_of(first, tid)
            name = first[side+'_team_name']
            label = '連勝' if previous_outcome else '連敗'
            head = f'{name}の{len(run)}{label}'
            # 札は前半・中盤・後半の実試合。派生した合計を独立情報として水増ししない。
            selected = [(0, '最初の試合'), (len(run)//2, '中盤の試合'), (len(run)-1, '最後の試合')]
            items = [(head, f'{date_label(run[i])}、{result_text(run[i], tid)}') for i, head in selected]
            spec = base(f"season_momentum_rs2026_{tid}_{first['game_id']}_{last['game_id']}",
                        head, f'2026年レギュラーシーズン。{name}は日本時間{date_label(first)}から'
                        f'{date_label(last)}まで{len(run)}{label}しました。試合結果を振り返ります。', items,
                        team_id=int(tid), stock_kind='momentum',
                        game_ids=[str(g['game_id']) for g in run],
                        source_paths=[g['source_path'] for g in run])
            out.append(spec)
        for g in rows:
            side = side_of(g, tid)
            before = record(g, side)
            outcome = g['final_score']['winner'] == side
            continuous = False
            if previous is not None and before is not None:
                ps = side_of(previous, tid)
                old = record(previous, ps)
                if old is not None:
                    expected = (old[0]+int(previous_outcome), old[1]+int(not previous_outcome))
                    continuous = before == expected
            if not continuous or outcome != previous_outcome:
                emit()
                run = []
            run.append(g)
            previous, previous_outcome = g, outcome
        emit()
    return out


def game_topics(games):
    """19得点以上の1点差。逆転・サヨナラなど経過が必要な語は使わない。"""
    out = []
    for g in games:
        score = g['final_score']
        if abs(score['home']-score['away']) != 1 or score['home']+score['away'] < 19:
            continue
        if not date_label(g) or any(record(g, side) is None for side in ('home', 'away')):
            continue
        winner = score['winner']
        loser = 'away' if winner == 'home' else 'home'
        win, lose = g[winner+'_team_name'], g[loser+'_team_name']
        items = [('試合の結果', f"{win}が{score[winner]}対{score[loser]}で{lose}に勝利")]
        for side in (winner, loser):
            w, l = record(g, side)
            items.append((f"試合前の{g[side+'_team_name']}", f'シーズン{w}勝{l}敗'))
        # 球団シーズン総括へ化けさせず、試合前の状況とこの試合の結果に限定。
        out.append(base(f"season_game_{g['game_id']}",
                        f"{win}対{lose}の{score[winner]}対{score[loser]}",
                        f"2026年レギュラーシーズン、日本時間{date_label(g)}の{win}対{lose}。"
                        '1点差の打撃戦を、試合前の両球団の成績とともに振り返ります。',
                        items, stock_kind='game', game_pk=int(g['game_id']),
                        source_paths=[g['source_path']]))
    return out

