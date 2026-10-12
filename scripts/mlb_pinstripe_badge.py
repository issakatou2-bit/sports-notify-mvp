"""5de76bddの縦じま案をMLB v4へ。描画の指定と球団IDは呼出側で管理。"""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PIL import Image,ImageChops,ImageColor,ImageDraw


def enabled():
    return os.environ.get('COLLESPO_MLB_BADGE','')=='pinstripe'


def render(tid,width,height):
    import notability_engine as ne
    import review_render_v3 as r3
    import short_v4_cards as cards
    tid=str(tid);width=round(width);height=round(height);scale=4
    base=ImageColor.getrgb(ne.MLB_TEAM_COLOR[tid]);abbr=ne.MLB_TEAM_ABBR[tid]
    ink=max(((255,255,255),(0,0,0)),key=lambda c:cards.contrast(c,base))
    im=Image.new('RGBA',(width*scale,height*scale));d=ImageDraw.Draw(im)
    cut=round(height*.21)
    points=[(cut,0),(width-1,0),(width-1-cut,height-1),(0,height-1)]
    shape=[(x*scale,y*scale) for x,y in points]
    d.polygon(shape,fill=base+(255,));d.line(shape+[shape[0]],fill=ink+(255,),width=max(3,round(scale*1.2)))
    # 斜めBの左帯。縦じまは札の形の内側へ切り取り、文字の背面へ入れない。
    stripes=Image.new('RGBA',im.size);sd=ImageDraw.Draw(stripes)
    stripe=tuple(round(.35*c+.65*255) for c in base)+(255,)
    band=width*.30
    for ratio in (.11,.16,.21,.26):
        x=round(width*ratio*scale)
        sd.line([(x,round(height*.14*scale)),(x,round(height*.86*scale))],fill=stripe,width=max(2,round(scale*.8)))
    mask=Image.new('L',im.size);ImageDraw.Draw(mask).polygon(shape,fill=255)
    stripes.putalpha(ImageChops.multiply(stripes.getchannel('A'),mask));im=Image.alpha_composite(im,stripes);d=ImageDraw.Draw(im)
    left=band+2;right=width-cut-3;room=right-left
    size=max(10,round(height*.71));font=r3.num_font(size)
    while font.getlength(abbr)>room and size>8:
        size-=1;font=r3.num_font(size)
    if font.getlength(abbr)>room:raise ValueError('縦じま札の略称が入りません: '+abbr)
    bbox=font.getbbox(abbr);tw=bbox[2]-bbox[0];th=bbox[3]-bbox[1]
    x=left+(room-tw)/2;y=(height-th)/2
    large=r3.num_font(size*scale);lb=large.getbbox(abbr)
    d.text((round(x*scale)-lb[0],round(y*scale)-lb[1]),abbr,font=large,fill=ink+(255,))
    im=im.resize((width,height),Image.Resampling.LANCZOS)
    im.info['badge']=dict(team_id=tid,abbr=abbr,base=base,ink=ink,style='pinstripe',
                          text_ratio=cards.contrast(ink,base),font_size=size,
                          text_box=[x,y,x+tw,y+th],motif_right=band)
    return im
