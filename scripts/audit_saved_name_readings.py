"""読みの欠測/一般語の誤検出を保存出力に照合。通信/音声生成/出力の変更なし。"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import audit_saved_outputs as saved
import name_reading_guard as guard


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--since',default='2026-09-13')
    ap.add_argument('--until',default='2026-10-12')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();rows,summary=saved.collect(ROOT,args.since,args.until,True)
    errors=[]
    for row in rows:
        try:guard.assert_known(row['text'])
        except guard.NameReadingError as e:
            errors.append(dict(reason=str(e),text=row['text'],sources=row['sources']))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(summary=summary,errors=errors),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('saved texts',summary['texts'],'recent',summary['recent_texts'],'reading candidates',len(errors),
          'read errors',len(summary['read_errors']))
    return bool(errors or summary['read_errors'])


if __name__=='__main__':raise SystemExit(main())
