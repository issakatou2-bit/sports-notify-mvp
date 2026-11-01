"""取得済み日別値の週次集計。欠測日は分母に含めない。"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path


def summarize(store):
    weeks = {}
    for day, rec in sorted(store.get('daily', {}).items()):
        stamp = date.fromisoformat(day)
        week = str(stamp - timedelta(days=stamp.weekday()))
        weeks.setdefault(week, []).append(rec)
    result = []
    for week, rows in weeks.items():
        pairs = [r for r in rows if r.get('views') is not None and r.get('likes') is not None]
        views = sum(r['views'] for r in pairs)
        subscribed = [r['subscribedViews'] for r in rows if r.get('subscribedViews') is not None]
        registrations = [r['subscribersGainedByContentType'] for r in rows if r.get('subscribersGainedByContentType') is not None]
        result.append(dict(week_start=week, timezone=store.get('daily_timezone'),
            likes_per_1000_views=1000*sum(r['likes'] for r in pairs)/views if views else None,
            engagement_days=len(pairs), subscribed_views_per_day=sum(subscribed)/len(subscribed) if subscribed else None,
            subscribed_days=len(subscribed), registration_days=len(registrations),
            registrations={k: sum(r.get(k, 0) for r in registrations) for k in ('shorts','videoOnDemand','liveStream','unspecified')} if registrations else None))
    return result


def by_outro(store, published):
    """最新の動画別取得期間を比較。日別の全体集計とは混ぜない。"""
    days = store.get('days', {})
    if not days:
        return {}
    latest = days[max(days)]
    variants = {rec['video_id']: rec['outro_next']
                for group in published.values() if isinstance(group, dict)
                for rec in group.values() if isinstance(rec, dict)
                and rec.get('video_id') and rec.get('outro_next', {}).get('enabled')
                and rec['outro_next'].get('eligible')}
    groups = {}
    for row in latest.get('videos', []):
        plan = variants.get(row.get('video'))
        if plan:
            groups.setdefault(plan['variant'], []).append(row)
    return dict(range=latest.get('range'), source='latest video report; top 200 only',
        groups={key: dict(videos=len(rows), views=sum(r.get('views',0) for r in rows),
            likes=sum(r.get('likes',0) for r in rows),
            subscribersGained=sum(r.get('subscribersGained',0) for r in rows))
            for key, rows in groups.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--analytics', default='data/analytics.json')
    parser.add_argument('--published', default='data/published_videos.json')
    args = parser.parse_args()
    store = json.loads(Path(args.analytics).read_text(encoding='utf-8'))
    published = json.loads(Path(args.published).read_text(encoding='utf-8'))
    print(json.dumps(dict(weeks=summarize(store), outro=by_outro(store,published)), ensure_ascii=False, indent=2))
