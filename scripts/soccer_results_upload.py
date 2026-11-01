"""欧州結果の非公開試験を通常の投稿記録から分離する入口。"""
import argparse
from functools import partial
import json
import os
from pathlib import Path

import upload_youtube as upload

PRIVATE_RECORD = Path('build/soccer_results/private_published_videos.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--privacy', choices=['public', 'private'], default='public')
    parser.add_argument('--publish-at')
    parser.add_argument('--video-date', required=True)
    args, _ = parser.parse_known_args()
    if args.privacy == 'public':
        return upload.main()
    if args.publish_at:
        parser.error('非公開試験に公開予約は指定できません')

    # 共通アップローダーの既定引数も差し替える。通常の投稿済み判定・
    # 記録には一切触れず、同じ日を試験しても朝の本投稿を妨げない。
    previous_lookup, previous_record = upload.published_video, upload.record_video
    upload.published_video = partial(previous_lookup, path=str(PRIVATE_RECORD))
    upload.record_video = partial(previous_record, path=str(PRIVATE_RECORD))
    try:
        upload.main()
    finally:
        upload.published_video, upload.record_video = previous_lookup, previous_record
    records = json.loads(PRIVATE_RECORD.read_text(encoding='utf-8')) if PRIVATE_RECORD.exists() else {}
    entry = records.get('soccer_results', {}).get(args.video_date, {})
    if not entry.get('video_id') or entry.get('publish_at'):
        raise RuntimeError('非公開試験のアップロード記録がありません（認証・アップロードを確認）')
    message = f"非公開試験: https://www.youtube.com/watch?v={entry['video_id']}"
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(message + '\n')


if __name__ == '__main__':
    main()
