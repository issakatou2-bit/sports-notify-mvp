"""保存済みの日次Analyticsだけで、予定どおりだった話者を種類別に比べる。"""
from datetime import timedelta
import hashlib
import math
import random
import statistics

import host_split as hs

WINDOWS = ((1, '24時間'), (3, '3日'), (7, '7日'))
METRICS = ('views', 'averageViewDuration', 'averageViewPercentage', 'likes', 'subscribersGained')
LABELS = {'morning': '日本人選手の成績', 'morning_voices': '現地の声', 'morning_press': '現地の報道',
          'daily': 'MLB予告', 'morning_postseason': 'PS情勢', 'daily_soccer': '欧州予告',
          'soccer_race': '欧州順位争い', 'soccer_week': '欧州の週末', 'soccer_results': '欧州の結果',
          'soccer_voices': '欧州の現地の声', 'soccer_now': 'サッカー試合速報', 'japan_reacts': '日本語の反応',
          'player_story': '選手の物語', 'reddit_reaction': 'ファンの反応', 'season_game': '試合の話題',
          'season_story': '選手・球団の物語', 'season_spotlight': '選手の活躍', 'season_league': 'リーグ成績',
          'season_team': '球団のシーズン', 'season_odds': '進出の見通し', 'season_momentum': '球団の流れ',
          'legend': '殿堂・歴史', 'v3': '資産動画'}


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def rows(videos, week_end):
    from weekly_report import parse_time
    out, seen = [], set()
    for by_day in videos.values():
        if not isinstance(by_day, dict):
            continue
        for rec in by_day.values():
            if not isinstance(rec, dict) or rec.get('privacy') not in (None, 'public'):
                continue
            assignment = rec.get('host_assignment')
            published = parse_time(rec.get('publish_at') or rec.get('published_at'))
            vid = rec.get('video_id')
            if not hs.valid(assignment) or not vid or vid in seen or not published or published.date() > week_end:
                continue
            seen.add(vid)
            out.append(dict(rec, published=published, kind=assignment['kind']))
    return out


def at_window(snaps, rec, days):
    # 保存欠けを何日も後の累計で埋めると、同じ24時間の比較ではなくなる。
    target = rec['published'].date()+timedelta(days=days)
    for day, start, values in snaps:
        if day == target and start <= rec['published'].date():
            row = values.get(rec['video_id']) or {}
            return {key: number(row.get(key)) for key in METRICS}
    return dict.fromkeys(METRICS)


def bootstrap(metan, ui, seed, draws=2000):
    if not metan or not ui:
        return None
    metan, ui = sorted(metan), sorted(ui)
    rng = random.Random(int(hashlib.sha256(seed.encode('utf8')).hexdigest(), 16))
    diffs = sorted(statistics.mean(rng.choices(ui, k=len(ui)))-statistics.mean(rng.choices(metan, k=len(metan)))
                   for _ in range(draws))
    return diffs[int(.025*(draws-1))], diffs[int(.975*(draws-1))]


def aggregate(records, snaps, end):
    result = {}
    for rec in records:
        group = result.setdefault(rec['kind'], dict(hosts={h: dict(planned=0, matched=0, windows={d: [] for d, _ in WINDOWS}) for h in hs.HOSTS},
                                                   fallback=0, unavailable=0, excluded=0, new=0))
        planned = rec.get('planned_host')
        actual = rec.get('actual_host')
        if (rec.get('host_delivery') or {}).get('comparison_eligible') is False:
            group['excluded'] += 1
            continue
        if planned != rec['host_assignment']['planned_host'] or planned not in hs.HOSTS:
            group['excluded'] += 1
            continue
        group['hosts'][planned]['planned'] += 1
        group['new'] += int(end-timedelta(days=6) <= rec['published'].date() <= end)
        if planned == 'ui' and actual == 'metan':
            group['fallback'] += 1
            group['unavailable'] += int(rec.get('host_fallback_reason') == 'ui_unavailable')
        if planned != actual:
            group['excluded'] += 1
            continue
        group['hosts'][planned]['matched'] += 1
        for days, _ in WINDOWS:
            group['hosts'][planned]['windows'][days].append(at_window(snaps, rec, days))
    for kind, group in result.items():
        differences = {}
        for days, _ in WINDOWS:
            samples = {host: [r['views'] for r in group['hosts'][host]['windows'][days] if r['views'] is not None] for host in hs.HOSTS}
            enough = all(len(v) >= 10 for v in samples.values())
            interval = bootstrap(samples['metan'], samples['ui'], kind+':'+str(days))
            differences[days] = dict(counts={h: len(v) for h, v in samples.items()}, interval=interval,
                                     delta=statistics.mean(samples['ui'])-statistics.mean(samples['metan']) if all(samples.values()) else None,
                                     enough=enough)
        group['differences'] = differences
    return result


def mean_metric(rows, metric, weighted=False):
    valid = [r for r in rows if r[metric] is not None]
    if weighted:
        valid = [r for r in valid if r['views'] is not None and r['views'] > 0]
        denominator = sum(r['views'] for r in valid)
        return (sum(r[metric]*r['views'] for r in valid)/denominator if denominator else None), len(valid)
    return (statistics.mean(r[metric] for r in valid) if valid else None), len(valid)


def cell(value, n, digits=1):
    return f'{value:,.{digits}f}（{n}本）' if value is not None else '—（0本）'


def render(videos, snaps, end, latest, lag):
    records = rows(videos, end)
    groups = aggregate(records, snaps, end)
    lines = ['', '## めたんと雨衣の半々比較', '',
             f'対象：実験の記録がある回の累計（公開日が{end}以前）。今週だけに絞らず、同じ種類で本数をためます。',
             f'出典：data/published_videos.json / data/analytics.json（最新保存 {latest or "なし"}、既存推定の集計遅れ {lag}日）。',
             '予定＝実際の回だけを比較し、雨衣の予定→めたんはめたん群にも混ぜません。旧動画の話者は題から推定しません。',
             '雨衣不可で最初から予定めたんにした回と、雨衣回を停止後めたんで作り直した回も比較から除外します。',
             '24時間・3日・7日はJST公開日の各日後に相当する日次保存の近似です。時刻ぴったりの値ではありません。対象日の保存欠け・上位200本に未掲載・未成熟は不明で、0にしません。',
             '再生は1本当たり平均。平均視聴秒数と視聴率は7日の観測値を再生数で重み付け、高評価・登録増は7日の合計です。括弧内は各指標を観測できた本数です。',
             '各話者の観測が10本未満なら判定しません。95%幅は動画単位の再標本化2,000回による平均再生差（雨衣−めたん）の目安で、因果や優劣を断定するものではありません。', '']
    if not groups:
        return '\n'.join(lines+['まだ比較対象の公開記録がありません。まだ差は言えない。', ''])
    for kind, group in sorted(groups.items()):
        start = min(r['published'].date() for r in records if r['kind'] == kind)
        label = LABELS.get(kind.removeprefix('asset:'), '資産動画' if kind.startswith('asset:') else kind)
        lines += [f'### {label}（{kind}）', '', f'公開期間：{start}〜{end}。今週の追加{group["new"]}本。雨衣の予定→めたん：{group["fallback"]}本（うち声を受け取れなかった回：{group["unavailable"]}本）。比較から除外：{group["excluded"]}本（代役を含む）。', '',
                  '| 話し手 | 予定本数 | 予定どおり本数 | 24時間 再生 | 3日 再生 | 7日 再生 | 平均視聴秒数（7日） | 平均視聴率%（7日） | 高評価（7日） | 登録増（7日） |',
                  '|---|---|---|---|---|---|---|---|---|---|']
        for host in hs.HOSTS:
            stats = group['hosts'][host]
            values = [cell(*mean_metric(stats['windows'][d], 'views')) for d, _ in WINDOWS]
            values += [cell(*mean_metric(stats['windows'][7], m, weighted=True)) for m in ('averageViewDuration', 'averageViewPercentage')]
            for metric in ('likes', 'subscribersGained'):
                observations = [r[metric] for r in stats['windows'][7] if r[metric] is not None]
                values.append(cell(sum(observations) if observations else None, len(observations), 0))
            lines.append('| '+('めたん' if host == 'metan' else '雨衣')+f' | {stats["planned"]} | {stats["matched"]} | '+' | '.join(values)+' |')
        lines += ['', '| 観測期間 | 平均再生差（雨衣−めたん） | 95%幅の目安 | 判定 |', '|---|---|---|---|']
        for days, label in WINDOWS:
            diff = group['differences'][days]
            interval = diff['interval']
            width = f'{interval[0]:+,.1f}〜{interval[1]:+,.1f}' if interval else '—'
            delta = f'{diff["delta"]:+,.1f}' if diff['delta'] is not None else '—'
            judgment = ('まだ差は言えない（各10本未満）' if not diff['enough'] else
                        'まだ差は言えない（幅に0を含む）' if interval[0] <= 0 <= interval[1] else
                        '雨衣が多い傾向（参考）' if interval[0] > 0 else 'めたんが多い傾向（参考）')
            lines.append(f'| {label} | {delta} | {width} | {judgment} |')
        lines += ['']
    lines += ['種類の内側でも、実際に公開できた曜日・題材・試合数には偏りが残ります。日程や季節の違いを話し手の効果とは断定しません。', '']
    return '\n'.join(lines)
