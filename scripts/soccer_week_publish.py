"""月曜朝の週末まとめを週キーで予約し、投稿結果を照合して記録する。"""
import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import soccer_jp_week as week
import soccer_now

ROOT = Path(__file__).resolve().parents[1]


def reservation(data, clock):
    monday = week.date.fromisoformat(data['key'])
    if monday.weekday() != 0 or clock.astimezone(week.JST).date() != monday:
        raise ValueError('対象の月曜日を確認してください')
    at = datetime.combine(monday, time(9), week.JST)
    # 共通アップローダーと同じく、遅れた同日分は即時公開へ回す。
    if at <= clock+timedelta(minutes=1):
        return None
    return at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--week', type=Path, required=True)
    ap.add_argument('--video-date', required=True)
    ap.add_argument('--privacy', default='public', choices=('public',))
    ap.add_argument('--publish-at', required=True)
    args, remaining = ap.parse_known_args()
    if os.environ.get('COLLESPO_SOCCER_WEEK') != 'on':
        raise ValueError('公開変数が無効')
    data = week._load(args.week)
    state_path = ROOT/'data/soccer_week_state.json'
    record_path = ROOT/'data/published_videos.json'
    state = week._load(state_path)
    ok, why = week.due(data, state, week._load(record_path), scheduled=True)
    if not ok:
        print(why)
        return
    at = reservation(data, datetime.now(timezone.utc))
    if args.video_date != data['key'] or args.publish_at != '09:00':
        raise ValueError('週キー・予約時刻が対象の月曜9:00と一致しません')
    key = data['key']
    state.setdefault('pending', {})[key] = dict(at=at)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    soccer_now.checkpoint_receipt(state_path, 'pending', state['pending'])
    import upload_youtube as upload
    previous_argv, previous_resolver = sys.argv, upload.resolve_publish_at
    sys.argv = [sys.argv[0], *remaining, '--video-date', args.video_date,
                '--privacy', args.privacy, '--publish-at', args.publish_at]
    resolved = [at]
    def resolve(spec):
        resolved[0] = reservation(data, datetime.now(timezone.utc))
        if resolved[0] is None:
            print('[info] 月曜9:00を過ぎたため、既存の公開処理と同じく即時公開します')
        return resolved[0]
    upload.resolve_publish_at = resolve
    try:
        upload.main()
    finally:
        sys.argv, upload.resolve_publish_at = previous_argv, previous_resolver
    record = week._load(record_path).get('soccer_week', {}).get(key, {})
    if not record.get('video_id') or record.get('publish_at') != resolved[0]:
        raise ValueError('アップロードと予約の記録を確認してください（pending継続）')
    state.setdefault('done', []).append(key)
    state['done'] = list(dict.fromkeys(state['done']))[-20:]
    state['pending'].pop(key)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    soccer_now.checkpoint_receipt(state_path, 'done', state['done'], ['data/published_videos.json'])


if __name__ == '__main__':
    main()
