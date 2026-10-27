"""保存した10/24〜26の1・2・4試合を本番v6の入口から静止画へ。通信・音声なし。"""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CASES=((1,'20261026'),(2,'20261024'),(4,'20261025'))


def plans():
    import soccer_selected_preview
    for count,day in CASES:
        data=json.loads((ROOT/'scripts/fixtures/soccer-daily'/f'{day}.json').read_text(encoding='utf8'))
        yield count,soccer_selected_preview.program(data)


def draw(plan,seg,t=3):
    import review_render_v3 as r3
    import soccer_slots_v4 as slots
    r3.set_caption(seg['text'],16,60,speaker=seg.get('speaker',2))
    r3.set_program_clock(t)
    try:
        return slots.frame(t,seg,plan)
    finally:
        r3.set_program_clock(None)
        r3.set_caption('',0,0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/soccer-daily-previews')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    os.environ.update(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',
                      COLLESPO_MOTION='on',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off')
    import soccer_readable
    from preview_unified_v3 import sheet
    images=[];labels=[];report=[]
    for count,plan in plans():
        seg=plan['narration']['segments'][0]
        im=draw(plan,seg)
        errors=soccer_readable.check_frame(im,plan['clubs'])
        im.save(args.out/f'preview-{count}.png')
        images.append(im);labels.append(f'{count}試合（保存材料）')
        report.append(dict(count=count,errors=errors,material_date=plan['data']['generated_at']))
    sheet(images,labels,args.out/'overview.png',columns=3)
    (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if any(row['errors'] for row in report):raise ValueError(report)
    print('1・2・4試合の静止画・一覧・検査記録:',args.out)


if __name__=='__main__':main()
