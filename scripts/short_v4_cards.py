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


def text(im, x, y, value, size=40, color=None, width=None, number=False):
    """文字の実際の上端を指定し、同じ実寸を安全域検査へ記録する。"""
    value = str(value)
    font = r3.num_font if number else r3.font
    while width and font(size).getlength(value) > width and size > 18:
        size -= 2
    if width and font(size).getlength(value) > width:
        raise ValueError('v4の文字が札の幅に入りません: '+value)
    f = font(size)
    dy = f.getbbox(value)[1]
    r3._text(ImageDraw.Draw(im), (x, y-dy), value, font=f, fill=color or r3.INK)


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
    ImageDraw.Draw(im).rounded_rectangle(box, radius=22, fill=fill or r3.colors(None)[0],
                                        outline=outline or r3.colors(None)[1], width=2)
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
    base,second,_=r3.colors(tid)
    return club_tag(im,x,y,abbr,base,second,width)


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
    im.info.setdefault('v4_badges',[]).append({'abbr':abbr,'base':base,'ink':ink})
    return w


def stat_values(headline):
    units='回(?:3分の[12])?|打数|本塁打|二塁打|三塁打|安打|打点|四球|奪三振|自責|被安打|失点|得点|盗塁|防御率'
    number=r'\d+(?:\.\d+)?'
    return [(m[1],m[2]) if m[1] else (m[4],m[3]) for m in
            re.finditer(r'(?<![\d.])('+number+r')('+units+r')|('+units+r')('+number+r')(?![\d.])',str(headline))]


def stat_cards(im,values,y,height=148):
    if not values:return
    gap=14;columns=min(5,len(values));w=(R-L-48-gap*(columns-1))//columns
    for i,(number,unit) in enumerate(values[:5]):
        x=L+24+i*(w+gap)
        panel(im,(x,y,x+w,y+height))
        text(im,x+16,y+14,number,76,r3.GOLD,width=w-32,number=True)
        text(im,x+16,y+height-46,unit,28,width=w-32)


def cover(t,spec):
    im=canvas(t,spec.get('label') or '日本人選手の成績')
    roster=spec['roster'];text(im,L,264,'出場した日本人選手',48,width=R-L)
    stat(im,L+30,348,len(roster),'人',208,width=R-L-60,unit_size=68)
    pages=max(1,(len(roster)+7)//8)
    page=min(pages-1,int(max(0,t)/max(.1,spec.get('dur',8)/pages)))
    for i,row in enumerate(roster[page*8:page*8+8]):
        w=(R-L-18)//2;x=L+(i%2)*(w+18);y=610+(i//2)*128
        panel(im,(x,y,x+w,y+112))
        text(im,x+18,y+18,row['name'],36,width=w-36)
        team_badge(im,x+18,y+58,row['abbr'],row.get('team_id'),100)
    im.info['v4_roster']={'names':[r['name'] for r in roster],'page':page,'pages':pages}
    return finish(im,t,spec.get('ticker',''),spec.get('source') or '出典：MLB公式（Stats API）')


def player_detail(t,spec,player):
    """1人用のv4。主数字が無い日は成績の札だけで表示する。"""
    im=canvas(t,spec.get('label') or '日本人選手の成績')
    panel(im,(L,258,R,1138))
    text(im,L+26,282,f'勝利貢献 第{player["rank"]}位',34,r3.GOLD,width=R-L-52)
    text(im,L+26,342,player['name'],60,width=R-L-52)
    x=L+26
    if player['abbr']:x+=team_badge(im,x,424,player['abbr'],player.get('team_id'))+20
    text(im,x,434,player.get('team_jp',''),34,width=R-x-24)
    big=player.get('big','');unit=player.get('unit','')
    if big:
        stat(im,L+34,508,big,unit,172,width=R-L-80,unit_size=54)
    y=730 if big else 528
    values=stat_values(player.get('headline',''))
    pages=max(1,(len(values)+4)//5)
    page=min(pages-1,int(max(0,t)/max(.1,spec.get('dur',8)/pages)))
    stat_cards(im,values[page*5:page*5+5],y)
    notes='\n'.join(str(s) for s in player.get('notes',[]) if s)
    if not values:
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
    if abbr:x+=team_badge(im,x,433,abbr,tid)+22
    text(im,x,446,spec.get('head2',''),34,width=R-x-24)
    stat(im,L+40,522,spec.get('big',''),spec.get('unit',''),258,width=R-L-100,unit_size=70)
    if rank and count:
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
    if values:
        gap=14;columns=min(5,len(values));w=(R-L-56-gap*(columns-1))//columns
        for i,(number,unit) in enumerate(values[:5]):
            x=L+28+i*(w+gap)
            panel(im,(x,944,x+w,1106))
            text(im,x+18,959,number,80,r3.GOLD,width=w-36,number=True)
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
    visible=[v for v in voices if t>=v.get('at',0)]
    active=next((v for v in reversed(visible) if v.get('read') is not False and t<v.get('end',4)),None)
    row=active or (visible[-1] if visible else None)
    im=canvas(t,label)
    text(im,L,264,common.screen_text(live),36,width=R-L)
    if not row:return finish(im,t,ticker,source)
    top=374
    # 読み終えた親の引用が収まるときは、返信の上に暗くして残す。
    parent=next((v for v in reversed(visible[:-1]) if not v.get('fact')),None) if row.get('reply') else None
    if parent:
        wrapped=lines(common.screen_text(parent.get('said','')),54,R-L-88)
        parent_h=96+len(wrapped)*68
        if parent_h+300 <= r3.CONTENT_BOTTOM-top:
            panel(im,(L,top,R,top+parent_h),CREAM)
            text(im,L+24,top+12,'“',64,(163,125,54))
            for i,line in enumerate(wrapped):text(im,L+44,top+58+i*68,line,54,r3.DARK_INK,width=R-L-88)
            region=ImageEnhance.Brightness(im.crop((L,top,R,top+parent_h))).enhance(.72)
            im.paste(region,(L,top))
            top+=parent_h+62
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
    return finish(im,t,ticker,source)


def schedule(t,spec,rows,label,source):
    if len(rows)>4:raise ValueError('全試合の一覧は4行までです')
    im=canvas(t,label);text(im,L,260,'明日の全試合の一覧',48,width=R-L)
    for i,row in enumerate(rows):
        y=348+i*194
        panel(im,(L,y,R,y+174))
        clock=row['when'].split()[-1]
        text(im,L+22,y+20,clock,76,r3.GOLD,width=185,number=True)
        text(im,L+230,y+28,row['home']+'対'+row['away'],40,width=R-L-258)
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
    club_tag(im,x+28,y+22,row['abbr'],base,second,width=110)
    text(im,x+156,y+30,row['name'],48,width=right-x-310)
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
            text(im,L+24,y,'・'.join(row['players']),40,width=R-L-48);y+=60
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
            club_tag(im,L+20,yy,row['abbr'],base,second,width=100)
            text(im,L+132,yy+4,row['name'],32,width=245)
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
