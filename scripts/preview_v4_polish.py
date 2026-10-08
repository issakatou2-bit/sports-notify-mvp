"""v4の全画面の確認画像。固定材料・声なし・投稿なし。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_render_v3 as r3
import v3_rules as rules
import test_v3_rules as fixtures
from preview_unified_v3 import sheet
from preview_asset_v4 import frames as asset_frames

ROOT=Path(__file__).resolve().parents[1]


def daily_frames(case):
    images=[];labels=[];records=[];clock=0
    for si,draw in enumerate(case['frames']):
        seen=set();duration=20
        seg=case['segments'][min(si,len(case['segments'])-1)]
        # 成績は1音声区間に複数の選手画面がある。各画面の元の音声を使う。
        for bound in draw.__defaults__ or ():
            if isinstance(bound,dict) and 'say' in bound:
                seg={'kind':bound['kind'],'text':bound['say']}
        r3.set_program_clock(clock);r3.set_caption('' if seg['kind']=='outro' else seg['text'],duration,20*len(case['frames']))
        # 入場の途中は画面の種類に数えない。引用は札が即時に出るので先頭から。
        begin=0 if case['name'] in ('voices','press') and seg['kind']!='outro' else 3
        for t in sorted(set([3,7,11,15,19]+[i+.5 for i in range(begin,20)])):
            r3.set_program_clock(clock+t);im=draw(t)
            errors=rules.check_layout(im)+rules.check_spacing(im)+rules.check_team_badges(im)
            if errors:raise ValueError(f'{case["name"]}/{si}/{t}: {errors}')
            body=[(e['role'],e.get('text','')) for e in im.info['v3_layout'] if e['role'] not in ('header','caption','ticker','source','card')]
            # 描画内容とページで重複を除く。背景の照明・字幕の変化は別画面として数えない。
            key=json.dumps(body,ensure_ascii=False)
            if key in seen:continue
            seen.add(key);images.append(im);labels.append(f'{si+1} {seg["kind"]} {t:g}s')
            records.append(dict(segment=si,time=t,layout=im.info['v3_layout'],badges=im.info.get('v4_badges',[]),
                                quote=im.info.get('v4_quote_group'),player=im.info.get('v4_player')))
        clock+=duration
    r3.set_program_clock(None);r3.set_caption('',0,0)
    return images,labels,records


def save(out,name,images,labels,records,nar):
    folder=out/name;folder.mkdir(exist_ok=True)
    for i,im in enumerate(images):im.save(folder/f'{i+1:02d}.png')
    path=out/(name+'.png');sheet(images,labels,path,columns=4)
    return dict(name=name,sheet=str(path),screens=len(images),frames=records,narration=nar)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    if r3.LOOK!='v4':raise ValueError('COLLESPO_SHORT_LOOK=v4 が必要です')
    args.out.mkdir(parents=True,exist_ok=True);manifest=[]
    for case in fixtures.daily_cases():
        if case['name']=='players':continue
        images,labels,records=daily_frames(case)
        manifest.append(save(args.out,case['name'],images,labels,records,case['segments']))
    for spec in fixtures.read('scripts/fixtures/v3-rules/game-v4.json')['topics']:
        images,labels,records,nar=asset_frames(spec)
        for im in images:
            if rules.check_team_badges(im):raise ValueError(rules.check_team_badges(im))
        manifest.append(save(args.out,spec['key'],images,labels,records,nar['segments']))
    (args.out/'screens.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'previews':[{k:m[k] for k in ('name','sheet','screens')} for m in manifest]},ensure_ascii=False))


if __name__=='__main__':main()
