"""保存したMLB公式2026年RS試合記録から日本人の資産を作る。通信・AI呼出しなし。"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

import season_stock as stock

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = 'data/jp_player_logs_2026.json'
KINDS = ('best', 'month', 'vs', 'streak', 'home', 'win', 'daynight', 'half', 'compare')
FIELDS = ('gamesPlayed', 'gamesStarted', 'plateAppearances', 'atBats', 'hits', 'homeRuns',
          'rbi', 'totalBases', 'baseOnBalls', 'hitByPitch', 'sacFlies', 'strikeOuts',
          'outs', 'inningsPitched', 'runs', 'earnedRuns')
# シーズン合計の再紹介にはしない。既存比較と異なる組を明示的に選ぶ。
PAIRS = ((660271, 808959), (673548, 672960), (807799, 663457),
         (808967, 808963), (684007, 608372), (673540, 837227))
JST = timezone(timedelta(hours=9))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8', newline='\n')


def outs(value):
    """投球回の小数部はアウト数。通常の小数として足さない。"""
    match = re.fullmatch(r'(\d+)\.([012])', str(value))
    if not match:
        raise ValueError('投球回が不正: '+str(value))
    return int(match[1])*3+int(match[2])


def ip(n):
    return f'{n//3}回'+(f'{n%3}/3' if n%3 else '')


def schedule_days(schedule):
    result = {}
    for day in (schedule or {}).get('dates', []):
        for game in day.get('games', []):
            # 延期時と振替後が同じgamePkで並ぶ場合は終了済みの試合を使う。
            if game.get('status', {}).get('codedGameState', 'F') != 'F':
                continue
            pk = game.get('gamePk')
            value = game.get('dayNight')
            if value not in ('day', 'night') or game.get('gameType', 'R') != 'R' or str(game.get('season', '2026')) != '2026':
                value = None
            result[pk] = value if pk not in result or result[pk] == value else None
    return result


def slim(raw, schedule=None, *, schedule_sha256=None):
    days = schedule_days(schedule)
    players = {}
    for pid, player in raw.items():
        result = {'jp': player['jp']}
        for group in ('hitting', 'pitching'):
            rows = []
            for row in player.get(group+'_gameLog', []):
                if row.get('season') != '2026' or row.get('gameType') != 'R':
                    raise ValueError('2026年RS以外の行')
                stat = {k: row['stat'][k] for k in FIELDS if k in row['stat']}
                if group == 'pitching':
                    if stat.get('outs') != outs(stat['inningsPitched']):
                        raise ValueError('アウト数と投球回が不一致')
                rows.append(dict(date=row['date'], game_pk=row['game']['gamePk'], game_number=row['game']['gameNumber'],
                                 opponent_id=row['opponent']['id'], stat=stat,
                                 **{k: row[k] for k in ('isHome', 'isWin') if k in row},
                                 **({'team_id': row['team']['id']} if 'team' in row else {}),
                                 # gameLogのdayNightは全行dayだったため、公式日程だけを昼夜の根拠にする。
                                 **({'dayNight': days[row['game']['gamePk']]} if days.get(row['game']['gamePk']) else {})))
            if len({r['game_pk'] for r in rows}) != len(rows):
                raise ValueError('同一選手・同一試合の重複')
            result[group] = sorted(rows, key=lambda r: (r['date'], r['game_number'], r['game_pk']))
        players[pid] = result
    result = dict(season='2026', game_type='R', source='MLB Stats API',
                acquired='2026-11-04', raw_sha256=hashlib.sha256(
                    json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), players=players)
    if schedule is not None:
        result.update(schedule_sha256=schedule_sha256 or hashlib.sha256(
            json.dumps(schedule, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            schedule_source='MLB Stats API / schedule / season=2026 / gameType=R')
    return result


def aggregate(rows):
    total = defaultdict(int)
    for row in rows:
        for key, value in row['stat'].items():
            if isinstance(value, int):
                total[key] += value
    total['appearances'] = len(rows)
    return dict(total)


def rate(s, group):
    if group == 'pitching':
        return Fraction(s['earnedRuns']*27, s['outs'])
    return Fraction(s['hits'], s['atBats'])


def ip_dec(outs):
    """投球回の数字（10.1 は10回と1/3）。MLBの表記で、数字だけ。"""
    return f'{outs//3}.{outs%3}'


def hook_v3(who, big, unit, sub, chips):
    """1枚目の大きな見せ方（v2）。数字はその回の items・集計にある値だけ。"""
    chips = [dict(score=str(a), label=b) for b, a in chips][:3]
    return dict(who=who, big=str(big), unit=unit, sub=sub, chips=chips)


def number(value):
    # 小数第4位を四捨五入。二進浮動小数の誤差を持ち込まない。
    n = (value.numerator*2000+value.denominator)//(value.denominator*2)
    return f'{n//1000}.{n%1000:03d}'


def date(value):
    day = datetime.fromisoformat(value)
    return f'{day.month}月{day.day}日'


def games_label(rows):
    """題に入れる試合。「8/5のカブス戦と8/17のロッキーズ戦」の形。"""
    days = [datetime.fromisoformat(r['date']) for r in rows]
    return 'と'.join(f'{d.month}/{d.day}の{club(r)}戦' for d, r in zip(days, rows))


def limits(group, relief, versus=False):
    if group == 'hitting':
        return (6, 20) if versus else (0, 50)
    return (3, 9 if relief else 27) if versus else (0, 15 if relief else 45)


def eligible(s, group, relief, versus=False):
    count, minimum = limits(group, relief, versus)
    field = ('atBats' if versus else 'plateAppearances') if group == 'hitting' else 'outs'
    return s.get('appearances', 0) >= count and s.get(field, 0) >= minimum and (
        s.get('atBats', 0) > 0 if group == 'hitting' else s.get('outs', 0) > 0)


def line(s, group):
    if group == 'hitting':
        return f"{s['atBats']}打数{s['hits']}安打、打率{number(rate(s, group))}。{s['homeRuns']}本塁打、{s['rbi']}打点"
    return f"{ip(s['outs'])}で{s['strikeOuts']}奪三振。失点{s['runs']}、自責点{s['earnedRuns']}"+(f"、防御率{number(rate(s, group))}" if s['outs'] else '')


def evidence(rows):
    return [str(r['game_pk']) for r in rows]


def make(kind, pid, player, group, suffix, heading, intro, items, rows, **extra):
    spec = stock.base(f'season_{kind}_2026_{pid}_{group}{suffix}', heading,
                      '2026年レギュラーシーズン。'+intro, items,
                      game_type='R', stock_kind=kind, jp_stock=True, jp=player['jp'],
                      player_ids=[str(pid)], comparison_group=group,
                      source_paths=[SOURCE_PATH], game_ids=evidence(rows), **extra)
    spec['title'] = f'{heading}｜2026年レギュラーシーズン #Shorts'
    return spec


def best(pid, player, group, rows, relief):
    fields = ('homeRuns', 'rbi') if group == 'hitting' else ('strikeOuts', 'outs')
    score = lambda r: tuple(r['stat'][k] for k in fields)
    maximum = max(map(score, rows))
    winners = [r for r in rows if score(r) == maximum]
    if group == 'hitting' and not maximum[0]:
        return None, '本塁打が0で最多本塁打の回として主題が薄い'
    if group == 'pitching' and maximum[0] < 3:
        return None, '最多奪三振が3未満で主題が薄い'
    # 同点なら一日だけを「最高」と断定しない。多すぎる場合も省略して代表日にしない。
    if len(winners) > 2:
        return None, f'最高値が{len(winners)}試合で1本に収まらない'
    heading = player['jp']+('の今季最多本塁打の試合' if group == 'hitting' else 'の今季最多奪三振の試合')
    criterion = '本塁打数、次に打点で比較' if group == 'hitting' else '奪三振数、次に投球回で比較'
    intro = f"{player['jp']}の今季の{len(rows)}{'出場試合' if group == 'hitting' else '登板'}を{criterion}しました。同じ最高値は{len(winners)}試合です。"
    items = []
    for i, r in enumerate(winners):
        s = r['stat']
        items.append((f"{date(r['date'])}の記録", line(s, group)))
    if len(items) == 1:
        s = winners[0]['stat']
        if group == 'hitting':
            items = [('本塁打と打点', f"{date(winners[0]['date'])}は{s['homeRuns']}本塁打、{s['rbi']}打点"),
                     ('打席の記録', f"{s['plateAppearances']}打席、{s['atBats']}打数{s['hits']}安打")]
        else:
            items = [('奪三振と投球回', f"{date(winners[0]['date'])}は{s['strikeOuts']}奪三振、{ip(s['outs'])}"),
                     ('失点と自責点', f"失点{s['runs']}、自責点{s['earnedRuns']}。被安打{s['hits']}、与四球{s['baseOnBalls']}")]
    two_way = {}
    if str(pid) == '660271' and group == 'pitching' and len(winners) == 1:
        batting = [r for r in player['hitting'] if r['game_pk'] == winners[0]['game_pk']]
        if batting:
            items.append(('同じ試合の打撃', line(batting[0]['stat'], 'hitting')))
            intro += '同じ試合の投打の記録を並べます。'
        elif player['hitting']:
            score_bat = lambda r: (r['stat']['homeRuns'], r['stat']['rbi'])
            top = max(map(score_bat, player['hitting']))
            batting = [r for r in player['hitting'] if score_bat(r) == top]
            if 0 < len(batting) <= 2 and top[0] > 0:
                days = 'と'.join(date(r['date']) for r in batting)
                items.append((f'打撃の最高値は{len(batting)}試合', f'本塁打数、次に打点で比較。{days}は'+('ともに' if len(batting)>1 else '')+f'{top[0]}本塁打、{top[1]}打点'))
                intro += '投打の別の試合の記録です。'
            else:
                batting = []
        if batting:
            two_way = dict(two_way=True, batting_game_ids=evidence(batting))
    if len(items) == 2:
        other = [r for r in rows if score(r)[0] == maximum[0]]
        items.append(('最多の回数', f"{'本塁打' if group == 'hitting' else '奪三振'}の今季1試合最多は{maximum[0]}{'本' if group == 'hitting' else '個'}。この数を記録したのは{len(other)}試合です"))
    return make('best', pid, player, group, '', heading, intro, items, winners,
                best_score=list(maximum), tied_games=len(winners), **two_way), None


def split_topic(kind, pid, player, group, rows, relief):
    groups = defaultdict(list)
    for r in rows:
        groups[int(r['date'][5:7]) if kind == 'month' else r['opponent_id']].append(r)
    totals = {k: aggregate(v) for k, v in groups.items()}
    qualified = {k: s for k, s in totals.items() if eligible(s, group, relief, kind == 'vs')}
    if len(qualified) < (3 if kind == 'month' else 2):
        return None, '母数基準を満たす月・相手が2つ未満'
    scores = {k: rate(s, group) for k, s in qualified.items()}
    good, bad = (min(scores.values()), max(scores.values())) if group == 'pitching' else (max(scores.values()), min(scores.values()))
    winners = sorted(k for k in scores if scores[k] == good)
    losers = sorted(k for k in scores if scores[k] == bad)
    if good == bad or len(winners) != 1 or (kind == 'month' and len(losers) != 1):
        return None, '最高・最低が同率で一つに限定できない'
    metric = '打率' if group == 'hitting' else '防御率'
    if kind == 'month':
        a, b = winners[0], losers[0]
        heading = f"{player['jp']}の月別{metric}の変化"
        intro = f"{player['jp']}の月別{metric}を、母数の条件を満たす{len(qualified)}か月で比較します。"
        items = [(f'{metric}が最も良い{a}月', f"{a}月は{qualified[a].get('plateAppearances', qualified[a].get('appearances'))}{'打席' if group == 'hitting' else '登板'}。"+line(qualified[a], group)),
                 (f'{metric}が最も低い{b}月' if group == 'hitting' else f'防御率が最も高い{b}月', f'{b}月は'+line(qualified[b], group))]
        selected = groups[a]+groups[b]
    else:
        from notability_engine import MLB_TEAM_NAME_JP
        a = winners[0]
        opponent = MLB_TEAM_NAME_JP.get(str(a)) or MLB_TEAM_NAME_JP.get(a)
        if not opponent:
            return None, '相手球団名が未登録'
        heading = f"{player['jp']}が最も{'打った' if group == 'hitting' else '抑えた'}相手"
        intro = f"{player['jp']}の相手別{metric}を比較します。母数の条件を満たす{len(qualified)}球団では、{opponent}戦が最も良い数字でした。"
        s = qualified[a]
        items = [(f'{opponent}戦の母数', f"{s['appearances']}{'試合' if group == 'hitting' else '登板'}で、"+(f"{s['plateAppearances']}打席、{s['atBats']}打数{s['hits']}安打" if group == 'hitting' else f"{ip(s['outs'])}、自責点{s['earnedRuns']}")),
                 (f'{opponent}戦の成績', (f"打率{number(good)}。{s['homeRuns']}本塁打、{s['rbi']}打点" if group == 'hitting' else f"防御率{number(good)}。{s['strikeOuts']}奪三振、被安打{s['hits']}"))]
        selected = groups[a]
    _, minimum = limits(group, relief, kind == 'vs')
    criterion = (f'{minimum}{"打数" if kind == "vs" else "打席"}以上' if group == 'hitting' else ip(minimum)+'以上')
    if kind == 'vs':
        criterion = ('6試合以上かつ' if group == 'hitting' else '3登板以上かつ')+criterion
    intro += criterion+'だけを対象にします。'
    if kind == 'month':
        c = next(k for k in sorted(qualified) if k not in (a, b))
        items.append((f'{c}月の記録', f'{c}月は'+line(qualified[c], group)))
        selected += groups[c]
    else:
        c = sorted((k for k in qualified if k != a), key=lambda k: (scores[k] if group == 'pitching' else -scores[k], k))[0]
        opponent2 = MLB_TEAM_NAME_JP.get(str(c)) or MLB_TEAM_NAME_JP.get(c)
        if not opponent2:
            return None, '比較相手の球団名が未登録'
        items.append((f'次に良い{opponent2}戦', f"{qualified[c]['appearances']}{'試合' if group == 'hitting' else '登板'}で"+line(qualified[c], group)))
        selected += groups[c]
    return make(kind, pid, player, group, '', heading, intro, items, selected,
                qualified=list(sorted(qualified)), best=winners, worst=losers if kind == 'month' else []), None


def home(pid, player, group, rows, relief):
    if any(type(r.get('isHome')) is not bool for r in rows):
        return None, 'ホーム区分の欠測'
    buckets = {v: [r for r in rows if r['isHome'] == v] for v in (True, False)}
    totals = {v: aggregate(rr) for v, rr in buckets.items()}
    if not all(eligible(s, group, relief) for s in totals.values()):
        return None, 'ホーム・アウェーの母数が月別基準未満'
    if abs(rate(totals[True], group)-rate(totals[False], group)) < (Fraction(1, 10) if group == 'hitting' else 3):
        return None, 'ホーム・アウェーの差が打率.100・防御率3.00未満'
    return make('home', pid, player, group, '', player['jp'], '', [], rows), None


def daynight(pid, player, group, rows, relief):
    if any(r.get('dayNight') not in ('day', 'night') for r in rows):
        return None, '昼夜区分の欠測・不明値'
    totals = {v: aggregate([r for r in rows if r['dayNight'] == v]) for v in ('day', 'night')}
    if not all(eligible(st, group, relief) for st in totals.values()):
        return None, 'デーゲーム・ナイターの母数が月別基準未満'
    if abs(rate(totals['day'], group)-rate(totals['night'], group)) < (Fraction(1, 10) if group == 'hitting' else 3):
        return None, 'デーゲーム・ナイターの差が打率.100・防御率3.00未満'
    return make('daynight', pid, player, group, '', player['jp'], '', [], rows), None


def half_period(row):
    # Stats APIの公式試合日を使い、日程のUTC開始時刻で月境界を変えない。
    month = datetime.fromisoformat(row['date']).month
    return 'first' if 3 <= month <= 6 else 'second' if 7 <= month <= 9 else None


def half(pid, player, group, rows, relief):
    if any(half_period(r) is None for r in rows):
        return None, '公式試合日が3〜9月の範囲外'
    totals = {v: aggregate([r for r in rows if half_period(r) == v]) for v in ('first', 'second')}
    if not all(eligible(st, group, relief) for st in totals.values()):
        return None, '前半・後半の母数が月別基準未満'
    if abs(rate(totals['first'], group)-rate(totals['second'], group)) < (Fraction(1, 10) if group == 'hitting' else 3):
        return None, '前半・後半の差が打率.100・防御率3.00未満'
    return make('half', pid, player, group, '', player['jp'], '', [], rows), None


def concise_stats(st, group):
    denominator = st.get('atBats', 0) if group == 'hitting' else st.get('outs', 0)
    metric = '打率' if group == 'hitting' else '防御率'
    value = display_rate(st, group) if denominator else '算出なし'
    if group == 'hitting':
        return f"{metric}{value}、{st.get('homeRuns', 0)}本塁打、{st.get('rbi', 0)}打点"
    return f"{metric}{value}、{ip(st.get('outs', 0))}、{st.get('strikeOuts', 0)}奪三振"


def win(pid, player, group, rows, relief):
    if any(type(r.get('team_id')) is not int or type(r.get('isWin')) is not bool for r in rows):
        return None, '所属・チーム勝敗の欠測'
    affiliations = player.get('hitting', [])+player.get('pitching', []) or rows
    if any(type(r.get('team_id')) is not int for r in affiliations):
        return None, '所属の欠測'
    if len({r['team_id'] for r in affiliations}) != 1:
        return None, 'シーズン途中の所属変更のため見送り'
    selected = [r for r in rows if (r['stat'].get('homeRuns', 0) > 0 if group == 'hitting' else r['stat'].get('gamesStarted') == 1)]
    if len(selected) < 6:
        return None, '本塁打試合・先発試合が6試合未満'
    return make('win', pid, player, group, '', player['jp'], '', [], selected,
                team_id=rows[0]['team_id']), None


def runs(rows, group):
    found, current = [], []
    for r in rows:
        # 打席のない出場は連続試合安打を切ると断定せず、この型全体を見送る。
        if group == 'hitting' and r['stat'].get('plateAppearances', 0) == 0:
            return []
        ok = r['stat']['hits'] > 0 if group == 'hitting' else r['stat']['runs'] == 0
        if ok:
            current.append(r)
        elif current:
            found.append(current); current = []
    if current:
        found.append(current)
    return found


def streak(pid, player, group, rows, relief):
    sequences = runs(rows, group)
    longest = max((len(r) for r in sequences), default=0)
    winners = [r for r in sequences if len(r) == longest]
    if longest < 3 or len(winners) != 1:
        return None, '3試合未満・最長同率・打席なし出場を含むため限定不可'
    run = winners[0]
    word = '連続試合安打' if group == 'hitting' else '連続無失点登板'
    heading = f"{player['jp']}の今季最長{longest}{'試合連続安打' if group == 'hitting' else '登板連続無失点'}"
    first, last = run[0], run[-1]
    intro = f"{player['jp']}の2026年の出場記録を順に確認しました。今季最長の{word}は{longest}{'試合' if group == 'hitting' else '登板'}です。"
    items = [('記録の期間', f"現地日付の{date(first['date'])}から{date(last['date'])}まで。"+line(aggregate(run), group)),
             ('最初の試合', f"{date(first['date'])}は"+line(first['stat'], group)),
             ('最後の試合', f"{date(last['date'])}は"+line(last['stat'], group))]
    return make('streak', pid, player, group, '', heading, intro, items, run,
                streak_length=longest), None


def expression_errors(spec):
    text = str([spec.get(k) for k in ('title', 'intro', 'items')])
    errors = [word for word in ('史上', '球団記録', '日本人記録', '歴代', '新記録', 'キャリア最高', '活躍') if word in text]
    if '、' in spec['title'] or re.search(r'[？?！!]', spec['title']):
        errors.append('題の呼びかけ・読点')
    if not re.sub(r'^【[^】]+】', '', spec['title']).startswith(spec['jp']):
        errors.append('日本人名が先頭にない')
    if spec.get('editorial_version') == 2:
        for phrase in ('比較しました', '同じ最高値', '母数', 'だけを対象', '順に確認', '比較します', '並べます', '代打', '満塁'):
            if phrase in text:
                errors.append(phrase)
        if not re.search(r'\d', spec['title']) or '｜2026年' in spec['title']:
            errors.append('題が数字中心でない')
        if spec.get('comparison_group') == 'hitting' and re.search(r'(?<!\d)0\.\d{3}', text):
            errors.append('打率の先頭0')
    return errors


def display_rate(stat, group):
    value = rate(stat, group)
    places = 3 if group == 'hitting' else 2
    scale = 10**places
    n = (value.numerator*scale*2+value.denominator)//(value.denominator*2)
    text = f'{n//scale}.{n%scale:0{places}d}'
    return text.removeprefix('0') if group == 'hitting' else text


def club(row):
    from notability_engine import MLB_TEAM_NAME_JP
    return MLB_TEAM_NAME_JP[str(row['opponent_id'])]


def detail(stat, group):
    if group == 'hitting':
        return f"{stat['atBats']}打数{stat['hits']}安打、{stat['homeRuns']}本塁打、{stat['rbi']}打点"
    return f"{ip(stat['outs'])}、{stat['strikeOuts']}奪三振、失点{stat['runs']}、自責点{stat['earnedRuns']}"


def editorial(spec, players):
    """11/2の採用基準。説明作業ではなく、記録の数字と場面を材料から写す。"""
    pid, group, kind = spec['player_ids'][0], spec['comparison_group'], spec['stock_kind']
    player = players[pid]
    name = player['jp']
    rows = player[group]
    selected = [r for r in rows if str(r['game_pk']) in spec['game_ids']]
    relief = sum(r['stat'].get('gamesStarted', 0) for r in rows)*2 < len(rows)
    note = '2026年レギュラーシーズン／MLB公式'
    title = None
    tag = hook = None
    if kind == 'best':
        a = selected[0]; s = a['stat']
        if group == 'hitting':
            if s['homeRuns'] < 2 and s['rbi'] < 5:
                return None, '最多試合が2本塁打・5打点のいずれにも届かない'
            focus = f"1試合{s['rbi']}打点" if s['rbi'] >= 5 else f"1試合{s['homeRuns']}本塁打"
            heading = f"{name} {s['homeRuns']}本塁打で{s['rbi']}打点" if s['rbi'] >= 5 else f'{name} {focus}'
            intro = f"{name}は1試合で{s['homeRuns']}本塁打、{s['rbi']}打点を記録しました。{date(a['date'])}の{club(a)}戦です。"
            items = [(f"{date(a['date'])}の{club(a)}戦", f"{s['homeRuns']}本塁打、{s['rbi']}打点"),
                     ('打席の記録', f"{s['plateAppearances']}打席、{s['atBats']}打数{s['hits']}安打")]
            note += '／本塁打数→打点順'
        else:
            if s['strikeOuts'] < 10 or any(r['stat'].get('gamesStarted') != 1 for r in selected):
                return None, '先発10奪三振以上に届かない'
            heading = f"{name} 今季最多は{s['strikeOuts']}奪三振"
            intro = f"{name}の今季最多は1試合{s['strikeOuts']}奪三振です。{date(a['date'])}の{club(a)}戦では{ip(s['outs'])}を投げました。"
            if len(selected) == 2:
                heading = f"{name} {ip(s['outs'])}{s['strikeOuts']}奪三振の2試合"
                intro = f"{name}は{ip(s['outs'])}{s['strikeOuts']}奪三振を2試合で記録しました。{date(a['date'])}の{club(a)}戦がその一つです。"
            items = [(f"{date(a['date'])}の{club(a)}戦", detail(s, group)),
                     ('被安打と四球', f"被安打{s['hits']}、与四球{s['baseOnBalls']}でした")]
            note += '／奪三振数→投球回順'
        if spec.get('two_way'):
            bats = [r for r in player['hitting'] if str(r['game_pk']) in spec['batting_game_ids']]
            dates = 'と'.join(date(r['date']) for r in bats)
            bs = bats[0]['stat']
            items.append((f"打者としては{bs['homeRuns']}本塁打", f"打撃では{dates}にそれぞれ{bs['homeRuns']}本塁打、{bs['rbi']}打点。投球とは別の試合です"))
        elif len(selected) == 2:
            b = selected[1]
            items.append((f"{date(b['date'])}の{club(b)}戦", detail(b['stat'], group)))
        else:
            # 別の季節合計を埋め草にせず、同じ日の具体的な記録を補う。
            if group == 'hitting':
                other_hits, other_bases = s['hits']-s['homeRuns'], s['totalBases']-4*s['homeRuns']
                composition = f"{s['homeRuns']}本の本塁打で{s['homeRuns']*4}塁打。"
                if other_hits:
                    composition += f'残る{other_hits}安打で{other_bases}塁打を加え、'
                composition += f"合計{s['totalBases']}塁打でした。{s['runs']}得点も記録しました"
                items.append(('塁打と得点', composition))
                if s['rbi'] == max(r['stat']['rbi'] for r in rows):
                    items[0] = (items[0][0], items[0][1]+'。この打点数が今季の1試合最多でした')
            else:
                # 「最多は1登板」を言い直さず、次に多い登板と比べる（11/3 今永の回が同じ話の繰り返しだった）。
                lower = [r['stat']['strikeOuts'] for r in rows if r['stat']['strikeOuts'] < s['strikeOuts']]
                if lower:
                    second = [r for r in rows if r['stat']['strikeOuts'] == max(lower)]
                    items.append(('次に多い登板', f"次に多いのは{max(lower)}奪三振で、"+'、'.join(date(r['date']) for r in second)+f"の{len(second)}登板でした"))
        note += f"／同値{len(selected)}試合"
        # 題だけでどの試合か分かるようにする（11/4 本人「8/5のカブス戦とか書いたほうがいい」）。
        record = (f"{s['homeRuns']}本塁打" + (f"{s['rbi']}打点" if s['rbi'] >= 5 else '') if group == 'hitting'
                  else (f"今季最多{s['strikeOuts']}奪三振" if len(selected) == 1 else f"{ip(s['outs'])}{s['strikeOuts']}奪三振"))
        title = f"{name} {games_label(selected)}で{record}"
        tag = '今季最高'
        tie = f'（同数{len(selected)}試合）' if len(selected) > 1 else ''
        if group == 'hitting':
            hook = hook_v3(name, s['homeRuns'], '本塁打', '今季の1試合最多'+tie,
                           [('打点', s['rbi']), ('安打', s['hits']), ('塁打', s['totalBases'])])
        else:
            hook = hook_v3(name, s['strikeOuts'], '奪三振', '今季の1試合最多'+tie,
                           [('投球回', ip_dec(s['outs'])), ('被安打', s['hits']), ('失点', s['runs'])])
    elif kind in ('month', 'vs'):
        buckets = defaultdict(list)
        for r in rows:
            buckets[int(r['date'][5:7]) if kind == 'month' else r['opponent_id']].append(r)
        totals = {k: aggregate(v) for k, v in buckets.items()}
        a = spec['best'][0]; sa = totals[a]
        good = rate(sa, group)
        _, minimum = limits(group, relief, kind == 'vs')
        note += '／'+((f'{minimum}打席以上' if kind == 'month' else '6試合・20打数以上') if group == 'hitting' else (ip(minimum)+'以上'+('・3登板以上' if kind == 'vs' else '')))
        metric = '打率' if group == 'hitting' else '防御率'
        if kind == 'month':
            b = spec['worst'][0]; sb = totals[b]
            spread = abs(good-rate(sb, group))
            if spread < (Fraction(1, 10) if group == 'hitting' else 3):
                return None, '最高・最低の差が打率.100・防御率3.00の基準未満'
            va, vb = display_rate(sa, group), display_rate(sb, group)
            heading = f'{name} {metric}{va}の{a}月と{vb}の{b}月'
            intro = f'{name}の{metric}は{a}月が{va}、{b}月が{vb}でした。'
            items = [(f'{a}月の記録', detail(sa, group)+(f"。{sa['plateAppearances']}打席" if group == 'hitting' else f"。{sa['appearances']}登板")),
                     (f'{b}月の記録', detail(sb, group)+(f"。{sb['plateAppearances']}打席" if group == 'hitting' else f"。{sb['appearances']}登板"))]
            c = next(k for k in spec['qualified'] if k not in (a,b))
            items.append((f'{c}月の記録', f'{metric}{display_rate(totals[c], group)}。'+detail(totals[c], group)))
            tag = '月別の成績'
            # 率は数字の後ろに「防御率」を置くと読みにくいので、単位を空にして句の側で言う。
            hook = hook_v3(name, va, '', f'{a}月の{metric}',
                           [(f'{b}月の{metric}', vb),
                            (f'{a}月の'+('打席' if group == 'hitting' else '登板'), sa['plateAppearances'] if group == 'hitting' else sa['appearances']),
                            (f'{c}月の{metric}', display_rate(totals[c], group))])
        else:
            cutoff = Fraction(325 if pid in ('660271','808959') else 350, 1000)
            if (good < cutoff if group == 'hitting' else good > Fraction(3, 2)):
                return None, '相手別の打率・防御率が採用基準未満'
            opponent = club(buckets[a][0]); value = display_rate(sa, group)
            heading = f'{name}が{metric}{value}を記録した相手'
            intro = f'{name}は{opponent}戦で{metric}{value}を記録しました。'
            items = [(f'{opponent}戦の記録', f"{sa['appearances']}{'試合' if group == 'hitting' else '登板'}。"+detail(sa, group)),
                     ('打席の数' if group == 'hitting' else '投球の内訳', f"{sa['plateAppearances']}打席、{sa['totalBases']}塁打、四球{sa['baseOnBalls']}" if group == 'hitting' else f"{ip(sa['outs'])}で被安打{sa['hits']}、与四球{sa['baseOnBalls']}")]
            c = sorted((k for k in spec['qualified'] if k != a), key=lambda k: (rate(totals[k], group) if group == 'pitching' else -rate(totals[k], group),k))[0]
            items.append((f"{club(buckets[c][0])}戦では", f'{metric}{display_rate(totals[c], group)}。'+detail(totals[c], group)))
            tag = '相手別の成績'
            hook = hook_v3(name, value, '', f'{opponent}戦の{metric}',
                           [('試合' if group == 'hitting' else '登板', sa['appearances']),
                            ('打席' if group == 'hitting' else '投球回', sa['plateAppearances'] if group == 'hitting' else ip_dec(sa['outs'])),
                            ('本塁打' if group == 'hitting' else '奪三振', sa['homeRuns'] if group == 'hitting' else sa['strikeOuts'])])
    elif kind in ('home', 'daynight', 'half'):
        field, keys, labels = ('isHome', (True, False), ('ホーム', 'アウェー')) if kind == 'home' else ('dayNight', ('day', 'night'), ('デーゲーム', 'ナイター'))
        if kind == 'half':
            keys, labels = ('first', 'second'), ('前半', '後半')
        totals = {v: aggregate([r for r in rows if (half_period(r) if kind == 'half' else r[field]) == v]) for v in keys}
        sa, sb = totals[keys[0]], totals[keys[1]]
        la, lb = labels
        metric = '打率' if group == 'hitting' else '防御率'
        va, vb = display_rate(sa, group), display_rate(sb, group)
        heading = f'{name} {la}{metric}{va}と{lb}{vb}'
        intro = f'{name}の{metric}は{la}が{va}、{lb}が{vb}でした。'
        items = [(label+'の記録', (concise_stats(st, group) if kind in ('daynight', 'half') else detail(st, group))) for label, st in [(la, sa), (lb, sb)]]
        items.append(('打席数' if group == 'hitting' else '登板数',
                      f"{la}{sa['plateAppearances']}打席、{lb}{sb['plateAppearances']}打席" if group == 'hitting' else
                      f"{la}{sa['appearances']}登板、{lb}{sb['appearances']}登板"))
        _, minimum = limits(group, relief)
        note += '／両方'+(f'{minimum}打席以上' if group == 'hitting' else ip(minimum)+'以上')
        tag = {'home': '本拠地と敵地', 'daynight': '昼と夜', 'half': '前半と後半'}[kind]
        first_better = (rate(sa, group) >= rate(sb, group)) == (group == 'hitting')
        (ga, gl), (ba, bl) = ((sa, la), (sb, lb)) if first_better else ((sb, lb), (sa, la))
        count = 'plateAppearances' if group == 'hitting' else 'appearances'
        unit_count = '打席' if group == 'hitting' else '登板'
        hook = hook_v3(name, display_rate(ga, group), '', f'{gl}の{metric}',
                       [(f'{bl}の{metric}', display_rate(ba, group)),
                        (f'{la}の{unit_count}', sa[count]), (f'{lb}の{unit_count}', sb[count])])
        if kind == 'daynight':
            note += '／昼夜はMLB公式日程'
        if kind == 'half':
            note += '／前半3〜6月・後半7〜9月／公式試合日'
    elif kind == 'win':
        from notability_engine import MLB_TEAM_NAME_JP
        team = MLB_TEAM_NAME_JP.get(str(spec['team_id']))
        if not team:
            return None, '所属球団名が未登録'
        wins = sum(r['isWin'] for r in selected)
        losses = len(selected)-wins
        condition = '本塁打を打った' if group == 'hitting' else '先発した'
        heading = f'{name} {condition}試合でチームは{wins}勝{losses}敗'
        intro = f'{name}が{condition}{len(selected)}試合で、{team}は{wins}勝{losses}敗でした。'
        items = [(f'{condition}{len(selected)}試合', concise_stats(aggregate(selected), group)),
                 (f'チームが勝った{wins}試合', concise_stats(aggregate([r for r in selected if r['isWin']]), group)),
                 (f'チームが敗れた{losses}試合', concise_stats(aggregate([r for r in selected if not r['isWin']]), group))]
        note += '／'+team+'の試合勝敗・個人の勝敗ではない'
        tag = '本塁打と勝敗' if group == 'hitting' else '先発と勝敗'
        won, lost = aggregate([r for r in selected if r['isWin']]), aggregate([r for r in selected if not r['isWin']])
        if group == 'hitting':
            chips = [('勝った試合の本塁打', won.get('homeRuns', 0)), ('敗れた試合の本塁打', lost.get('homeRuns', 0))]
        else:
            chips = [('勝った試合の防御率', display_rate(won, group) if won.get('outs') else None),
                     ('敗れた試合の防御率', display_rate(lost, group) if lost.get('outs') else None)]
        hook = hook_v3(name, wins, '勝', f'{losses}敗（{condition}{len(selected)}試合）', [c for c in chips if c[1] is not None])
    elif kind == 'streak':
        n = spec['streak_length']
        minimum = (8 if pid in ('660271','808959') else 10) if group == 'hitting' else (8 if relief else 4)
        if n < minimum:
            return None, f'連続記録が採用基準{minimum}未満'
        a,b = selected[0],selected[-1]
        word = f'{n}試合連続安打' if group == 'hitting' else f'{n}登板連続無失点'
        heading = f'{name} {word}'
        intro = f"{name}は{word}を記録しました。{date(a['date'])}の{club(a)}戦から{date(b['date'])}の{club(b)}戦まで続きました。"
        items = [('期間中の成績', detail(aggregate(selected), group)),
                 (f"始まりは{club(a)}戦", f"{date(a['date'])}は"+detail(a['stat'], group)),
                 (f"最後は{club(b)}戦", f"{date(b['date'])}は"+detail(b['stat'], group))]
        note += '／本人の出場順・失点0で判定'
        tag = '連続記録'
        agg = aggregate(selected)
        if group == 'hitting':
            hook = hook_v3(name, n, '試合', '連続で安打',
                           [('期間中の安打', agg['hits']), ('打数', agg['atBats']), ('本塁打', agg['homeRuns'])])
        else:
            hook = hook_v3(name, n, '登板', '連続で無失点',
                           [('期間中の投球回', ip_dec(agg['outs'])), ('奪三振', agg['strikeOuts']), ('失点', agg['runs'])])
    else:
        b = players[spec['player_ids'][1]]
        pairs = []
        for month in spec['compare_months']:
            aa = aggregate([r for r in rows if int(r['date'][5:7]) == month])
            bb = aggregate([r for r in b[group] if int(r['date'][5:7]) == month])
            pairs.append((month, aa, bb))
        m,sa,sb = max(pairs, key=lambda v: abs(rate(v[1],group)-rate(v[2],group)))
        metric = '打率' if group == 'hitting' else '防御率'
        va,vb = display_rate(sa,group),display_rate(sb,group)
        heading = f'{name}と{b["jp"]} {m}月の{metric}{va}と{vb}'
        intro = f'{name}は{m}月に{metric}{va}、{b["jp"]}は{vb}を記録しました。'
        items = [(f'{month}月の{metric}', f"{name}は{display_rate(aa,group)}、{b['jp']}は{display_rate(bb,group)}。"+(f"打席数は{aa['plateAppearances']}と{bb['plateAppearances']}" if group == 'hitting' else f"投球回は{ip(aa['outs'])}と{ip(bb['outs'])}")) for month,aa,bb in pairs]
        note += '／同月同士・'+('各50打席以上' if group == 'hitting' else '各15回以上')
        tag = '2人を比べる'
        hook = hook_v3(f'{name}と{b["jp"]}', f'{va}/{vb}', '', f'{m}月の{metric}（左が{name}）',
                       [(f'{month}月の{metric}', f'{display_rate(aa,group)}/{display_rate(bb,group)}') for month,aa,bb in pairs])
    spec.update(title=f'【{tag}】'+(title or heading)+' #Shorts', label=heading, heading=heading, hook=heading,
                intro=intro, items=items, criteria_note=note, editorial_version=2)
    spec['v3'] = dict(spec.get('v3') or {}, source=note, **hook)
    return spec, None


def duplicate(spec, done, catalog):
    if spec['key'] in done:
        return True
    for key, row in done.items():
        old = catalog.get(key, {})
        if spec['title'] == row.get('title') or spec['title'] == old.get('title'):
            return True
        if spec['stock_kind'] == 'compare':
            match = re.fullmatch(r'season_compare_2026_(\d+)_(\d+)', key)
            if match and set(match.groups()) == set(spec['player_ids']):
                return True
        # 個人の試合回として公開した同じ選手・試合は再利用しない。
        if key.startswith(('season_best_', 'season_streak_', 'ps_pitcher_', 'ps_game_')):
            if set(map(str, old.get('player_ids', row.get('player_ids', [])))) & set(spec['player_ids']) and set(map(str, old.get('game_ids', []))) & set(spec['game_ids']):
                return True
    return False


def balanced_schedule(topics):
    """1日2本までの見本順。前日・当日の選手と、直前・同日の型を重ねない。"""
    pending = list(topics)
    days, previous_players, last_kind = [], set(), None
    while pending:
        picked, used_players, used_kinds = [], set(), set()
        for _ in range(2):
            counts = {k: sum(t['stock_kind'] == k for t in pending) for k in KINDS}
            candidates = [t for t in pending if t['stock_kind'] not in used_kinds and t['stock_kind'] != last_kind
                          and not set(t['player_ids']) & (previous_players | used_players)]
            if not candidates:
                break
            t = min(candidates, key=lambda t: (-counts[t['stock_kind']], t['key']))
            picked.append(t)
            pending.remove(t)
            used_players.update(t['player_ids'])
            used_kinds.add(t['stock_kind'])
            last_kind = t['stock_kind']
        days.append([t['key'] for t in picked])
        previous_players = used_players
        if len(days) > 60:
            raise ValueError('公開順を組めません')
    return days


def build(root=ROOT):
    doc = stock.read(root/SOURCE_PATH)
    if doc.get('season') != '2026' or doc.get('game_type') != 'R' or doc.get('source') != 'MLB Stats API':
        return dict(season='2026', topics=[], skipped=[dict(reason='公式2026年RS材料なし')])
    players = doc['players']
    done = {**stock.read(root/'data/published_assets.json').get('assets', {}),
            **stock.read(root/'data/published_videos.json').get('asset', {})}
    catalog = {t['key']: t for t in stock.read(root/'data/season_topics.json').get('topics', [])}
    topics, skipped = [], []
    def accept(spec, reason, pid, group, kind):
        if spec:
            spec, reason = editorial(spec, players)
        if spec and duplicate(spec, done, catalog):
            reason, spec = '公開済みの同一題材', None
        if spec:
            errors = expression_errors(spec)
            if errors:
                raise ValueError(errors)
            topics.append(spec)
        else:
            skipped.append(dict(player_id=pid, jp=players[pid]['jp'], group=group, kind=kind, reason=reason))
    for pid, p in players.items():
        for group in ('hitting', 'pitching'):
            rows = p[group]
            if not rows:
                for kind in KINDS[:-1]:
                    accept(None, '出場記録なし', pid, group, kind)
                continue
            relief = sum(r['stat'].get('gamesStarted', 0) for r in rows)*2 < len(rows)
            for kind, func in [('best', best), ('month', lambda *a: split_topic('month', *a)),
                               ('vs', lambda *a: split_topic('vs', *a)), ('streak', streak), ('home', home), ('win', win), ('daynight', daynight), ('half', half)]:
                spec, reason = func(pid, p, group, rows, relief)
                accept(spec, reason, pid, group, kind)
    for aid, bid in PAIRS:
        a, b = players[str(aid)], players[str(bid)]
        group = 'pitching' if a['pitching'] and b['pitching'] else 'hitting'
        ar, br = a[group], b[group]
        # 比較の主題は月ごとの打率/防御率。既存season_player合計のなぞりを避ける。
        common = []
        for m in range(3, 10):
            aa = [r for r in ar if int(r['date'][5:7]) == m]
            bb = [r for r in br if int(r['date'][5:7]) == m]
            sa, sb = aggregate(aa), aggregate(bb)
            if eligible(sa, group, False) and eligible(sb, group, False):
                common.append((m, aa, bb, sa, sb))
        if len(common) < 3:
            accept(None, '両者の母数を満たす共通月が3未満', str(aid), group, 'compare')
            continue
        metric = '打率' if group == 'hitting' else '防御率'
        heading = f"{a['jp']}と{b['jp']}の月別{metric}"
        # 最大差の月を中心に前後を含む3か月を選ぶ。同月同士だけ比較。
        center = max(range(len(common)), key=lambda i: abs(rate(common[i][3], group)-rate(common[i][4], group)))
        start = max(0, min(center-1, len(common)-3))
        selected = common[start:start+3]
        items = [(f'{m}月の{metric}', f"{a['jp']}は{number(rate(sa, group))}、{b['jp']}は{number(rate(sb, group))}。"+(f"打席数は{sa['plateAppearances']}と{sb['plateAppearances']}" if group == 'hitting' else f"投球回は{ip(sa['outs'])}と{ip(sb['outs'])}")) for m, aa, bb, sa, sb in selected]
        spec = make('compare', aid, a, group, '_'+str(bid), heading,
                    f"{a['jp']}と{b['jp']}の同じ月の{metric}を並べます。両者とも{'50打席' if group == 'hitting' else '15回'}以上の月から、差が最も大きい{common[center][0]}月を含む3か月です。", items,
                    [r for _, aa, _, _, _ in selected for r in aa])
        spec.update(player_ids=[str(aid), str(bid)], compare_months=[x[0] for x in selected])
        accept(spec, None, str(aid), group, 'compare')
    schedule = balanced_schedule(topics)
    ranks = {key: i for i, key in enumerate(key for day in schedule for key in day)}
    for t in topics:
        t['stock_order'] = ranks[t['key']]
    topics.sort(key=lambda t: t['stock_order'])
    return dict(season='2026', source='MLB Stats API / 保存済みRS試合記録', topics=topics, skipped=skipped, schedule=schedule)


def rotation_available(topic, spec, ledgers, as_of=None):
    """JSTの今日と前日の選手を避ける。予約は予定日を使う。"""
    import jp_assets
    now = as_of or datetime.now(JST)
    day = now.astimezone(JST).date()
    players = jp_assets.ids(topic, spec)
    import asset_policy
    rows = asset_policy.merge_records(ledgers[0].get('asset', {}), ledgers[1].get('assets', {}))
    for key, row in rows.items():
        try:
            stamp = datetime.fromisoformat(str(row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
        except (ValueError, KeyError):
            continue
        on = stamp.astimezone(JST).date()
        if on in (day-timedelta(days=1), day) and players & jp_assets.ids(key, row):
            return False
    return True


def rotation_priority(topic, spec, ledgers, as_of=None):
    """既存の当日・前日禁止を保ち、最後の登場が古い選手を先にする。"""
    if not spec.get('jp_stock'):
        return (0, 0)
    import jp_assets
    import asset_policy
    now = as_of or datetime.now(JST)
    ids = jp_assets.ids(topic, spec)
    last, count = 0, 0
    rows = asset_policy.merge_records(ledgers[0].get('asset', {}), ledgers[1].get('assets', {}))
    for key, row in rows.items():
        if not ids & jp_assets.ids(key, row):
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp > now:
                continue
        except (ValueError, KeyError):
            continue
        last = max(last, stamp.astimezone(JST).date().toordinal())
        count += 1
    return (last, count)


def validate_spec(spec, root=ROOT):
    """制作の直前にも原資料から再計算。材料JSONの台詞・数字の書換えは通さない。"""
    expected = next((t for t in build(root)['topics'] if t['key'] == spec['key']), None)
    fields = ('title', 'intro', 'items', 'player_ids', 'comparison_group', 'game_ids', 'two_way', 'batting_game_ids', 'criteria_note', 'editorial_version', 'stock_kind', 'team_id', 'jp_stock', 'source_paths')
    normalized = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False)
    if not expected or expression_errors(spec) or any(normalized(spec.get(k)) != normalized(expected.get(k)) for k in fields):
        raise ValueError('日本人資産の数字・台詞が保存した公式試合記録と一致しません')
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--import-raw', type=Path)
    ap.add_argument('--import-schedule', type=Path)
    ap.add_argument('--out', type=Path, default=Path('build/jp_stock_topics.json'))
    args = ap.parse_args()
    if args.import_raw:
        schedule = json.loads(args.import_schedule.read_text(encoding='utf8')) if args.import_schedule else None
        digest = hashlib.sha256(args.import_schedule.read_bytes()).hexdigest() if args.import_schedule else None
        write(ROOT/SOURCE_PATH, slim(stock.read(args.import_raw), schedule, schedule_sha256=digest))
    elif args.import_schedule:
        ap.error('--import-schedule は --import-raw と一緒に指定してください')
    doc = build()
    write(args.out, doc)
    print(f"日本人新型: {len(doc['topics'])}本、見送り{len(doc['skipped'])}件")


if __name__ == '__main__':
    main()
