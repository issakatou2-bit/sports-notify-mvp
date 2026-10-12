"""斜めBを土台に野球らしい3案。見本だけで、本番へ接続しない。"""
import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image,ImageColor,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import preview_mlb_badges as previous

BACKGROUND=previous.BACKGROUND
VARIANTS={'1':'赤いボールの縫い目','2':'ホームベース','3':'ピンストライプと番号書体'}
ne=previous.ne
r3=previous.r3
contrast=previous.contrast


def badge(tid,variant,height=34):
    if variant not in VARIANTS:raise ValueError('1/2/3だけです')
    tid=str(tid);abbr=ne.MLB_TEAM_ABBR[tid]
    base=ImageColor.getrgb(ne.MLB_TEAM_COLOR[tid])
    ink=max(((255,255,255),(0,0,0)),key=lambda c:contrast(c,base))
    width=92;cut=round(height*.21);scale=4
    im=Image.new('RGB',((width+4)*scale,(height+4)*scale),BACKGROUND)
    d=ImageDraw.Draw(im)
    def pts(points):return [(round(x*scale),round(y*scale)) for x,y in points]
    def polygon(points,color):d.polygon(pts(points),fill=color)
    def line(points,color,stroke=1):d.line(pts(points),fill=color,width=round(stroke*scale))
    # Bの斜めの向き、寸法、球団の主色を全案で共有。
    shape=[(2+cut,2),(width+1,2),(width+1-cut,height+1),(2,height+1)]
    polygon(shape,base)
    line(shape+[shape[0]],ink,1.3)
    motif_box=(5,5,25,30)
    if variant=='1':
        # 縫い目は白い左帯の中だけ。赤の小さな曲線と対になる縫い目。
        polygon([(cut+5,4),(28,4),(21,height-1),(5,height-1)],(247,246,241))
        red=(196,45,55)
        points=[]
        for k in range(41):
            y=6+k*24/40;x=13+6*((y-18)/12)**2
            points.append((x,y))
        line(points,red,1.4)
        for y in (8,13,18,23,28):
            x=13+6*((y-18)/12)**2
            line([(x-2,y-1),(x+2,y+1)],red,1.2)
    elif variant=='2':
        # ホームベースの五角形を左の目印に。文字はBと同じ水平面。
        plate=[(9,8),(25,8),(25,20),(17,28),(9,20)]
        polygon(plate,(247,246,241))
        line(plate+[plate[0]],(74,84,94),.8)
        line([(11,11),(22,11)],(196,45,55),1.6)
    else:
        # ストライプを左の帯へ限定し、略称の後ろは主色のまま。
        stripe=tuple(round(.35*c+.65*255) for c in base)
        for x in (10,15,20,25):line([(x,6),(x-4,30)],stripe,.8)
        line([(29,6),(24,30)],ink,1)
    font=r3.num_font(24) if variant=='3' else r3.font(20)
    b=font.getbbox(abbr);tw=b[2]-b[0];th=b[3]-b[1]
    left=31;right=width-cut-4;top=2
    x=left+(right-left-tw)/2;y=top+(height-th)/2
    # 書体は4倍の同じフォントで描き、字と曲線の端を滑らかにする。
    large=r3.num_font(24*scale) if variant=='3' else r3.font(20*scale)
    lb=large.getbbox(abbr)
    d.text((round(x*scale)-lb[0],round(y*scale)-lb[1]),abbr,font=large,fill=ink)
    text_box=(math.floor(x),math.floor(y),math.ceil(x+tw),math.ceil(y+th))
    if not (29<=text_box[0]<text_box[2]<=width-cut-3 and 4<=text_box[1]<text_box[3]<=height):
        raise ValueError('略称が文字専用領域の外: '+abbr)
    ratio=contrast(ink,base);edge=max(contrast(base,BACKGROUND),contrast(ink,BACKGROUND))
    if ratio<4.5 or edge<3:raise ValueError('コントラスト不足')
    im=im.resize((width+4,height+4),Image.Resampling.LANCZOS)
    im.info['check']=dict(team_id=tid,abbr=abbr,variant=variant,primary=base,ink=ink,
                          text_ratio=ratio,edge_ratio=edge,text_box=text_box,motif_box=motif_box,
                          native_height=height,lettering='Oswald Bold' if variant=='3' else 'existing bold font')
    return im


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
    teams=sorted(ne.MLB_TEAM_NAME_JP,key=lambda t:ne.MLB_TEAM_ABBR[t]);records=[]
    variants={'current':'現在v4','B':'元の斜めB',**VARIANTS}
    comparison=Image.new('RGB',(1900,160+len(teams)*88),BACKGROUND)
    previous.label(comparison,(28,20),'MLBの札　斜めBから野球らしい3案',32)
    previous.label(comparison,(28,65),'同じ高さ34px。球団名の左隣へ置いた比較用見本。',23)
    for col,title in enumerate(variants.values()):previous.label(comparison,(28+col*374,110),title,22)
    sheets={v:Image.new('RGB',(1920,1060),BACKGROUND) for v in VARIANTS}
    for v,sheet in sheets.items():
        previous.label(sheet,(32,20),v+'　'+VARIANTS[v]+'　30球団',32)
        previous.label(sheet,(32,68),'左：実寸34px　右：同じ画像の2倍（補間なし）',23)
    for index,tid in enumerate(teams):
        name=ne.MLB_TEAM_NAME_JP[tid]
        for col,v in enumerate(variants):
            im=previous.baseline(tid) if v=='current' else previous.badge(tid,'B') if v=='B' else badge(tid,v)
            folder=out/v;folder.mkdir(exist_ok=True)
            im.save(folder/(tid+'-native.png'))
            doubled=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST)
            doubled.save(folder/(tid+'-2x.png'))
            x=28+col*374;y=155+index*88
            comparison.paste(im,(x,y));previous.label(comparison,(x+im.width+9,y+5),name,19)
            if v not in VARIANTS:continue
            records.append(im.info['check']);sheet=sheets[v]
            sx=32+(index%6)*316;sy=130+(index//6)*182
            previous.label(sheet,(sx,sy),name,20)
            sheet.paste(im,(sx,sy+44));sheet.paste(doubled,(sx+112,sy+32))
    comparison.save(out/'comparison-30-teams.png')
    for v,sheet in sheets.items():sheet.save(out/(v+'-30-teams-native-and-2x.png'))
    minimum=min(r['text_ratio'] for r in records)
    checks=dict(teams=30,candidates=3,checks=records,min_text_ratio=minimum,
                min_edge_ratio=min(r['edge_ratio'] for r in records),published=False,production_connected=False)
    (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # 個別画像を本当のピクセル寸法で表示する。大きい一覧画像の縮小表示だけに頼らない。
    body='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MLBの札 Bからの3案</title><style>body{background:#0d171f;color:#e6f0ec;font-family:system-ui;padding:20px}a{color:#c7f743}.sheet{max-width:100%}table{border-collapse:collapse}td,th{padding:12px;white-space:nowrap;text-align:left}.scroll{overflow-x:auto}.native{width:auto;height:auto}section{margin:32px 0}</style><h1>MLBの札 Bからの3案</h1><p>1 縫い目 / 2 ホームベース / 3 ピンストライプと番号書体。採用前の見本。</p><p>下の表は実寸と2倍。横へスクロールして現在v4・元Bと比べられます。</p><div class="scroll"><table><tr><th>球団</th>'
    body+=''.join(f'<th>{title}</th>' for title in variants.values())+'</tr>'
    for tid in teams:
        body+=f'<tr><td>{ne.MLB_TEAM_NAME_JP[tid]}</td>'
        for v in variants:
            body+=f'<td><img class="native" src="{v}/{tid}-native.png" alt="{variants[v]} 実寸"><br><img class="native" src="{v}/{tid}-2x.png" alt="{variants[v]} 2倍"></td>'
        body+='</tr>'
    body+='</table></div>'
    for v,title in VARIANTS.items():body+=f'<section><h2>{v} {title}</h2><a href="{v}-30-teams-native-and-2x.png"><img class="sheet" src="{v}-30-teams-native-and-2x.png"></a></section>'
    body+='<section><h2>名前の左隣の比較</h2><a href="comparison-30-teams.png"><img class="sheet" src="comparison-30-teams.png"></a></section></html>'
    (out/'index.html').write_text(body,encoding='utf8')
    print(f'30 teams / 3 candidates / 90 contrast checks PASS (min {minimum:.3f}) / production disconnected')
    return 0


if __name__=='__main__':raise SystemExit(main())
