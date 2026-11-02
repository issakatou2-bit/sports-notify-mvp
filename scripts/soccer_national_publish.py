"""代表番組の予約時刻を公開直前にも確認する。通信なし。"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import soccer_national as n


def validate(data, now):
    if not n.enabled() or data.get('sample'):
        raise ValueError('代表番組は既定停止、または見本です')
    at=n.instant(data['publish_at'])
    if at<=now+timedelta(minutes=1) or at.astimezone(n.JST).date()!=now.astimezone(n.JST).date():
        raise ValueError('当日の未来の予約時刻が必要です。遅延時は次の定時で再確認します')
    if data['mode']=='preview' and at>=n.instant(data['game']['start_utc']):
        raise ValueError('開始後の予告は公開しません')
    return at


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--time',action='store_true')
    ap.add_argument('--data',type=Path,default=n.ROOT/'build/soccer_national/material.json')
    args=ap.parse_args()
    at=validate(n.read(args.data),datetime.now(timezone.utc))
    if args.time:print(at.astimezone(n.JST).strftime('%H:%M'))


if __name__=='__main__':main()
