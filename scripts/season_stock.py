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
            row = dict(g, archive_day=path.stem, source_path=path.relative_to(root).as_posix())
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

# 全選手を調べ、出場単位の最大値・大差だけを取り上げる。
INSIGHT_PREFIX = 'season_insight_'
INSIGHT_PATH = 'data/season_insights.json'


def insight_topic(pid, name, metric, title, ask, answer, rows, group, *, source_path):
    source = f'https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&season=2026&group={group}&gameType=R'
    key = f'{INSIGHT_PREFIX}2026_{pid}_{metric}'
    return dict(key=key, label=title, heading=title, hook=title, title=f'{title} #Shorts',
                jp=name, player_id=int(pid), game_type='R', season_stock=True,
                source='MLB Stats API / 2026年レギュラーシーズン', source_paths=[source_path],
                items=rows, insight=dict(ask=ask, answer=answer, rows=rows, source=source))


def standout_games(games, name, metrics):
    for metric, label, minimum, unit in metrics:
        peak = max(game['stat'].get(metric, 0) for game in games)
        if peak < minimum:
            continue
        best = [game for game in games if game['stat'].get(metric, 0) == peak]
        if len(best) > 4 or len(best) * 5 > len(games):
            continue
        month, day = map(int, best[0]['date'].split('-')[1:])
        at = f'{month}月{day}日'
        number = f'{peak}{unit}'
        yield (f'game_{metric}', f'1試合で最多{number}',
               f'{name}は今季、1試合で最多いくつの{label}を記録したのだ？',
               f'{at}の{number}が最多よ。今季の{len(games)}試合の中で、'
               f'この数字を記録したのは{len(best)}試合だったわ。'
               f'今季の合計は{sum(g['stat'].get(metric, 0) for g in games)}{unit}よ。',
               [[at, f'今季最多 {number}'], ['同じ数字の試合', f'{len(games)}試合中{len(best)}試合'],
                ['今季の合計', f'{sum(g['stat'].get(metric, 0) for g in games)}{unit}']])


def home_run_month(games, name):
    by_month = defaultdict(list)
    for game in games:
        by_month[int(game['date'][5:7])].append(game['stat'])
    months = []
    for month, stats in by_month.items():
        pa = sum(s.get('plateAppearances', 0) for s in stats)
        hr = sum(s.get('homeRuns', 0) for s in stats)
        if pa >= 65:
            months.append((hr / pa, month, pa, hr))
    if len(months) < 2:
        return
    high, low = max(months), min(months)
    _, m1, pa1, hr1 = high
    _, m2, pa2, hr2 = low
    if hr1 >= 5 and high[0] - low[0] >= .045 and high[0] >= 2.5 * low[0]:
        total = sum(g['stat'].get('homeRuns', 0) for g in games)
        yield ('hr_month', f'本塁打が最も出やすかったのは{m1}月',
               f'{name}がいちばん本塁打を打ったペースは、何月なのだ？',
               f'65打席以上の月で見ると、{m1}月が{pa1}打席で{hr1}本。'
               f'最も出にくかった{m2}月は{pa2}打席で{hr2}本だったわ。今季は全部で{total}本よ。',
               [[f'{m1}月', f'{pa1}打席・{hr1}本'], [f'{m2}月', f'{pa2}打席・{hr2}本'], ['今季の合計', f'{total}本']])


def long_scoreless_starts(games, name):
    starts = [g for g in games if g['stat'].get('gamesStarted') == 1]
    qualified = [g for g in starts if g['stat'].get('runs') == 0 and g['stat'].get('outs', 0) >= 18]
    if len(qualified) >= 5 and len(qualified) * 3 >= len(starts):
        longest = max(g['stat']['outs'] for g in qualified)
        innings, outs = divmod(longest, 3)
        duration = f'{innings}回' + (f'と3分の{outs}' if outs else '')
        yield ('scoreless', f'6回以上無失点が{len(qualified)}試合',
               f'{name}は、今季何試合で6回以上を無失点に抑えたのだ？',
               f'今季の先発{len(starts)}試合のうち、6回以上を投げて無失点だったのが{len(qualified)}試合よ。'
               f'その中で最も長く投げた試合は{duration}を無失点だったわ。',
               [['先発', f'{len(starts)}試合'], ['6回以上・無失点', f'{len(qualified)}試合'], ['最長', duration]])


def home_run_streak(games, name):
    from datetime import date
    runs, run = [], []
    for game in sorted(games, key=lambda g: (g['date'], g.get('game_number', 1))):
        if game['stat'].get('homeRuns', 0):
            run.append(game)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    best = max(runs, key=len, default=[])
    if len(best) < 3:
        return
    start, end = (date.fromisoformat(g['date']) for g in (best[0], best[-1]))
    homers = sum(g['stat']['homeRuns'] for g in best)
    period = f'{start.month}月{start.day}日から{end.month}月{end.day}日'
    hit_games = sum(bool(g['stat'].get('homeRuns', 0)) for g in games)
    yield ('hr_streak', f'出場{len(best)}試合連続で本塁打',
           f'{name}は今季、出場何試合続けて本塁打を打ったのだ？',
           f'最長は{len(best)}試合よ。現地時間の{period}にかけて、合わせて{homers}本だったわ。'
           f'シーズンを通して、本塁打が出た試合は{hit_games}試合よ。',
           [['期間（現地）', period], ['出場連続', f'{len(best)}試合で{homers}本'],
            ['今季の本塁打あり', f'{hit_games}試合']])


def player_insights(logs):
    if str(logs.get('season')) != '2026' or logs.get('game_type') != 'R':
        return []
    out = []
    for pid, player in logs['players'].items():
        name = player['jp']
        hitting = player.get('hitting') or []
        pitching = player.get('pitching') or []
        hitting_facts = list(home_run_month(hitting, name)) + list(home_run_streak(hitting, name))
        if hitting:
            hitting_facts.extend(standout_games(hitting, name, (
                ('homeRuns', '本塁打', 2, '本'), ('rbi', '打点', 5, '打点'),
                ('hits', '安打', 4, '安打'), ('baseOnBalls', '四球', 4, '四球'),
            )))
        pitching_facts = list(standout_games(pitching, name, (
            ('strikeOuts', '三振', 10, '奪三振'),
        ))) if pitching else []
        pitching_facts.extend(long_scoreless_starts(pitching, name))
        # 同じ試合の本塁打と打点などは、先に並べた着眼点だけ残す。
        seen = set()
        for group, facts in (('hitting', hitting_facts), ('pitching', pitching_facts)):
            for metric, title, ask, answer, rows in facts:
                signature = (group, rows[0][0])
                if signature in seen:
                    continue
                seen.add(signature)
                out.append(insight_topic(pid, name, metric, f'{name} {title}', ask, answer,
                                         rows, group, source_path='data/jp_player_logs_2026.json'))
    return out
