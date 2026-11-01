"""All narrated slots, fixed bundled materials/fonts; no fetch, voice or upload."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
TEXT='山本由伸は6回を投げて8奪三振。3打数1安打でした。'


@contextmanager
def setup():
    env={'COLLESPO_SHORT_LOOK':'v4','COLLESPO_SOCCER_LOOK':'v4','COLLESPO_FONT':str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf'),
         'COLLESPO_CAPTION_BREAKS':'','COLLESPO_EXPR':'','COLLESPO_DUO':'off'}
    with patch.dict(os.environ,env):
        import ps_brand_components as brand
        brand._cache.clear()
        with patch.dict(brand.FONT_CANDIDATES,{'jp':[env['COLLESPO_FONT']], 'serif':[env['COLLESPO_FONT']],
                                            'latin':[str(ROOT/'assets/fonts/Oswald[wght].ttf')]}):
            import review_render_v3 as r3
            import generate_longform as old
            import longform_render_v3 as new
            import video_common as vc
            with patch.object(vc,'font',lambda size:r3.font(size)),patch.object(r3,'LOOK','v4'),patch.object(old,'font',lambda size:r3.font(size)),patch.object(new,'font',lambda size,weight='Bold':r3.font(size)):
                yield
        brand._cache.clear()


def cases():
    import test_v3_rules as fixture
    import review_render_v3 as r3
    out=[]
    for case in fixture.daily_cases()+fixture.asset_cases():
        idx=next((i for i,s in enumerate(case['segments']) if s.get('kind') not in ('cover','intro','outro')),0)
        seg=case['segments'][idx]
        out.append((case['name'],seg,case['frames'][idx]))
    import soccer_slots_v4 as soccer
    for mode in ('preview','race','week'):
        data=json.loads((ROOT/'scripts/fixtures/soccer-slots'/f'{mode}.json').read_text(encoding='utf-8'))
        plan=soccer.program(mode,data)
        seg=next(s for s in plan['narration']['segments'] if s['kind'] not in ('cover','intro','outro'))
        out.append(('soccer-'+mode,seg,lambda t,s=seg,p=plan:soccer.frame(t,s,p)))
        def v5(t,s=seg,p=plan):
            with patch.dict(os.environ,{'COLLESPO_SOCCER_LOOK':'v5'}):return soccer.frame(t,s,p)
        out.append(('soccer-v5-'+mode,seg,v5))
    import test_soccer_results as results
    import soccer_results_render as rr
    import soccer_result_story as follow
    data=results.fixed()
    seg=next(s for s in rr.narration(data)['segments'] if s['kind'] not in ('intro','outro'))
    out.append(('soccer-results',seg,lambda t,s=seg,d=data:rr.frame(t,s,d)))
    from copy import deepcopy
    fd=deepcopy(data);game=fd['games'][0]
    fd['preview_followup']={'games':[{'event_id':game['id'],'answer':None,'rank_changes':[]}]}
    fs=follow.narration(fd)['segments'][0]
    out.append(('soccer-result-followup',fs,lambda t:follow.frame(t,fs,fd,follow.clubs_for(fd))))
    import test_soccer_voices as voices
    import soccer_voices as sv
    import soccer_voices_render as vr
    vd=voices.sample();vs=next(s for s in sv.narration(vd)['segments'] if s['kind'] not in ('intro','outro'))
    out.append(('soccer-voices',vs,lambda t:vr.frame(t,vs,vd,vr.clubs_for(vd),20)))
    import soccer_now as now
    boards,summaries=results.fixture()
    nd,errors=now.build(boards,summaries,now.results.utc('2026-09-20T17:15:00Z'), goal_short=None)
    if errors:raise ValueError(errors)
    ns=next(s for s in now.narration(nd[0])['segments'] if s['kind'] not in ('intro','outro'))
    out.append(('soccer-now',ns,lambda t:now.frame(nd[0],t,ns)))
    import japan_reacts as jr
    jd=jr.read(ROOT/'scripts/fixtures/japan-reacts/sponichi-saved.json');js=jd['segments'][1]
    out.append(('japan-reacts',js,lambda t:jr.frame(jd,t,js)))
    import test_player_story as player
    import player_story_render as pr
    pd=player.StoryTests().fixture();ps=next(s for s in pd['segments'] if s['kind'] not in ('intro','outro'))
    out.append(('player-story',ps,lambda t:pr.frame(t,ps,pd)))
    import generate_longform as old
    import longform_render_v3 as new
    for key,module in [('longform-legacy',old),('longform-v3',new)]:
        for speaker in (2,3):
            ls={'kind':'talk','text':TEXT,'speaker':speaker}
            def draw(t,m=module,s=ls):
                page=m.paginate([s])[0]
                return m.render_line(t,page,portrait_dir=str(ROOT/'assets/portraits'),topic='保存材料の吹き出し比較',panel={'kind':'stat','label':'投球成績','value':'8','unit':'奪三振'})
            out.append((key+'-'+str(speaker),ls,draw))
    import bubble_styles as bs
    import generate_weekly as weekly
    import generate_verdict_short as verdict
    import generate_video as daily
    seg={'text':TEXT,'speaker':2}
    out.append(('weekly-summary',seg,lambda t:bs.narration_frame(weekly.render_intro(1,'保存材料の週次まとめ'),seg,t,20)))
    out.append(('weekly-verdict',seg,lambda t:bs.narration_frame(verdict.render_outro(1),seg,t,20)))
    out.append(('daily-legacy',seg,lambda t:bs.narration_frame(daily.render_intro(1,'10月14日'),seg,t,20)))
    # Explicit old v3 and duo presenters remain selectable independently of v4.
    import duo_presenter as duo
    def portrait(t,duo_mode=False):
        im=r3.background(t,None)
        if duo_mode:duo.presenter(im,t)
        else:
            with patch.object(r3,'LOOK','v3'):r3.presenter(im,t)
        return im
    out.append(('short-v3',seg,portrait))
    out.append(('short-duo',seg,lambda t:portrait(t,True)))
    return out


def inspect(im):
    import bubble_styles as bs
    meta=im.info.get('bubble_style')
    if not meta:raise ValueError('新しい吹き出しが描かれていません')
    box=im.info['duo_caption']['box'];x0,y0,x1,y1=box
    if not (0<=x0<x1<=im.width and 24<=y0<y1<=im.height):raise ValueError('吹き出しが画面外')
    if meta['contrast']<4.5 or meta['name_contrast']<4.5:raise ValueError('コントラスト不足')
    text=''.join(meta['lines'])
    import caption_breaks as cb
    if cb.violations(text,meta['lines']):raise ValueError('文節または数字を切断')
    d=ImageDraw.Draw(im)
    runs,_,_=bs._runs(d,text,box,meta['style'],light=meta['style']=='glass',band=meta['variant']=='band')
    for x,y,value,f,_ in runs:
        b=d.textbbox((x,y),value,font=f,anchor='ls')
        if b[0]<x0 or b[1]<y0 or b[2]>x1 or b[3]>y1:raise ValueError('本文が吹き出し外: '+str(b))
    content=im.info.get('narrated_content_box')
    if content and content[3]>=y0-24:raise ValueError('既存情報と名札が重なる')
    return dict(box=box,contrast=meta['contrast'],name_contrast=meta['name_contrast'],lines=meta['lines'],bounds='PASS',breaks='PASS')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);receipts=[];tiles=[];html=[]
    with setup():
        import review_render_v3 as r3
        for index,(name,seg,render) in enumerate(cases()):
            pair=[]
            for style in ('slant','glass'):
                with patch.dict(os.environ,{'COLLESPO_BUBBLE':style}):
                    r3.set_program_clock(0);r3.set_caption(seg.get('text') or TEXT,20,20,speaker=seg.get('speaker',2));r3.set_program_clock(2)
                    im=render(2);check=inspect(im);file=f'{index:02}-{style}.png';im.save(args.out/file)
                    receipts.append(dict(slot=name,style=style,file=file,**check))
                    thumb=im.copy();thumb.thumbnail((440,570));pair.append(thumb)
                    html.append(f'<figure><figcaption>{name} / {style}</figcaption><a href="{file}"><img src="{file}"></a></figure>')
            tile=Image.new('RGB',(880,610),(15,30,26));d=ImageDraw.Draw(tile)
            d.text((12,10),name,fill='white')
            for i,thumb in enumerate(pair):tile.paste(thumb,(440*i,36))
            tiles.append(tile);print(name,'PASS',flush=True)
    sheet=Image.new('RGB',(1760,610*((len(tiles)+1)//2)),(15,30,26))
    for i,tile in enumerate(tiles):sheet.paste(tile,((i%2)*880,(i//2)*610))
    sheet.save(args.out/'all-slots.png')
    (args.out/'confirmation.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.out/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>全枠の吹き出し</title><style>body{background:#0f1e1a;color:white;font:16px sans-serif}main{display:grid;grid-template-columns:repeat(2,1fr)}img{max-width:100%;max-height:75vh}a{color:#ffd25a}</style><h1>全枠 slant / glass</h1><p>固定の保存材料。同梱書体。公開処理なし。</p><a href="confirmation.json">配置・改行・コントラスト検査</a> / <a href="run_checks.log">全体検査</a><main>'+''.join(html)+'</main>',encoding='utf-8')


if __name__=='__main__':main()
