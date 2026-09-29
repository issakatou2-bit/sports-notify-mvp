"""Data-bound channel templates. Draft renderer, with no upload capability."""
import argparse, json, copy, math
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw
from ps_brand_components import TOKENS, THEME, text, font
from video_common import lift_color

ROOT=Path(__file__).resolve().parents[1]
LAYOUTS={'schedule':4,'facts':3,'bracket':2,'quote':1}

@lru_cache(maxsize=8)
def _prepared_presenter(data,crop,max_size):
    # Content bytes invalidate even same-size/same-timestamp replacements.
    # Reading remains; repeated decode/crop/resize is avoided. Never mutate it.
    with Image.open(BytesIO(data)) as source:
        sprite=source.convert('RGBA').crop(crop)
    sprite.thumbnail(max_size,Image.Resampling.LANCZOS)
    return sprite
def paginate(card):
    if card.get('layout') not in LAYOUTS:raise ValueError('Unsupported layout')
    if not card.get('date') or not card.get('source_url','').startswith('https://'):
        raise ValueError('Date and evidence URL are required')
    items=card.get('items',[])
    if not items:return []
    limit=LAYOUTS[card['layout']]
    pages=[]
    for start in range(0,len(items),limit):
        page=copy.deepcopy(card);page['items']=items[start:start+limit]
        page['page']=len(pages)+1;pages.append(page)
    return pages

def overlaps(a,b):
    return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]

def background(style='stadium',seconds=0):
    t=TOKENS[style];im=Image.new('RGB',(1080,1920),t['bg']);d=ImageDraw.Draw(im)
    drift=round(9*math.sin(seconds/6))
    for r in (340,430,520):d.arc((680-r+drift,140-r,680+r+drift,140+r),10,155,fill=t['line'],width=2)
    d.polygon([(540,1520),(800,1750),(540,1890),(280,1750)],outline=t['line'],width=2)
    return im

def render(card,presenters=None,style='stadium',layers=False):
    if presenters is None:presenters=THEME['presenter']['default']
    if presenters not in ('none','left','right','both'):raise ValueError('Unsupported presenter placement')
    t=TOKENS[style];im=Image.new('RGBA',(1080,1920),(0,0,0,0));d=ImageDraw.Draw(im);trace=[]
    def put(x,y,value,size=48,width=864,role='important',color=None,latin=False):
        box=text(d,(x,y),str(value),size,color or t['ink'],width=width,latin=latin,minimum=40 if role=='important' else 24)
        trace.append({'text':str(value),'box':list(box),'role':role})
        if role=='important' and (box[0]<72 or box[2]>936 or box[1]<210 or box[3]>1280):
            raise ValueError('Important text outside the reserved area: '+str(value))
    put(72,65,'コレスポ',44,role='brand')
    badge=card.get('sport','MLB')+' / '+card.get('label','')
    put(354,90,badge,26,role='brand',color=t['muted'],latin=badge.isascii())
    if card.get('card_index') is not None:
        index,total=card['card_index'],card.get('card_total')
        if type(index) is not int or type(total) is not int or not 1<=index<=total:
            raise ValueError('Invalid card progress')
        put(748,156,'カード',26,width=105,role='utility',color=t['muted'])
        put(865,145,f'{index}/{total}',40,width=125,role='utility',color=t['accent'],latin=True)
    if card.get('round_game'):
        put(72,151,card['round_game'],36,width=620,role='utility',color=t['accent'])
    for i,line in enumerate(card['headline'].split('\n')):
        if i>1:raise ValueError('Headline needs an editorial rewrite')
        marker=(card.get('headline_colors') or [None,None])[i]
        if marker:
            d.line((72,222+i*125,936,222+i*125),fill=marker,width=7)
            secondary=(card.get('headline_secondary_colors') or [None,None])[i]
            if secondary:d.line((72,228+i*125,936,228+i*125),fill=secondary,width=3)
        put(72,230+i*125,line,100)
    put(72,485,card.get('subhead',''),40,color=t['accent'])
    layout=card['layout']
    for i,item in enumerate(card['items']):
        if layout=='schedule':
            y=600+i*156;d.line((72,y-12,936,y-12),fill=t['line'],width=2)
            day, separator, time = item['when'].partition(' ')
            if separator:
                put(72,y,day,40,width=235,color=t['muted'],latin=True)
                put(72,y+55,time,50,width=235,color=t['accent'],latin=time.isascii())
            else:
                put(72,y,item['when'],42,width=235,color=t['accent'],latin=item['when'].isascii())
            for offset,side in ((0,'home'),(70,'away')):
                tint=lift_color(item.get(side+'_color'),fallback=t['ink'])
                d.line((329,y+offset+7,329,y+offset+48),fill=tint,width=6)
                if item.get(side+'_secondary'):d.line((338,y+offset+7,338,y+offset+48),fill=item[side+'_secondary'],width=3)
                put(350,y+offset,('vs ' if side=='away' else '')+item[side],48 if side=='home' else 46,width=575)
        elif layout=='facts':
            y=580+i*200;d.line((72,y-10,936,y-10),fill=t['line'],width=2)
            put(72,y,item['label'],40,color=t['muted'])
            if item.get('team_color'):
                d.line((72,y-10,936,y-10),fill=item['team_color'],width=5)
                if item.get('team_secondary'):d.line((72,y-5,936,y-5),fill=item['team_secondary'],width=2)
            put(72,y+57,item['value'],item.get('value_size',86),color=t['accent'])
        elif layout=='bracket':
            y=590+i*350;d.rounded_rectangle((72,y,560,y+260),radius=18,fill=t['panel'])
            for offset,side in ((22,'home'),(111,'away')):
                if item.get(side+'_color'):d.line((81,y+offset+8,81,y+offset+51),fill=lift_color(item[side+'_color']),width=5)
            put(98,y+22,item['home'],50,width=435)
            put(98,y+111,'vs '+item['away'],46,width=435)
            put(98,y+193,item['when'],32,width=435,role='utility',color=t['muted'])
            d.line((574,y+125,645,y+125),fill=t['accent'],width=5)
            d.polygon([(648,y+125),(632,y+115),(632,y+135)],fill=t['accent'])
            put(650,y+73,item['next'],46,width=286)
            put(655,y+144,'勝者と対戦',31,width=279,role='utility',color=t['accent'])
            put(655,y+195,'相手待ち',30,width=279,role='utility',color=t['muted'])
        else:
            words=item['quote'];lines=[];line=''
            for c in words:
                if d.textbbox((0,0),line+c,font=font(56))[2]>805:lines.append(line);line=c
                else:line+=c
            if line:lines.append(line)
            if len(lines)>7:raise ValueError('Quote needs an editorial excerpt')
            for row,line in enumerate(lines):put(100,610+row*85,line,56,width=805)
            put(100,1220,item['attribution'],28,role='utility',color=t['muted'])
    if len(card.get('affiliations',[]))>2:raise ValueError('Too many affiliation rows')
    for i,value in enumerate(card.get('affiliations',[])):
        put(72,1165+i*55,value,40,color=t['muted'])
    suffix=' / 日本時間' if card.get('production') else ' / 日本時間・デザイン確認用'
    put(72,1320,card['date']+suffix,28,role='utility',color=t['muted'])
    put(350,1490,'用語メモ',26,width=320,role='utility',color=t['accent'])
    put(350,1540,card.get('glossary',''),29,width=320,role='utility',color=t['muted'])
    put(350,1625,'出典：'+card.get('source_label','説明欄'),26,width=320,role='utility',color=t['muted'])
    avatars=[]
    framing=THEME['presenter']
    config=[('left','zundamon/C-cheer/base-black-brow-candidate.png'),('right','metan/3-black/base.png')]
    for side,path in config:
        if presenters not in (side,'both'):continue
        data=(ROOT/'assets/portraits/collespo-20260923'/path).read_bytes()
        sprite=_prepared_presenter(data,tuple(framing['crop']),tuple(framing['max_size']))
        x=framing['edge_px'] if side=='left' else im.width-framing['edge_px']-sprite.width
        y=im.height-sprite.height;box=(x,y,x+sprite.width,y+sprite.height)
        for row in trace:
            if row['role']=='important' and overlaps(box,row['box']):raise ValueError('Presenter covers content')
        im.alpha_composite(sprite,(x,y));avatars.append({'side':side,'box':box,'asset':path})
    result=background(style);result.paste(im,(0,0),im)
    manifest={'theme_version':THEME['version'],'card':card,'text':trace,'presenters':avatars,'public':False}
    return (result,manifest,im) if layers else (result,manifest)

def ps_cards(snapshot):
    ctx=snapshot['editorial']
    if ctx.get('stage')!='bracket_preview':raise ValueError('Four verified preview matchups required')
    common={'date':ctx['date_jst'],'source_url':ctx['source_url'],'source_label':'MLB公式日程','sport':'MLB','glossary':'WC＝ワイルドカード','label':'POSTSEASON'}
    schedule=dict(common,layout='schedule',headline='ワイルドカード\n初戦の日程',subhead='すべて日本時間',items=[{'when':m['first_game']['label'],'home':m['home']['name'],'away':m['away']['name']} for m in ctx['matchups']])
    out=paginate(schedule)
    for league,name in ((103,'ア・リーグ'),(104,'ナ・リーグ')):
        card=dict(common,layout='bracket',headline=name+'の\n対戦表',subhead='ワイルドカード → 地区シリーズ',items=[{'when':'初戦 '+m['first_game']['label'],'home':m['home']['name'],'away':m['away']['name'],'next':m['bye']['name']} for m in ctx['matchups'] if m['league']==league])
        out.extend(paginate(card))
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--material',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    cards=ps_cards(json.loads(args.material.read_text(encoding='utf-8')))
    manifests=[];sheet=Image.new('RGB',(1440,710),'#e1e3df');sd=ImageDraw.Draw(sheet)
    for i,placement in enumerate(('none','left','right','both')):
        im,manifest=render(cards[0],placement);im.save(args.out/f'schedule-{placement}.png')
        text(sd,(i*360+12,12),{'none':'キャラなし','left':'左下 / ずんだもん','right':'右下 / めたん','both':'両側 / 掛け合い'}[placement],24,'#243329',width=338)
        sheet.paste(im.resize((360,640),Image.Resampling.LANCZOS),(i*360,70));manifests.append(manifest)
    sheet.save(args.out/'presenter-comparison.png')
    for i,card in enumerate(cards[1:]):
        im,manifest=render(card,'both');im.save(args.out/f'bracket-{i}.png');manifests.append(manifest)
    (args.out/'template-manifest.json').write_text(json.dumps(manifests,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pages':len(cards),'preview_files':len(manifests),'template_version':THEME['version'],'posted':False}))
