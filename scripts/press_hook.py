"""報道Bの主見出し。既存の表紙・引用札を使い、文字を縮めない。"""
import re


def caption_prefix(text, limit):
    """字幕の上限で次の文の数字だけを残さない。原稿そのものは変更しない。"""
    if len(text)<=limit:return text
    prefix=text[:limit]
    ends=list(re.finditer(r'[。！？!?]',prefix))
    if ends:return prefix[:ends[-1].end()]+'…'
    # 長い単文でも、小数/スコア/時刻/数＋単位の途中では切らない。
    for match in re.finditer(r'\d+(?:[.,:/-]\d+)*(?:年前|年|月|日|時|分|語|件|人|点|本|万|億|ドル|対)*',text):
        if match.start()<limit<match.end():prefix=text[:match.start()];break
    return prefix.rstrip('、。')+'…'


def main_title(text):
    # 因果の長い見出しは同じ主役・事実の短い表題へ。全文は3秒から引用札で示す。
    match=re.fullmatch(r'([^、]{1,12})、.+敗退を受けて(?:\d+語の)?感謝メッセージを投稿[。]?',text)
    if match:return match[1]+'\n敗退を受けて感謝'
    return text.rstrip('。')


def frame(elapsed, progress, meta, reporters, *, modern=False):
    import generate_morning_short as g
    import review_render_v3 as r3
    from PIL import ImageDraw
    sources=meta.get('source_headlines') or []
    if not sources:raise ValueError('報道Bの主見出しの原材料がありません')
    source=sources[0];full=source.get('jp') or source.get('title','')
    if elapsed>=3:
        if modern:
            import press_v3
            segment=dict(kind='intro',text=full,meta=meta)
            im=press_v3.frame(elapsed-3,segment,reporters,max(1,len(full)/5))
        else:
            im=g.render_headlines(min(1,(elapsed-3)/g.ANIM_END),sources)
        im.info['press_hook']=dict(kind='headline_detail',page=0,headline=full)
        return im
    if modern:
        im=r3.background(elapsed,None);d=ImageDraw.Draw(im)
        r3._header(d,'現地の報道',None)
        draw_font=r3.font;ink=r3.INK;accent=r3.GOLD;dim=r3.INK
        d.text((80,260),g.jp_date(meta.get('date','')),font=draw_font(40),fill=dim)
    else:
        im,d=g.base(progress);draw_font=g.font;ink=g.TEXT;accent=g.ACCENT;dim=g.DIM
        d.text((80,290),g.jp_date(meta.get('date','')),font=draw_font(40),fill=dim)
        d.text((80,350),'現地の報道',font=draw_font(44),fill=dim)
        d.text((80,g.H-170),'コレスポ　collespo.com',font=draw_font(38),fill=dim)
    # 表紙の題と同じ96px。長い題も縮小/省略せず2行ごとに送る。
    lines=[]
    for paragraph in main_title(full).split('\n'):
        lines.extend(g.wrap(d,paragraph,draw_font(96),g.W-160))
    pages=[lines[i:i+2] for i in range(0,len(lines),2)] or [['']]
    page=min(len(pages)-1,int(elapsed/max(1,3/len(pages))))
    shown=pages[page];boxes=[]
    for i,text in enumerate(shown):
        box=(80,510+i*126,80+d.textlength(text,font=draw_font(96)),630+i*126)
        d.text((box[0],box[1]),text,font=draw_font(96),fill=accent if i==0 else ink)
        boxes.append(box)
    g.topic_band(d,source.get('source') or '現地メディア',850,note='見出しの訳：コレスポ')
    im.info['press_hook']=dict(kind='headline_main',page=page,pages=len(pages),headline=full,
                               title_lines=shown,font_size=96,boxes=boxes)
    return im
