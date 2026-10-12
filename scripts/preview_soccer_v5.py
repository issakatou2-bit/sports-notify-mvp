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
    import name_reading_guard as readings
    readings.validate_dialogue(narr)
    directory=out/'audio';directory.mkdir(exist_ok=True)
    old_path=directory/'manifest.json'
    old=json.loads(old_path.read_text(encoding='utf-8')).get('segments',[]) if old_path.exists() else []
    audio=[]
    for i,seg in enumerate(narr['segments']):
        file=directory/f'{i:02d}.wav'
        reuse=i<len(old) and file.is_file() and (seg['text'],seg['speaker'])==(old[i].get('text'),old[i].get('speaker'))
        checked_path=file.with_suffix('.reading.json')
        if reuse:
            try:
                saved=json.loads(checked_path.read_text(encoding='utf-8'))
                reuse=saved['spoken']==sn.apply_readings(seg['text'])
                readings.validate_query(seg['text'],saved['query'])
            except (OSError,ValueError,KeyError):reuse=False
        if not reuse and not sn.synth_one(seg['text'],seg['speaker'],file):raise ValueError('実音声を合成できません')
        audio.append(dict(seg,file=str(file.resolve()),duration=sn.audio_duration(file)))
    save_json(old_path,dict(segments=audio))
    return audio


def detailed_badge_comparison(out):
    from PIL import Image
    import soccer_v5_cards as c
    clubs=c.original.load_clubs()
    names=['Real Madrid CF','Aston Villa FC','Manchester City FC','Paris Saint-Germain FC']
    rows=[clubs[n] for n in names if n in clubs]
    if len(rows)<4:rows=list({r['team_en']:r for r in clubs.values()}.values())[:4]
    sheet=Image.new('RGB',(1080,160+len(rows)*220),c.PITCH)
    c.text(sheet,40,26,'札A / B　左は実寸35px　右は2倍（同じ画素）',30,width=990)
    measurements=[]
    for index,club in enumerate(rows):
        y=100+index*220;c.text(sheet,40,y,c.club_display_names.display(club),26,width=990)
        images=[]
        for variant in ('A','B'):
            im=Image.new('RGB',(150,45),c.PITCH);c.scarf(im,(8,5,142,40),club,variant=variant)
            images.append(im)
        for j,im in enumerate(images):
            sheet.paste(im,(40+j*200,y+60))
            sheet.paste(im.resize((300,90),Image.Resampling.NEAREST),(460+j*300,y+50))
        different=sum(p!=q for p,q in zip(images[0].get_flattened_data(),images[1].get_flattened_data()))
        measurements.append(dict(club=club['team_en'],different_pixels=different,native_height=35))
    sheet.save(out/'club-tags-native-and-2x.png');save_json(out/'club-tags-native-and-2x.json',measurements)


def saved_preview_material():
    import notability_engine as ne
    import club_display_names as names
    import soccer_match_interest as interest
    data=json.loads((ROOT/'data/soccer_games.json').read_text(encoding='utf-8'))
    data=interest.attach_season_stats(data)
    selected=[];leagues=set()
    for game in sorted(data['games'],key=lambda g:not bool(interest.expectation(g))):
        # 保存材料は日本人フラグを持たない。既存名簿から所属だけを補う。
        # 出場・先発・今の所属を新しく確認した材料としては扱わない。
        people={side:[p['name_jp'] for p in ne.jp_players_for_club(
            (names.lookup(game[side+'_team_name']) or {}).get('id',game[side+'_team_name']))]
            for side in ('home','away')}
        if any(people.values()) and game['league'] not in leagues:
            selected.append(dict(game,is_notable=True,home_has_jp=bool(people['home']),
                                 away_has_jp=bool(people['away']),jp_by_side=people))
            leagues.add(game['league'])
        if len(selected)==3:break
    if len(selected)<3:raise ValueError('異なるリーグの実カード3件を保存材料から選べません')
    return dict(data,games=selected,source='ESPN・football-data.org',
                preview_provenance='保存された実カード/日時＋既存名簿による表示試作。新しい出場確認/公開は行わない。')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer-v5-previews')
    ap.add_argument('--screens-only',action='store_true')
    ap.add_argument('--compare-badges',action='store_true',help='以前のA/B比較も明示的に作る（既定は選んだ札だけ）')
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
    badge_sheet(out,os.environ.get('COLLESPO_SOCCER_BADGE','B'))
    if args.compare_badges:
        a,b=(badge_sheet(out,v) for v in ('A','B'))
        detailed_badge_comparison(out)
        compare=__import__('PIL.Image',fromlist=['Image']).new('RGB',(2160,1920),c.PITCH)
        compare.paste(a,(0,0));compare.paste(b,(1080,0));compare.save(out/'05_club_tags_AB.png')
    reports=[];collection=[];labels=[]
    for mode in ('preview','race','week','results','voices'):
        directory=out/mode;directory.mkdir(exist_ok=True)
        if mode in ('preview','race','week'):
            data=(saved_preview_material() if mode=='preview' else
                  json.loads((ROOT/'scripts/fixtures/soccer-slots'/f'{mode}.json').read_text(encoding='utf-8')))
            plan=slots.program(mode,data);narr=plan['narration']
            draw=lambda t,seg:slots.frame(t,seg,plan)
            check=lambda im:slots.check_frame(im,plan)
            movie=lambda audio:slots.render_video(plan,audio,directory)
        elif mode=='results':
            data=results.build(json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf-8')),
                json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf-8')),'2026-09-20')
            from soccer_v5_program import add_player_scene
            narr=add_player_scene(render.narration(data),data);clubs=render.resolve_clubs(data)
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
