"""保存した本物の3枠をv5で声つき試作。ほかの2枠は全画面画像。公開しない。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def save_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def badge_sheet(out,variant):
    import soccer_v5_cards as c
    palette=json.loads((ROOT/'data/club_colors.json').read_text(encoding='utf-8'))
    clubs=c.original.load_clubs()
    im=c.canvas(3,clubs,'札 '+variant+'　'+('縦じま＋斜め' if variant=='A' else '斜めだけ'))
    c.heading(im,'5大リーグ 96クラブの札')
    y=330;cols=7;gap=10;width=(c.R-c.L-gap*(cols-1))//cols
    for code,league in palette['leagues'].items():
        c.text(im,c.L,y,league['name_jp'],24,c.CHALK,width=c.R-c.L);y+=28
        for start in range(0,len(league['clubs']),cols):
            for j,club in enumerate(league['clubs'][start:start+cols]):
                club=dict(club,league=code)
                x=c.L+j*(width+gap);c.scarf(im,(x,y,x+width,y+35),club,variant=variant)
            y+=41
        y+=4
    c.text(im,c.L,y+12,'色不明は灰色　略称は各リーグ公式',22,c.MUTED,width=860)
    im=c.finish(im,3,dict(source='出典: クラブ色の表（ユニフォーム・リーグ公式）',ticker='クラブのマフラー札　'+('A：縦じま＋斜め' if variant=='A' else 'B：斜めだけ')))
    errors=c.check_frame(im,clubs)
    if errors:raise ValueError('札の一覧: '+str(errors))
    im.save(out/f'05_club_tags_{variant}.png')
    save_json(out/f'05_club_tags_{variant}-checks.json',dict(clubs=len(im.info['v5_contrasts']),layout='PASS',contrast=im.info['v5_contrasts']))
    return im


def audio_for(narr,out):
    import synthesize_narration as sn
    directory=out/'audio';directory.mkdir(exist_ok=True)
    old_path=directory/'manifest.json'
    old=json.loads(old_path.read_text(encoding='utf-8')).get('segments',[]) if old_path.exists() else []
    audio=[]
    for i,seg in enumerate(narr['segments']):
        file=directory/f'{i:02d}.wav'
        reuse=i<len(old) and file.is_file() and (seg['text'],seg['speaker'])==(old[i].get('text'),old[i].get('speaker'))
        if not reuse and not sn.synth_one(seg['text'],seg['speaker'],file):raise ValueError('実音声を合成できません')
        audio.append(dict(seg,file=str(file.resolve()),duration=sn.audio_duration(file)))
    save_json(old_path,dict(segments=audio))
    return audio


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer-v5-previews')
    ap.add_argument('--screens-only',action='store_true')
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ['COLLESPO_SOCCER_LOOK']='v5';os.environ['COLLESPO_SHORT_LOOK']='v4';os.environ['COLLESPO_DUO']='off'
    import soccer_v5_cards as c
    import soccer_slots_v4 as slots
    import soccer_results as results
    import soccer_results_render as render
    import soccer_voices as voices
    import soccer_voices_render as vr
    import review_render_v3 as r3
    from preview_unified_v3 import sheet
    render.ensure_ffmpeg(out)
    a,b=(badge_sheet(out,v) for v in ('A','B'))
    compare=__import__('PIL.Image',fromlist=['Image']).new('RGB',(2160,1920),c.PITCH)
    compare.paste(a,(0,0));compare.paste(b,(1080,0));compare.save(out/'05_club_tags_AB.png')
    reports=[];collection=[];labels=[]
    for mode in ('preview','race','week','results','voices'):
        directory=out/mode;directory.mkdir(exist_ok=True)
        if mode in ('preview','race','week'):
            data=json.loads((ROOT/'scripts/fixtures/soccer-slots'/f'{mode}.json').read_text(encoding='utf-8'))
            plan=slots.program(mode,data);narr=plan['narration']
            draw=lambda t,seg:slots.frame(t,seg,plan)
            check=lambda im:slots.check_frame(im,plan)
            movie=lambda audio:slots.render_video(plan,audio,directory)
        elif mode=='results':
            data=results.build(json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf-8')),
                json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf-8')),'2026-09-20')
            narr=render.narration(data);clubs=render.resolve_clubs(data)
            draw=lambda t,seg:render.frame(t,seg,data,clubs)
            check=lambda im:render.validate_frame(im,data,clubs)
            movie=lambda audio:render.render_video(data,narr,audio,directory)
        else:
            data=vr.prepare(voices.sample_input(ROOT/'scripts/fixtures/soccer-voices/fictional.json'))
            if not data['can_make']:raise ValueError(data['reason'])
            narr=voices.narration(data);clubs=vr.clubs_for(data)
            draw=lambda t,seg:vr.frame(t,seg,data,clubs,duration=20)
            check=lambda im:vr.check_frame(im,data,clubs)
        save_json(directory/'material.json',data);save_json(directory/'narration.json',narr)
        provenance={'material_sha256':hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                    'sample_fictional':mode=='voices','publication':'not performed'}
        if mode in ('preview','race','results') and not args.screens_only:
            report=movie(audio_for(narr,directory));provenance.update({k:v for k,v in report.items() if k!='frames'})
        images=[]
        for i,seg in enumerate(narr['segments']):
            r3.set_program_clock(0);r3.set_caption(seg['text'],20,100,speaker=2,hide_caption=seg['kind']=='outro');r3.set_program_clock(18)
            im=draw(18,seg);errors=check(im)
            if errors:raise ValueError(f'{mode}画面{i}: {errors}')
            im.save(directory/f'{i+1:02d}.png');images.append(im)
        sheet(images,[s['kind'] for s in narr['segments']],directory/'all-screens.png',columns=4)
        collection.extend(images)
        labels.extend(mode+' '+str(i+1)+' '+seg['kind'] for i,seg in enumerate(narr['segments']))
        save_json(directory/'preview-checks.json',dict(provenance,screens=len(images),layout='PASS'))
        reports.append(dict(provenance,mode=mode,screens=len(images)));print(mode,'screens',len(images),flush=True)
    r3.set_program_clock(None)
    sheet(collection,labels,out/'all-screens.png',columns=4)
    save_json(out/'confirmation.json',dict(previews=reports,colors_table='data/club_colors.json（mainのv2）',published=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
