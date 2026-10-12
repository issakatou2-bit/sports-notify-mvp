"""MLBの札3案を30球団で比較する専用見本。本番の描画へ接続しない。"""
import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image,ImageColor,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import notability_engine as ne
import review_render_v3 as r3
import short_v4_cards as current

BACKGROUND=(13,23,31)
VARIANTS={'A':'電光掲示板のドット','B':'サッカーとそろえる斜め','C':'ホームベース'}
DOTS={
 'A':['01110','10001','10001','11111','10001','10001','10001'],
 'B':['11110','10001','10001','11110','10001','10001','11110'],
 'C':['01111','10000','10000','10000','10000','10000','01111'],
 'D':['11110','10001','10001','10001','10001','10001','11110'],
 'E':['11111','10000','10000','11110','10000','10000','11111'],
 'F':['11111','10000','10000','11110','10000','10000','10000'],
 'G':['01111','10000','10000','10111','10001','10001','01111'],
 'H':['10001','10001','10001','11111','10001','10001','10001'],
 'I':['11111','00100','00100','00100','00100','00100','11111'],
 'J':['00111','00010','00010','00010','10010','10010','01100'],
 'K':['10001','10010','10100','11000','10100','10010','10001'],
 'L':['10000','10000','10000','10000','10000','10000','11111'],
 'M':['10001','11011','10101','10101','10001','10001','10001'],
 'N':['10001','11001','11001','10101','10011','10011','10001'],
 'O':['01110','10001','10001','10001','10001','10001','01110'],
 'P':['11110','10001','10001','11110','10000','10000','10000'],
 'Q':['01110','10001','10001','10001','10101','10010','01101'],
 'R':['11110','10001','10001','11110','10100','10010','10001'],
 'S':['01111','10000','10000','01110','00001','00001','11110'],
 'T':['11111','00100','00100','00100','00100','00100','00100'],
 'U':['10001','10001','10001','10001','10001','10001','01110'],
 'V':['10001','10001','10001','10001','10001','01010','00100'],
 'W':['10001','10001','10001','10101','10101','11011','10001'],
 'X':['10001','10001','01010','00100','01010','10001','10001'],
 'Y':['10001','10001','01010','00100','00100','00100','00100'],
 'Z':['11111','00001','00010','00100','01000','10000','11111']}


def contrast(a,b):
    def lum(rgb):
        values=[c/255 for c in rgb];values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(values,(.2126,.7152,.0722)))
    a,b=sorted((lum(a),lum(b)),reverse=True)
    return (a+.05)/(b+.05)


def badge(tid,variant,height=34):
    tid=str(tid)
    if variant not in VARIANTS:raise ValueError('A/B/Cだけです')
    abbr=ne.MLB_TEAM_ABBR[tid];base=ImageColor.getrgb(ne.MLB_TEAM_COLOR[tid])
    second=ImageColor.getrgb(r3.TEAM_SECONDARY_COLORS.get(tid,'#C4CED4'))
    ink=max(((255,255,255),(0,0,0)),key=lambda c:contrast(c,base))
    width=92;im=Image.new('RGB',(width+4,height+4),BACKGROUND);d=ImageDraw.Draw(im)
    if variant=='A':
        d.rounded_rectangle((2,2,width+1,height+1),radius=4,fill=base,outline=ink,width=2)
        step=3;w=(len(abbr)*6-1)*step;x=(im.width-w)//2;y=(im.height-7*step)//2
        for k,ch in enumerate(abbr):
            for row,values in enumerate(DOTS[ch]):
                for col,value in enumerate(values):
                    if value=='1':
                        left=x+k*6*step+col*step;top=y+row*step
                        d.rectangle((left,top,left+1,top+1),fill=ink)
        text_box=(x,y,x+w,y+21)
    else:
        if variant=='B':
            cut=round(height*.21)
            shape=[(2+cut,2),(width+1,2),(width+1-cut,height+1),(2,height+1)]
            d.polygon(shape,fill=base);d.line(shape+[shape[0]],fill=ink,width=2)
            d.polygon([(cut+5,4),(cut+13,4),(13,height-1),(5,height-1)],fill=second)
            left=24;room=width-left-cut-4;top=2;area=height
        else:
            shape=[(2,2),(width+1,2),(width+1,2+round(height*.66)),(width//2+2,height+1),(2,2+round(height*.66))]
            d.polygon(shape,fill=base);d.line(shape+[shape[0]],fill=ink,width=2)
            left=12;room=width-24;top=2;area=round(height*.65)
        f=r3.font(20);b=f.getbbox(abbr)
        x=left+(room-(b[2]-b[0]))/2;y=top+(area-(b[3]-b[1]))/2
        d.text((x-b[0],y-b[1]),abbr,font=f,fill=ink)
        text_box=(math.floor(x),math.floor(y),math.ceil(x+b[2]-b[0]),math.ceil(y+b[3]-b[1]))
    if contrast(ink,base)<4.5:raise ValueError('字のコントラストが足りません')
    edge=max(contrast(base,BACKGROUND),contrast(ink,BACKGROUND))
    if edge<3:raise ValueError('札の輪郭が地色から見えません')
    if not (2<=text_box[0]<text_box[2]<=im.width-2 and 2<=text_box[1]<text_box[3]<=im.height-2):raise ValueError('略称が札の外です')
    im.info['check']=dict(team_id=tid,abbr=abbr,variant=variant,primary=base,secondary=second,ink=ink,
                          text_ratio=contrast(ink,base),edge_ratio=edge,text_box=text_box,native_height=height)
    return im


def baseline(tid,height=34):
    width=current.inline_badge_width(tid,36)
    im=Image.new('RGB',(width+4,height+4),BACKGROUND)
    current.inline_badge(im,2,2,tid,36,height)
    return im


def label(im,at,text,size=20,fill=(230,240,236)):
    ImageDraw.Draw(im).text(at,text,font=r3.font(size),fill=fill)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
    teams=sorted(ne.MLB_TEAM_NAME_JP,key=lambda t:ne.MLB_TEAM_ABBR[t]);records=[]
    comparison=Image.new('RGB',(1440,160+len(teams)*96),BACKGROUND)
    label(comparison,(30,20),'MLBの札　現在v4 / A 電光 / B 斜め / C ホームベース',32)
    label(comparison,(30,65),'同じ球団色・同じ名前の左隣。見本だけ、本番へ接続していません。',24)
    for k,title in enumerate(('現在v4','A 電光','B 斜め','C ホームベース')):label(comparison,(30+k*350,110),title,24)
    sheets={v:Image.new('RGB',(1920,1060),BACKGROUND) for v in VARIANTS}
    for v,im in sheets.items():
        label(im,(32,20),v+'　'+VARIANTS[v]+'　30球団',34)
        label(im,(32,68),'左：実寸34px　右：同じ画像の2倍（補間なし）',23)
    for index,tid in enumerate(teams):
        name=ne.MLB_TEAM_NAME_JP[tid]
        original=baseline(tid);row=150+index*96
        for col,v in enumerate(('current','A','B','C')):
            im=original if v=='current' else badge(tid,v)
            x=30+col*350;comparison.paste(im,(x,row));label(comparison,(x+im.width+10,row+5),name,20)
            folder=out/v;folder.mkdir(exist_ok=True);im.save(folder/(tid+'-native.png'))
            im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST).save(folder/(tid+'-2x.png'))
            if v=='current':continue
            records.append(im.info['check']);sheet=sheets[v];sx=32+(index%6)*316;sy=130+(index//6)*182
            label(sheet,(sx,sy),name,20);sheet.paste(im,(sx,sy+44));sheet.paste(im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST),(sx+112,sy+32))
    comparison.save(out/'comparison-30-teams.png')
    for v,im in sheets.items():im.save(out/(v+'-30-teams-native-and-2x.png'))
    (out/'checks.json').write_text(json.dumps(dict(teams=30,candidates=3,checks=records,published=False,production_connected=False),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    body='<!doctype html><html lang="ja"><meta charset="utf-8"><title>MLBの札3案</title><style>body{background:#0d171f;color:#e6f0ec;font-family:system-ui;padding:24px}img{max-width:100%}a{color:#c7f743}section{margin:36px 0}</style><h1>MLBの札3案</h1><p>現在v4を土台にした比較用の見本。本番の描画には接続していません。</p>'
    for v,title in VARIANTS.items():body+=f'<section><h2>{v} {title}</h2><a href="{v}-30-teams-native-and-2x.png"><img src="{v}-30-teams-native-and-2x.png"></a></section>'
    body+='<section><h2>現在v4と名前の左隣で比べる</h2><a href="comparison-30-teams.png"><img src="comparison-30-teams.png"></a></section></html>'
    (out/'index.html').write_text(body,encoding='utf8')
    print('30 teams / 3 candidates / 90 contrast checks PASS / production disconnected')
    return 0


if __name__=='__main__':raise SystemExit(main())
