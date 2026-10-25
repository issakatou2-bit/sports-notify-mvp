"""固定したESPN実3試合のv6見本。通信・音声生成・設定変更なし。"""
import argparse
import copy
import subprocess
import types
import sys
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cases(supplementary=False):
    saved=json.loads((ROOT/'scripts/fixtures/soccer-stats/saved-cases.json').read_text(encoding='utf8'))
    return saved['cases']+(saved.get('supplementary_cases',[]) if supplementary else [])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'docs/audit-evidence/20261026/soccer-stats/revised')
    args = ap.parse_args()
    # この試作プロセスだけ。本番の変数は変更しない。
    os.environ.update(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4',
                      COLLESPO_SOLO_HOST='metan', COLLESPO_DUO='off', COLLESPO_BUBBLE='slant')
    import soccer_results_render as render
    import soccer_readable as layout
    import soccer_stats
    import review_render_v3 as r3
    from PIL import Image, ImageDraw
    args.out.mkdir(parents=True, exist_ok=True)
    # 同じ保存材料で83441c26の描画と比較する。旧ファイルを変更しない。
    def previous(name):
        source=subprocess.check_output(['git','show',f'83441c26:scripts/{name}.py'],cwd=ROOT).decode('utf8')
        module=types.ModuleType(name+'_previous')
        exec(compile(source,name+'_previous','exec'),module.__dict__)
        return module
    old_layout=previous('soccer_readable');old_stats=previous('soccer_stats')
    reports=[]
    for case in cases(supplementary=True):
        data=case['data'];game=data['games'][0];clubs=render.resolve_clubs(data)
        narr=render.production_narration(data)
        (args.out/(game['id']+'-narration.json')).write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        scenes=[s for s in narr['segments'] if s['kind'] in ('followup','followup-detail','team-stats','player-stats','roster')]
        images=[];old_images=[];errors=[]
        for i,seg in enumerate(scenes):
            r3.set_program_clock(None)
            r3.set_caption(seg['text'],12,40,speaker=seg['speaker'],caption_units=seg.get('caption_units'))
            im=render.frame(3,seg,data,clubs)
            errors.extend(render.validate_frame(im,data,clubs))
            im.save(args.out/f"{game['id']}-stars-{i+1}.png")
            images.append(im.resize((432,768)))
            # 旧版には交代由来の分を渡さない。
            baseline=copy.deepcopy(data)
            for p in baseline['games'][0]['players']:
                if p.get('minutes_approx'):
                    for key in ('minutes','minutes_source','minutes_approx'):p.pop(key,None)
            baseline['players']=sorted(baseline['games'][0]['players'],key=__import__('soccer_results').rank_key)
            # frame() はsoccer_readableを遅延importするため、その間だけ旧モジュールへ。
            sys.modules['soccer_readable']=old_layout;sys.modules['soccer_stats']=old_stats
            try:
                before=render.frame(3,seg,baseline,clubs)
            finally:
                sys.modules['soccer_readable']=layout;sys.modules['soccer_stats']=soccer_stats
            old_images.append(before.resize((432,768)))
        comparison=Image.new('RGB',(864,768*len(images)+80),(18,29,26))
        d=ImageDraw.Draw(comparison);font=layout.c.jp(30)
        d.text((20,12),'修正前 83441c26',font=font,fill='white')
        d.text((452,12),'修正後 台詞順に表示',font=font,fill='white')
        for i,(before,after) in enumerate(zip(old_images,images)):
            comparison.paste(before,(0,80+768*i));comparison.paste(after,(432,80+768*i))
        comparison.save(args.out/f"{game['id']}-comparison.png")
        storyboard=Image.new('RGB',(432*4,808*((len(images)+3)//4)),(18,29,26))
        draw=ImageDraw.Draw(storyboard)
        for i,(im,seg) in enumerate(zip(images,scenes)):
            x=(i%4)*432;y=(i//4)*808
            draw.text((x+10,y+4),f"{i+1} {seg['kind']}",font=layout.c.jp(22),fill='white')
            storyboard.paste(im,(x,y+40))
        storyboard.save(args.out/f"{game['id']}-storyboard.png")
        eligible=[p['name'] for p in game['players'] if soccer_stats.attack(p) is not None]
        supplementary=case not in cases()
        if not supplementary and not eligible:raise ValueError('攻撃関与が出る選手がいません: '+game['id'])
        reports.append(dict(event_id=game['id'],errors=errors,attack_players=eligible,supplementary=supplementary,
                            minimum_visual_seconds=sum(layout.minimum_seconds(s,data) for s in narr['segments']),
                            script_characters=sum(len(s['text']) for s in narr['segments']),actual_audio_duration=None))
    (args.out/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if any(r['errors'] for r in reports):raise ValueError(reports)
    print(json.dumps(reports,ensure_ascii=False))


if __name__=='__main__':main()
