"""Motion proof with saved voice and native scene rendering. Never uploads."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def motion_checks(out):
    """Same text/pose/base at both times: measure only the support pattern motion."""
    import bubble_styles as bs
    import characters
    from PIL import Image
    import numpy as np
    receipts=[]
    with patch.dict(os.environ,{'COLLESPO_BUBBLE':'glass'}):
        for pattern in ('stripes','lights'):
            with patch.dict(os.environ,{'COLLESPO_GLASS_BACKGROUND':pattern}):
                samples=[]
                for seconds in (0,4,8):
                    im=Image.new('RGB',(1080,1920),(24,44,36))
                    bs.draw(im,'metan','山本由伸は6回を投げて8奪三振。',seconds=seconds)
                    samples.append(im.crop((64,1220,940,1468)))
                sheet=Image.new('RGB',(876*3,248))
                for i,im in enumerate(samples):sheet.paste(im,(876*i,0))
                sheet.save(out/f'motion-{pattern}-0-4-8s.png')
                diff=np.abs(np.asarray(samples[0],dtype=float)-np.asarray(samples[-1],dtype=float))
                if not diff.any():raise ValueError('模様が動いていません')
                receipts.append(dict(pattern=pattern,times=[0,4,8],changed_pixels=int(np.any(diff,axis=2).sum()),mean_channel_delta=float(diff.mean()),
                                     stripes_pixels_per_second=3 if pattern=='stripes' else None,max_light_pixels_per_second=3.52 if pattern=='lights' else None,
                                     name_colors={k:list(v) for k,v in characters.COLORS.items()}))
    (out/'motion-checks.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mlb-dir',type=Path,required=True)
    ap.add_argument('--soccer-dir',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--fps',type=int,default=12,help='Native sampling rate; MP4 is resampled to 24fps')
    args=ap.parse_args()
    if not 4<=args.fps<=30:raise ValueError('fps must be 4..30')
    os.environ.update(COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v5',COLLESPO_DUO='off',COLLESPO_EXPR='',COLLESPO_SLANT_VARIANT='cream')
    import ps_brand_components as fonts
    fonts.FONT_CANDIDATES['jp']=[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')]
    fonts.FONT_CANDIDATES['latin']=[str(ROOT/'assets/fonts/Oswald[wght].ttf')]
    fonts.FONT_CANDIDATES['serif']=fonts.FONT_CANDIDATES['jp'];fonts._cache.clear()
    # Match the existing bold production type with the bundled variable font.
    for size in range(19,91):
        face=fonts.font(size)
        face.set_variation_by_name('Bold')
    import bignumber_render as bn
    import bubble_styles as bubbles
    import caption_breaks as breaks
    import characters
    import review_render_v3 as r3
    import soccer_slots_v4 as slots
    import synthesize_narration as sn
    import video_common as vc
    import imageio_ffmpeg
    from PIL import Image
    from preview_unified_v3 import sheet
    args.out.mkdir(parents=True,exist_ok=True)
    bindir=args.out/'bin';bindir.mkdir(exist_ok=True)
    ffmpeg=bindir/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')
    shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(),ffmpeg)
    ffmpeg=ffmpeg.resolve();os.environ['PATH']=str(bindir.resolve())+os.pathsep+os.environ.get('PATH','')
    datasets=[]
    for label,source in [('mlb-1700',args.mlb_dir),('soccer',args.soccer_dir)]:
        narr=load(source/'narration.json');audio=load(source/'audio/manifest.json')['segments']
        if len(audio)!=len(narr['segments']):raise ValueError('保存音声の区間不足')
        for seg,voice in zip(narr['segments'],audio):
            if any(seg[k]!=voice[k] for k in ('text','speaker','kind','meta')):raise ValueError('保存音声と原稿が違います')
            voice['file']=str((source/'audio'/Path(voice['file']).name).resolve())
        if label=='mlb-1700':
            times=[sn.audio_duration(Path(s['file']))+.7 for s in audio]
            plan=bn.timeline(bn.scenes_from_morning(load(source/'recap.json'),narr),times)
            render=lambda t,s,i,plan=plan:bn.frame(t,plan)
        else:
            plan=slots.program('preview',load(source/'material.json'));plan['narration']=narr
            times=slots.durations(narr['segments'],audio)
            render=lambda t,s,i,plan=plan:slots.frame(t-sum(plan['times'][:i]),s,plan)
            plan['times']=times
        datasets.append((label,narr,audio,times,render))
    reports=[];variants=[]
    for label,narr,audio,times,render in datasets:
        directory=args.out/label;directory.mkdir(exist_ok=True)
        track=vc.build_narration_track(audio,times,directory)
        (directory/'narration.json').write_text(json.dumps(narr,ensure_ascii=False,indent=2),encoding='utf-8')
        for style,pattern in [('slant','stripes'),('glass','stripes'),('glass','lights')]:
            os.environ.update(COLLESPO_BUBBLE=style,COLLESPO_GLASS_BACKGROUND=pattern,COLLESPO_SLANT_VARIANT='cream')
            folder=args.out/(style+'-'+pattern)/label;folder.mkdir(parents=True,exist_ok=True)
            video=folder/'preview.mp4'
            cmd=[str(ffmpeg),'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r',str(args.fps),'-i','-',
                 '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-r','24','-pix_fmt','yuv420p','-c:a','aac','-t',str(sum(times)),'-movflags','+faststart',str(video)]
            images=[];captions=[];ratios=[];clock=0;written=0;seen=set();first_background=None;last_background=None
            with (folder/'ffmpeg.log').open('w',encoding='utf-8') as log:
                proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
                try:
                    for i,(seg,dur) in enumerate(zip(narr['segments'],times)):
                        r3.set_program_clock(clock);r3.set_caption(seg['text'],dur,sum(times),speaker=seg['speaker'],hide_caption=seg['kind']=='outro')
                        pages=r3.caption_chunks(seg['text'])
                        errors=breaks.violations(seg['text'],pages)
                        if errors:raise ValueError(errors)
                        captions.append(dict(segment=i,pages=pages,check='PASS'))
                        end=round((clock+dur)*args.fps)
                        for k in range(written,end):
                            now=k/args.fps;r3.set_program_clock(now)
                            image=render(now,seg,i)
                            meta=image.info.get('bubble_style')
                            if meta:
                                if min(meta['contrast'],meta['name_contrast'])<4.5:raise ValueError('文字のコントラスト不足')
                                ratios.append(min(meta['contrast'],meta['name_contrast']))
                                current=r3.current_sentence(now-clock,seg['text'],dur)
                                seen.add((i,current))
                                pixels=image.crop(bubbles.geometry()).tobytes()
                                if first_background is None:first_background=pixels
                                last_background=pixels
                            if k==written or k==written+max(1,round(min(1.5,dur*.5)*args.fps)):
                                name=f'{i+1:02d}-{k-written:03d}.png';image.save(folder/name);images.append(image.copy())
                            proc.stdin.write(image.convert('RGB').tobytes())
                        written=end;clock+=dur
                finally:proc.stdin.close()
                if proc.wait():raise ValueError('動画出力失敗')
            for i,seg in enumerate(narr['segments']):
                if seg['kind']!='outro' and any((i,p) not in seen for p in r3.caption_chunks(seg['text'])):raise ValueError('動画で表示されなかったページ')
            if style=='glass' and first_background==last_background:raise ValueError('ガラスが動いていません')
            sheet(images,[str(i+1) for i in range(len(images))],folder/'all-screens.png',columns=4)
            decode=subprocess.run([str(ffmpeg),'-v','error','-i',str(video),'-f','null','-'],capture_output=True)
            if decode.returncode:raise ValueError('全尺復号失敗')
            record=dict(slot=label,style=style,pattern=pattern,seconds=sum(times),sample_fps=args.fps,video=str(video),minimum_contrast=min(ratios),pages=captions,full_decode='PASS',motion='native frames and moving glass background',box=list(bubbles.geometry()))
            reports.append(record)
            print(label,style,pattern,'PASS',flush=True)
        # Render a clean native frame, then put the three alternate captions on it.
        i=next(i for i,s in enumerate(narr['segments']) if s['kind'] not in ('cover','outro'))
        seg=narr['segments'][i];start=sum(times[:i]);snap=min(1.5,times[i]*.5)
        r3.set_program_clock(start);r3.set_caption(seg['text'],times[i],sum(times),speaker=seg['speaker'])
        r3.set_program_clock(start+snap)
        with patch.object(characters,'bubble',lambda *a:None):base=render(start+snap,seg,i)
        text=r3.current_sentence(snap,seg['text'],times[i])
        for variant in ('dark','band','glass'):
            image=base.copy();bubbles.draw(image,'metan',text,style='slant',variant=variant)
            image.save(args.out/f'{label}-slant-{variant}.png');variants.append(image)
    sheet(variants,['MLB a','MLB b','MLB c','サッカー a','サッカー b','サッカー c'],args.out/'slant-variants.png',columns=3)
    names=[]
    for who in characters.NAMES:
        image=Image.new('RGB',(1080,1920),(24,44,36));bubbles.draw(image,who,'3打数1安打。',style='slant',variant='band')
        names.append(image.crop((64,1220,940,1468)))
    tag_sheet=Image.new('RGB',(876,248*3),(24,44,36))
    for i,image in enumerate(names):tag_sheet.paste(image,(0,248*i))
    tag_sheet.save(args.out/'name-colors.png')
    r3.set_program_clock(None)
    (args.out/'confirmation.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    html=['<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>吹き出しの試作2</title><style>body{font:16px sans-serif;background:#132820;color:white;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}video{width:100%;max-height:75vh}img{max-width:100%}a{color:#ffdc8a}</style><h1>横長の吹き出しと動くガラス</h1><p>保存材料・保存音声。公開していません。全ページを文節・数字の区切りで検査済み。</p><main>']
    for r in reports:
        rel=Path(r['video']).relative_to(args.out).as_posix()
        label=('MLB17時' if r['slot']=='mlb-1700' else 'サッカー')+' '+('斜めカット' if r['style']=='slant' else 'ガラス '+('縦じま' if r['pattern']=='stripes' else '球場の光'))
        html.append(f'<article><h2>{label}</h2><video controls preload="metadata" src="{rel}"></video><p>最小コントラスト {r["minimum_contrast"]:.2f}</p></article>')
    html.append('</main><h2>斜めカットの3案</h2><p>a: 半透明の濃い地とぼかし / b: クリームと話者色の帯 / c: 斜めのガラス</p><img src="slant-variants.png"><h2>3人の名札</h2><img src="name-colors.png"><p><a href="confirmation.json">検査記録</a> / <a href="run_checks.log">全体検査</a></p></html>')
    (args.out/'review.html').write_text('\n'.join(html),encoding='utf-8')
    motion_checks(args.out)


if __name__=='__main__':main()
