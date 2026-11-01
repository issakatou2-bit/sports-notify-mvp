"""保存ESPN材料で、本番と同じ原稿・声・描画のサッカー結果を試作する。投稿なし。"""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scoreboards',type=Path,default=ROOT/'scripts/fixtures/soccer-results/scoreboards.json')
    ap.add_argument('--summaries',type=Path,default=ROOT/'scripts/fixtures/soccer-results/summaries.json')
    ap.add_argument('--date',default='2026-09-20')
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer-results-preview')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    os.environ['COLLESPO_SHORT_LOOK']='v4'
    import soccer_results as results
    import soccer_results_render as render
    import synthesize_narration as sn
    boards=json.loads(args.scoreboards.read_text(encoding='utf-8'));summaries=json.loads(args.summaries.read_text(encoding='utf-8'))
    data=results.build(boards,summaries,args.date)
    if not data['can_make']:raise ValueError('この保存材料の日には日本人選手の出場がありません')
    (args.out/'soccer_results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    narr=render.narration(data)
    (args.out/'narration.json').write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    directory=args.out/'audio';directory.mkdir(exist_ok=True);manifest=directory/'manifest.json'
    previous=json.loads(manifest.read_text(encoding='utf-8')).get('segments',[]) if manifest.exists() else []
    audio=[]
    for i,seg in enumerate(narr['segments']):
        path=directory/f'{i:02d}.wav'
        reuse=i<len(previous) and path.exists() and previous[i].get('text')==seg['text'] and previous[i].get('speaker')==seg['speaker']
        if not reuse and not sn.synth_one(seg['text'],seg['speaker'],path):raise ValueError('VOICEVOXの声の合成に失敗')
        audio.append(dict(seg,file=str(path.resolve()),duration=sn.audio_duration(path)))
    manifest.write_text(json.dumps({'segments':audio},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    render.render_video(data,narr,audio,args.out)


if __name__=='__main__':main()
