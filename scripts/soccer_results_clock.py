"""結果の期間と朝の時刻。設定の入口はdata/soccer_results_schedule.json。"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
JST=timezone(timedelta(hours=9))
CONFIG=json.loads((Path(__file__).resolve().parents[1]/'data/soccer_results_schedule.json').read_text(encoding='utf8'))

def window(target):
    hour,minute=map(int,CONFIG['cutoff_jst'].split(':'))
    start=datetime(target.year,target.month,target.day,hour,minute,tzinfo=JST)
    return start,start+timedelta(days=1)

def target_day(now=None,scheduled=False):
    now=(now or datetime.now(JST)).astimezone(JST)
    if not scheduled:return (now-timedelta(days=1)).date()
    start,_=window(now.date())
    return (now-timedelta(days=1 if now>=start else 2)).date()

def publish_spec(now=None):
    # GitHubのscheduleは2時間以上遅れることがある（10/21は7:20の予定が9:39）。
    # 公開時刻が過ぎていたら、上げ終わる少し後に予約して止まらないようにする。
    now=(now or datetime.now(JST)).astimezone(JST)
    hour,minute=map(int,CONFIG['publish_jst'].split(':'))
    planned=datetime(now.year,now.month,now.day,hour,minute,tzinfo=JST)
    if now<planned-timedelta(minutes=5):return CONFIG['publish_jst']
    return (now+timedelta(minutes=15)).strftime('%H:%M')

if __name__=='__main__':print(publish_spec())
