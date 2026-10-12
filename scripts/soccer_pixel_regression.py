"""保存した実材料・原稿・時計で、全5枠の既存画素を比較する。"""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
FIX=ROOT/'scripts/fixtures/soccer-slots'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def cases():
    import soccer_slots_v4 as slots
    import soccer_results as results
    import soccer_results_render as result_render
    import soccer_voices as voices
    import soccer_voices_render as voice_render
    import review_render_v3 as r3
    if slots.enabled():
        for mode in ('preview','race','week'):
            plan=slots.program(mode,read(FIX/(mode+'.json')))
            for index,seg in enumerate(plan['narration']['segments']):
                yield mode,index,seg,lambda t,seg=seg,plan=plan:slots.frame(t,seg,plan)
        data=results.build(read(ROOT/'scripts/fixtures/soccer-results/scoreboards.json'),
                           read(ROOT/'scripts/fixtures/soccer-results/summaries.json'),'2026-09-20')
        for index,seg in enumerate(result_render.narration(data)['segments']):
            yield 'results',index,seg,lambda t,seg=seg,data=data:result_render.frame(t,seg,data)
        data=voice_render.prepare(voices.sample_input(ROOT/'scripts/fixtures/soccer-voices/fictional.json'))
        for index,seg in enumerate(voices.narration(data)['segments']):
            yield 'voices',index,seg,lambda t,seg=seg,data=data:voice_render.frame(t,seg,data,duration=12)
    else:
        import generate_video as gv
        import generate_morning_short as gm
        preview,race,week=(read(FIX/(m+'.json')) for m in ('preview','race','week'))
        comp=next(c for c in race['competitions'] if c['code'] in race['picked'])
        old=[(gv,'render_intro',('10月10日',{})),(gv,'render_game',(preview['games'][0],1,3)),
             (gm,'render_week_intro',(week,'9月22日')),(gm,'render_week_rows',(week,[0,1])),
             (gm,'render_race_intro',(race,'9月24日')),(gm,'render_race_japanese',(race,)),
             (gm,'render_race_line',(comp,comp['lines'][0]))]
        for index,(module,name,args) in enumerate(old):
            seg=dict(kind=name,text='',speaker=2,meta={})
            yield 'legacy',index,seg,lambda t,module=module,name=name,args=args:getattr(module,name)(t,*args)
    r3.set_program_clock(None)


def hashes():
    import review_render_v3 as r3
    output={}
    for mode,index,seg,draw in cases():
        for t in ((3.,) if seg['kind']=='outro' else (0.,.8,1.4)):
            r3.set_program_clock(0)
            r3.set_caption(seg['text'],12,40,speaker=2,hide_caption=seg['kind']=='outro')
            r3.set_program_clock(t)
            image=draw(t)
            key=f'{mode}/{index}/{seg["kind"]}/{t}'
            output[key]=hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
    r3.set_program_clock(None)
    return output


if __name__=='__main__':
    print(json.dumps(hashes(),ensure_ascii=False,sort_keys=True))
