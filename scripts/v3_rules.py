"""共通v3の規則を、描画の記録と元の材料から検査する。"""
from collections import Counter
import re
import unicodedata
import review_render_v3 as r3


SLACK = 3


def content_group(image):
    """固定見出し・出典・字幕を除いた札と本文。入れ子の札は一群として扱う。"""
    entries=[e for e in image.info.get('v3_layout',[]) if e['role'] not in ('header','source','caption','ticker')]
    cards=[e for e in entries if e['role']=='card']
    def inside(a,b):
        return b[0]<=a[0] and b[1]<=a[1] and a[2]<=b[2] and a[3]<=b[3]
    outer=[c for c in cards if not any(c is not other and c['box']!=other['box'] and inside(c['box'],other['box']) for other in cards)]
    moving=[e for e in entries if e['box'][1]>=320 or any(inside(e['box'],c['box']) for c in cards)]
    if image.info.get('v3_card_contents') and outer:
        # 共通frameの複数行の見出しは、札の先頭より上に固定する。
        card_top=min(c['box'][1] for c in outer)
        moving=[e for e in moving if e['box'][1]>=card_top]
    return moving,outer


def check_spacing(image):
    """v4の空札・200px以上の札内/札下余白を止める。短い1札の中央配置は許す。"""
    if r3.LOOK!='v4':return []
    errors=[];entries=image.info.get('v3_layout',[])
    for card in (e for e in entries if e['role']=='card'):
        x,y,right,bottom=card['box']
        children=[e for e in entries if e is not card and e['role'] not in ('header','source','caption','ticker')
                  and x<=e['box'][0] and y<=e['box'][1] and e['box'][2]<=right and e['box'][3]<=bottom]
        if bottom-y>=200 and (not children or bottom-max(e['box'][3] for e in children)>=200):
            errors.append({'empty_card_bottom':card['box']})
    moving,outer=content_group(image)
    if moving:
        top=min(e['box'][1] for e in moving);bottom=max(e['box'][3] for e in moving)
        centered=abs((top+bottom)/2-(320+r3.CONTENT_BOTTOM)/2)<=24
        if r3.CONTENT_BOTTOM-bottom>=200 and not (len(outer)<=1 and centered):
            errors.append({'empty_screen_bottom':r3.CONTENT_BOTTOM-bottom,'content':(top,bottom)})
    return errors


def check_layout(image):
    errors=[]
    entries=image.info.get('v3_layout')
    if not entries:
        return ['描画位置の記録がありません']
    for e in entries:
        x,y,right,bottom=e['box']
        top,end={'header':(160,r3.CONTENT_TOP),'source':(r3.SOURCE_BOTTOM-80,r3.SOURCE_BOTTOM+8),'ticker':(1486,1574),
                  'caption':(r3.CAPTION_TOP-30,r3.CAPTION_BOTTOM)}.get(e['role'],(r3.CONTENT_TOP,r3.CONTENT_BOTTOM))
        left=r3.LEFT-8 if e['role']=='caption' else r3.LEFT
        edge=r3.CAPTION_RIGHT if e['role']=='caption' else r3.SAFE_RIGHT
        # 字の張り出し（Linux の Noto で「A」が1px左へ出る等）は許す。はみ出しの検査なので数px は問題にしない。
        if not (left-SLACK<=x<=right<=edge+SLACK and top-SLACK<=y<=bottom<=end+SLACK):
            errors.append(e)
    for card in image.info.get('v3_card_contents',[]):
        w,h=card['size']
        for e in card['text']:
            x,y,right,bottom=e['box']
            if not (0<=x<=right<=w and 0<=y<=bottom<=h):
                errors.append({'card_text':e,'size':card['size']})
    return errors


def check_quotes(quotes):
    texts=[''.join(str(s).split()).strip('「」') for s in quotes]
    return [s for s,n in Counter(texts).items() if s and n>1]


def numbers(text):
    return set(re.findall(r'\d+対\d+|\d+(?:\.\d+)?',unicodedata.normalize('NFKC',str(text)).replace(',','')))


def check_speech(spec,items):
    rows=dict(items);errors=[]
    for head,speech in (spec.get('speech') or {}).items():
        if head not in rows:
            errors.append({'head':head,'error':'画面の項目がありません'});continue
        missing=numbers(speech)-numbers(rows[head])
        if missing:
            errors.append({'head':head,'numbers':sorted(missing)})
    return errors


def check_marks(spec):
    errors=[]
    for c in (spec.get('v3') or {}).get('chips',[]):
        if (c.get('symbol') or any(x in str(c.get('label',''))+str(c.get('score','')) for x in ('○','●','◯','◎','★','☆','✓','✔'))) and not c.get('symbol_explanation'):
            errors.append(c)
    return errors
