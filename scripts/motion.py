"""Opt-in channel motion. Timings are seconds; coordinates are output pixels.

No speech is inferred from a rank or elapsed fraction. A cue names a row and
the exact caption/voice segment that owns it. Missing evidence means overview.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from contextvars import ContextVar
from functools import lru_cache, wraps
import inspect
import math
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
import calm_motion as calm

ROOT = Path(__file__).resolve().parents[1]
# One tuning table, shared by every slot. No per-slot speed overrides.
SETTINGS = calm.TUNING
VIEW = (72, 236, 940, 1140)
SPEECH = {}  # exact text -> measured waveform duration, scoped by writer
HIGHLIGHTS = []
DEPTH = ContextVar('motion_depth', default=0)


def enabled():
    return os.environ.get('COLLESPO_MOTION') == 'on'


def ease(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


@dataclass(frozen=True)
class Cue:
    key: str
    start: float
    end: float
    text: str


def cue_for(row, text, duration, start=0):
    """Only explicit/unique anchors can own a voice segment."""
    if row.get('anchor') and row['anchor'] in text:
        return Cue(str(row['key']), start, start + SPEECH.get(text, duration), text)
    return None


def validate_cues(rows, cues, duration):
    keys = [str(r['key']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('動きの項目IDが重複しています')
    previous = 0
    for cue in cues:
        row = next((r for r in rows if str(r['key']) == cue.key), None)
        if (not row or not row.get('anchor') or row['anchor'] not in cue.text
                or not 0 <= cue.start < cue.end <= duration + .001
                or cue.start < previous):
            raise ValueError('読み上げ区間と寄る項目が一致しません')
        previous = cue.end


@lru_cache(maxsize=64)
def font(size):
    from PIL import ImageFont
    face = ImageFont.truetype(str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf'), size)
    face.set_variation_by_axes([700])
    return face


def wrap(text, size, width):
    """Keep every glyph. Fit failures stop rather than silently truncate."""
    import caption_breaks
    f = font(size)
    return caption_breaks.wrap(str(text), f.getlength, width)


def excerpt(text, fits):
    """一覧の引用だけを省略。収まる文末、読点、文字境界の順で選ぶ。"""
    low, high = 0, len(text)
    while low < high:
        middle = (low+high+1)//2
        if fits(text[:middle].rstrip()+'…'):
            low = middle
        else:
            high = middle-1
    if not low:
        return '…'
    prefix = text[:low].rstrip()
    for marks in (r'[。！？!?]', r'[、，,；;]'):
        endings = [m for m in re.finditer(marks, prefix) if m.end() >= min(12, low//2)]
        if endings:
            prefix = prefix[:endings[-1].end()]
            break
    return prefix.rstrip()+'…'


@lru_cache(maxsize=32)
def _list_tiles(payload, heading, soccer, quote_keys=()):
    scale = SETTINGS['scale']; w = VIEW[2]-VIEW[0]; h = VIEW[3]-VIEW[1]
    ink = (242, 243, 228); accent = (192, 224, 93) if soccer else (242, 207, 135)
    bg = (23, 53, 43) if soccer else (28, 41, 51)
    canvas = Image.new('RGB', (w*scale, h*scale), bg)
    d = ImageDraw.Draw(canvas)
    for y in range(0, h*scale, 48*scale):
        d.line((0, y, w*scale, y-180*scale), fill=(34, 59, 60), width=2*scale)
    top = 145 if len(payload)<=3 else 110
    step = min(210, (h-top-140)//len(payload))
    if step < 80:
        raise ValueError('一覧が安全域に入りません。項目を次の画面へ分けてください')
    tiles = []; boxes = []; texts = []
    for key, title, body, metric in payload:
        index = len(tiles); box = (80, top+index*step, w-80, top+(index+1)*step-(6 if len(payload)>=6 else 12))
        tile = Image.new('RGB', ((box[2]-box[0])*scale, (box[3]-box[1])*scale), bg)
        draw = ImageDraw.Draw(tile)
        draw.rounded_rectangle((0, 0, tile.width-1, tile.height-1), radius=16*scale,
                               fill=(40, 63, 62) if soccer else (43, 57, 69), outline=accent, width=2*scale)
        original_title = title
        suffix = '　'.join(v for v in (body,metric) if v)
        compact=len(payload)>3;dense=len(payload)>=6
        if dense:
            title='　'.join(v for v in (title,body,metric) if v);body='';metric=''
        elif compact:
            body='　'.join(v for v in (body,metric) if v);metric=''
        size = 44 if not compact else 34
        for _ in range(8):
            title_lines = wrap(title, size*scale, tile.width-48*scale)
            body_lines = wrap(body, max(28, size-8)*scale, tile.width-48*scale) if body else []
            required = ((12+len(title_lines)*size+max(0,len(title_lines)-1)*6) if dense else
                        (16 if compact else 32) + len(title_lines)*(size+8) + len(body_lines)*(max(28,size-8)+6) + (40 if metric else 0))
            if required <= box[3]-box[1]:break
            size -= 2
        if size<28 or required>box[3]-box[1]:
            if key not in quote_keys:
                raise ValueError('一覧の文字が読める大きさで収まりません: '+title)
            size = 28
            def fits(value):
                lines = wrap(value, size*scale, tile.width-48*scale)
                body_count = len(wrap(body, 28*scale, tile.width-48*scale)) if body else 0
                height = ((12+len(lines)*size+max(0,len(lines)-1)*6) if dense else
                          (16 if compact else 32)+len(lines)*(size+8)+body_count*34+(40 if metric else 0))
                return height <= box[3]-box[1]
            if dense and suffix:
                title = excerpt(original_title, lambda value: fits(value+'　'+suffix))+'　'+suffix
            else:
                title = excerpt(title, fits)
            if not fits(title):
                raise ValueError('引用以外の一覧情報が枠に収まりません: '+body)
            title_lines = wrap(title, size*scale, tile.width-48*scale)
            body_lines = wrap(body, 28*scale, tile.width-48*scale) if body else []
        y = 6 if compact else 14
        for value, lines, sz, color in ((title,title_lines,size,ink), (body,body_lines,max(28,size-8),ink)):
            for line in lines:
                draw.text((24*scale,y*scale),line,font=font(sz*scale),fill=color)
                b=draw.textbbox((24*scale,y*scale),line,font=font(sz*scale))
                texts.append(dict(key=key,box=tuple(v/scale + (box[0] if i%2==0 else box[1]) for i,v in enumerate(b)),text=line,size=sz))
                y += sz+(6 if dense else 8)
        number_box = None
        if metric:
            y = box[3]-box[1]-46
            draw.text((24*scale,y*scale),metric,font=font(28*scale),fill=accent)
            b=draw.textbbox((24*scale,y*scale),metric,font=font(28*scale))
            number_box=tuple(v/scale for v in b)
            texts.append(dict(key=key,box=tuple(v/scale + (box[0] if i%2==0 else box[1]) for i,v in enumerate(b)),text=metric,size=28))
        tiles.append((tile, number_box));boxes.append(box)
    return canvas, tiles, boxes, texts


def pulse(tile, box, elapsed):
    if not SETTINGS['pulse'] and not SETTINGS['light']:return tile
    if box is None or not 0 <= elapsed <= SETTINGS['pulse_seconds']:return tile
    s=SETTINGS['scale'];x0,y0,x1,y1=[round(v*s) for v in box]
    area=tile.crop((x0,y0,x1,y1));phase=elapsed/SETTINGS['pulse_seconds']
    factor=1+SETTINGS['pulse']*math.sin(math.pi*phase)
    large=area.resize((max(1,round(area.width*factor)),max(1,round(area.height*factor))),Image.Resampling.LANCZOS)
    out=tile.copy();out.paste(large,(x0-(large.width-area.width)//2,y0-(large.height-area.height)//2))
    # One sweep, clipped to the same emphasized numeric rectangle.
    mask=Image.new('L',area.size);d=ImageDraw.Draw(mask);x=round(phase*(area.width+80*s))-80*s
    d.polygon([(x,0),(x+24*s,0),(x+64*s,area.height),(x+40*s,area.height)],fill=round(255*SETTINGS['light']))
    out.paste(Image.composite(Image.new('RGB',area.size,(255,248,211)),out.crop((x0,y0,x1,y1)),mask),(x0,y0))
    return out


def list_frame(im, t, rows, heading, cues=(), duration=8, entrance=True, soccer=False):
    if not enabled() or len(rows)<2:return im
    validate_cues(rows,cues,duration)
    payload=tuple((str(r['key']),str(r['title']),str(r.get('body') or ''),str(r.get('metric') or '')) for r in rows)
    quote_keys=tuple(str(r['key']) for r in rows if r.get('quote'))
    base,tiles,boxes,texts=_list_tiles(payload,heading,soccer,quote_keys)
    s=SETTINGS['scale'];canvas=background(base,t)
    timeline=[(max(c.start,SETTINGS['overview']),c.end,
               next(i for i,r in enumerate(rows) if str(r['key'])==c.key)) for c in cues]
    weights=calm.weights(timeline,t,len(rows))
    active=next((i for i,v in enumerate(weights) if v>0),None)
    transformed=[]
    w=VIEW[2]-VIEW[0];h=VIEW[3]-VIEW[1]
    for i,((tile,num_box),box) in enumerate(zip(tiles,boxes)):
        at=i*SETTINGS['stagger'] if entrance else -SETTINGS['pulse_seconds']
        progress=ease((t-at)/SETTINGS['entrance']) if entrance else 1
        row=pulse(tile,num_box,t-at).convert('RGBA')
        row,gw,gh=calm.styled(row,weights[i],max(weights,default=0))
        brightness=.86+.14*progress
        if brightness<1:row=ImageEnhance.Brightness(row).enhance(brightness)
        dy=round(SETTINGS['rise']*(1-progress)*s)
        x=round(box[0]*s)-gw//2;y=round(box[1]*s)-gh//2+dy
        canvas.paste(row,(x,y),row)
        scale=1+(SETTINGS['focus_scale']-1)*weights[i]
        # styledの固定余白は拡大率に含めない。検査の文字座標も小数の変換と一致させる。
        px=(row.width-tile.width*scale)/2
        py=(row.height-tile.height*scale)/2
        for entry in (e for e in texts if e['key']==str(rows[i]['key'])):
            b=entry['box']
            new=tuple((v-box[j%2])*scale+((x+px) if j%2==0 else (y+py))/s+VIEW[j%2] for j,v in enumerate(b))
            if new[0]<VIEW[0]-1 or new[1]<VIEW[1]+68 or new[2]>VIEW[2]+1 or new[3]>VIEW[3]+1:
                raise ValueError('一覧の文字が安全域から出ています: '+entry['text'])
            for portrait in im.info.get('duo_portraits',[]):
                p=portrait['box']
                if max(new[0],p[0])<min(new[2],p[2]) and max(new[1],p[1])<min(new[3],p[3]):
                    raise ValueError('一覧の文字が立ち絵に重なります: '+entry['text'])
            transformed.append(dict(entry,box=new))
    piece=canvas.resize((w,h),Image.Resampling.LANCZOS)
    head=base.crop((0,0,w*s,68*s))
    ImageDraw.Draw(head).text((24*s,12*s),heading,font=font(36*s),fill=(242,243,228))
    piece.paste(head.resize((w,68),Image.Resampling.LANCZOS),(0,0))
    out=im.copy();out.paste(piece,VIEW[:2]);out.info.update(im.info)
    out.info['motion']=dict(active=str(rows[active]['key']) if active is not None else None,zoom=1.,
                            row_scale=1+(SETTINGS['focus_scale']-1)*max(weights,default=0),
                            weights=weights,crop=(0,0,w,h),view=VIEW,source_size=canvas.size,texts=transformed,
                            cues=[vars(c) for c in cues],overview=active is None,time=t)
    if im.info.get('duo_layer'):
        import characters
        characters.redraw(out,im.info['duo_layer'])
    return out


def measured(audio):
    """Call after validating manifest against narration; no cache across jobs."""
    SPEECH.clear()
    for row in audio:
        if row.get('duration'):SPEECH[row['text']]=float(row['duration'])


def caption_cues(rows, duration):
    import review_render_v3 as r3
    text=r3._CAPTION['text'];parts=r3.caption_chunks(text);cursor=0.;out=[]
    for part in parts:
        span=duration*len(part)/max(1,sum(map(len,parts)))
        matched=[r for r in rows if r.get('anchor') and r['anchor'] in part]
        if len(matched)==1:
            start=max(SETTINGS['overview'],cursor)
            if cursor+span>start:out.append(Cue(str(matched[0]['key']),start,cursor+span,part))
        cursor+=span
    return out


def background(im,t):
    if not enabled():return im
    # Background only, called before text/chrome/portraits are drawn.
    sx,sy=SETTINGS['drift_speed']
    dx=SETTINGS['drift']*math.sin(t*sx);dy=SETTINGS['drift']*math.sin(t*sy)
    return im.transform(im.size,Image.Transform.AFFINE,(1,0,dx,0,1,dy),Image.Resampling.BICUBIC)


def transition(previous, im, k, fps=30, style=None):
    if not enabled():return None
    count=max(2,round(SETTINGS['transition']*fps))
    if not previous or k>=count:return im.tobytes()
    prev=Image.frombytes('RGB',im.size,previous);p=ease(k/(count-1))
    style=style or ('glass' if os.getenv('COLLESPO_BUBBLE')=='glass' else 'slant')
    view=((72,236,940,1140) if im.size==(1080,1920)
          else (56,144,1136,760) if im.size==(1920,1080) else (0,0,*im.size))
    if p==0:
        mixed=prev.crop(view)
    elif p==1:
        return im.tobytes()
    elif style=='glass':
        radius=5*math.sin(math.pi*p)
        mixed=Image.blend(prev.crop(view).filter(ImageFilter.GaussianBlur(radius)),im.crop(view).filter(ImageFilter.GaussianBlur(radius)),p)
    elif style=='slant':
        old=prev.crop(view);new=im.crop(view);mask=Image.new('L',new.size);d=ImageDraw.Draw(mask)
        x=-new.height*.3+p*(new.width+new.height*.3)
        d.polygon([(0,0),(x,0),(x+new.height*.3,new.height),(0,new.height)],fill=255)
        mixed=Image.composite(new,old,mask)
    else:raise ValueError('未知の切り替え: '+style)
    out=im.copy();out.paste(mixed,view[:2])
    # A portrait's head can extend into the content viewport. Keep its whole
    # current rectangle, just like the fixed subtitle and speaker name.
    for portrait in im.info.get('duo_portraits',[]):
        box=tuple(portrait['box']);out.paste(im.crop(box),box[:2])
    return out.tobytes()


def prepare_highlights(material, segments, durations):
    """#152's fact-based decision, without enabling its faces or sound effects."""
    import fan_events
    HIGHLIGHTS.clear();start=0
    for seg,duration in zip(segments,durations):
        decision=fan_events.decision(seg.get('text',''),material,motion_only=True)
        if decision:
            HIGHLIGHTS.append(dict(start=start,end=start+duration,text=seg.get('text',''),
                                   speech=float(seg.get('duration') or duration),decision=decision))
        start+=duration


def highlight_event(part):
    if not enabled():return None
    import fan_events
    import review_render_v3 as r3
    now=r3._PROGRAM_CLOCK[0]
    if now is None:return None
    row=fan_events.current() or next((r for r in HIGHLIGHTS if r['start']<=now<r['end']),None)
    if not row or not row.get('decision'):return None
    import re
    target=next((v for v in row['decision']['highlights'] if (match:=re.search(r'\d+(?:\.\d+)?',v)) and match[0]==part),None)
    if not target or target not in row['text']:return None
    at=row['start']+row['text'].find(target)/max(1,len(row['text']))*row['speech']
    phase=(now-at)/SETTINGS['pulse_seconds']
    return phase if 0<=phase<=1 else None


def number_font(face, part):
    """Same targets/time gate as #152; outside that gate return the exact face."""
    phase=highlight_event(part)
    if phase is None:return face
    factor=1+SETTINGS['pulse']*math.sin(math.pi*phase)
    return variant(face,max(1,round(face.size*factor)))


@lru_cache(maxsize=256)
def variant(face,size):
    if size==face.size:return face
    new=face.font_variant(size=size)
    # FreeType font_variant otherwise resets variable fonts to their Thin/Regular.
    try:new.set_variation_by_name('Bold')
    except (OSError,ValueError):pass
    return new


def reserve_font(face):
    if not enabled():return face
    return variant(face,math.ceil(face.size*(1+SETTINGS['pulse'])))


def draw_number(draw, xy, text, face, fill, anchor='ls'):
    """One clipped glint, only on #152's highlighted digits."""
    draw.text(xy,text,font=number_font(face,text),fill=fill,anchor=anchor)
    phase=highlight_event(text)
    if phase is None:return
    b=tuple(round(v) for v in draw.textbbox(xy,text,font=face,anchor=anchor))
    if b[2]<=b[0] or b[3]<=b[1]:return
    size=(b[2]-b[0],b[3]-b[1]);mask=Image.new('L',size)
    ImageDraw.Draw(mask).text((xy[0]-b[0],xy[1]-b[1]),text,font=face,fill=round(255*SETTINGS['light']),anchor=anchor)
    clip=Image.new('L',size);d=ImageDraw.Draw(clip);x=round(phase*(size[0]+40))-40
    d.polygon([(x,0),(x+16,0),(x+40,size[1]),(x+24,size[1])],fill=255)
    from PIL import ImageChops
    mask=ImageChops.multiply(mask,clip)
    gleam=(255,245,194) if max(fill[:3])>190 else (0,0,0)
    draw._image.paste(Image.new(draw._image.mode,size,gleam),b[:2],mask)


def slot(kind):
    """Small adapters call this one component, with unchanged legacy fallback."""
    def decorate(fn):
        @wraps(fn)
        def render(t,*args,**kwargs):
            if not enabled():return fn(t,*args,**kwargs)
            if DEPTH.get():return fn(t,*args,**kwargs)
            bound=inspect.signature(fn).bind(t,*args,**kwargs);bound.apply_defaults()
            values=tuple(v for name,v in bound.arguments.items() if name!='t')
            rows,heading,cues,duration,entrance,soccer=adapt(kind,t,values,{})
            if not rows:return fn(t,*args,**kwargs)
            token=DEPTH.set(1)
            try:im=fn(t,*args,**kwargs)
            finally:DEPTH.reset(token)
            if im.info.get('soccer_readable'):return im
            return list_frame(im,t,rows,heading,cues,duration,entrance,soccer)
        return render
    return decorate


def adapt(kind,t,args,kwargs):
    import review_render_v3 as r3
    duration=max(.1,r3._CAPTION['duration'] or 8);rows=[];heading='一覧';cues=[];entrance=True;soccer=False
    if kind=='reddit':
        seg,narr=args[:2]
        if narr.get('program')!='reddit_reaction' or seg['kind'] not in ('intro','fan'):return [],heading,[],duration,True,False
        fans=[s for s in narr['segments'] if s['kind']=='fan']
        for i,s in enumerate(fans):
            m=s['meta'];metric=[]
            for field,label in (('likes','高評価'),('replies','返信')):
                if m.get(field) is not None:metric.append(f'{label} {m[field]:,}')
            at=m.get('at') or ''
            if 'T' in at:
                posted=datetime.fromisoformat(at.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=9)))
                at=f'{posted.month}/{posted.day}'
            source=m['source']+('　'+at if at else '')
            rows.append(dict(key=str(i),title=m['translation'],body=source,metric='　'.join(metric),anchor=s['text'],quote=True))
        heading='匿名のファンの感想';entrance=seg['kind']=='intro'
        found=[r for r in rows if r['anchor']==seg['text']]
        cues=[c for r in found if (c:=cue_for(r,seg['text'],duration))]
    elif kind=='mlb':
        spec=args[0];rows=spec.get('motion_rows') or [];heading='今日の勝利貢献順位'
        duration=spec.get('dur',duration);entrance=spec.get('kind')=='cover'
        text=spec.get('say','');found=[r for r in rows if r.get('anchor') and r['anchor'] in text]
        if len(found)==1:cues=[cue_for(found[0],text,duration)]
    elif kind=='soccer':
        seg,plan=args[:2];soccer=True
        if plan['mode']=='preview' and seg['kind'] in ('cover','preview'):
            games=[s for s in plan['narration']['segments'] if s['kind']=='preview']
            for i,s in enumerate(games):
                m=s['meta'];clubs=plan['clubs']
                home=clubs[m['home']]['name_jp'];away=clubs[m['away']]['name_jp']
                rows.append(dict(key=str(i),title=home+' 対 '+away,body=m['date']+'　'+m['league'],metric=m['time']+' 日本時間',anchor=s['text']))
            heading='注目試合の一覧';entrance=seg['kind']=='cover'
            found=[r for r in rows if r['anchor']==seg['text']]
            cues=[c for r in found if (c:=cue_for(r,seg['text'],duration))]
    elif kind=='quotes':
        voices=args[0];heading=args[1]
        for i,v in enumerate(voices):
            if v.get('fact'):continue
            # 絵文字は日本語の字体に無く、一覧で四角になる（11/1 コメントの回）。声と照合する anchor は元の文のまま。
            import v3_slot_render
            shown=v3_slot_render.screen_text(v.get('said','')).strip()
            if not shown:continue
            rows.append(dict(key=str(i),title=shown,body=v.get('who') or '匿名のファン',anchor=v.get('said',''),quote=True))
            if v.get('read') is not False and v.get('end',0)>v.get('at',0):
                start=max(SETTINGS['overview'],v.get('at',0));end=min(duration,v['end'])
                if end>start:cues.append(Cue(str(i),start,end,v['said']))
    elif kind=='items':
        spec,source,label,credit,times,replies,ends,page_seconds=args
        heading=label
        for i,(head,body) in enumerate(source):
            rows.append(dict(key=str(i),title=head or body,body=body if head else '',anchor=body or head))
            if times is not None and ends is not None:
                start=max(SETTINGS['overview'],times[i]);end=min(duration,ends[i])
                if end>start:cues.append(Cue(str(i),start,end,body or head))
        if len(rows)>8:rows=[];cues=[]
        elif not cues:cues=caption_cues(rows,duration)
    elif kind in ('ranking','schedule','roster','others','standings','jp_roster'):
        spec=args[0];soccer=kind in ('standings','jp_roster')
        source=(args[1] if kind in ('ranking','schedule') else spec.get('rows') if soccer else spec.get('roster') if kind=='roster' else spec.get('other_players')) or []
        heading={'ranking':'今日の勝利貢献順位','schedule':'全試合の一覧','roster':'日本人選手の一覧','others':'日本人選手の一覧','standings':spec.get('title','順位表'),'jp_roster':spec.get('title','日本人選手の一覧')}[kind]
        for i,r in enumerate(source):
            name=r.get('name') or r.get('team') or r.get('home','')+' 対 '+r.get('away','')
            body=r.get('body') or r.get('club') or r.get('abbr','')
            metric=r.get('score') or r.get('when') or (str(r['points'])+'勝点' if 'points' in r else str(r.get('big') or '')+str(r.get('unit') or ''))
            if soccer:
                clubs=args[1]
                name=clubs.get(r.get('team'),{}).get('name_jp',name)
                body=clubs.get(r.get('club'),{}).get('name_jp',body)
                if 'position' in r:
                    name=f"{r['position']}位 {name}";body=f"{r['played']}試合"
                    label=dict(spec.get('lines',[])).get(r['position'])
                    if label:body+='　'+label+'の線'
                if r.get('team')==spec.get('focus') and spec.get('gap'):body+=spec['gap']
            if r.get('values'):metric='　'.join(str(v)+u for v,u in r['values'])
            if r.get('note'):metric=r['note']
            anchor=r.get('spoken_name') or (clubs.get(r.get('team'),{}).get('name_jp',name) if soccer else r.get('home') or r.get('name') or name)
            if not soccer and r.get('rank'):name=f"{r['rank']}位 {name}"
            rows.append(dict(key=str(i),title=name,body=body,metric=metric,anchor=anchor))
        if len(rows)>8:rows=[]  # retain existing pagination, never omit a row
        cues=caption_cues(rows,duration)
    return rows,heading,[c for c in cues if c],duration,entrance,soccer
