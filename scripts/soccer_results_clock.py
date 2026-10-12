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

def target_day(now=None):
    now=(now or datetime.now(JST)).astimezone(JST)
    start,_=window(now.date())
    return (now-timedelta(days=1 if now>=start else 2)).date()

if __name__=='__main__':print(CONFIG['publish_jst'])
