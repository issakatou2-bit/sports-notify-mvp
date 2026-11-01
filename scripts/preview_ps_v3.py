"""保存した公式材料の2枠を再生するだけ。新規取得・公開・台帳更新はしない。"""
import argparse
from datetime import datetime
from pathlib import Path
import ps_program as p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=Path(__file__).parent/'fixtures/ps-design/2026-10-07.json')
    parser.add_argument('--out',type=Path,default=Path('build/ps-design'))
    args=parser.parse_args()
    saved=p.read(args.fixture)
    now=datetime.fromisoformat(saved['evidence']['retrieved_at'])
    for slot in ('forecast','situation'):
        program=p.prepare(saved['snapshot'],saved['evidence'],slot,now,saved['ledger'])
        if not program:raise ValueError('試作材料に対応するPS枠がありません')
        program['rehearsal']=True
        program['rehearsal_real_retrieved_at']=now.isoformat()
        p.check_program(program)
        p.write(args.out/f'{slot}-program.json',program)
        p.write(args.out/f'{slot}-narration.json',p.script(program))
        print(f'[info] {slot}: {len(program["segments"])}画面。保存材料の日時 {now.isoformat()}。公開不可。')


if __name__=='__main__':main()
