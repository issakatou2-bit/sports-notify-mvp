"""右下の聞き手/解説者と、話者色の3行字幕。素材の差し替え先は一か所。"""
import functools
import math
from PIL import Image, ImageDraw, ImageEnhance
import review_render_v3 as r3

# New approved design can replace this one directory, including local expression files.
ZUNDAMON_DIR = r3.ROOT / r3.PORTRAITS / 'zundamon/C-black'
GREEN = (166, 212, 120)
WIDTH, HEIGHT = 170, 220
GAP = 0


def geometry():
    mx = r3.SAFE_RIGHT - WIDTH
    zx = mx - WIDTH - GAP
    return dict(metan=(mx, 1260, r3.SAFE_RIGHT, 1480),
                zundamon=(zx, 1260, zx+WIDTH, 1480),
                caption=(r3.LEFT-8, r3.CAPTION_TOP, zx-16, r3.CAPTION_BOTTOM))


@functools.lru_cache(maxsize=32)
def portrait(who, face, dark=False):
    directory = ZUNDAMON_DIR if who == 'zundamon' else r3.ROOT / r3.PORTRAITS / 'metan/3-black'
    path = directory / (face+'.png')
    if not path.exists():
        path = directory / 'base.png'
    art = Image.open(path).convert('RGBA').crop((185,0,805,800))
    art.thumbnail((WIDTH,HEIGHT))
    if dark:
        rgb = ImageEnhance.Brightness(art.convert('RGB')).enhance(.70)
        rgb.putalpha(art.getchannel('A'))
        art = rgb
    return art


def zunda_face(line):
    if '？' in line or '?' in line:return 'question'
    if any(w in line for w in ('記録','初めて','自己最多','！')):return 'surprise'
    if any(w in line for w in ('勝','本塁打','好投')):return 'smile'
    return 'base'


def presenter(im, t):
    ctx = r3._CAPTION
    clock = r3._PROGRAM_CLOCK[0]
    elapsed = clock-ctx['start'] if clock is not None else t
    line = r3.current_sentence(elapsed,ctx['text'],ctx['duration'])
    who = 'zundamon' if ctx.get('speaker') == 3 else 'metan'
    speaking = bool(line) and elapsed < max(.1,ctx['duration']-.25)
    mouth = speaking and int(elapsed*r3.MOUTH_RATE)%2 == 1
    boxes = geometry()
    records=[]
    for person in ('zundamon','metan'):
        active = person == who
        mood = zunda_face(line) if person=='zundamon' else r3.face_for(line,elapsed,ctx['duration'])
        if mood=='talk':mood='base'
        face = ('talk' if mouth else mood) if active else 'base'
        art = portrait(person,face,not active)
        left,_,right,bottom=boxes[person]
        bob=round(3*math.sin(elapsed*math.pi*2/1.2)) if active and speaking else 0
        x=right-art.width;y=bottom-art.height-3+bob
        im.paste(art,(x,y),art)
        records.append(dict(who=person,active=active,face=face,box=[x,y,x+art.width,y+art.height]))
    im.info['duo_portraits']=records
    caption(im,t)
    r3.progress(ImageDraw.Draw(im))


def caption(im,t):
    ctx=r3._CAPTION
    if not ctx['text'] or ctx.get('hide_caption'):return
    clock=r3._PROGRAM_CLOCK[0]
    elapsed=clock-ctx['start'] if clock is not None else t
    # Split at glyphs into measured <=3-line pages; never silently slice long text.
    size=48;box=geometry()['caption'];width=box[2]-box[0]-56
    d=ImageDraw.Draw(im)
    rows=r3._caption_lines(d,ctx['text'],size,width)
    pages=[rows[i:i+3] for i in range(0,len(rows),3)]
    weights=[sum(len(run) for row in page for run,_ in row) for page in pages]
    at=max(0,elapsed)/max(.1,ctx['duration'])*sum(weights);end=0;page=pages[-1]
    for p,w in zip(pages,weights):
        end+=w
        if at<end:page=p;break
    color,name=(GREEN,'ずんだもん') if ctx.get('speaker')==3 else (r3.METAN_PINK,'四国めたん')
    layer=Image.new('RGBA',im.size);ld=ImageDraw.Draw(layer)
    ld.rounded_rectangle(box,radius=22,fill=(11,20,32,240))
    ld.rectangle((box[0],box[1]+18,box[0]+10,box[3]-18),fill=color)
    merged=im.convert('RGBA');merged.alpha_composite(layer);im.paste(merged.convert('RGB'))
    d=ImageDraw.Draw(im);f=r3.font(24);w=f.getlength(name)+32
    d.rounded_rectangle((box[0]+24,box[1]-22,box[0]+24+w,box[1]+22),radius=8,fill=color)
    d.text((box[0]+40,box[1]-17),name,font=f,fill=r3.DARK_INK)
    for i,row in enumerate(page):
        x=box[0]+28;base=box[1]+62+i*68
        for text,numeric in row:
            fnt=r3.num_font(round(size*1.18)) if numeric else r3.font(size)
            d.text((x,base),text,font=fnt,fill=r3.GOLD if numeric else r3.INK,anchor='ls')
            r3.record_box(im,'caption',d.textbbox((x,base),text,font=fnt,anchor='ls'),text)
            x+=fnt.getlength(text)
    r3.record_box(im,'caption',box,ctx['text'])
    im.info['duo_caption']=dict(speaker=ctx.get('speaker'),font_size=size,rows=len(page),box=box)
