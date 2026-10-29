"""保存材料3本を本番render_v3で動画化。API・音声生成・公開は行わない。"""
import argparse
import json
from pathlib import Path
import subprocess

import game_ui_short as ui
import generate_asset_video as asset
import review_render_v3 as r3

ROOT=Path(__file__).resolve().parents[1]


def scenes(spec):
    segments=[{'kind':'intro','text':spec['intro'],'meta':{}}]
    for i,(head,body) in enumerate(spec['items']):
        segments.append({'kind':'list','text':body+'。','meta':{'start':i,'count':1}})
    if spec.get('next_line'):
        segments.append({'kind':'next_line','text':spec['next_line']['say'],'meta':{'next_line':spec['next_line']}})
    return ui.annotate(segments,spec)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/game-ui-short/videos')
    ap.add_argument('--fixture',default='*',help='保存材料のファイル名（拡張子なし、glob可）')
    args=ap.parse_args()
    if r3.LOOK!='v4':raise ValueError('COLLESPO_SHORT_LOOK=v4 が必要です')
    args.out.mkdir(parents=True,exist_ok=True)
    for fixture in sorted((ROOT/'scripts/fixtures/game-ui-short').glob(args.fixture+'.json')):
        saved=json.loads(fixture.read_text(encoding='utf-8'));spec=saved['topic']
        asset.LIST_TOPICS[spec['key']]=spec
        segments=scenes(spec);fps=24;seconds=3
        folder=args.out/fixture.stem;folder.mkdir(parents=True,exist_ok=True)
        video=folder/(fixture.stem+'.mp4')
        command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','1080x1920',
                 '-framerate',str(fps),'-i','-','-an','-c:v','libx264','-preset','ultrafast','-crf','21',
                 '-threads','2','-pix_fmt','yuv420p',str(video)]
        records=[];timeline=[]
        with subprocess.Popen(command,stdin=subprocess.PIPE) as proc:
            try:
                for index,seg in enumerate(segments):
                    r3.set_program_clock(index*seconds)
                    r3.set_caption(seg['text'],seconds,len(segments)*seconds,speaker=2)
                    timeline.append({'start':index*seconds,'end':(index+1)*seconds})
                    for k in range(fps*seconds):
                        t=k/fps;r3.set_program_clock(index*seconds+t)
                        im=asset.render_v3(t,seg['kind'],seg['meta'],spec,spec['key'])
                        if k==fps:
                            im.save(folder/f'{index+1:02}.png')
                            records.append({'scene':index+1,'game_ui':im.info['game_ui'],
                                            'v3_layout':im.info.get('v3_layout',[]),'portraits':im.info.get('duo_portraits',[])})
                        proc.stdin.write(im.tobytes())
            finally:
                proc.stdin.close()
            if proc.wait():raise RuntimeError('ffmpeg failed')
        (folder/'timeline.json').write_text(json.dumps({'scenes':timeline},indent=2),encoding='utf-8')
        (folder/'verification.json').write_text(json.dumps({'provenance':saved['provenance'],'frames':records,
                  'audio':'none; layout/motion review only','layout':'passed before frame encoding'},ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(video),flush=True)


if __name__=='__main__':main()
