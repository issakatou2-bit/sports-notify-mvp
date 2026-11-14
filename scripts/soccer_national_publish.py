"""代表番組の予約を確認し、投稿直前に同日の予約時刻を取り直す。"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import soccer_national as n


def validate(data, now):
    if not n.enabled() or data.get('sample') or (data.get('national_numbers') or {}).get('fixture'):
        raise ValueError('代表番組は既定停止、または見本です')
    at=n.instant(data['publish_at'])
    if data['mode']=='result':
        # 結果は定時の回ではないので、日付をまたいでも出す（11/14 本人）。ただし試合から36時間を過ぎた古い結果は出さない。
        at=max(at,now+timedelta(minutes=2))
        start=(data.get('game') or {}).get('start_utc')
        if start and at-n.instant(start)>timedelta(hours=36):
            raise ValueError('試合から36時間を過ぎた結果は公開しません')
    else:
        if at.astimezone(n.JST).date()!=now.astimezone(n.JST).date():
            raise ValueError('当日の予約時刻が必要です。日付を越えた回は公開しません')
        at=max(at,now+timedelta(minutes=2))
        if at.astimezone(n.JST).date()!=now.astimezone(n.JST).date():
            raise ValueError('当日中の未来の予約時刻を確保できません')
    if data['mode']=='preview' and at>=n.instant(data['game']['start_utc']):
        raise ValueError('開始後の予告は公開しません')
    return at


def upload(argv):
    """共通処理の予約解決だけを代表専用に差し替え、送信直前にも再判定する。"""
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--kind',required=True,choices=['soccer_national'])
    parser.add_argument('--games',type=Path,required=True)
    parser.add_argument('--publish-at')
    args,_=parser.parse_known_args(argv)
    data=n.read(args.games)
    validate(data,datetime.now(timezone.utc))
    original=n.instant(data['publish_at']).astimezone(n.JST).strftime('%H:%M')
    if args.publish_at and args.publish_at!=original:
        raise ValueError('代表の元の予約時刻と一致しません')
    import upload_youtube as uploader
    previous_argv,previous_resolver=sys.argv,uploader.resolve_publish_at
    def resolve(spec):
        if spec!=original:
            raise ValueError('代表の元の予約時刻と一致しません')
        return validate(data,datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    # 原稿と材料の元予約は保持し、共通側の一致検査を通す。
    sys.argv=[sys.argv[0],*argv,'--publish-at',original]
    uploader.resolve_publish_at=resolve
    try:
        return uploader.main()
    finally:
        sys.argv,uploader.resolve_publish_at=previous_argv,previous_resolver


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--time',action='store_true')
    ap.add_argument('--upload',action='store_true',help='代表専用の予約再計算を通して投稿')
    ap.add_argument('--data',type=Path,default=n.ROOT/'build/soccer_national/material.json')
    args,remaining=ap.parse_known_args(argv)
    if args.upload:
        return upload(remaining)
    if remaining:ap.error('不明な引数: '+' '.join(remaining))
    at=validate(n.read(args.data),datetime.now(timezone.utc))
    if args.time:print(at.astimezone(n.JST).strftime('%H:%M'))


if __name__=='__main__':raise SystemExit(main() or 0)
