"""欧州サッカーv5「ピッチとマフラー」。207の形/色/時刻表、実材料のみ。

既存v4の関数・書体・色は変更しない。幅と字の実際の箱を測り、入らなければ停止する。
"""
from functools import lru_cache
import math
from pathlib import Path
import re

from PIL import Image, ImageColor, ImageDraw
from PIL import ImageFont
import soccer_look
soccer_look.activate()
import review_render_v3 as r3
import soccer_v4_cards as original

L,R=72,940
TOP,BOTTOM=236,1150
SLANT=.21
PITCH=(8,27,21)
GRASS=(12,36,28)
CHALK=(240,246,240)
LIME=(196,244,76)
MUTED=(150,180,166)
DARK=(18,28,24)
BOARD=(20,48,36)
FONT_DIR=Path(__file__).resolve().parents[1]/'assets/fonts/soccer-v5'
LINE_COLORS=original.LINE_COLORS


@lru_cache(maxsize=128)
def jp(size,weight=700):
    f=ImageFont.truetype(str(FONT_DIR/'NotoSansJP-VF.ttf'),size)
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=96)
def num(size):
    return ImageFont.truetype(str(FONT_DIR/'BarlowCondensed-ExtraBoldItalic.ttf'),size)


@lru_cache(maxsize=4096)
def has_glyph(ch,number=False):
    f=num(40) if number else jp(40)
    found,missing=f.getmask(ch),f.getmask('\U0010ffff')
    return (found.size,bytes(found))!=(missing.size,bytes(missing))


def screen_text(value,number=False):
    # 原稿・保存する原文は変えず、表示だけ書体に無い絵文字等を外す。
    return ''.join(ch for ch in str(value) if ch.isspace() or has_glyph(ch,number))


def measure(value,size,number=False,weight=700):
    """本文内の数字もBarlow。送り幅と実際の張り出しを同じ字列で測る。"""
    parts=[str(value)] if number else [s for s in re.split(r'(\d[\d.,:+\-]*)',str(value)) if s]
    runs=[];x=0;boxes=[]
    for part in parts:
        numeric=number or part[0].isdigit()
        f=num(size if number else round(size*1.12)) if numeric else jp(size,weight)
        b=f.getbbox(part);runs.append((part,f,x));boxes.append((x+b[0],b[1],x+b[2],b[3]));x+=f.getlength(part)
    if not boxes:return runs,0,(0,0,0,0)
    box=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
    return runs,max(x,box[2]-box[0]),box


def mix(a,b,k):
    return tuple(round(x+(y-x)*k) for x,y in zip(a,b))


def contrast(a,b):
    def lum(rgb):
        channels=[c/255 for c in rgb]
        channels=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels]
        return sum(c*k for c,k in zip(channels,(.2126,.7152,.0722)))
    hi,lo=sorted((lum(a),lum(b)),reverse=True)
    return (hi+.05)/(lo+.05)


def colors(club):
    # mainのv2表（data/club_colors.json）を読んだ値を使う。明るいグラデーションを加えない。
    base=ImageColor.getrgb(club['primary']) if club.get('primary') else (70,78,78)
    second=ImageColor.getrgb(club['secondary']) if club.get('secondary') else (184,194,188)
    woven=mix(base,(255,255,255) if sum(base)<600 else (0,0,0),.055)
    requested=ImageColor.getrgb(club['ink']) if club.get('ink') else CHALK
    choices=(requested,(0,0,0),(255,255,255))
    ink=max(choices,key=lambda c:min(contrast(c,base),contrast(c,woven)))
    while min(contrast(ink,base),contrast(ink,woven))<4.5:
        woven=mix(woven,base,.5)
        ink=max(choices,key=lambda c:min(contrast(c,base),contrast(c,woven)))
    # 2色目は内側の帯で保持。白地+淡い2色目にも読める無彩色の外縁を独立して足す。
    outline=max(((0,0,0),CHALK),key=lambda c:contrast(c,base))
    return base,second,ink,outline,woven


def para(box):
    x,y,right,bottom=box;cut=round((bottom-y)*SLANT)
    return [(x+cut,y),(right,y),(right-cut,bottom),(x,bottom)]


def rec(im,role,box,text='',**extra):
    r3.record_box(im,role,box,text)
    im.info['v3_layout'][-1].update(extra)


def fit(value,size,width,number=False,minimum=18,weight=700):
    value=screen_text(value,number)
    while True:
        f=num(size) if number else jp(size,weight)
        runs,length,b=measure(value,size,number,weight)
        if width is None or length<=width:return f,size,length,b
        if size<=minimum:raise ValueError('字が幅に入りません（描画停止）: '+value)
        size-=1


def text(im,x,y,value,size=36,color=CHALK,width=None,number=False,role='text',club_id=None,minimum=18,weight=700):
    value=screen_text(value,number)
    if role=='text' and club_id is None:
        for name in im.info.get('soccer_club_names',()):
            if name in value:raise ValueError('クラブ名は札と一緒に描く: '+value)
    f,size,w,b=fit(value,size,width,number,minimum,weight)
    # 斜体の負のbearingと右側の張り出しも含めて、実際の字の左上を合わせる。
    x,y=round(x),round(y)
    d=ImageDraw.Draw(im)
    for part,font,offset in measure(value,size,number,weight)[0]:
        d.text((x-b[0]+offset,y-b[1]),part,font=font,fill=color)
    box=[x,y,x+b[2]-b[0],y+b[3]-b[1]]
    rec(im,role,box,value,club_id=club_id,v5_font=size,v5_advance=w,v5_color=color)
    return box


def tag_width(club,height):
    f=num(max(14,round(height*.78)))
    b=f.getbbox(club['abbr'])
    return math.ceil(max(f.getlength(club['abbr']),b[2]-b[0])+height*SLANT+height*.82+22)


def scarf(im,box,club,variant='A',label=True,fringe=False,inline=False):
    x,y,right,bottom=map(round,box);w,h=right-x,bottom-y
    base,second,ink,outline,woven=colors(club)
    layer=Image.new('RGB',(w,h),base);d=ImageDraw.Draw(layer)
    if variant=='A':
        for sx in range(0,w,6):d.rectangle((sx,0,sx+1,h),fill=woven)
        # 織り目は主色の小さな濃淡のみ。略称の下に2色目の帯を通さない。
        for yy in range(3,h,6):d.line((0,yy,w,yy),fill=mix(base,woven,.45),width=1)
    sk=round(h*SLANT);band=max(4,round(h*.36))
    d.polygon([(sk+3,0),(sk+3+band,0),(3+band,h),(3,h)],fill=second)
    d.polygon([(w-4,0),(w,0),(w-sk,h),(w-sk-4,h)],fill=second)
    mask=Image.new('L',(w,h),0);shape=para((0,0,w-1,h-1))
    ImageDraw.Draw(mask).polygon(shape,fill=255)
    im.paste(layer,(x,y),mask)
    ImageDraw.Draw(im).line(para((x,y,right-1,bottom-1))+[para((x,y,right-1,bottom-1))[0]],fill=outline,width=2)
    if fringe:
        if h<60:raise ValueError('房は大きい札だけ')
        for yy in range(y+5,bottom-3,7):
            fx=x+round((bottom-yy)*SLANT)
            ImageDraw.Draw(im).line((fx-10,yy,fx-2,yy),fill=second,width=2)
        rec(im,'decoration',(x-10,y,right,bottom))
    rec(im,'team_badge',box,club_id=club['team_en'])
    if label:
        left=x+sk+band+8;right_text=right-sk-9;room=right_text-left
        f,size,_,b=fit(club['abbr'],max(14,round(h*.78)),room,True,minimum=10)
        tx=left+(room-(b[2]-b[0]))/2;ty=y+(h-(b[3]-b[1]))/2
        text(im,tx,ty,club['abbr'],size,ink,width=room,number=True,role='badge',minimum=10)
    im.info.setdefault('v4_badges',[]).append(dict(club_id=club['team_en'],abbr=club['abbr'],base=base,ink=ink,box=list(box),inline=inline))
    im.info.setdefault('v5_contrasts',[]).append(dict(club=club['team_en'],base=base,secondary=second,ink=ink,outline=outline,
        text_ratio=min(contrast(ink,base),contrast(ink,woven)),edge_ratio=contrast(outline,base),variant=variant))
    return w


def club_name(im,x,y,club,size=36,color=CHALK,suffix='',width=None,display_name=None):
    value=(display_name or club.get('name_jp') or club['team_en'])+suffix
    while True:
        runs,length,b=measure(value,size);h=b[3]-b[1];w=tag_width(club,h)
        if width is None or w+12+length<=width:break
        if size<=18:raise ValueError('クラブ名が幅に入りません（描画停止）: '+value)
        size-=1
    # 札と字の実寸・上端・高さを同じ値から算出する。
    box=[round(x),round(y),round(x)+w,round(y)+h]
    scarf(im,box,club,inline=True)
    b=text(im,x+w+12,y,value,size,color,club_id=club['team_en'])
    return b[2]


def panel(im,box,fill=BOARD,edge=None):
    d=ImageDraw.Draw(im)
    d.polygon(para(box),fill=fill)
    if edge:d.line(para(box)+[para(box)[0]],fill=edge,width=2)
    rec(im,'card',box)


@lru_cache(maxsize=12)
def _background(tints=()):
    im=Image.new('RGB',(1080,1920),PITCH);d=ImageDraw.Draw(im)
    for y in range(0,1920,144):d.rectangle((0,y,1080,y+71),fill=GRASS)
    if len(tints)==2:
        # 試合結果だけ、両クラブの色を暗くして斜めに分ける。
        a,b=tints;d.polygon([(0,236),(1080,236),(760,1150),(0,1150)],fill=mix(PITCH,a,.17))
        d.polygon([(1080,236),(1080,1150),(760,1150)],fill=mix(PITCH,b,.17))
    line=(32,62,46)
    d.line((0,660,1080,660),fill=line,width=3)
    d.ellipse((210,320,870,1000),outline=line,width=3)
    d.rectangle((-120,420,140,890),outline=line,width=3)
    d.rectangle((940,420,1200,890),outline=line,width=3)
    return im


def canvas(t,clubs,label='欧州サッカー',tints=()):
    im=_background(tuple(tints)).copy()
    im.info=dict(soccer_v5=True,v3_layout=[],soccer_club_names=tuple(sorted({n for n,c in clubs.items() if n in (c.get('name_jp'),c['team_en']) and len(n)>=2},key=len,reverse=True)),v5_elapsed=t)
    d=ImageDraw.Draw(im)
    d.polygon(para((L,168,L+12,206)),fill=LIME)
    text(im,L+30,168,'コレスポ',40,role='header',weight=900,width=260)
    text(im,L+310,175,label,30,MUTED,role='header',width=R-L-310)
    d.line((L,224,R,224),fill=(49,74,56),width=3)
    return im


def lines(value,size,width):
    out=[];current=''
    for part in str(value).split('\n'):
        for ch in part:
            if current and measure(current+ch,size)[1]>width:
                out.append(current);current=''
            if measure(ch,size)[1]>width:raise ValueError('文字が行幅に入りません')
            current+=ch
        if current:out.append(current);current=''
    return out


def _body_effect(im,t):
    # 内容層のみ。固定の見出し・出典・字幕・立ち絵はこのあと描く。
    clubs=im.info.get('v4_badges',[])
    palettes=[]
    for club in clubs:
        if club['base'] not in palettes:palettes.append(tuple(club['base']))
    im.info['v5_wipe_colors']=palettes[:2] or [GRASS,LIME]
    cards=[e for e in im.info['v3_layout'] if e['role']=='card']
    # 外札を1つの窓で切り、札ごと0.07秒ずらす。移動した画素は札の窓内に限定。
    outer=[c for c in cards if not any(c is not o and c['box']!=o['box'] and o['box'][0]<=c['box'][0] and o['box'][1]<=c['box'][1] and c['box'][2]<=o['box'][2] and c['box'][3]<=o['box'][3] for o in cards)]
    for i,c in enumerate(outer):
        x,y,right,bottom=map(round,c['box']);w,h=right-x,bottom-y
        k=r3.ease_out((t-.45-i*.07)/.35)
        if k<1:
            old=im.crop((x,y,right,bottom));blank=_background(tuple(im.info.get('v5_tints',()))).crop((x,y,right,bottom))
            blank.paste(old,(round(-90*(1-k)),round(90*SLANT*(1-k))))
            im.paste(blank,(x,y))
    if 1.6<=t<2.2:
        k=(t-1.6)/.6
        for c in outer:
            x,y,right,bottom=map(round,c['box']);w,h=right-x,bottom-y
            beam=Image.new('RGBA',(w,h),(0,0,0,0));d=ImageDraw.Draw(beam)
            at=round(-120+k*(w+h*SLANT+240))
            d.polygon([(at,0),(at+60,0),(at+60-round(h*SLANT),h),(at-round(h*SLANT),h)],fill=(240,255,232,32))
            base=im.crop((x,y,right,bottom)).convert('RGBA');base.alpha_composite(beam)
            im.paste(base.convert('RGB'),(x,y))


def _presenter(im,t):
    import characters
    ctx=r3._CAPTION;clock=r3._PROGRAM_CLOCK[0]
    elapsed=clock-ctx['start'] if clock is not None else t
    line=r3.current_sentence(elapsed,ctx['text'],ctx['duration']) if ctx['text'] else ''
    characters.place_busts(im,'metan',line,elapsed,ctx['duration'] or 1,('metan',))
    if line and not ctx.get('hide_caption'):
        box=characters.BUBBLE
        ImageDraw.Draw(im).polygon(para(box),fill=CHALK)
        x,y,right,bottom=box
        ImageDraw.Draw(im).polygon(para((x+28,y-18,x+240,y+26)),fill=LIME)
        text(im,x+54,y-8,'四国めたん',24,DARK,role='caption',width=180)
        # 同じ読んでいる区間を、3行以内で全文表示する。切り捨てない。
        size=48
        while True:
            rows=lines(line,size,right-x-116)
            if len(rows)<=3 and len(rows)*(size+10)<=bottom-y-42:break
            if size<=24:raise ValueError('字幕が安全域に入りません')
            size-=1
        top=y+30+(bottom-y-42-len(rows)*(size+10))//2
        for i,row in enumerate(rows):text(im,x+62,top+i*(size+10),row,size,DARK,width=right-x-116,role='caption')
        im.info['duo_caption']=dict(box=list(box),speaker='metan',font_size=size,rows=len(rows))
    total=ctx.get('total',0)
    if total and clock is not None:
        ImageDraw.Draw(im).rectangle((L,222,L+round((R-L)*max(0,min(1,clock/total))),226),fill=LIME)


def finish(im,t,spec):
    _body_effect(im,t)
    source=spec.get('source','');body=lines(source,22,610)
    if len(body)>2:raise ValueError('出典が2行に入りません')
    for i,line in enumerate(body):text(im,L,1166+i*28,line,22,MUTED,width=610,role='source')
    d=ImageDraw.Draw(im);d.rectangle((0,1486,1080,1574),fill=PITCH)
    d.line((0,1488,1080,1488),fill=LIME,width=2);d.line((0,1572,1080,1572),fill=LIME,width=2)
    for yy in range(1495,1570,8):d.line((0,yy,1080,yy),fill=GRASS,width=1)
    if spec.get('ticker'):
        value=spec['ticker'];text(im,L,1512,value,30,CHALK,width=R-L,role='ticker')
    _presenter(im,t)
    return im


def heading(im,value,sub=None):
    text(im,L,262,value,40,CHALK,width=R-L,weight=900)
    if sub:text(im,L,324,sub,28,MUTED,width=R-L)


def stat(im,box,value,unit,accent=LIME):
    panel(im,box)
    x,y,right,bottom=box
    size=min(250,round((bottom-y)*.7))
    f,size,_,b=fit(value,size,right-x-120,True)
    w=b[2]-b[0]
    text(im,x+(right-x-w)/2,y+30,value,size,accent,number=True)
    text(im,x+64,bottom-64,unit,32,CHALK,width=right-x-128)


def chips(im,y,values,height=126):
    values=[v for v in values if v and str(v[0])!=''][:4]
    if not values:return y
    gap=14;w=(R-L-gap*(len(values)-1))//len(values)
    for i,(value,unit) in enumerate(values):
        x=L+i*(w+gap);panel(im,(x,y,x+w,y+height))
        f,size,_,b=fit(value,64,w-66,True)
        text(im,x+(w-(b[2]-b[0]))/2,y+12,value,size,LIME,number=True,width=w-66)
        text(im,x+30,y+height-44,unit,26,CHALK,width=w-60)
    return y+height


def cover(t,spec,clubs):
    im=canvas(t,clubs,spec.get('label','欧州サッカー'))
    heading(im,spec['kicker'])
    if spec.get('club_first'):
        club_name(im,L+20,348,clubs[spec['club']],64,width=R-L-40)
        text(im,L+20,440,spec['name']+'の所属クラブ',30,MUTED,width=R-L-40)
        text(im,L+20,505,spec['big_label'],38,CHALK,width=R-L-40)
        stat(im,(L,574,R,930),spec['big'],spec.get('unit',''))
    else:
        text(im,L+20,340,spec['name'],72,width=R-L-40,weight=900)
        club_name(im,L+20,450,clubs[spec['club']],36,width=R-L-40)
        stat(im,(L,538,R,930),spec.get('big') or '—',spec.get('unit',''),CHALK if spec.get('unit')=='日本時間' else LIME)
        if spec.get('context') and not spec.get('chips'):
            panel(im,(L,986,R,1070))
            text(im,L+36,1008,spec['context'],28,MUTED,width=R-L-72)
    chips(im,982,spec.get('chips',[]))
    # 数字以外の補足がない表紙は主札を下へ中央配置し、空きは透かしで埋めない。
    if not spec.get('chips'):im.info['v5_allow_centered']=True
    return finish(im,t,spec)


def preview(t,spec,clubs):
    im=canvas(t,clubs,spec.get('label','欧州サッカー　予告'))
    heading(im,spec['league']+'　'+spec['date'],'キックオフは日本時間')
    stat(im,(L,392,R,654),spec['time'],'キックオフ',CHALK)
    y=716
    for side in ('home','away'):
        panel(im,(L,y,R,y+174))
        club_name(im,L+42,y+20,clubs[spec[side]],46,width=R-L-200)
        rank=(spec.get('ranks') or {}).get(side)
        if rank:text(im,R-138,y+26,str(rank)+'位',32,MUTED,width=98)
        text(im,L+36,y+100,'ホーム' if side=='home' else 'アウェー',24,MUTED,width=120)
        names='・'.join((spec.get('jp') or {}).get(side,[]))
        if names:text(im,L+176,y+100,names,30,LIME,width=R-L-224)
        y+=206
    return finish(im,t,spec)


def jp_roster(t,spec,clubs):
    im=canvas(t,clubs,spec.get('label','欧州サッカー'))
    heading(im,spec['title'])
    rows=spec['rows'];step=min(108,(1118-350)//max(1,len(rows)))
    if step<84:raise ValueError('一覧は次の画面が必要です')
    top=1118-len(rows)*step
    for i,row in enumerate(rows):
        y=top+i*step;panel(im,(L,y,R,y+step-10))
        text(im,L+30,y+10,row['name'],34,width=250)
        club_name(im,L+30,y+53,clubs[row['club']],24,MUTED,width=310)
        x=L+350
        if row.get('note'):text(im,x,y+26,row['note'],26,MUTED,width=R-x-40)
        else:
            for value,unit in row.get('values',[]):
                box=text(im,x,y+12,value,50,LIME,number=True,width=70)
                x=box[2]+8;text(im,x,y+37,unit,24,width=98);x+=jp(24).getlength(unit)+30
    return finish(im,t,spec)


def jp_player(t,spec,clubs):
    im=canvas(t,clubs,spec.get('label','欧州サッカー'))
    heading(im,spec['kicker'])
    text(im,L+20,340,spec['name'],68,width=R-L-40,weight=900)
    club_name(im,L+20,440,clubs[spec['club']],36,width=R-L-40)
    if spec.get('big'):stat(im,(L,520,R,810),spec['big'],spec.get('unit',''))
    chips(im,862,spec.get('chips',[]))
    for i,line in enumerate(spec.get('notes',[])):
        text(im,L+30,1032+i*36,line,28,MUTED,width=R-L-60)
    return finish(im,t,spec)


def standings(t,spec,clubs):
    im=canvas(t,clubs,spec.get('label','欧州サッカー　順位争い'));heading(im,spec['title'])
    rows={r['position']:r for r in spec['rows']};shown=[p for a,b in spec['shown'] for p in range(a,b+1) if p in rows]
    labels=dict(spec.get('lines',[]));line_count=sum(p in labels for p in shown)
    available=1115-386-(100 if spec.get('gap') else 0)-line_count*42
    step=min(104,available//max(1,len(shown)))
    if step<43:raise ValueError('順位表は次の画面が必要です')
    top=1115-len(shown)*step-line_count*42-(100 if spec.get('gap') else 0)
    text(im,R-225,top-42,'試合',24,MUTED,width=64);text(im,R-112,top-42,'勝点',24,MUTED,width=80)
    y=top
    for p in shown:
        row=rows[p];highlight=row['team']==spec.get('focus') or row['team'] in spec.get('highlights',[])
        panel(im,(L,y,R,y+step-8),mix(BOARD,LIME,.1) if highlight else BOARD)
        size=min(38,max(22,step-22))
        text(im,L+22,y+9,p,size+8,CHALK,number=True,width=60)
        club_name(im,L+88,y+12,clubs[row['team']],size,LIME if highlight else CHALK,width=R-L-348)
        text(im,R-230,y+9,row['played'],size+8,MUTED,width=65,number=True)
        text(im,R-110,y+9,row['points'],size+8,LIME if highlight else CHALK,width=80,number=True)
        y+=step
        if p in labels:
            label=labels[p];kind=original._line_kind(label);color=LINE_COLORS.get(kind,MUTED)
            label='残留ライン　この下は降格圏' if kind=='残留' else label+'の線' if kind in ('CL','EL') and '線' not in label else label
            ImageDraw.Draw(im).line((L,y-4,R,y-4),fill=color,width=3)
            text(im,L+22,y+4,label,24,color,width=R-L-44);y+=42
    if spec.get('gap'):
        panel(im,(L,y+18,R,y+92),mix(BOARD,LIME,.12))
        club_name(im,L+26,y+36,clubs[spec['focus']],30,LIME,suffix=spec['gap'],width=R-L-52)
    im.info['soccer_standings']=dict(shown=shown,lines=labels)
    return finish(im,t,spec)


def outro(t,spec,exclude,credit,tagline):
    # 同じ共通締めの行と文を使う。サッカーの色・字・板だけを専用層に描く。
    im=canvas(t,{},'欧州サッカー');im.info['v3_outro']=True
    text(im,L+20,282,'コレスポ',100,CHALK,width=R-L-40,weight=900)
    text(im,L+20,430,tagline,36,MUTED,width=R-L-40)
    text(im,L+20,500,'毎日のお届け',28,width=R-L-40)
    y=558
    for at,name in r3.outro_rows(exclude):
        panel(im,(L,y,R-244,y+62))
        text(im,L+28,y+10,at,42,LIME,width=124,number=True)
        text(im,L+182,y+18,name,30,width=R-L-450)
        y+=72
    panel(im,(L,y+10,R-140,y+84),LIME)
    text(im,L+42,y+32,'チャンネル登録で毎日届きます',32,DARK,width=R-L-210)
    return finish(im,t,dict(spec,source=credit))


def scarf_transition(previous,image,t):
    """0.6秒。地と中身だけを入れ替え、固定部分は次画面のまま。"""
    if previous is None or t>=.6:return image.tobytes()
    old=Image.frombytes('RGB',image.size,previous);new=image.copy()
    x0,y0,x1,y1=0,TOP,1080,BOTTOM
    w,h=x1-x0,y1-y0;k=max(0,min(1,t/.6));k=k*k*(3-2*k)
    band=170;lead=-h*SLANT+k*(w+h*SLANT+band)
    mask=Image.new('L',(w,h),0);d=ImageDraw.Draw(mask)
    trail=lead-band
    d.polygon([(0,0),(trail+h*SLANT,0),(trail,h),(0,h)],fill=255)
    oldbody=old.crop((x0,y0,x1,y1));newbody=new.crop((x0,y0,x1,y1));oldbody.paste(newbody,(0,0),mask)
    colors_=image.info.get('v5_wipe_colors') or [GRASS,LIME]
    d=ImageDraw.Draw(oldbody)
    for i in range(5):
        x=lead-band+i*band/5
        color=colors_[i%len(colors_)]
        d.polygon([(x+h*SLANT,0),(x+band/5+h*SLANT,0),(x+band/5,h),(x,h)],fill=color)
        for yy in range(0,h,9):
            px=lead+SLANT*(h-yy)
            d.line((px-12,yy,px,yy),fill=CHALK,width=2)
    new.paste(oldbody,(x0,y0))
    # 胸から上の立ち絵は中身の下端に重なる。ワイプの後に同じ絵を描き戻す。
    import characters
    # 元画面の半透明の縁もそのまま保持する。立ち絵の二重合成はしない。
    for item in image.info.get('duo_layer',[]):
        art=characters.bust(item['who'],item['face'],item['height'],item['dim'])
        if art is None:continue
        art=art.crop((0,0,art.width,min(art.height,item['cut'])))
        x,y=item['at'];region=(x,y,x+art.width,y+art.height)
        mask=art.getchannel('A').point(lambda value:255 if value else 0)
        new.paste(image.crop(region),(x,y),mask)
    return new.tobytes()


def check_frame(im,clubs):
    import v3_rules
    import characters
    errors=v3_rules.check_layout(im)+v3_rules.check_spacing(im)+original.check_club_badges(im,clubs)
    # v5は平行四辺形の切欠きもあるため、数字なしの空札/文字の箱は独立して記録する。
    for item in im.info.get('v5_contrasts',[]):
        if item['text_ratio']<4.5 or item['edge_ratio']<3:errors.append(dict(contrast=item))
    for e in im.info.get('v3_layout',[]):
        if e['role'] in ('header','caption','ticker','source','card','team_badge','badge','decoration'):continue
        if e['box'][2]>R+1 or e['box'][3]>BOTTOM+1:errors.append(dict(overflow=e))
    for panel_ in im.info.get('v5_quote_panels',[]):
        x,y,right,bottom=panel_['box']
        for e in panel_['contents']:
            a,b,c,d=e['box']
            if not (y<=b<=d<=bottom and a>=x+(bottom-b)*SLANT-2 and c<=right-(d-y)*SLANT+2):
                errors.append(dict(outside_quote_panel=e))
    # 安全域内でも右下の立ち絵に数字/字が隠れる配置は止める。実際のアルファで判定。
    for item in im.info.get('duo_layer',[]):
        art=characters.bust(item['who'],item['face'],item['height'],item['dim'])
        if art is None:continue
        alpha=art.getchannel('A').crop((0,0,art.width,min(art.height,item['cut'])))
        px,py=item['at']
        for e in im.info.get('v3_layout',[]):
            if e['role'] not in ('text','badge','team_badge'):continue
            if e['role']=='team_badge' and not any(b.get('inline') and b['box']==e['box'] for b in im.info.get('v4_badges',[])):continue
            x,y,right,bottom=e['box']
            if bottom> BOTTOM:continue
            region=(max(0,round(x-px)),max(0,round(y-py)),min(alpha.width,round(right-px)),min(alpha.height,round(bottom-py)))
            if region[2]<=region[0] or region[3]<=region[1]:continue
            crop=alpha.crop(region)
            if crop.getbbox():errors.append(dict(covered_by_presenter=e))
    return errors
