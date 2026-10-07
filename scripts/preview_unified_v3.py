"""保存材料だけで4枠の確認画像を作る。音声生成と投稿は持たない。"""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bignumber_render as bn
import daily_v3
import generate_morning_short as g
import ps_program as ps
import ps_unified_v3 as unified
import review_render_v3 as r3

ROOT=Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8'))


def sheet(frames, labels, path):
    out=Image.new('RGB',(540*len(frames),1000),'#101820')
    d=ImageDraw.Draw(out)
    for i,(image,label) in enumerate(zip(frames,labels)):
        out.paste(image.resize((540,960)),(i*540,40))
        d.text((i*540+16,7),label,font=r3.font(22),fill='white')
    out.save(path)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=Path('build/unified-previews'))
    ap.add_argument('--only-ps',action='store_true')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if args.only_ps:
        ps_preview(args.out)
        print('PS確認画像のみ更新: '+str(args.out/'design-v3-ps.png'))
        return
    bn._no_network()
    data=read('scripts/fixtures/bignumber/morning_recap.json')
    data['players']=g.sort_players(data.get('players') or [])
    with patch.object(g,'week_line',return_value=('',[])),patch.dict(os.environ,{'COLLESPO_PLAYERS_DESIGN':'bignumber'}):
        nar=g.build_narration(data,'players')
    scenes=bn.scenes_from_morning(data,nar)
    errors=bn.check_scenes(scenes,nar,data)
    if errors:raise ValueError(errors)
    chosen=scenes[:4]
    sheet([bn.scene(3,s) for s in chosen],['成績 表紙','順位表','1位 詳細','2位以下'],args.out/'design-v3-players.png')
    report={'players': {'segments':len(nar['segments']),'checks':errors}}
    for mode, filename in [('voices','local_voices-preview.json'),('press','local_reporters-preview.json')]:
        material=read('scripts/fixtures/comment/'+filename)
        data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}
        with patch.dict(os.environ,{'COLLESPO_COMMENTS_DESIGN':'comments','COLLESPO_PRESS_DESIGN':'v3'}):
            nar=g.build_narration(data,mode);before=copy.deepcopy(nar)
            design=daily_v3.prepare(data,nar,mode)
        if [s['text'] for s in before['segments']] != [s['text'] for s in nar['segments']]:raise ValueError('台本変更')
        if mode=='voices':
            threads=[s for s in nar['segments'] if s['kind']=='thread' and any(v.get('read') and not v.get('fact') for v in s['meta'].get('quote_rows',[]))]
            segments=[nar['segments'][0],threads[0],threads[-1]];times=[3,3,3]
        else:
            quotes=[s for s in nar['segments'] if any(v.get('read') and not v.get('fact') for v in s['meta'].get('quote_rows',[]))]
            segments=[quotes[0],next(s for s in quotes if s['kind']=='headlines'),next(s for s in reversed(quotes) if s['kind']=='reporters')];times=[3,3,3]
        sheet([daily_v3.frame(t,s,design,20) for t,s in zip(times,segments)],
              [mode+' '+s['kind']+f' {t}秒' for t,s in zip(times,segments)],args.out/f'design-v3-{mode}.png')
        report[mode]={'segments':len(nar['segments']),'text_unchanged':True}
    report.update(ps_preview(args.out))
    (args.out/'design-v3-confirmation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('4枠の確認画像と照合結果を保存: '+str(args.out))


def ps_preview(out):
    saved=read('scripts/fixtures/ps-design/2026-10-07.json');frames=[];labels=[];report={}
    for slot in ('forecast','situation'):
        with patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            program=ps.prepare(saved['snapshot'],saved['evidence'],slot,datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        ps.check_program(program);lead=unified.lead_card(program);line=unified.program_ticker(program)
        for seg,t in [(program['segments'][0],3),(program['segments'][1],.8),(program['segments'][1],3)]:
            frames.append(unified.frame(t,seg['meta']['card'],lead,cover=seg is program['segments'][0],ticker_line=line));labels.append(slot+f' {t}秒')
        previous=unified.frame(20,program['segments'][0]['meta']['card'],lead,ticker_line=line).tobytes()
        current=unified.frame(.1,program['segments'][1]['meta']['card'],lead,ticker_line='')
        frames.append(Image.frombytes('RGB',(1080,1920),unified.transition(previous,current,2,6,20.1,line)))
        labels.append(slot+' 切替0.1秒')
        report[slot]={'segments':len(program['segments']),'edition_key':program['edition_key'],'ticker':line}
        if slot=='situation':
            for seg in program['segments'][2:]:
                frames.append(unified.frame(3,seg['meta']['card'],lead,ticker_line=line))
                labels.append('情勢 '+seg['meta']['card']['headline'].replace('\n',''))
            report[slot]['series_included']=[s['meta']['card']['headline'].replace('\n','') for s in program['segments']]
    sheet(frames,labels,out/'design-v3-ps.png')
    return report


if __name__=='__main__':main()
