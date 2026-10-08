"""固定材料3本の全画面。音声生成・投稿なし。"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asset_v4_cards as cards
import generate_asset_video as asset
import review_render_v3 as r3
import v3_rules as rules
from preview_unified_v3 import sheet

ROOT=Path(__file__).resolve().parents[1]


def frames(spec):
    # generate_asset_video.main と同じv3素材の話者・クレジット。
    asset.VOICE_CREDIT='音声: VOICEVOX:四国めたん'
    key=spec['key']
    with patch.dict(asset.LIST_TOPICS,{key:spec}):
        nar=asset.build_narration(key)
    images=[];labels=[];records=[]
    clock=0
    for si,seg in enumerate(nar['segments']):
        kind=seg['kind'];meta=seg['meta'];duration=40
        r3.set_program_clock(clock);r3.set_caption(seg['text'],duration,40*len(nar['segments']))
        times=[3]
        if kind=='list':
            rows=spec['items'][meta['start']:meta['start']+meta['count']]
            weights=[len((spec.get('speech') or {}).get(h) or f'{h}。{b}。') for h,b in rows]
            times=[]
            for i,(head,body) in enumerate(rows):
                pages=cards.item_pages(spec,head,body)
                for p in range(pages):
                    times.append(duration*(sum(weights[:i])+weights[i]*(p+.5)/pages)/sum(weights))
        elif kind=='people':
            rows=spec.get(meta.get('group','japanese')) or []
            weights=[len(r['name']+'が'+r.get('line',r.get('why',''))+'、') for r in rows[:3]]
            times=[duration*(sum(weights[:i])+w*.5)/sum(weights) for i,w in enumerate(weights)]
        for index,t in enumerate(times):
            r3.set_program_clock(clock+t)
            with patch.dict(asset.LIST_TOPICS,{key:spec}):
                im=asset.render_v3(t,kind,meta,spec,key)
            errors=rules.check_layout(im)
            if errors:raise ValueError(f'{key}/{si}/{index}: {errors}')
            label=f'{si+1}.{index+1} '+(im.info.get('asset_v4',{}).get('head') or im.info.get('asset_v4',{}).get('name') or kind)
            images.append(im);labels.append(label)
            records.append({'segment':si,'kind':kind,'time':t,'card':im.info.get('asset_v4',{}),'layout':im.info.get('v3_layout',[])})
        clock+=duration
    r3.set_program_clock(None);r3.set_caption('',0,0)
    return images,labels,records,nar


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/asset-v4-previews')
    args=ap.parse_args()
    if r3.LOOK!='v4':raise ValueError('COLLESPO_SHORT_LOOK=v4 で実行してください')
    args.out.mkdir(parents=True,exist_ok=True);manifest=[]
    saved=json.loads((ROOT/'scripts/fixtures/v3-rules/game-v4.json').read_text(encoding='utf-8'))
    for spec in saved['topics']:
        images,labels,records,nar=frames(spec)
        path=args.out/(spec['key']+'.png')
        sheet(images,labels,path,columns=4)
        # 全寸の各画面も保存し、細字と球団札を拡大確認できるようにする。
        folder=args.out/spec['key'];folder.mkdir(exist_ok=True)
        for i,im in enumerate(images):im.save(folder/f'{i+1:02d}.png')
        manifest.append({'topic':spec['key'],'image':str(path),'screens':len(images),'frames':records,'narration':nar})
    (args.out/'game-v4-confirmation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'look':r3.LOOK,'images':[{k:v for k,v in m.items() if k in ('topic','image','screens')} for m in manifest],'layout':'全画面が安全域内'},ensure_ascii=False))


if __name__=='__main__':main()
