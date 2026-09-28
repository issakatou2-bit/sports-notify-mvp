"""Advance only the rehearsal clock to the eve of verified WCS; never posts."""
import argparse
import copy
from datetime import datetime, timedelta
import ps_program as p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='build/ps_forecast_narration.json')
    args=parser.parse_args()
    source=p.read('build/ps_editorial_source.json')
    snapshot=p.read('data/postseason.json')
    real=datetime.fromisoformat(source['retrieved_at'])
    ctx,_=p.validate_source(snapshot,source,real)
    if ctx['stage']!='bracket_preview':
        print('[info] WCS開幕前の4カード再現は対象外');return
    start=min(datetime.fromisoformat(m['first_game']['start_utc']).astimezone(p.JST) for m in ctx['matchups'])
    now=datetime.combine(start.date()-timedelta(days=1),datetime.min.time(),p.JST).replace(hour=16)
    snapshot=copy.deepcopy(snapshot);snapshot['date']=now.date().isoformat()
    source=copy.deepcopy(source);source['retrieved_at']=now.isoformat()
    program=p.prepare(snapshot,source,'forecast',now,{})
    if not program:
        raise ValueError('公式の翌日全カードを再現できません')
    program['rehearsal']=True
    program['rehearsal_real_retrieved_at']=real.isoformat()
    p.write('build/ps_program_forecast.json',program)
    p.write(args.out,p.script(program))
    print('[info] 翌日を想定した非公開再現。実際の取得時刻: '+real.isoformat())


if __name__=='__main__':main()
