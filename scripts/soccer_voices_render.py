"""サッカーの現地の声。原文/訳/返信を同じ画面に、共通の立ち絵・字幕・締めで描く。"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from PIL import ImageDraw
import review_render_v3 as r3
import short_v4_cards as v4
import soccer_v4_cards as cards
import soccer_slots_v4 as slots
import soccer_voices as sv
import v3_rules as rules
import v3_slot_render as common
import video_common as vc

ROOT=Path(__file__).resolve().parents[1]
FPS=30
L,R=cards.L,cards.R
TAGLINE='欧州の日本人選手とMLBを、毎日数字で'


def clubs_for(data):
    clubs=slots.clubs_for(data['video']['clubs'])
    # Quote originals retain the actual Latin name. They use the same material club identity.
    palette=cards.load_clubs()
    for alias,c in palette.items():
        for own in list(clubs.values()):
            if c['team_en']==own['team_en']: clubs[alias]=own; break
    return clubs


def text_runs(value,clubs):
    """原文は書き換えず、名前の左へ材料に対応した札を置く。"""
    names=sorted((n for n in clubs if len(n)>=3),key=len,reverse=True)
    if not names: return [(value,None)]
    pattern='('+ '|'.join(re.escape(n) for n in names)+')'
    lookup={n.casefold():c for n,c in clubs.items()}
    return [(s,lookup.get(s.casefold())) for s in re.split(pattern,value,flags=re.I) if s]


def wrapped(value,size,width,clubs):
    """クラブの札込みで折る。クラブ名の語を途中で切らない。"""
    f=r3.font(size);out=[];line=[];used=0
    for run,club in text_runs(common.screen_text(value),clubs):
        tokens=[run] if club else re.findall(r'[A-Za-zÀ-ž0-9]+|.',run)
        for token in tokens:
            span=f.getlength(token)+(cards.badge_width(club,size)+12 if club else 0)
            if span>width: raise ValueError('原文/訳の語が札の幅に入りません')
            if token=='\n' or (line and used+span>width):
                out.append(line);line=[];used=0
                if token=='\n':continue
            line.append((token,club));used+=span
    if line:out.append(line)
    return out


def draw_lines(im,x,y,lines,size,color):
    f=r3.font(size)
    for row in lines:
        px=x
        # A single baseline keeps Roman/Japanese characters and each badge on the same line.
        row_dy=f.getbbox(''.join(s for s,_ in row))[1]
        for token,club in row:
            dy=f.getbbox(token)[1];height=f.getbbox(token)[3]-dy
            if club:
                px+=cards.club_badge(im,px,y+dy-row_dy,club,size,height)+12
            r3._text(ImageDraw.Draw(im),(px,y-row_dy),token,font=f,fill=color)
            e=im.info['v3_layout'][-1];e['v4_font']=size
            if club:e['club_id']=club['team_en']
            px+=f.getlength(token)
        y+=size+12
    return y


def pair_layout(voice,clubs,reply=False):
    width=R-L-88
    size=38 if reply else 54
    original=voice.get('original') or voice['title']
    ja=wrapped(voice['ja'],size,width,clubs)
    raw=wrapped(original,28 if reply else 32,width,clubs)
    # heading, quote, translation, original label/text, padding, metadata.
    height=70+len(ja)*(size+12)+40+len(raw)*((28 if reply else 32)+12)+40
    metadata=[]
    if not reply:
        metadata=[('称賛' if voice['tone']=='称賛' else '中立',v4.TONE_COLORS[voice['tone']])]
        if voice.get('likes') is not None:metadata.append((f"高評価 {voice['likes']}",None))
        if voice.get('replies') is not None:metadata.append((f"返信 {voice['replies']}",None))
        height+=56
    return dict(ja=ja,raw=raw,height=height,size=size,original_size=28 if reply else 32,metadata=metadata)


def quote_fits(v,clubs):
    try:
        total=pair_layout(v,clubs)['height']+sum(pair_layout(r,clubs,True)['height']+16 for r in v.get('reply_ja',[]))
        return total <= r3.CONTENT_BOTTOM-342
    except ValueError:return False


def spec(data):
    return dict(ticker=sv.FICTION if data.get('sample_fictional') else sv.LABEL+'　'+data['video']['matchup_jp'],
                source=(sv.FICTION+'　' if data.get('sample_fictional') else '')+data['screen_source'])


def cover(t,data,clubs):
    im=cards.canvas(t,clubs,sv.LABEL);v4.panel(im,(L,270,R,1080))
    cards.plain(im,L+30,300,'現地ファンの反応',38,r3.GOLD,width=R-L-60)
    cards.plain(im,L+30,396,data['star'],84,width=R-L-60)
    cards.plain(im,L+30,522,'何と言ったか',76,r3.GOLD,width=R-L-60)
    cards.plain(im,L+30,650,data['video']['competition']+'　公式ハイライト',30,width=R-L-60)
    for name,y in zip(data['video']['clubs'],(738,860)):
        cards.club_name(im,L+30,y,clubs[name],44,width=R-L-60)
    if data.get('sample_fictional'):
        cards.plain(im,L+30,1002,'架空の見本・実在の投稿ではありません',28,r3.GOLD,width=R-L-60)
    return cards.finish(im,t,spec(data))


def quote_panel(im,y,voice,layout,clubs,reply=False,reading=True):
    h=layout['height'];color=v4.CREAM if reading else (186,185,173)
    v4.panel(im,(L,y,R,y+h),color)
    v4.text(im,L+24,y+4,'“',72,(163,125,54),width=80)
    cards.plain(im,L+74,y+20,'↳ 返信（訳）' if reply else 'コメント（訳）',26,r3.DARK_INK,width=R-L-105)
    pos=draw_lines(im,L+44,y+70,layout['ja'],layout['size'],r3.DARK_INK)
    cards.plain(im,L+44,pos+8,'原文',24,(85,89,93),width=R-L-88)
    pos=draw_lines(im,L+44,pos+42,layout['raw'],layout['original_size'],r3.DARK_INK)
    x=L+30
    for value,fill in layout['metadata']:
        x+=v4.tag(im,x,y+h-68,value,fill or (49,60,73),size=24,width=min(260,R-30-x))+12
    return y+h


def voice_screen(t,data,voice,clubs,duration):
    im=cards.canvas(t,clubs,sv.LABEL)
    # This comes from the material roster; player identity is not inferred from the quote.
    players=sv.players_in_match(data['video'],sv.load_names())
    named=[p for p in players if p['name_jp'] in voice['jp_players']]
    if named:
        p=named[0]
        cards.club_name(im,L,266,clubs[p['team_en']],28,suffix='　'+p['name_jp'],width=R-L)
    parent=pair_layout(voice,clubs)
    reply_layouts=[pair_layout(r,clubs,True) for r in voice['reply_ja']]
    if not quote_fits(voice,clubs):raise ValueError('引用と返信が同じ画面の安全域に入りません')
    spoken=sv.spoken_names(voice['ja'],players)
    total=len(spoken)+sum(len('。返信は、'+sv.spoken_names(r['ja'],players)) for r in voice['reply_ja'])
    reply_at=len(spoken)/max(1,total)*duration
    y=quote_panel(im,342,voice,parent,clubs,reading=not voice['reply_ja'] or t<reply_at)
    shown=[voice['ja']]
    for i,(reply,layout) in enumerate(zip(voice['reply_ja'],reply_layouts)):
        if t<reply_at:break
        y=quote_panel(im,y+16,reply,layout,clubs,reply=True);shown.append(reply['ja'])
    im.info.update(v4_quote=True,soccer_voice_pairs=[{'said':voice['ja'],'original':voice['title']}],
                   soccer_shown_quotes=shown,soccer_reading='reply' if voice['reply_ja'] and t>=reply_at else 'parent')
    return cards.finish(im,t,spec(data))


def frame(t,seg,data,clubs=None,duration=20):
    if r3.LOOK!='v4':raise ValueError('新設のサッカー現地の声はv4専用')
    clubs=clubs or clubs_for(data)
    if seg['kind']=='outro':
        credit='音声: VOICEVOX:四国めたん　'+spec(data)['source']
        im=r3.outro(t,{},'soccer_voices',credit,tagline=TAGLINE)
        im.info['soccer_outro_elapsed']=t
        return im
    if seg['kind']=='intro':return cover(t,data,clubs)
    return voice_screen(t,data,data['voices'][seg['meta']['index']],clubs,duration)


def material_numbers(data):
    values=set()
    for v in data['voices']:
        values.update(sv.numbers(v['title']))
        for key in ('likes','replies'):
            if v.get(key) is not None:values.add(str(v[key]))
        for r in v['reply_ja']:values.update(sv.numbers(r['original']))
    return values


def check_frame(im,data,clubs):
    errors=rules.check_layout(im)+cards.check_club_badges(im,clubs)
    # Shared outro rows slide in; evaluate its final spacing after the entrance, without changing it.
    if not im.info.get('v3_outro') or im.info.get('soccer_outro_elapsed',0)>=3:
        errors+=rules.check_spacing(im)
    if not im.info.get('v3_outro'):
        extra=set(cards.drawn_numbers(im))-material_numbers(data)
        if extra:errors.append({'numbers_missing_from_material':sorted(extra)})
    if data.get('sample_fictional'):
        labels=[e.get('text','') for e in im.info.get('v3_layout',[])]
        if not any('架空' in s for s in labels):errors.append({'fictional_label_missing':True})
    return errors


def prepare(data):
    """収まらない返信から外す。引用本文を切ったり小さくして隠さない。"""
    data=json.loads(json.dumps(data,ensure_ascii=False));sv.validate_data(data)
    if not data['can_make']:return data
    clubs=clubs_for(data);kept=[]
    for v in data['voices']:
        if not quote_fits(v,clubs):v['reply_ja']=[]
        if quote_fits(v,clubs):kept.append(v)
    if len(kept)<sv.MIN_NAMED:return sv.empty('安全域内に出せる引用が3件未満なので作らない',data.get('sample_fictional'))
    data['voices']=kept;data['spoken_chars']=sum(len(s['text']) for s in sv.narration(data)['segments'])
    sv.validate_data(data)
    return data


def render_video(data,narr,audio,out):
    sv.validate_data(data)
    if narr!=sv.narration(data):raise ValueError('原稿と採用した材料が一致しません')
    times=slots.durations(narr['segments'],audio)
    times=[math.ceil(t*FPS)/FPS for t in times]
    if sum(times)>sv.LIMIT:raise ValueError('フレームの丸め後40秒を超える')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if not shutil.which('ffmpeg'):raise ValueError('FFmpegをinstall_video_tools.shで入れてください')
    track=vc.build_narration_track(audio,times,out)
    if not track:raise ValueError('実音声なしでは動画を作りません')
    video=out/'collespo_soccer_voices.mp4';images=[];layouts=[];previous=None;clock=0;clubs=clubs_for(data)
    cmd=['ffmpeg','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r',str(FPS),'-i','-',
         '-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',
         '-t',str(sum(times)),'-movflags','+faststart',str(video)]
    with (out/'ffmpeg.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for i,(seg,duration) in enumerate(zip(narr['segments'],times)):
                r3.set_caption(seg['text'],duration,sum(times),speaker=2,duo=False,hide_caption=seg['kind']=='outro')
                snap=min(3,duration*.6) if seg['kind']=='outro' else max(.5,duration-.5)
                r3.set_program_clock(clock+snap);im=frame(snap,seg,data,clubs,duration)
                errors=check_frame(im,data,clubs)
                if errors:raise ValueError(f'画面{i}: {errors}')
                im.save(out/f'{i+1:02d}.png');images.append(im);layouts.append(im.info)
                for k in range(round(duration*FPS)):
                    r3.set_program_clock(clock+k/FPS);im=frame(k/FPS,seg,data,clubs,duration)
                    proc.stdin.write(vc.short_transition(previous,im,k,FPS,True))
                previous=im.tobytes();clock+=duration
        finally:
            proc.stdin.close();code=proc.wait();r3.set_program_clock(None)
    if code:raise ValueError('動画生成失敗。ffmpeg.logを確認')
    from preview_unified_v3 import sheet
    sheet(images,[s['kind'] for s in narr['segments']],out/'all-screens.png',columns=3)
    probe=subprocess.run(['ffmpeg','-hide_banner','-i',str(video)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    m=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
    if not m:raise ValueError('実動画の尺が読めません')
    seconds=int(m[1])*3600+int(m[2])*60+float(m[3])
    if seconds>sv.LIMIT:raise ValueError('実動画が40秒を超える')
    report=dict(seconds=seconds,voice_seconds=sum(v['duration'] for v in audio),title=data['title'],
                sample_fictional=data['sample_fictional'],screens=len(images),layout_badges_numbers='PASS',
                publication='not performed',frames=layouts)
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},ensure_ascii=False))
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data',type=Path,default=ROOT/'data/soccer_voices.json')
    ap.add_argument('--narration-out',type=Path)
    ap.add_argument('--audio-dir',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_voices')
    args=ap.parse_args();data=json.loads(args.data.read_text(encoding='utf-8'))
    if args.narration_out:
        data=prepare(data)
        args.data.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        args.narration_out.parent.mkdir(parents=True,exist_ok=True)
        args.narration_out.write_text(json.dumps(sv.narration(data),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not data['can_make']:print(data['reason']);return 0
    if args.audio_dir:
        audio=json.loads((args.audio_dir/'manifest.json').read_text(encoding='utf-8'))['segments']
        render_video(data,sv.narration(data),audio,args.out)
    return 0


if __name__=='__main__':raise SystemExit(main())
