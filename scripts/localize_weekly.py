"""直近14日の公開動画を検査。既定は数えるだけ、更新は本数で制限。"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import localize_videos as lv


def audit(yt, now, limit=10, apply=False, ai=None):
    if limit < 0:
        raise ValueError('limitは0以上で指定してください')
    cutoff = now - timedelta(days=14)
    ids = list(dict.fromkeys(lv.all_ids(yt)))
    missing = []
    title_missing = checked = 0
    for offset in range(0, len(ids), 50):
        result = yt.videos().list(part='snippet,status,localizations',
                                  id=','.join(ids[offset:offset + 50])).execute()
        for video in result.get('items', []):
            if video.get('status', {}).get('privacyStatus') != 'public':
                continue
            stamp = video.get('snippet', {}).get('publishedAt')
            if not stamp:
                continue
            published = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if not cutoff <= published <= now:
                continue
            checked += 1
            en = (video.get('localizations') or {}).get('en') or {}
            if not str(en.get('title') or '').strip():
                title_missing += 1
            if not lv.english_complete(en):
                missing.append(video['id'])
    attempted = updated = 0
    store = lv.load_store() if apply else {}
    if apply and limit and missing:
        if ai is None:
            key = os.getenv('ANTHROPIC_API_KEY')
            if key and lv.anthropic is not None:
                ai = lv.anthropic.Anthropic(api_key=key)
        if ai is None:
            print('[warn] 英訳用の認証情報/部品がないため件数確認のみ')
        else:
            for video_id in missing[:limit]:
                attempted += 1
                # backfillと同じ処理。手元の済記録よりYouTubeの実際の値を優先。
                if lv.localize(yt, ai, video_id, store):
                    updated += 1
            lv.save_store(store)
    report = dict(start=cutoff.isoformat(), end=now.isoformat(), checked=checked,
                  missing_title=title_missing, missing_metadata=len(missing),
                  missing_ids=missing, attempted=attempted, updated=updated,
                  max_update_units=limit * 50, dry_run=not apply)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limitは0以上にしてください')
    yt = lv.client()
    if yt is None:
        return 0
    report = audit(yt, datetime.now(timezone.utc), args.limit,
                   apply=args.apply and not args.dry_run)
    path = Path('build/localize-weekly.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = (f"対象期間 {report['start']} ～ {report['end']}（YouTube API）\n"
               f"公開動画 {report['checked']}本 / 英語の題なし {report['missing_title']}本 / "
               f"題または説明なし {report['missing_metadata']}本 / 更新 {report['updated']}本\n"
               f"dry_run={report['dry_run']} / 更新上限 {args.limit}本（videos.update最大{args.limit * 50}ユニット）\n")
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
