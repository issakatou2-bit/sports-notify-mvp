"""ショートv4専用の札。材料・台本・共通の背景/字幕/時計は変更しない。"""
import re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import ImageDraw, ImageEnhance
import review_render_v3 as r3

CREAM = (247, 242, 223)
L, R = r3.LEFT, r3.SAFE_RIGHT
TONE_COLORS = {'称賛': (40, 108, 80), '批判': (163, 56, 62), '中立': (75, 83, 98)}


def text(im, x, y, value, size=40, color=None, width=None, number=False, team_id=None):
    """文字の実際の上端を指定し、同じ実寸を安全域検査へ記録する。"""
    value = str(value)
    from team_names import team_names_jp
    import notability_engine as ne
    value=team_names_jp(value) if not number else value
    names={name:str(tid) for tid,name in ne.MLB_TEAM_NAME_JP.items()}
    pattern='('+ '|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))+')'
    runs=re.split(pattern,value) if not number else [value]
    if team_id is not None and any(names[v]!=str(team_id) for v in runs if v in names):
        raise ValueError('材料のteam_idと球団名が一致しません')
    font = r3.num_font if number else r3.font
    def advance(s):
        return font(s).getlength(value)+sum(inline_badge_width(names[v],s)+12 for v in runs if v in names)
    while width and advance(size) > width and size > 18:
        size -= 2
    if width and advance(size) > width:
        raise ValueError('v4の文字が札の幅に入りません: '+value)
    f = font(size)
    dy = f.getbbox(value)[1]
    for run in runs:
        if not run:continue
        if run in names:
            tid=str(team_id) if team_id is not None else names[run]
            height=f.getbbox(run)[3]-f.getbbox(run)[1]
            inline_badge(im,x,y+f.getbbox(run)[1]-dy,tid,size,height)
            x+=inline_badge_width(tid,size)+12
        r3._text(ImageDraw.Draw(im),(x,y-dy),run,font=f,fill=color or r3.INK)
        entry=im.info['v3_layout'][-1]
        entry.update(v4_font=size,v4_color=color or r3.INK)
        if run in names:entry['team_id']=tid
        x+=f.getlength(run)


def inline_badge_width(tid,size):
    import notability_engine as ne
    return round(r3.font(max(14,round(size*.55))).getlength(ne.MLB_TEAM_ABBR[str(tid)]))+16


def inline_badge(im,x,y,tid,size,height):
    """球団名の文字と同じ高さ、同じ行。材料のIDと結び付けて記録する。"""
    import notability_engine as ne
    from PIL import ImageColor
    tid=str(tid);base=ImageColor.getrgb(ne.MLB_TEAM_COLOR[tid])
    second=ImageColor.getrgb(r3.TEAM_SECONDARY_COLORS.get(tid,'#C4CED4'))
    width=inline_badge_width(tid,size);box=[x,y,x+width,y+height]
    d=ImageDraw.Draw(im);d.rounded_rectangle(box,radius=6,fill=base,outline=second,width=2)
    r3.record_box(im,'team_badge',box)
    f=r3.font(max(14,round(size*.55)));abbr=ne.MLB_TEAM_ABBR[tid]
    dy=f.getbbox(abbr)[1];h=f.getbbox(abbr)[3]-dy
    r3._text(d,(x+8,y+(height-h)/2-dy),abbr,font=f,fill=badge_ink(base))
    im.info.setdefault('v4_badges',[]).append(dict(team_id=tid,abbr=abbr,base=base,ink=badge_ink(base),box=box,inline=True))


def lines(value, size, width):
    """書体の送り幅で折る。本文は縮小も省略もしない。"""
    f = r3.font(size); result=[]; line=''
    for ch in str(value):
        if ch == '\n':
            result.append(line);line='';continue
        if line and f.getlength(line+ch) > width:
            # Latinの単語も可能な範囲で途中切れを避ける。
            if ch.isascii() and ch.isalpha():
                word=re.search(r'[A-Za-z]+$',line)
                if word and word.start()>0:
                    result.append(line[:word.start()]);line=line[word.start():]+ch;continue
            result.append(line);line=''
        line += ch
    if line:result.append(line)
    return result or ['']


def panel(im, box, fill=None, outline=None):
    if not (L <= box[0] < box[2] <= R and r3.CONTENT_TOP <= box[1] < box[3] <= r3.CONTENT_BOTTOM):
        raise ValueError('v4の札が安全域外です: '+str(box))
    d=ImageDraw.Draw(im);x,y,right,bottom=box
    d.rounded_rectangle(box,radius=22,fill=(5,12,20))
    d.rounded_rectangle((x,y,right-2,bottom-4),radius=22,fill=fill or r3.colors(None)[0],
                        outline=outline or r3.colors(None)[1],width=2)
    d.line((x+22,y+7,min(right-22,x+100),y+7),fill=outline or r3.GOLD,width=3)
    r3.record_box(im, 'card', box)


def tag(im, x, y, value, fill=None, color=None, size=28, width=None):
    f=r3.font(size)
    if width:
        while f.getlength(str(value))+28 > width and size > 18:
            size-=2;f=r3.font(size)
    w=round(f.getlength(str(value)))+28;h=size+26
    panel(im,(x,y,x+w,y+h),fill or r3.DARK_INK,fill or r3.GOLD)
    text(im,x+14,y+10,value,size,color or r3.INK,width=w-28)
    return w


def canvas(t, label):
    im=r3.background(t,None)
    r3._header(ImageDraw.Draw(im),label,None,r3.colors(None)[1])
    return im


def finish(im,t,ticker='',source='',once=False):
    r3.ticker(im,t,ticker,once=once)
    r3.source(ImageDraw.Draw(im),source,r3.colors(None)[1])
    r3.presenter(im,t)
    if r3.LOOK=='v4':
        im.info['v4_ticker_text']=ticker
        ensure_team_badges(im)
        balance_content(im,t)
    return im


def balance_content(im,t):
    """中身を描いた後、札内の余白を詰め、短い内容は安全域の中央へ。共通の帯等は触らない。"""
    import v3_rules as rules
    entries=im.info.get('v3_layout',[])
    blank=None
    def backdrop():
        nonlocal blank
        if blank is None:blank=r3.background(t,None)
        return blank
    # 大きな外札の下だけが空いている場合も、外枠の高さで検査を逃がさない。
    for card in [e for e in entries if e['role']=='card']:
        x,y,right,bottom=card['box']
        if bottom-y<200:continue
        children=[e for e in entries if e is not card and e['role'] not in ('header','source','caption','ticker')
                  and x<=e['box'][0] and y<=e['box'][1] and e['box'][2]<=right and e['box'][3]<=bottom]
        end=max((e['box'][3] for e in children),default=y)
        if bottom-end<200:continue
        new_bottom=round(end+28)
        if new_bottom<=y:continue
        # Pillowの矩形描画は右/下端を含む。cropの除外端を1px広げ、旧枠線も消す。
        box=(round(x),round(y),round(right)+1,round(bottom)+1);saved=im.crop(box)
        im.paste(backdrop().crop(box),box[:2])
        ImageDraw.Draw(im).rounded_rectangle((x,y,right,new_bottom),radius=22,
                                             fill=r3.colors(None)[0],outline=r3.colors(None)[1],width=2)
        # 中身と上辺/左右辺は原画を保ち、下辺だけを新しい位置にする。
        height=max(0,new_bottom-round(y)-22)
        im.paste(saved.crop((0,0,saved.width,height)),(round(x),round(y)))
        card['box']=[x,y,right,new_bottom]
    moving,outer=rules.content_group(im)
    if not moving:return im
    top=min(e['box'][1] for e in moving);bottom=max(e['box'][3] for e in moving)
    if r3.CONTENT_BOTTOM-bottom<200:return im
    shift=round((320+r3.CONTENT_BOTTOM-top-bottom)/2)
    if len(outer)>1 and r3.CONTENT_BOTTOM-(bottom+shift)>=200:
        shift=round(r3.CONTENT_BOTTOM-180-bottom)
    shift=max(0,min(shift,round(r3.CONTENT_BOTTOM-bottom)))
    if not shift:return im
    x=max(0,int(min(e['box'][0] for e in moving))-3);right=min(im.width,int(max(e['box'][2] for e in moving))+4)
    box=(x,int(top),right,int(bottom)+1);saved=im.crop(box)
    im.paste(backdrop().crop(box),box[:2]);im.paste(saved,(x,box[1]+shift))
    for e in moving:
        a,b,c,d=e['box'];e['box']=[a,b+shift,c,d+shift]
    for badge in im.info.get('v4_badges',[]):
        a,b,c,d=badge['box']
        if top<=b and d<=bottom:badge['box']=[a,b+shift,c,d+shift]
    im.info['v4_content_shift']=shift
    return im


def stat(im,x,y,value,unit,size=96,color=None,width=280,unit_size=30):
    """Oswaldの数字と小さい単位。幅を見て数字を調整する。"""
    color=color or r3.GOLD;unit=str(unit);value=str(value)
    uw=r3.font(unit_size).getlength(unit)
    room=max(30,width-uw-14)
    while r3.num_font(size).getlength(value)>room and size>30:size-=2
    text(im,x,y,value,size,color,number=True)
    end=x+r3.num_font(size).getlength(value)+12
    text(im,end,y+max(0,size*.65-unit_size),unit,unit_size,color,width=uw+1)


def team_badge(im,x,y,abbr,tid=None,width=110):
    import notability_engine as ne
    from PIL import ImageColor
    base=ImageColor.getrgb(ne.MLB_TEAM_COLOR.get(str(tid),'#102833'))
    second=ImageColor.getrgb(r3.TEAM_SECONDARY_COLORS.get(str(tid),'#C4CED4'))
    return club_tag(im,x,y,abbr,base,second,width)


def mini_badge(im,x,y,tid):
    import notability_engine as ne
    from PIL import ImageColor
    abbr=ne.MLB_TEAM_ABBR[str(tid)]
    base=ImageColor.getrgb(ne.MLB_TEAM_COLOR[str(tid)])
    second=ImageColor.getrgb(r3.TEAM_SECONDARY_COLORS.get(str(tid),'#C4CED4'));ink=badge_ink(base)
    box=[x,y,x+70,y+38]
    panel(im,box,base,second);text(im,x+10,y+8,abbr,20,ink,width=50)
    im.info.setdefault('v4_badges',[]).append(dict(abbr=abbr,base=base,ink=ink,box=box))


def ensure_team_badges(im):
    """旧札の本文行だけをインライン化。帯や空きから所属を推測しない。"""
    import v3_rules as rules
    if r3.LOOK!='v4' or im.info.get('v3_outro'):return im
    entries=im.info.get('v3_layout',[])
    targets=[]
    for tid,entry in rules.team_mentions(im):
        if 'team_id' not in entry and not any(entry is old for old in targets):targets.append(entry)
    for entry in targets:
        x,y,right,bottom=entry['box'];value=entry['text']
        containers=[e['box'] for e in entries if e['role']=='card' and e['box'][0]<=x and e['box'][1]<=y and right<=e['box'][2] and bottom<=e['box'][3]]
        edge=min((b[2]-12 for b in containers),default=R)
        neighbors=[e['box'][0]-12 for e in entries if e is not entry and e['role']=='text' and e['box'][0]>right and abs(e['box'][1]-y)<8]
        if neighbors:edge=min(edge,min(neighbors))
        # 元の行の書体サイズと色を実画素から保つ。札の幅はこの行の中で予約する。
        size=entry.get('v4_font') or min(range(18,85),key=lambda n:abs((r3.font(n).getbbox(value)[3]-r3.font(n).getbbox(value)[1])-(bottom-y)))
        bg=im.getpixel((max(0,int(x)-2),max(0,int(y)-2)))
        from collections import Counter
        crop=im.crop((int(x),int(y),int(right)+1,int(bottom)+1))
        pixels=Counter(crop.get_flattened_data() if hasattr(crop,'get_flattened_data') else crop.getdata())
        color=entry.get('v4_color') or next((rgb for rgb,count in pixels.most_common() if sum(abs(a-b) for a,b in zip(rgb,bg))>100),r3.INK)
        ImageDraw.Draw(im).rectangle((x,y,right,bottom),fill=bg)
        entries.remove(entry)
        text(im,x,y,value,size,color,width=max(40,edge-x))
    return im


def contrast(a,b):
    def luminance(rgb):
        values=[c/255 for c in rgb]
        values=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in values]
        return sum(c*w for c,w in zip(values,(.2126,.7152,.0722)))
    bright,dark=sorted((luminance(a),luminance(b)),reverse=True)
    return (bright+.05)/(dark+.05)


def badge_ink(base):
    return max((r3.INK,r3.DARK_INK),key=lambda ink:contrast(base,ink))


def club_tag(im,x,y,abbr,base,second,width=110):
    ink=badge_ink(base)
    w=tag(im,x,y,abbr,base,ink,28,width)
    # 色は帯/枠へ残し、略称の字には明暗のコントラストを使う。
    ImageDraw.Draw(im).rounded_rectangle((x,y,x+w,y+54),radius=22,outline=second,width=2)
    im.info.setdefault('v4_badges',[]).append({'abbr':abbr,'base':base,'ink':ink,'box':[x,y,x+w,y+54]})
    return w


def stat_values(headline):
    units='回(?:3分の[12])?|打数|本塁打|二塁打|三塁打|安打|打点|四球|奪三振|自責|被安打|失点|得点|盗塁|防御率'
    number=r'\d+(?:\.\d+)?'
    return [(m[1],m[2]) if m[1] else (m[4],m[3]) for m in
            re.finditer(r'(?<![\d.])('+number+r')('+units+r')|('+units+r')('+number+r')(?![\d.])',str(headline))]


def without_big(values,big):
    """主数字と同じ成績を小札に繰り返さない。投球回の表記揺れも照合。"""
    def key(pair):
        from fractions import Fraction
        n,u=map(str,pair)
        if u.startswith('回3分の'):
            return (Fraction(n)+Fraction(int(u[-1]),3),'回')
        if u=='回' and re.fullmatch(r'\d+\.[12]',n):
            whole,part=n.split('.')
            return (Fraction(whole)+Fraction(int(part),3),'回')
        return (Fraction(n),u)
    if not big or not big[0]:return values
    return [p for p in values if key(p)!=key(big)]


def stat_cards(im,values,y,height=148):
    if not values:return
    gap=14;columns=min(5,len(values));w=(R-L-48-gap*(columns-1))//columns
    for i,(number,unit) in enumerate(values[:5]):
        x=L+24+i*(w+gap)
        panel(im,(x,y,x+w,y+height))
        text(im,x+16,y+14,number,76,r3.GOLD,width=w-32,number=True)
        ImageDraw.Draw(im).line((x+16,y+height-60,x+w-16,y+height-60),fill=r3.GOLD,width=1)
        text(im,x+16,y+height-46,unit,28,width=w-32)


def cover(t,spec):
    im=canvas(t,spec.get('label') or '日本人選手の成績')
    roster=spec['roster'];text(im,L,264,'出場した日本人選手',48,width=R-L-180)
    stat(im,R-164,258,len(roster),'人',122,width=164,unit_size=40)
    pages=max(1,(len(roster)+6)//7)
    page=min(pages-1,int(max(0,t)/max(.1,spec.get('dur',8)/pages)))
    for i,row in enumerate(roster[page*7:page*7+7]):
        large=i<3;rank=row['rank'];w=R-L if large else (R-L-18)//2
        x=L if large else L+((i-3)%2)*(w+18)
        y=410+i*126 if large else 800+((i-3)//2)*158
        h=114 if large else 142
        panel(im,(x,y,x+w,y+h),outline=r3.GOLD if rank==1 else None)
        primary,secondary,_=r3.colors(row.get('team_id'))
        ImageDraw.Draw(im).rounded_rectangle((x+3,y+18,x+11,y+h-18),radius=4,fill=secondary)
        text(im,x+24,y+18,rank,60 if large else 38,r3.GOLD,number=True,width=60)
        bx=x+92 if large else x+72
        team_badge(im,bx,y+20,row['abbr'],row.get('team_id'),90)
        text(im,bx+102,y+22,row['name'],46 if large else 34,width=w-(bx-x)-124)
        if row.get('big'):
            stat(im,x+w-240 if large else x+24,y+65 if large else y+82,
                 row['big'],row.get('unit',''),54 if large else 42,width=216,unit_size=24)
    im.info['v4_roster']={'names':[r['name'] for r in roster],'page':page,'pages':pages}
    return finish(im,t,spec.get('ticker',''),spec.get('source') or '出典：MLB公式（Stats API）')


def player_detail(t,spec,player):
    """1人用のv4。主数字が無い日は成績の札だけで表示する。"""
    im=canvas(t,spec.get('label') or '日本人選手の成績')
    panel(im,(L,258,R,1138))
    text(im,L+26,282,player.get('tag') or f'勝利貢献 第{player["rank"]}位',34,r3.GOLD,width=R-L-52)
    text(im,L+26,342,player['name'],60,width=R-L-52)
    x=L+26
    text(im,x,434,player.get('team_jp',''),34,width=R-x-24,team_id=player.get('team_id'))
    big=player.get('big','');unit=player.get('unit','')
    if big:
        stat(im,L+34,508,big,unit,172,width=R-L-80,unit_size=54)
    y=730 if big else 528
    values=without_big(stat_values(player.get('headline','')),(big,unit) if big else None)
    pages=max(1,(len(values)+4)//5)
    page=min(pages-1,int(max(0,t)/max(.1,spec.get('dur',8)/pages)))
    stat_cards(im,values[page*5:page*5+5],y)
    notes='\n'.join(str(s) for s in player.get('notes',[]) if s)
    if not values and not big:
        # 整数以外の成績や結果だけの日も、元の行を省略しない。
        notes='\n'.join(s for s in (player.get('headline',''),notes) if s)
    if notes:
        body=lines(notes,34,R-L-96);top=y+174;bottom=1120
        capacity=max(1,(bottom-top-48)//46)
        note_pages=[body[i:i+capacity] for i in range(0,len(body),capacity)]
        at=min(len(note_pages)-1,int(max(0,t)/max(.1,spec.get('dur',8)/len(note_pages))))
        current=note_pages[at];h=48+len(current)*46
        panel(im,(L+24,top,R-24,top+h))
        for i,line in enumerate(current):text(im,L+48,top+24+i*46,line,34,width=R-L-96)
        im.info['v4_annotation']={'lines':body,'page':at,'pages':len(note_pages)}
    im.info['v4_player']={'name':player['name'],'rank':player['rank'],'big':big,'unit':unit,
                          'stats':values,'page':page,'pages':pages}
    return finish(im,t,spec.get('ticker',''),spec.get('source') or '出典：MLB公式（Stats API）')


def others(t,spec):
    players=spec['other_players'];duration=max(.1,spec.get('dur',8));spoken=spec.get('say','')
    if spec.get('kind')=='others':
        im=canvas(t,spec.get('label') or '日本人選手の成績')
        text(im,L,260,'ほかの日本人選手',48,width=R-L)
        count=len(players);height=min(150,(r3.CONTENT_BOTTOM-352)//max(1,count)-12)
        for i,p in enumerate(players):
            y=342+i*(height+12)
            panel(im,(L,y,R,y+height))
            mini_badge(im,L+20,y+20,p.get('team_id'))
            text(im,L+130,y+24,p['name'],36,width=380)
            big=p.get('big');unit=p.get('unit') or ''
            if big:
                text(im,R-220,y+20,big,60,r3.GOLD,number=True,width=120)
                text(im,R-110,y+48,unit,24,width=85)
        im.info['v4_others']=[p['name'] for p in players]
        return finish(im,t,spec.get('ticker',''),'出典：MLB Stats API',once=True)
    # 元の「ほか、スガノ、スズキ。」を保ち、次の名前を読む位置で切り替える。
    positions=[0]+[spoken.find(p['spoken_name']) for p in players[1:]]
    index=0
    for i,pos in enumerate(positions):
        at=pos/max(1,len(spoken))*duration if pos>=0 else i/len(players)*duration
        if t>=at:index=i
    return player_detail(t,spec,players[index])


def ranking(t,spec,rows,source):
    im=canvas(t,'日本人選手の成績')
    text(im,L,260,'きょうの勝利貢献順位',48,width=R-L)
    for i,row in enumerate(rows[:5]):
        y=346+i*160;first=i==0
        panel(im,(L,y,R,y+146),CREAM if first else None)
        ink=r3.DARK_INK if first else r3.INK
        gold=(152,110,37) if first else r3.GOLD
        text(im,L+22,y+25,row['rank'],86,gold,number=True,width=80)
        text(im,L+114,y+26,row['name'],46,ink,width=335)
        team_badge(im,L+116,y+84,row['abbr'],row.get('team_id'))
        match=re.fullmatch(r'(\d+)(.*)',row['score'])
        if not match:
            match=re.search(r'(\d+)(位)$',row['score'])
        if match:
            stat(im,L+492,y+22,match[1],match[2],106,gold,width=R-L-510)
        else:
            text(im,L+492,y+45,row['score'],36,gold,width=R-L-510)
    return finish(im,t,(spec.get('v3') or {}).get('ticker',''),source)


def hero(t,spec):
    im=canvas(t,spec.get('label') or '日本人選手の成績')
    panel(im,(L,258,R,1142))
    rank=spec.get('rank');count=spec.get('roster_count')
    text(im,L+28,284,f'勝利貢献 第{rank}位' if rank else 'きょうの成績',38,r3.GOLD,width=R-L-56)
    text(im,L+28,350,spec.get('head',''),66,width=R-L-56)
    from notability_engine import MLB_TEAM_ABBR
    tid=spec.get('player_team_id')
    abbr=MLB_TEAM_ABBR.get(str(tid),'')
    x=L+28
    text(im,x,446,spec.get('head2',''),34,width=R-x-24,team_id=tid)
    stat(im,L+40,522,spec.get('big',''),spec.get('unit',''),258,width=R-L-100,unit_size=70)
    # 出場が1人の日は「1人の中で1位」・1位〜1位の目盛りを出さない（10/9 の本番で出ていた）
    if rank and count and count>1:
        tag(im,L+300,745,f'{count}人の中で{rank}位',r3.GOLD,r3.DARK_INK,32,width=R-L-328)
        d=ImageDraw.Draw(im);start=L+48;end=R-48;y=840
        d.line((start,y,end,y),fill=r3.colors(None)[1],width=5)
        for k in range(count):
            at=start+(end-start)*k/max(1,count-1)
            d.line((at,y-9,at,y+9),fill=r3.GOLD if k+1==rank else r3.INK,width=3)
        at=start+(end-start)*(rank-1)/max(1,count-1)
        d.rounded_rectangle((at-9,y-13,at+9,y+13),radius=6,fill=r3.GOLD)
        text(im,start,864,'1位',28)
        text(im,end-90,864,f'{count}位',28,width=90)
    # 小数の投球回を札の主数字にしない。整数の成績だけを切り出す。
    units='打数|安打|本塁打|打点|奪三振|自責|被安打|四球'
    values=[(m[1],m[2]) if m[1] else (m[4],m[3])
            for m in re.finditer(r'(?<![\d.])(\d+)('+units+r')|('+units+r')(\d+)(?![\d.])',spec.get('sub',''))]
    values=without_big(values,(spec.get('big'),spec.get('unit')))
    im.info['v4_stat_tiles']=values
    if values:
        gap=14;columns=min(5,len(values));w=(R-L-56-gap*(columns-1))//columns
        for i,(number,unit) in enumerate(values[:5]):
            x=L+28+i*(w+gap)
            panel(im,(x,944,x+w,1106))
            text(im,x+18,959,number,80,r3.GOLD,width=w-36,number=True)
            ImageDraw.Draw(im).line((x+18,1042,x+w-18,1042),fill=r3.GOLD,width=1)
            text(im,x+18,1054,unit,28,width=w-36)
    return finish(im,t,spec.get('ticker',''),spec.get('source') or '出典：MLB公式（Stats API）')


def metadata(row):
    result=[]
    tone=row.get('tone')
    if tone in TONE_COLORS:result.append((tone,TONE_COLORS[tone]))
    for key,label in [('likes','高評価'),('replies','返信')]:
        if row.get(key) is not None:
            result.append((f'{label} {row[key]:,}',r3.DARK_INK))
    for key in ('outlet','author'):
        if row.get(key):result.append((str(row[key]),r3.DARK_INK))
    return result


def quote_pages(row,top=374):
    """引用は52/44pxを維持し、入らない行を次ページへ送る。"""
    import v3_slot_render as common
    size=44 if row.get('reply') else 54
    body=common.screen_text(row.get('said',''))
    wrapped=lines(body,size,R-L-88)
    # 引用符・下の札のために高さを先に予約する。
    capacity=max(1,(r3.CONTENT_BOTTOM-top-182)//(size+14))
    return [wrapped[i:i+capacity] for i in range(0,len(wrapped),capacity)],size


def quotes(t,voices,label,live,ticker,source):
    import v3_slot_render as common
    voices=[v for v in voices if not v.get('fact')]
    visible=[v for v in voices if t>=v.get('at',0)]
    active=next((v for v in reversed(visible) if v.get('read') is not False and t<v.get('end',4)),None)
    row=active or (visible[-1] if visible else (voices[0] if voices else None))
    im=canvas(t,label)
    text(im,L,264,common.screen_text(live),36,width=R-L)
    if not row:return finish(im,t,ticker,source)
    top=374
    # 読み終えた親の引用が収まるときは、返信の上に暗くして残す。
    parent=next((v for v in voices if not v.get('reply')),None) if row.get('reply') else None
    if parent:
        wrapped=lines(common.screen_text(parent.get('said','')),38,R-L-88)
        parent_h=110+len(wrapped)*52
        if parent_h+300 <= r3.CONTENT_BOTTOM-top:
            panel(im,(L,top,R,top+parent_h),CREAM)
            text(im,L+24,top+12,'“',64,(163,125,54))
            for i,line in enumerate(wrapped):text(im,L+44,top+58+i*52,line,38,r3.DARK_INK,width=R-L-88)
            parent_chips=metadata(parent)
            x=L+28
            for value,color in parent_chips:
                x+=tag(im,x,top+parent_h-54,common.screen_text(value),color,size=22,width=(R-L-72)//max(1,len(parent_chips)))+12
            region=ImageEnhance.Brightness(im.crop((L,top,R,top+parent_h))).enhance(.72)
            im.paste(region,(L,top))
            top+=parent_h+54
    pages,size=quote_pages(row,top)
    elapsed=max(0,t-row.get('at',0));dur=max(.1,row.get('end',4)-row.get('at',0))
    lengths=[sum(len(line) for line in page) for page in pages]
    spoken=min(1,elapsed/dur)*sum(lengths)
    page=0;finished=lengths[0]
    while page<len(pages)-1 and spoken>=finished:
        page+=1;finished+=lengths[page]
    body=pages[page]
    heading=('↳ 返信' if row.get('reply') else 'コメント（訳）'
             if not row.get('fact') and not row.get('outlet') and not row.get('author')
             else common.screen_text(row.get('who','')))
    text(im,L,top-50,heading,30,width=R-L)
    h=144+len(body)*(size+14)
    h=min(h,r3.CONTENT_BOTTOM-top)
    panel(im,(L,top,R,top+h),CREAM)
    if not row.get('fact'):
        text(im,L+22,top+6,'“',92,(163,125,54),width=80)
    for i,line in enumerate(body):
        text(im,L+44,top+74+i*(size+14),line,size,r3.DARK_INK,width=R-L-88)
    x=L+28;y=top+h-60
    chips=metadata(row)
    for value,color in chips:
        room=R-x-28
        if room<60:raise ValueError('引用の属性札が幅を超えました')
        # 記者名などは全て残すため、札ごとの幅を分配する。
        width=min(room,(R-L-56-12*(len(chips)-1))//max(1,len(chips)))
        x+=tag(im,x,y,common.screen_text(value),color,size=24,width=width)+12
    if row.get('read') is False or t>=row.get('end',4):
        # 同じ位置の既読の札を少し暗くする。読み上げの文はそのまま。
        region=im.crop((L,top,R,top+h));region=ImageEnhance.Brightness(region).enhance(.72)
        im.paste(region,(L,top))
    im.info['v4_quote']={'said':row.get('said',''),'page':page,'pages':len(pages),'active':active is not None}
    im.info['v4_quote_group']={'parent':parent.get('said') if parent else row.get('said') if row else '',
                             'said':[v.get('said') for v in voices],'overview_cards':0}
    return finish(im,t,ticker,source)


def schedule(t,spec,rows,label,source):
    if len(rows)>4:raise ValueError('全試合の一覧は4行までです')
    im=canvas(t,label);text(im,L,260,'明日の全試合',48,width=R-L)
    text(im,L,314,'時刻は日本時間',24,width=R-L)
    for i,row in enumerate(rows):
        y=348+i*194
        panel(im,(L,y,R,y+174))
        clock=row['when'].split()[-1]
        text(im,L+22,y+20,clock,76,r3.GOLD,width=185,number=True)
        import notability_engine as ne
        for j,side in enumerate(('home','away')):
            name=row[side];tid=str(row.get(side+'_id') or next((tid for tid,n in ne.MLB_TEAM_NAME_JP.items() if n==name),''))
            text(im,L+230,y+18+j*52,name,32,width=R-L-260,team_id=tid or None)
        score=(f'{row["home"]} {row["home_wins"]}勝　{row["away"]} {row["away_wins"]}勝'
               if 'home_wins' in row and 'away_wins' in row else 'シリーズ勝敗は確認中')
        text(im,L+24,y+116,score,30,width=R-L-48)
    v=spec.get('v3') or {}
    return finish(im,t,v.get('ticker',''),source,v.get('ticker_once',False))


def wins(im,x,y,won,need):
    """目は材料の決着勝数だけ。意味を必ず同じ画面で記す。"""
    if not isinstance(need,int) or not 1<=need<=4 or not 0<=won<=need:
        raise ValueError('シリーズの勝数/決着勝数が材料と合いません')
    d=ImageDraw.Draw(im)
    for i in range(need):
        at=x+i*44
        d.ellipse((at,y,at+26,y+26),fill=r3.GOLD if i<won else (76,86,102))
    explanation=f'{need}勝で決着'
    im.info.setdefault('v4_marks',[]).append({'need':need,'wins':won,'explanation':explanation})
    text(im,x,y+40,explanation,26,width=200)


def team_row(im,box,row,need):
    panel(im,box)
    x,y,right,bottom=box;d=ImageDraw.Draw(im)
    from PIL import ImageColor
    second=row.get('secondary') or '#C4CED4';base=row.get('color') or '#102833'
    second=ImageColor.getrgb(second) if isinstance(second,str) else second
    base=ImageColor.getrgb(base) if isinstance(base,str) else base
    d.rectangle((x+2,y+18,x+10,bottom-18),fill=second)
    text(im,x+28,y+30,row['name'],48,width=right-x-200,team_id=row.get('team_id'))
    wins(im,x+32,y+98,row['wins'],need)
    stat(im,right-174,y+70,row['wins'],'勝',100,width=150)


def focus(t,card,view):
    im=canvas(t,card.get('label','PS予告'))
    text(im,L,256,card.get('round_game') or card.get('subhead',''),40,width=R-L)
    v=view['v3'];clock=v.get('big','')
    if clock:
        text(im,L,330,clock+v.get('unit',''),112,r3.GOLD,width=430,number=True)
        text(im,L+470,395,'日本時間開始',34,width=R-L-470)
    board=card['scoreboard'];need=board['need']
    for i,row in enumerate(board['rows']):
        team_row(im,(L,498+i*198,R,680+i*198),row,need)
    # 注目カードの材料にある日本人選手だけ。
    player_rows=[r for r in board['rows'] if r.get('players')]
    if player_rows:
        panel(im,(L,918,R,1138))
        y=936
        for row in player_rows:
            text(im,L+24,y,row['name']+'の日本人選手',28,width=R-L-48);y+=44
            phrase=(card.get('v4_club_mentions') or {}).get(row['name'])
            if phrase==row['name']:
                text(im,L+24,y,'注目球団',32,r3.GOLD,width=R-L-48)
            else:text(im,L+24,y,'・'.join(row['players']),40,width=R-L-48)
            y+=60
    return finish(im,t,v.get('ticker',''),'出典：'+card.get('source_label','MLB公式日程'),True)


def situation(t,card,view):
    all_rows=card.get('v4_series') or [card]
    # 回戦が切り替わる日の決着済みシリーズも、積み増しせず別ページへ。
    current=next((i for i,c in enumerate(all_rows) if c['scoreboard']==card.get('scoreboard')),0)
    page=current//4
    rows=all_rows[page*4:page*4+4]
    im=canvas(t,'PS情勢')
    text(im,L,260,'全シリーズの勝敗',48,width=R-L)
    im.info['v4_series_page']={'page':page,'pages':(len(all_rows)+3)//4,'count':len(all_rows)}
    for i,series in enumerate(rows):
        y=350+i*194;board=series['scoreboard'];need=board['need']
        active=board==card.get('scoreboard')
        panel(im,(L,y,R,y+178),outline=r3.GOLD if active else None)
        for j,row in enumerate(board['rows']):
            yy=y+16+j*76
            from PIL import ImageColor
            base=ImageColor.getrgb(row.get('color') or '#102833')
            second=ImageColor.getrgb(row.get('secondary') or '#C4CED4')
            ImageDraw.Draw(im).rectangle((L+6,yy,L+12,yy+54),fill=second)
            text(im,L+20,yy+4,row['name'],32,width=365,team_id=row.get('team_id'))
            # 全シリーズでも勝数の目を必ず説明する。
            d=ImageDraw.Draw(im)
            for k in range(need):
                at=L+392+k*36
                d.ellipse((at,yy+6,at+22,yy+28),fill=r3.GOLD if k<row['wins'] else (76,86,102))
            im.info.setdefault('v4_marks',[]).append({'need':need,'wins':row['wins'],'explanation':f'{need}勝で決着'})
        text(im,L+594,y+18,'-'.join(str(r['wins']) for r in board['rows']),92,r3.GOLD,width=R-L-614,number=True)
        next_text=next((str(r['value']) for r in series['items'] if r['label']=='次の試合'),series.get('subhead',''))
        text(im,L+20,y+142,f'{need}勝で決着　'+next_text,24,width=R-L-40)
    return finish(im,t,view['v3'].get('ticker',''),'出典：'+card.get('source_label','MLB公式日程'),True)
