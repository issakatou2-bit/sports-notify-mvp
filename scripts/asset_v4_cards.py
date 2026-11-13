"""試合の話題・投手の話題のv4札。共通の字幕・帯・締めには触れない。"""
import re
from PIL import ImageDraw
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_render_v3 as r3
import short_v4_cards as c
import v3_slot_render as common

L, R = r3.LEFT, r3.SAFE_RIGHT


def enabled(spec):
    return bool(spec.get('game') or spec.get('spotlight') or spec.get('offseason'))


def finish(im, t, spec, source=None):
    v = spec.get('v3') or {}
    if spec.get('_game_ui_static'):
        c.balance_content(im,t)
        r3.ticker(im,t,v.get('ticker',''),once=v.get('ticker_once',False))
        r3.source(ImageDraw.Draw(im),source or v.get('source') or r3.page_source(spec.get('items') or []),r3.colors(None)[1])
        r3.presenter(im,t)
        return im
    return c.finish(im, t, v.get('ticker', ''), source or v.get('source') or r3.page_source(spec.get('items') or []), v.get('ticker_once', False))


def block(im, value, y, size=48, color=None, x=L+24, width=R-L-48):
    for line in c.lines(common.screen_text(value), size, width):
        c.text(im, x, y, line, size, color, width=width)
        y += size+14
    return y


HOOK_BOTTOM = 1020


def hook_v2(spec):
    """新しい見た目（v2）の日本人選手の数字の回：1枚目を名前・特大の数字・結論・札で描く。"""
    return bool(r3.STYLE_V2 and spec.get('jp_stock') and (spec.get('v3') or {}).get('big'))


def _fit(value, size, width, floor=40):
    while size > floor and c.text_length(value, size) > width:
        size -= 2
    return size


def intro_v2(t, spec, label):
    """名前（96前後）→特大の数字＋単位→結論の句→札3行（左にラベル・右にOswaldの数字）。"""
    im = c.canvas(t, label)
    v = spec.get('v3') or {}
    width = R-L
    who = str(v.get('who') or spec.get('label', ''))
    who_size = _fit(who, 96, width)
    c.text(im, L+(width-c.text_length(who, who_size))/2, 262, who, who_size)
    big, unit = str(v['big']), str(v.get('unit') or '')
    chips = (v.get('chips') or [])[:3]
    row_h, gap = 88, 8
    chips_h = len(chips)*row_h+max(0, len(chips)-1)*gap
    sub = str(v.get('sub') or '')
    unit_size = 72
    uw = r3.font(unit_size).getlength(unit)+14 if unit else 0
    top = 380
    size = 340
    while size > 120 and r3.num_font(size).getlength(big)+uw > width:
        size -= 4
    def metrics(n):
        bb = r3.num_font(n).getbbox(big)
        return bb[3]-bb[1]
    # 右下のキャラの頭（y約1035）より上に札が収まるまで数字を縮める。
    while size > 120 and top+metrics(size)+36+(76 if sub else 0)+(34+chips_h if chips else 0) > HOOK_BOTTOM:
        size -= 4
    height = metrics(size)
    nw = r3.num_font(size).getlength(big)
    x = L+(width-nw-uw)/2
    c.text(im, x, top, big, size, r3.GOLD, number=True)
    r3.record_box(im, 'number', (x, top, x+nw, top+height), big)
    if unit:
        uh = r3.font(unit_size).getbbox(unit)
        c.text(im, x+nw+14, top+height-(uh[3]-uh[1]), unit, unit_size, r3.GOLD, width=uw)
    y = top+height+36
    sub_size = 0
    if sub:
        sub_size = _fit(sub, 56, width)
        c.text(im, L+(width-c.text_length(sub, sub_size))/2, y, sub, sub_size)
        y += 76
    y += 34
    chip_sizes = []
    for chip in chips:
        c.panel(im, (L, y, R, y+row_h))
        score, label_text = str(chip.get('score', '')), str(chip.get('label', ''))
        num_size = 56
        nwid = r3.num_font(num_size).getlength(score)
        nb = r3.num_font(num_size).getbbox(score)
        c.text(im, R-28-nwid, y+(row_h-(nb[3]-nb[1]))/2, score, num_size, r3.GOLD, number=True)
        room = width-28-nwid-28-24
        ls = _fit(label_text, 40, room)
        lb = r3.font(ls).getbbox(label_text)
        c.text(im, L+28, y+(row_h-(lb[3]-lb[1]))/2, label_text, ls, width=room)
        chip_sizes.append(ls)
        y += row_h+gap
    im.info['asset_v4'] = {'kind': 'intro', 'v2_hook': dict(who=who, who_size=who_size, big=big, big_size=size,
                           unit=unit, sub=sub, chips=len(chips), chip_label_sizes=chip_sizes)}
    return finish(im, t, spec)


def intro(t, spec, label):
    if hook_v2(spec):
        return intro_v2(t, spec, label)
    im = c.canvas(t, label)
    v = spec.get('v3') or {}
    c.text(im, L, 262, v.get('who') or spec.get('label', ''), 44, width=R-L)
    big = str(v.get('big') or '')
    if big:
        c.stat(im,L,430,big,v.get('unit',''),size=300,width=R-L,unit_size=64)
    else:
        block(im,spec.get('hook',''),410,64)
    if v.get('sub'):c.text(im,L,732,v['sub'],36,width=R-L)
    if v.get('tag'):c.tag(im,L,800,common.screen_text(v['tag']),r3.GOLD,r3.DARK_INK,30,width=R-L)
    chips = v.get('chips') or []
    # 同じ4札の材料を使い、Oswaldの数字と小さいラベルへ。
    for i, chip in enumerate(chips[:4]):
        x=L+(i%2)*(R-L+16)//2;y=882+(i//2)*124;w=(R-L-16)//2
        c.panel(im,(x,y,x+w,y+112))
        c.text(im,x+18,y+10,str(chip.get('score','')),62,r3.GOLD,number=True,width=w-36)
        c.text(im,x+18,y+79,chip.get('label',''),24,width=w-36)
    im.info['asset_v4']={'kind':'intro'}
    return finish(im,t,spec)


def score(t,spec,label,page=0):
    board=(spec.get('game_v4') or {}).get('score')
    if not board:return None
    innings=board['innings'];groups=[innings[i:i+9] for i in range(0,len(innings),9)]
    chosen=groups[min(page,len(groups)-1)]
    im=c.canvas(t,label);c.text(im,L,262,'試合の結果',48,width=R-L)
    # 九つの回＋計。球団名は上に独立させ、回の数字の幅を確保する。
    winner='away' if board['away']['total']>board['home']['total'] else 'home'
    c.panel(im,(L,344,R,850))
    x0=L+132;cell=(R-x0-90-20)/len(chosen);total_x=R-84
    d=ImageDraw.Draw(im);grid=(79,92,108)
    d.rectangle((L+3,360,R-3,438),fill=(32,47,61))
    for n,side in enumerate(('away','home')):
        fill=(44,48,48) if side==winner else ((19,32,44) if n%2==0 else (25,39,51))
        d.rectangle((L+3,439+n*182,R-3,620+n*182),fill=fill)
    for i in range(len(chosen)+1):
        x=x0-10+i*cell;d.line((x,360,x,802),fill=grid,width=1)
    for y in (438,620,802):d.line((L+3,y,R-3,y),fill=grid,width=1)
    d.line((total_x-12,360,total_x-12,802),fill=r3.GOLD,width=3)
    im.info['v4_score_grid']={'columns':len(chosen)+1,'rows':2,'winner':winner}
    for i,row in enumerate(chosen):
        c.text(im,x0+i*cell,386,row['num'],30,r3.GOLD,number=True,width=cell-3)
    c.text(im,total_x,386,'計',30,width=66)
    for n,side in enumerate(('away','home')):
        row=board[side];y=464+n*182;col=r3.GOLD if side==winner else r3.INK
        for i,inn in enumerate(chosen):
            c.text(im,x0+i*cell,y+10,'—' if inn[side] is None else inn[side],46,col,number=inn[side] is not None,width=cell-3)
        c.text(im,total_x,y-4,row['total'],76,col,number=True,width=66)
        c.text(im,L+24,y+76,row['name'],32,col,width=R-L-48,team_id=row['id'])
    c.tag(im,L,886,board[winner]['name']+'の勝ち',r3.GOLD,r3.DARK_INK,34,width=R-L)
    result=dict(spec.get('items') or []).get('試合の結果','')
    series=result.split('　')[-1]
    if '勝' in series and '敗' in series:c.text(im,L,968,series,32,width=R-L)
    if len(groups)>1:c.text(im,L,1040,f'{page+1}/{len(groups)}',28,width=R-L)
    im.info['asset_v4']={'kind':'score','innings':chosen,'board':board,'page':page,'pages':len(groups)}
    return finish(im,t,spec,'出典: MLB公式（Stats API / linescore）')


def decisive(spec,body):
    card=(spec.get('game_v4') or {}).get('decisive')
    if card:return card
    inning,_,rest=body.partition('　')
    if '相手の' in rest and ('失策' in rest or '暴投' in rest or '捕逸' in rest):
        subject='相手の送球失策' if '送球' in rest else '相手の失策' if '失策' in rest else '相手の暴投' if '暴投' in rest else '相手の捕逸'
        return {'inning':inning,'subject':subject,'action':'決勝点','detail':''}
    main,_,detail=rest.partition('（');who,_,event=main.partition('の')
    return {'inning':inning,'subject':who,'action':event,'detail':detail.rstrip('）')}


def stat_pairs(value):
    # 表示は材料にある数字だけ。「無失点」を新しい0に換算しない。
    value=str(value).replace('回と3分の','回3分の')
    fractional=re.findall(r'(?:(\d+)回)?(?:と)?3分の([12])回?',value)
    value=re.sub(r'(?:(\d+)回)?(?:と)?3分の([12])回?', '', value)
    pairs=[(whole,'回3分の'+part) if whole else (part+'/3','回') for whole,part in fractional]+c.stat_values(value)
    extra=re.findall(r'(\d+(?:\.\d+)?)(球|キロ|マイル|本)(?!塁)',value)
    pitches=re.findall(r'(フォーシーム|スプリット|カーブ|カッター|シンカー|スライダー)(\d+)',value)
    return pairs+extra+[(n,u) for u,n in pitches]


def person_rows(body):
    # 先発の球団＋名前＋成績を分割。日本語球団名は既存の表を参照する。
    import notability_engine as ne
    names=sorted(ne.MLB_TEAM_NAME_JP.values(),key=len,reverse=True)
    pattern='|'.join(re.escape(n) for n in names)
    parts=re.split('(?=(?:'+pattern+') )',body)
    return [p.strip('　 ') for p in parts if p.strip('　 ')]


def mixed_lines(value,size=54,number_size=None,width=R-L-48):
    """本文48〜56px、数字はOswald。実寸で折り、文を省かない。"""
    number_size=number_size or size
    result=[];row=[];w=0
    # カタカナの語・英語の語・漢字の続き（2字まで）は途中で切らない。行頭に句読点・小さい字を置かない
    for token in re.findall(r'\d+(?:\.\d+)?|[ァ-ヴー・]+|[A-Za-z][A-Za-z.\-]*|[一-龥]{1,2}|[^\d]',common.screen_text(value)):
        numeric=bool(re.fullmatch(r'\d+(?:\.\d+)?',token))
        font=r3.num_font(number_size) if numeric else r3.font(size)
        tw=0 if token=='\n' else font.getlength(token)  # Linuxのraqmは改行の長さを測れず落ちる
        import notability_engine as ne
        named=next((tid for tid,name in ne.MLB_TEAM_NAME_JP.items() if token==name),None)
        if named:tw+=c.inline_badge_width(named,size)+12
        if token=='\n' or (row and w+tw>width):
            carry=[]
            # 行頭に句読点・閉じ括弧・小さい字を置かない: 前の1つを一緒に次の行へ送る
            if token!='\n' and token[0] in '、。）」ゃゅょっャュョッー' and len(row)>1:
                carry=[row.pop()]
            result.append(row);row=carry;w=sum((r3.num_font(number_size) if n else r3.font(size)).getlength(t) for t,n in carry)
            if token=='\n':continue
        row.append((token,numeric));w+=tw
    if row:result.append(row)
    return result or [[]]


def text_pages(head,body,illustrated=False):
    number_size=104 if head=='次の試合' else 54
    wrapped=mixed_lines(body,54,number_size,width=R-L-48-(260 if illustrated else 0))
    line_height=number_size+18
    capacity=max(1,(r3.CONTENT_BOTTOM-(638 if illustrated else 348)-56)//line_height)
    return [wrapped[i:i+capacity] for i in range(0,len(wrapped),capacity)],number_size,line_height


def text_screen(t,spec,label,head,body,page=0):
    art = __import__('market_art').for_item(spec, head, body)
    im=c.canvas(t,label);c.text(im,L,262,head,44,width=R-L)
    pages,number_size,lh=text_pages(head,body,bool(art));rows=pages[min(page,len(pages)-1)]
    height=56+len(rows)*lh
    # 安全域の中央に、内容に合う高さの札を置く。
    top=round(((638 if art else 348)+r3.CONTENT_BOTTOM-height)/2)
    c.panel(im,(L,top,R-(260 if art else 0),top+height))
    for i,row in enumerate(rows):
        x=L+24;y=top+28+i*lh
        # 1字ずつ上端で揃えると「ー」が上へ浮く（10/8 試作「ポストシ¯ズン」）。行の下の線で揃える
        base=y+number_size
        d=ImageDraw.Draw(im)
        for token,numeric in row:
            size=number_size if numeric else 54
            f=r3.num_font(size) if numeric else r3.font(size)
            c.text(im,x,base+f.getbbox(token,anchor='ls')[1],token,size,r3.GOLD if numeric else r3.INK,number=numeric)
            x+=f.getlength(token)
            import notability_engine as ne
            tid=next((tid for tid,name in ne.MLB_TEAM_NAME_JP.items() if token==name),None)
            if tid:x+=c.inline_badge_width(tid,size)+12
    im.info['asset_v4']={'kind':'text','head':head,'body':body,'page':page,'pages':len(pages),
                        'font_size':54,'number_font':'Oswald','number_size':number_size}
    if art:
        import market_art_render
        market_art_render.draw(im, art, spec.get('_market_art_elapsed', t))
    im = finish(im,t,spec)
    if art:
        errors = market_art_render.check_layout(im) + __import__('v3_rules').check_layout(im)
        if errors:
            raise ValueError('挿絵が文字・安全域に重なっています: ' + str(errors))
    return im


def stat_screen(t,spec,label,head,body,page=0):
    if not stat_pairs(body):return text_screen(t,spec,label,head,body,page)
    im=c.canvas(t,label);c.text(im,L,262,head,44,width=R-L)
    parts=person_rows(body) if head=='先発' else body.split('　') if head=='本塁打' else [body]
    if len(parts)>1:
        for i,part in enumerate(parts):
            y=346+i*358;c.panel(im,(L,y,R,y+332))
            title=re.split(r'(?=\d)',part,maxsplit=1)[0].strip('（　 ')
            import notability_engine as ne
            team=next(((tid,name) for tid,name in ne.MLB_TEAM_NAME_JP.items() if title.startswith(name)),None)
            if team:
                c.text(im,L+24,y+30,title,36,width=R-L-48,team_id=team[0])
            else:c.text(im,L+24,y+26,title,40,width=R-L-48)
            pairs=stat_pairs(part)
            if pairs:c.stat_cards(im,pairs,y+102,height=196)
            else:block(im,part,y+110,38)
            if head=='本塁打':
                names=re.search(r'（(.+)）',part)
                if names:c.text(im,L+24,y+304,names[1],22,width=R-L-48)
        pages=1
    else:
        c.panel(im,(L,348,R,1134))
        pairs=stat_pairs(body);values=[pairs[i:i+10] for i in range(0,len(pairs),10)] or [[]]
        pages=len(values);selected=values[min(page,pages-1)]
        # 名前や説明を消さず、材料の行も残す。
        title=body.split('（')[0].strip() if head=='勝ち投手' else head
        y=block(im,title,382,40)
        if head=='勝ち投手' and spec.get('team_id'):
            import notability_engine as ne
            c.text(im,L+24,444,ne.MLB_TEAM_NAME_JP[str(spec['team_id'])],34,width=R-L-48,team_id=spec['team_id'])
            y=492
        if selected:
            # 主要な整数を大きく、全成績を1枚ずつ。6個以上も安全域の2段へ。
            hero=next(((n,u) for unit in ('奪三振','安打','本塁打','打点','回','キロ') for n,u in selected if u==unit),selected[0])
            if y<=556:
                c.stat(im,L+24,552,*hero,size=236,width=R-L-48,unit_size=44)
                selected=c.without_big(selected,hero)
            im.info['v4_stat_tiles']=selected
            im.info['v4_big_stat']=hero
            for k in range(0,len(selected),5):c.stat_cards(im,selected[k:k+5],810+(k//5)*164,height=148)
    im.info['asset_v4']={'kind':'stats','head':head,'body':body,'stats':stat_pairs(body),'page':page,'pages':pages}
    return finish(im,t,spec)


def item_pages(spec,head,body):
    if spec.get('offseason'):
        return len(text_pages(head,body,bool(__import__('market_art').for_item(spec,head,body)))[0])
    if head=='試合の結果' and (spec.get('game_v4') or {}).get('score'):
        return (len(spec['game_v4']['score']['innings'])+8)//9
    if body.startswith('「') or '見出しから' in head or '投稿から' in head:
        return len(c.quote_pages({'said':body.strip('「」')})[0])
    if not stat_pairs(body):return len(text_pages(head,body)[0])
    return max(1,(len(stat_pairs(body))+9)//10)


def item(t,spec,label,head,body,page=0):
    if spec.get('offseason'):
        return text_screen(t,spec,label,head,body,page)
    if head=='試合の結果':
        image=score(t,spec,label,page)
        if image is not None:return image
    if head in ('決勝点','先制で決勝の一打'):
        v=decisive(spec,body);im=c.canvas(t,label);c.text(im,L,262,head,44,width=R-L)
        c.panel(im,(L,344,R,1134))
        c.tag(im,L+24,370,v['inning'],size=34)
        y=block(im,v['subject'],464,64,r3.GOLD)
        y=block(im,v['action'],y+44,68)
        if v.get('detail'):block(im,v['detail'],y+58,32)
        im.info['asset_v4']={'kind':'decisive',**v}
        return finish(im,t,spec)
    if body.startswith('「') or '見出しから' in head or '投稿から' in head:
        source=spec.get('headline') if '見出し' in head else spec.get('source') if '投稿' in head else spec.get('voice')
        row=dict(source or {},who=head,said=body.strip('「」'),at=0,end=1,read=True)
        if '見出し' in head:row.setdefault('outlet','MLB.com')
        # quote_pagesの比率に対応するページ時刻。
        pages,_=c.quote_pages(row);lengths=[sum(map(len,p)) for p in pages]
        qt=(sum(lengths[:page])+lengths[min(page,len(pages)-1)]*.5)/max(1,sum(lengths))
        row.update(at=t-qt,end=t-qt+1)
        im=c.quotes(t,[row],label,head,(spec.get('v3') or {}).get('ticker',''),r3.page_source([(head,body)]),animate=False)
        im.info['asset_v4']={'kind':'quote','head':head,'said':row['said'],'page':page,'pages':len(pages)}
        return im
    return stat_screen(t,spec,label,head,body,page)


def timing(t, weights, duration=None):
    """字幕と同じ文字数比率。札の切替はその項目を読む時間の中で行う。"""
    duration=duration or r3._CAPTION.get('duration') or 20
    at=max(0,t)/max(.1,duration)*sum(weights)
    before=0
    for i,w in enumerate(weights):
        if at<before+w or i==len(weights)-1:return i,max(0,min(.999,(at-before)/max(1,w)))
        before+=w
    return 0,0


def list_page(t,spec,items,start,count,page,pages,label):
    selected=list(items)[start:start+count]
    if spec.get('offseason'):
        from offseason_news import item_speech
        weights=[len(item_speech(h,b)) for h,b in selected]
    else:
        weights=[len((spec.get('speech') or {}).get(h) or f'{h.replace("｜","、")}。{b}。') for h,b in selected]
    i,fraction=timing(t,weights);head,body=selected[i]
    total=item_pages(spec,head,body);p=min(total-1,int(fraction*total))
    duration=r3._CAPTION.get('duration') or 20
    elapsed=(fraction*total-p)*duration*weights[i]/sum(weights)/total
    if count==1:elapsed=t  # a duo question+answer shares one running scene clock
    view = dict(spec, _market_art_elapsed=elapsed) if (spec.get('offseason') or {}).get('kind') == 'market' else spec
    im=item(t,view,label,head,body,p)
    im.info['asset_v4'].update(item=start+i,fraction=fraction,animation_time=elapsed)
    return im


def people(t,spec,rows,heading,label):
    rows=rows[:3]
    i,_=timing(t,[len(r.get('name','')+'が'+r.get('line',r.get('why',''))+'、') for r in rows])
    row=rows[i];line=row.get('line',row.get('why',''));pairs=stat_pairs(line)
    # 打者は安打/本塁打/打点、投手は奪三振→投球回。順位は新しく作らない。
    order=('奪三振','回','回3分の1','回3分の2') if '回' in line else ('安打','本塁打','打点')
    def positive(n):
        from fractions import Fraction
        return sum(Fraction(part) for part in str(n).split('+'))>0
    big=next(((n,u) for unit in order for n,u in pairs if u==unit and positive(n)),None)
    import notability_engine as ne
    team=next(((tid,name) for tid,name in ne.MLB_TEAM_NAME_JP.items() if name in line),None)
    im=c.canvas(t,label);c.text(im,L,262,heading,40,width=R-L)
    c.panel(im,(L,340,R,1134));c.text(im,L+24,378,row.get('name',''),64,width=R-L-48)
    if team:c.text(im,L+24,470,team[1],34,width=R-L-48,team_id=team[0])
    if big:c.stat(im,L+24,550,*big,size=236,width=R-L-48,unit_size=54)
    else:block(im,line,560,46)
    tiles=c.without_big(pairs,big)
    if tiles:c.stat_cards(im,tiles,930,height=170)
    im.info['v4_stat_tiles']=tiles
    im.info['v4_big_stat']=big
    im.info['asset_v4']={'kind':'people','name':row.get('name',''),'big':big,'stats':pairs,'row':i}
    return finish(im,t,spec,'出典: MLB公式（Stats API）')
