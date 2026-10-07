"""共通v3の規則を、描画の記録と元の材料から検査する。"""
from collections import Counter
import re
import unicodedata
import review_render_v3 as r3


SLACK = 3


def check_layout(image):
    errors=[]
    entries=image.info.get('v3_layout')
    if not entries:
        return ['描画位置の記録がありません']
    for e in entries:
        x,y,right,bottom=e['box']
        top,end={'header':(160,r3.CONTENT_TOP),'source':(r3.SOURCE_BOTTOM-80,r3.SOURCE_BOTTOM+8),'ticker':(1486,1574),
                  'caption':(r3.CAPTION_TOP-30,r3.CAPTION_BOTTOM)}.get(e['role'],(r3.CONTENT_TOP,r3.CONTENT_BOTTOM))
        # 字の張り出し（Linux の Noto で「A」が1px左へ出る等）は許す。はみ出しの検査なので数px は問題にしない。
        if not (r3.LEFT-SLACK<=x<=right<=r3.SAFE_RIGHT+SLACK and top-SLACK<=y<=bottom<=end+SLACK):
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
