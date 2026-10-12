"""登録名を既存ローカルVOICEVOXのaudio_queryと照合。音声/公開/利用者辞書は変更しない。"""
import argparse
import json
from pathlib import Path
import sys
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_reading_guard as guard
import club_display_names as clubs


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--url',default='http://127.0.0.1:50021')
    args=ap.parse_args();records=[]
    groups=[('player',guard.player_readings()),('club',{c['display']:c['reading'] for c in clubs.rows()}),('manager',guard.managers())]
    for kind,names in groups:
        for name,reading in names.items():
            original=name+'です。';spoken=guard.apply(original)
            response=requests.post(args.url+'/audio_query',params=dict(text=spoken,speaker=2),timeout=30)
            response.raise_for_status();raw_query=response.json()
            query=guard.prepare_query(original,raw_query,2,args.url)
            try:check=guard.validate_query(original,query)
            except guard.NameReadingError as e:check=dict(status='FAIL',reason=str(e))
            records.append(dict(kind=kind,name=name,reading=reading,spoken=spoken,check=check,raw_query=raw_query,query=query))
        print(kind,len(names),flush=True)
    before=requests.post(args.url+'/audio_query',params=dict(text='上田綺世です。',speaker=2),timeout=30)
    before.raise_for_status()
    failed=sum(r['check']['status']!='PASS' for r in records)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(records=records,failed=failed,ueda_before=before.json(),engine=args.url),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('query',len(records),'failed',failed)
    return bool(failed)


if __name__=='__main__':raise SystemExit(main())
