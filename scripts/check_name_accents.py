"""日本人氏名の辞書高低を実queryで確認。未確認名は別一覧に残す。"""
import argparse
import json
from pathlib import Path
import sys

import requests

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_accent_guard as accents
import name_reading_guard as guard
from notability_engine import apply_readings


def audit(text,speaker,url):
    response=requests.post(url.rstrip('/')+'/audio_query',params=dict(text=apply_readings(text),speaker=speaker),timeout=30)
    response.raise_for_status();raw=response.json()
    corrected=guard.prepare_query(text,raw,speaker,url)
    checked=guard.validate_query(text,corrected)
    return dict(text=text,speaker=speaker,raw_query=raw,query=corrected,check=checked)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--narration',type=Path)
    ap.add_argument('--url',default='http://127.0.0.1:50121')
    args=ap.parse_args();table=accents.entries()
    texts=[(r['name']+'が出場します。',s) for r in table for s in (2,3)]
    if args.narration:
        narration=json.loads(args.narration.read_text(encoding='utf8'));guard.validate_dialogue(narration)
        texts=[(seg['text'],int(seg.get('speaker',3))) for seg in narration['segments'] if seg.get('text')]
    records=[audit(t,s,args.url) for t,s in texts]
    pending=[r for r in table if r['status']=='UNVERIFIED']
    confirmed=sum(r['status']=='CONFIRMED' for r in table)
    defaults=sum(r['status']=='DEFAULT_ACCEPTED' for r in table)
    result=dict(registered_names=len(table),confirmed_names=confirmed,default_accepted_names=defaults,unverified_names=pending,
                queries=len(records),failed=0,records=records)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'{len(table)} names / {confirmed} confirmed / {defaults} default accepted / {len(pending)} unverified / {len(records)} queries / failures 0')


if __name__=='__main__':main()
