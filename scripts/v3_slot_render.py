"""枠ごとの材料を、連勝回の既存部品で描く。台本と尺は扱わない。"""
import motion
import functools
from PIL import Image, ImageDraw, ImageEnhance
import review_render_v3 as r3
import calm_motion as calm


@functools.lru_cache(maxsize=4096)
def _supported(ch):
    f = r3.font(52)
    mask = f.getmask(ch)
    missing = f.getmask('\U0010ffff')
    return (mask.size, bytes(mask)) != (missing.size, bytes(missing))


def screen_text(text):
    """画面専用。未収録グリフと絵文字の制御文字を原稿の写しから外す。"""
    return ''.join(ch for ch in str(text) if ch not in '\u200d\ufe0e\ufe0f'
                   and not 0x1f3fb <= ord(ch) <= 0x1f3ff and (ch.isspace() or _supported(ch)))


def item(head, body, width, base, second, reply=False, height=900):
    return r3._item_card(head, body, width, base, second, quote_size=38 if reply else 52,
                         attribution_above=str(body).startswith('「'),
                         quote_height=height)


# カード本体の見た目を含むキャッシュへ一本化。
item.cache_clear = r3._item_card.cache_clear
item.cache_info = r3._item_card.cache_info


def outro(t,spec,exclude,credit='音声: VOICEVOX:四国めたん　データ: MLB Stats API'):
    renderer=getattr(r3,'outro',None)
    return renderer(t,spec,exclude,credit) if callable(renderer) else None


def heading(spec):
    probe=ImageDraw.Draw(Image.new('RGB',(8,8)))
    lines,size=r3._lines(probe,spec.get('heading') or spec.get('label') or '',52,r3.SAFE_RIGHT-r3.LEFT,2)
    return lines,size,250+len(lines)*(size+10)+44


def paginate(spec,rows,replies=None):
    """札の実寸で分割。大きすぎる引用も全文を次のページへ分ける。"""
    base,second,_=r3.colors(spec.get('team_id'))
    _,_,top=heading(spec);bottom=r3.CONTENT_BOTTOM;width=r3.SAFE_RIGHT-r3.LEFT
    pages=[[]];y=top
    def parts(head,body,reply):
        try:
            card=item(head,body,width,base,second,reply,bottom-top)
            if card.height<=bottom-top:
                return [(body,card)]
        except ValueError:
            pass
        quoted=body.startswith('「') and body.endswith('」')
        raw=body[1:-1] if quoted else body
        if len(raw)<2:
            raise ValueError('一文字の札も安全域に収まりません')
        pivot=len(raw)//2
        a,b=raw[:pivot],raw[pivot:]
        if quoted:
            a,b='「'+a+'」','「'+b+'」'
        return parts(head,a,reply)+parts(head,b,reply)
    for index,(head,body) in enumerate(rows):
        split=parts(str(head),str(body),bool((replies or [False]*len(rows))[index]))
        total=sum(len(b) for b,_ in split);offset=0
        for body,card in split:
            if pages[-1] and y+card.height>bottom:
                pages.append([]);y=top
            pages[-1].append({'card':card,'row':index,'fraction':(offset/total,(offset+len(body))/total),
                             'box':(r3.LEFT,y,r3.SAFE_RIGHT,y+card.height),'body':body})
            offset+=len(body);y+=card.height+28
    return pages


def check_pages(spec,rows,replies=None):
    _,_,top=heading(spec)
    return [box for page in paginate(spec,rows,replies) for cell in page
            if not (r3.LEFT<= (box:=cell['box'])[0]<box[2]<=r3.SAFE_RIGHT and top<=box[1]<box[3]<=r3.CONTENT_BOTTOM)]


def frame(t, spec, rows, label, source_text="", times=None, replies=None, ends=None, page_seconds=4, focus=None):
    """高さを超えたら次ページへ。引用は読む札を明るくする。"""
    base, second, _ = r3.colors(spec.get("team_id"))
    im = r3.background(t, spec.get("team_id"))
    d = ImageDraw.Draw(im)
    pages=paginate(spec,rows,replies)
    if not calm.enabled():
        focus=None
    elif focus is None and len(rows)>1 and not motion.DEPTH.get():
        if times is not None and ends is not None:
            timeline=[(a,b,i) for i,(a,b) in enumerate(zip(times,ends)) if b>a]
            focus=calm.weights(timeline,t,len(rows))
        else:
            duration=r3._CAPTION.get('duration') or 0
            markers=[head or body for head,body in rows]
            settle=r3.T_CARD0+(len(rows)-1)*r3.T_CARD_GAP+r3.SLIDE
            focus=calm.focus_for(t,r3._CAPTION['text'],duration,len(rows),markers=markers,settle=settle)
    if times is not None:
        selected=0
        for p,page in enumerate(pages):
            first=page[0] if page else None
            if first:
                i=first['row'];a,b=first['fraction']
                start=times[i]+a*((ends or times)[i]-times[i])
                if t>=start:
                    selected=p
    else:
        selected=min(int(max(0,t)/max(.1,page_seconds)),len(pages)-1)
    r3._header(d,label,f'{selected+1}/{len(pages)}' if len(pages)>1 else spec.get('page'),second)
    lines,size,top=heading(spec)
    for i, line in enumerate(lines):
        r3._text(d,(r3.LEFT, 250+i*(size+10)), line, font=r3.font(size), fill=r3.INK)
    # 札を大きくするぶんだけ、左に余白を取る（右は安全域の端から出さない）。focus が無ければ 0（今と同じ）。
    pad=(round((r3.SAFE_RIGHT-r3.LEFT)*(calm.TUNING['focus_scale']-1))+2) if focus else 0
    layer=Image.new('RGBA',(r3.SAFE_RIGHT-r3.LEFT+pad,r3.CONTENT_BOTTOM-top),(0,0,0,0))
    lifted=[]
    for j,cell in enumerate(pages[selected]):
        i=cell['row'];a,b=cell['fraction'];card=cell['card']
        if times is not None:
            end=(ends or [times[k]+4 for k in range(len(times))])[i]
            at=times[i]+a*(end-times[i]);finished=times[i]+b*(end-times[i])
            if t<at:
                continue
            if t>=finished:
                original=card
                card=ImageEnhance.Brightness(card).enhance(.72)
                card.info.update(original.info)
            progress=1
        else:
            progress=r3.back_out((t-selected*page_seconds-r3.T_CARD0-j*r3.T_CARD_GAP)/r3.SLIDE)
        y=cell['box'][1]-top
        if focus:
            own=focus[i] if i<len(focus) else 0.0
            others=max([w for k,w in enumerate(focus) if k!=i] or [0.0])
            card,gw,gh=calm.styled(card,own,others,anchor='right')
            # その場で大きくする: 右端はそのまま、上下は真ん中から。画面全体は動かさない。
            x=pad-gw;y=max(0,min(layer.height-card.height,y-gh//2))
            if own>0:
                # 上がっている札は最後に描く（となりの札の上に重なる）
                lifted.append((own,i,card,x,y,progress));continue
            r3._paste_card(layer,card,x,y,progress)
        else:
            r3._paste_card(layer,card,0,y,progress)
    focus_info=[]
    for own,i,card,x,y,progress in sorted(lifted,key=lambda e:e[0]):
        before=len(layer.info.get('v3_layout',[]))
        r3._paste_card(layer,card,x,y,progress)
        added=layer.info.get('v3_layout',[])[before:]
        box=next((e['box'] for e in added if e['role']=='card'),None)
        focus_info.append({'row':i,'weight':round(own,3),
                           'box':[box[0]+r3.LEFT-pad,box[1]+top,box[2]+r3.LEFT-pad,box[3]+top] if box else None,
                           'text':[e['text'] for e in added if e['role']!='card']})
    im.paste(layer,(r3.LEFT-pad,top),layer)
    for entry in layer.info.get('v3_layout',[]):
        a,b,c,e=entry['box']
        r3.record_box(im,entry['role'],(a+r3.LEFT-pad,b+top,c+r3.LEFT-pad,e+top),entry['text'])
        saved=im.info['v3_layout'][-1]
        for key in ('team_id','v4_font','v4_color'):
            if key in entry:
                saved[key]=entry[key]
    for badge in layer.info.get('v4_badges',[]):
        a,b,c,e=badge['box']
        moved=dict(badge)
        moved['box']=[a+r3.LEFT-pad,b+top,c+r3.LEFT-pad,e+top]
        im.info.setdefault('v4_badges',[]).append(moved)
    if focus:
        im.info['v3_focus']=focus_info
    im.info['v3_card_contents']=layer.info.get('v3_card_contents',[])
    import render_timeline
    render_timeline.scene(im, dict(page=selected))
    v3 = spec.get('v3') or {}
    r3.ticker(im, t, v3.get('ticker'), once=v3.get('ticker_once',False))
    r3.source(d, source_text, second)
    r3.presenter(im,t)
    return im


@motion.slot('ranking')
def ranking(t,spec,rows,source_text):
    if r3.LOOK == 'v4':
        from short_v4_cards import ranking as draw
        return draw(t,spec,rows,source_text)
    im=r3.background(t,spec.get('team_id'));d=ImageDraw.Draw(im)
    base,second,_=r3.colors(spec.get('team_id'))
    r3._header(d,'日本人選手の成績',None,second)
    r3._text(d,(r3.LEFT,250),'今日の勝利貢献順位',font=r3.font(48),fill=r3.INK)
    for i,row in enumerate(rows[:5]):
        y=350+i*150
        r3.record_box(im,'card',(r3.LEFT,y,r3.SAFE_RIGHT,y+128))
        d.rounded_rectangle((r3.LEFT,y,r3.SAFE_RIGHT,y+128),radius=20,fill=base,outline=second,width=2)
        r3._text(d,(r3.LEFT+20,y+38),str(row['rank']),font=r3.num_font(48),fill=r3.GOLD)
        r3._text(d,(r3.LEFT+82,y+40),row['name'],font=r3.font(36),fill=r3.INK)
        team_base,team_second,_=r3.colors(row.get('team_id'))
        r3._badge(d,r3.LEFT+355,y+26,row['abbr'],team_base,team_second)
        lines,size=r3._lines(d,row['score'],40,290,2)
        for j,line in enumerate(lines):
            r3._text(d,(r3.LEFT+530,y+20+j*(size+6)),line,font=r3.font(size),fill=r3.GOLD)
    r3.ticker(im,t,(spec.get('v3') or {}).get('ticker'))
    r3.source(d,source_text,second);r3.presenter(im,t)
    return im


@motion.slot('schedule')
def schedule(t,spec,rows,label,source_text):
    if r3.LOOK == 'v4':
        from short_v4_cards import schedule as draw
        return draw(t,spec,rows,label,source_text)
    if len(rows)>4:
        raise ValueError('PS全試合一覧は4行までです')
    im=r3.background(t,None);d=ImageDraw.Draw(im)
    base,second,_=r3.colors(None)
    r3._header(d,label,None,second)
    r3._text(d,(r3.LEFT,250),'明日の全試合の一覧',font=r3.font(48),fill=r3.INK)
    for i,row in enumerate(rows):
        y=340+i*180
        r3.record_box(im,'card',(r3.LEFT,y,r3.SAFE_RIGHT,y+156))
        d.rounded_rectangle((r3.LEFT,y,r3.SAFE_RIGHT,y+156),radius=20,fill=base,outline=second,width=2)
        clock=row['when'].split()[-1]
        r3._text(d,(r3.LEFT+24,y+24),clock,font=r3.num_font(48),fill=r3.GOLD)
        pair=row['home']+'対'+row['away']
        lines,size=r3._lines(d,pair,38,620,1)
        r3._text(d,(r3.LEFT+210,y+24),lines[0],font=r3.font(size),fill=r3.INK)
        score=(f'{row["home"]} {row["home_wins"]}勝　{row["away"]} {row["away_wins"]}勝'
               if 'home_wins' in row and 'away_wins' in row else 'シリーズ勝敗は確認中')
        lines,size=r3._lines(d,score,32,820,1)
        r3._text(d,(r3.LEFT+24,y+92),lines[0],font=r3.font(size),fill=second)
    v3=spec.get('v3') or {}
    r3.ticker(im,t,v3.get('ticker'),once=v3.get('ticker_once',False))
    r3.source(d,source_text,second);r3.presenter(im,t)
    return im


def cues(rows, times=None):
    result = r3.cues("list", {}, rows, 0, len(rows))
    if times is not None:
        # notifyだけ残るので、削除された通常行の時刻を詰めて割り当てない。
        timing = {r3.T_CARD0 + i * r3.T_CARD_GAP: at for i, at in enumerate(times)}
        result = [result[0]] + [(timing.get(cue[0], cue[0]), *cue[1:]) for cue in result[1:]]
    return result
