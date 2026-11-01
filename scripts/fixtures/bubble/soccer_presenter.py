"""Frozen main 09b1ea3e soccer presenter; supplied module globals in tests."""
def _presenter(im,t):
    import characters
    ctx=r3._CAPTION;clock=r3._PROGRAM_CLOCK[0]
    elapsed=clock-ctx['start'] if clock is not None else t
    line=r3.current_sentence(elapsed,ctx['text'],ctx['duration']) if ctx['text'] else ''
    characters.place_busts(im,'metan',line,elapsed,ctx['duration'] or 1,('metan',))
    if line and not ctx.get('hide_caption'):
        box=characters.BUBBLE
        ImageDraw.Draw(im).polygon(para(box),fill=CHALK)
        x,y,right,bottom=box
        ImageDraw.Draw(im).polygon(para((x+28,y-18,x+240,y+26)),fill=LIME)
        text(im,x+54,y-8,'四国めたん',24,DARK,role='caption',width=180)
        # 同じ読んでいる区間を、3行以内で全文表示する。切り捨てない。
        size=48
        while True:
            rows=lines(line,size,right-x-116)
            if len(rows)<=3 and len(rows)*(size+10)<=bottom-y-42:break
            if size<=24:raise ValueError('字幕が安全域に入りません')
            size-=1
        top=y+30+(bottom-y-42-len(rows)*(size+10))//2
        for i,row in enumerate(rows):text(im,x+62,top+i*(size+10),row,size,DARK,width=right-x-116,role='caption')
        im.info['duo_caption']=dict(box=list(box),speaker='metan',font_size=size,rows=len(rows))
    total=ctx.get('total',0)
    if total and clock is not None:
        ImageDraw.Draw(im).rectangle((L,222,L+round((R-L)*max(0,min(1,clock/total))),226),fill=LIME)
