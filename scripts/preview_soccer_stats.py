"""固定したESPN実3試合のv6見本。通信・音声生成・設定変更なし。"""
import argparse
import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cases():
    return json.loads((ROOT/'scripts/fixtures/soccer-stats/saved-cases.json').read_text(encoding='utf8'))['cases']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'docs/audit-evidence/20261026/soccer-stats')
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
    reports=[]
    for case in cases():
        data=case['data'];game=data['games'][0];clubs=render.resolve_clubs(data)
        narr=render.production_narration(data)
        (args.out/(game['id']+'-narration.json')).write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        result=next(s for s in narr['segments'] if s['kind']=='followup')
        players=[s for s in narr['segments'] if s['kind']=='player-stats']
        columns=[];errors=[]
        for style in ('stars','stages'):
            game['attack_style']=style
            images=[]
            for i,seg in enumerate([result]+players):
                r3.set_program_clock(None)
                r3.set_caption(seg['text'],12,40,speaker=seg['speaker'],caption_units=seg.get('caption_units'))
                im=render.frame(3,seg,data,clubs)
                errors.extend(render.validate_frame(im,data,clubs))
                im.save(args.out/f"{game['id']}-{style}-{i+1}.png")
                images.append(im.resize((432,768)))
            column=Image.new('RGB',(432,768*len(images)),(18,29,26))
            for i,im in enumerate(images):column.paste(im,(0,768*i))
            columns.append(column)
        game.pop('attack_style',None)
        comparison=Image.new('RGB',(864,columns[0].height+160),(18,29,26))
        comparison.paste(columns[0],(0,80));comparison.paste(columns[1],(432,80))
        d=ImageDraw.Draw(comparison)
        font=layout.c.jp(30)
        d.text((20,12),'案A 星表示',font=font,fill='white')
        d.text((452,12),'案B 段階表示',font=font,fill='white')
        d.text((20,comparison.height-64),'実試合：出場分不明のため独自指標なし',font=font,fill='white')
        comparison.save(args.out/f"{game['id']}-comparison.png")
        reports.append(dict(event_id=game['id'],errors=errors,
                            minimum_visual_seconds=sum(layout.minimum_seconds(s,data) for s in narr['segments']),
                            script_characters=sum(len(s['text']) for s in narr['segments']),
                            attack_hidden='ESPN minutesPlayed absent',
                            actual_audio_duration=None))
    # 実試合に推測の分や数字を足さない。形式の差だけ架空の独立カードで見せる。
    sample=dict(name='表示例の選手（架空）',club=game['players'][0]['club'],position='FW',
                status='starter',minutes=60,goals=1,assists=0,shots=3,on_target=2)
    examples=[]
    r3.set_caption('',0,0)
    for style in ('stars','stages'):
        g=copy.deepcopy(game);g['attack_style']=style
        im=layout.Screen(clubs,3).player_statistics(g,[sample],render.program_spec(data))
        errors=layout.check_frame(im,clubs)
        if errors:raise ValueError(errors)
        im.save(args.out/f'format-example-{style}.png')
        examples.append(im.resize((432,768)))
    sheet=Image.new('RGB',(864,900),(18,29,26));d=ImageDraw.Draw(sheet)
    d.text((20,12),'形式比較専用・架空の数値（実試合と別）',font=font,fill='white')
    for i,im in enumerate(examples):sheet.paste(im,(i*432,70))
    d.text((20,850),soccer_stats.NOTICE,font=font,fill='white')
    sheet.save(args.out/'00-format-comparison.png')
    (args.out/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if any(r['errors'] for r in reports):raise ValueError(reports)
    print(json.dumps(reports,ensure_ascii=False))


if __name__=='__main__':main()
