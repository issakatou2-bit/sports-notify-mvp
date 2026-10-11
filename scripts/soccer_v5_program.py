"""結果/現地の声の材料をv5の板へ渡す。原稿と選手の数字は既存のまま。"""
import re
from PIL import Image, ImageDraw
import soccer_v5_cards as c
import review_render_v3 as r3

L,R=c.L,c.R
TAGLINE='欧州の日本人選手とMLBを、毎日数字で'


def results_frame(t,seg,data,clubs,spec,credit):
    import soccer_results as results
    if seg['kind']=='outro':return c.outro(t,spec,'soccer_results',credit,TAGLINE)
    if seg['kind']=='roster':
        rows=[p for p in data['players'] if p['status']!='none'][:seg['meta']['count']]
        display=[dict(name=p['name'],club=p['club'],values=[(p[k],u) for k,u in (('goals','得点'),('assists','A')) if p.get(k) is not None],note='') for p in rows]
        im=c.jp_roster(t,dict(spec,title='日本人選手の結果　A＝アシスト',rows=display),clubs)
        # 出場区分は数字と重ならない名前の行に。出場なしは名前だけ・読み上げない。
        for row,p in zip([e for e in im.info['v3_layout'] if e['role']=='card'],rows):
            y=row['box'][1];c.text(im,L+350,y+66,results.STATUS[p['status']],22,c.MUTED,width=200)
        absent=seg['meta'].get('absent') or []
        if absent:c.text(im,L,1125,'出場なし：'+'・'.join(absent[:4]),22,c.MUTED,width=R-L)
        im.info['soccer_roster']=rows
        return im
    game=next(g for g in data['games'] if g['id']==seg['meta']['event_id'])
    if seg['kind']=='intro':
        lead=next(p for p in data['players'] if p['status']!='none')
        value=lead['goals'] if lead.get('goals') else lead['assists'] if lead.get('assists') else None
        im=c.canvas(t,clubs,spec['label'])
        c.heading(im,lead['name']+results.action(lead))
        c.club_name(im,L+20,348,clubs[lead['club']],40,width=R-L-40)
        if value is not None:c.stat(im,(L,428,R,780),value,'得点' if lead.get('goals') else 'アシスト')
        else:
            c.panel(im,(L,466,R,694));c.text(im,L+72,540,results.STATUS[lead['status']],86,width=R-L-144)
        for side,y in (('home',816),('away',938)):
            club=clubs[game[side]['name_jp']];ink=c.colors(club)[2]
            c.scarf(im,(L+14,y,R,y+110),club,label=False,fringe=True)
            c.club_name(im,L+50,y+36,club,40,ink,width=R-L-230)
            c.text(im,R-138,y+16,game['score'][side],92,ink,number=True,width=90)
        return c.finish(im,t,spec)
    goals=seg['meta'].get('goals',game['goals'])
    tints=tuple(c.colors(clubs[game[s]['name_jp']])[0] for s in ('home','away'))
    im=c.canvas(t,clubs,spec['label'],tints);im.info['v5_tints']=tints
    c.heading(im,game['league_jp']+'　試合終了')
    for side,y in (('home',344),('away',464)):
        club=clubs[game[side]['name_jp']]
        ink=c.colors(club)[2]
        c.scarf(im,(L+14,y,R,y+106),club,label=False,fringe=True)
        c.club_name(im,L+50,y+32,club,40,ink,width=R-L-230)
        c.text(im,R-138,y+12,game['score'][side],90,ink,width=90,number=True)
    mid=816;left,right=L+60,R-60;d=ImageDraw.Draw(im)
    c.panel(im,(L,616,R,1118))
    d.line((left,mid,right,mid),fill=c.MUTED,width=3)
    half=(left+right)/2;d.line((half,mid-18,half,mid+18),fill=c.MUTED,width=2)
    c.text(im,left,mid+24,'前半',24,c.MUTED,width=90);c.text(im,half+18,mid+24,'後半',24,c.MUTED,width=90)
    groups={side:[g for g in goals if g['side']==side] for side in ('home','away')}
    reveal={id(g):i for i,g in enumerate(sorted(goals,key=lambda g:(not bool(g['japanese_goal'] or g['japanese_assists']),int(g['minute'].split('+')[0]))))}
    for side,rows in groups.items():
        # 近接した得点は折り返した小さなレーンへ。材料は最大4件/側に改ページ済み。
        span=(right-left)/max(1,len(rows));width=min(210,span-12)
        for index,g in enumerate(sorted(rows,key=lambda g:int(g['minute'].split('+')[0]))):
            minute=int(g['minute'].split('+')[0]);x=left+(right-left)*min(minute,90)/90
            lx=left+index*span+(span-width)/2
            y=mid-116 if side=='home' else mid+84
            color=c.LIME if g['japanese_goal'] or g['japanese_assists'] else c.CHALK
            lay=Image.new('RGBA',im.size,(0,0,0,0));lay.info['soccer_club_names']=im.info['soccer_club_names']
            md=ImageDraw.Draw(lay)
            # 点は実際の分の位置、注記は左から同じ順。密集した得点も4列まで重ならない。
            md.line((x,mid,x,mid-26 if side=='home' else mid+58),fill=color,width=2)
            md.line((x,mid-26 if side=='home' else mid+58,lx+width/2,y+70 if side=='home' else y-8),fill=color,width=2)
            md.ellipse((x-6,mid-6,x+6,mid+6),fill=color)
            b=c.text(lay,lx,y,g['minute'],34,color,number=True,width=width-60)
            c.text(lay,b[2]+6,y+8,'分'+(' OG' if g['own_goal'] else ''),22,color,width=60)
            if g['japanese_goal']:c.text(lay,lx,y+42,g['scorer'],26,color,width=width)
            elif g['japanese_assists']:c.text(lay,lx,y+42,'・'.join(g['japanese_assists'])+' A',26,color,width=width)
            else:
                club=clubs[game[side]['name_jp']]
                c.scarf(lay,(lx,y+42,lx+min(width,150),y+80),club)
            # 1.25秒から0.25秒ごとに落とす。記録は最終配置、動く画素は中身の窓内。
            start=1.25+reveal[id(g)]*.25
            if t>=start:
                dy=round(-18*(1-r3.ease_out((t-start)/.2)))
                im.paste(lay,(0,dy),lay)
            for key in ('v3_layout','v4_badges','v5_contrasts'):
                im.info.setdefault(key,[]).extend(lay.info.get(key,[]))
    if not goals:c.text(im,L+80,740,'得点なし' if game['goals_complete'] else '得点経過は未取得',42,width=R-L-160)
    c.text(im,L+44,1080,'ライム＝日本人選手の得点・アシスト　OG＝オウンゴール',22,c.MUTED,width=R-L-88)
    im.info['soccer_goals']=goals
    return c.finish(im,t,spec)


def quote_lines(value,size,width,clubs):
    out=[];line=[];used=0
    names=sorted((n for n in clubs if len(n)>=3),key=len,reverse=True)
    lookup={n.casefold():club for n,club in clubs.items()}
    parts=re.split('('+'|'.join(re.escape(n) for n in names)+')',value,flags=re.I) if names else [value]
    for run in parts:
        if not run:continue
        club=lookup.get(run.casefold())
        tokens=[run] if club else re.findall(r'[A-Za-zÀ-ž0-9]+|.',run)
        for token in tokens:
            runs,span,b=c.measure(token,size)
            if club:span+=c.tag_width(club,b[3]-b[1])+12
            if span>width:raise ValueError('引用の語が行幅に入りません')
            if token=='\n' or (line and used+span>width):
                out.append(line);line=[];used=0
                if token=='\n':continue
            line.append((token,club));used+=span
    if line:out.append(line)
    return out


def quote_layout(v,clubs,reply=False):
    size=36 if reply else 52;raw_size=24 if reply else 26
    padding=86
    for _ in range(10):
        ja=quote_lines(v['ja'],size,R-L-padding*2,clubs)
        raw=quote_lines(v.get('original') or v['title'],raw_size,R-L-padding*2,clubs)
        h=62+len(ja)*(size+12)+40+len(raw)*(raw_size+12)+24+(48 if not reply else 0)
        required=max(86,round(h*c.SLANT)+18)
        if required<=padding:return dict(ja=ja,raw=raw,size=size,raw_size=raw_size,height=h,padding=padding)
        padding=required
    raise ValueError('引用が斜めの板に入りません')


def quote_fits(v,clubs):
    try:return quote_layout(v,clubs)['height']+sum(quote_layout(r,clubs,True)['height']+16 for r in v.get('reply_ja',[]))<=c.BOTTOM-342
    except ValueError:return False


def _quote_rows(im,x,y,rows,size,color):
    for row in rows:
        used=x
        row_top=c.measure(''.join(token for token,club in row),size)[2][1]
        for token,club in row:
            top=y+c.measure(token,size)[2][1]-row_top
            if club:used=c.club_name(im,used,top,club,size,color,display_name=token)
            else:
                box=c.text(im,used,top,token,size,color,role='text')
                used+=c.measure(token,size)[1]
        y+=size+12
    return y


def _quote(im,y,voice,clubs,reply=False,reading=True):
    lay=quote_layout(voice,clubs,reply);height=lay['height']
    before_panel=len(im.info['v3_layout'])
    c.panel(im,(L,y,R,y+height),c.CHALK if reading else (174,193,181))
    quote_x=L+round(height*c.SLANT)+18
    c.text(im,quote_x,y+16,'“',64,c.DARK,width=52,number=True,role='badge')
    if reply:
        d=ImageDraw.Draw(im);d.line((quote_x+58,y+22,quote_x+58,y+37,quote_x+71,y+37),fill=c.DARK,width=2)
        d.polygon([(quote_x+66,y+32),(quote_x+75,y+37),(quote_x+66,y+42)],fill=c.DARK)
    label_x=quote_x+(84 if reply else 58)
    c.text(im,label_x,y+20,'返信（翻訳）' if reply else '現地の声（翻訳）',24,c.DARK,width=R-label_x-36)
    x=L+lay['padding']
    pos=_quote_rows(im,x,y+62,lay['ja'],lay['size'],c.DARK)
    c.text(im,x,pos+4,'原文',22,(62,80,66),width=100)
    before=len(im.info['v3_layout'])
    _quote_rows(im,x,pos+36,lay['raw'],lay['raw_size'],c.DARK)
    actual=''.join(e['text'] for e in im.info['v3_layout'][before:] if e['role']=='text')
    wanted=c.screen_text(voice.get('original') or voice['title'])
    if ''.join(actual.split())!=''.join(wanted.split()):raise ValueError('表示する原文が元の文と違います')
    im.info.setdefault('v5_quote_originals',[]).append(dict(original=wanted,drawn=actual))
    if not reply:
        values=[voice['tone']]
        if voice.get('likes') is not None:values.append(f"高評価 {voice['likes']}")
        if voice.get('replies') is not None:values.append(f"返信 {voice['replies']}")
        x=L+72
        for value in values:
            f,sz,w,b=c.fit(value,22,210);c.panel(im,(x,y+height-52,x+w+36,y+height-14),c.BOARD)
            c.text(im,x+18,y+height-43,value,sz,c.CHALK,width=w+2);x+=w+52
    im.info.setdefault('v5_quote_panels',[]).append(dict(box=[L,y,R,y+height],contents=im.info['v3_layout'][before_panel+1:]))
    return y+height


def voices_frame(t,seg,data,clubs,duration,spec):
    import soccer_voices as voices
    if data.get('sample_fictional'):
        spec=dict(spec,source='見本（架空・実在の投稿ではありません）')
    if seg['kind']=='outro':
        im=c.outro(t,spec,'soccer_voices','音声: VOICEVOX:四国めたん　'+spec['source'],TAGLINE)
        im.info['soccer_outro_elapsed']=t;return im
    im=c.canvas(t,clubs,voices.LABEL)
    if seg['kind']=='intro':
        c.heading(im,'現地ファンの反応')
        c.text(im,L+20,376,data['star'],78,width=R-L-40,weight=900)
        c.panel(im,(L,496,R,740))
        c.text(im,L+70,540,'何と言ったか',74,c.CHALK,width=R-L-140)
        c.text(im,L+66,658,data['video']['competition']+'　公式ハイライト',30,c.MUTED,width=R-L-132)
        for name,y in zip(data['video']['clubs'],(818,972)):
            c.panel(im,(L,y,R,y+106));c.club_name(im,L+38,y+32,clubs[name],44,width=R-L-76)
    else:
        voice=data['voices'][seg['meta']['index']]
        if not quote_fits(voice,clubs):raise ValueError('引用と返信が同じ安全域に入りません')
        players=voices.players_in_match(data['video'],voices.load_names())
        named=[p for p in players if p['name_jp'] in voice['jp_players']]
        if named:
            p=named[0];c.club_name(im,L,266,clubs[p['team_en']],28,suffix='　'+p['name_jp'],width=R-L)
        spoken=voices.spoken_names(voice['ja'],players)
        total=len(spoken)+sum(len('。返信は、'+voices.spoken_names(r['ja'],players)) for r in voice['reply_ja'])
        reply_at=len(spoken)/max(1,total)*duration
        total_height=quote_layout(voice,clubs)['height']+sum(quote_layout(r,clubs,True)['height']+16 for r in voice['reply_ja'])
        top=max(342,round((320+c.BOTTOM-total_height)/2))
        y=_quote(im,top,voice,clubs,reading=not voice['reply_ja'] or t<reply_at);shown=[voice['ja']]
        for reply in voice['reply_ja']:
            y=_quote(im,y+16,reply,clubs,reply=True,reading=t>=reply_at);shown.append(reply['ja'])
        im.info.update(v4_quote=True,soccer_shown_quotes=shown,soccer_reading='reply' if voice['reply_ja'] and t>=reply_at else 'parent',soccer_voice_pairs=[dict(said=voice['ja'],original=voice['title'])])
    if data.get('sample_fictional'):
        # 締めも含め出典に全画面表示される。架空のクラブ色は推測で足さない。
        spec=dict(spec,source='見本（架空・実在の投稿ではありません）')
    return c.finish(im,t,spec)
