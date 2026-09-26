"""Rebuild named historical editions privately; never modify the public originals."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCES = {
    '2026-09-24': ('4af9b107aadd7ceb63e08ac394a42d63b6a125eb','UAGTxHrNlwU'),
    '2026-09-25': ('d09b72f459ffe8c3e835dbbe741709cedcbd32f4','4AMCA2hnTZY'),
    '2026-09-26': ('4f3d01557ef72fa5a219692921a79dbc574c7a4f','q1sabe4E8pI'),
}
ROOT = Path('build/ps-label-repair')


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def historical(ref, path):
    return json.loads(subprocess.check_output(['git','-c','safe.directory='+Path.cwd().as_posix(),
                                               'show',ref+':'+path]))


def prepare(day):
    ref, old_id = SOURCES[day]
    out=ROOT/day
    ps=historical(ref,'data/postseason.json')
    recap=historical(ref,'data/morning_recap.json')
    record=historical(ref,'data/published_videos.json')['morning_postseason'][day]
    if ps.get('date')!=day or recap.get('date_jst')!=day or record['video_id']!=old_id:
        raise ValueError('Historical date or original video mismatch')
    write(out/'postseason.json',ps)
    write(out/'recap.json',recap)
    write(out/'empty.json',{})
    write(out/'source.json',{'day':day,'commit':ref,'old_video_id':old_id,'record':record})
    from check_rendered_claims import audit
    audit('postseason',out/'postseason.json',day,out/'claims.json')
    # Render review frames too, from exactly the historical materials.
    import generate_morning_short as video
    for lid, league in ps['leagues'].items():
        video.render_ps_league(1,league,lid).save(out/f'league-{lid}.png')
    print(day+': historical inputs verified; no LLM calls')


def render(day):
    prepare(day)
    out=ROOT/day
    cmd=[sys.executable,'scripts/generate_morning_short.py','--mode','postseason',
         '--recap',str(out/'recap.json'),'--postseason',str(out/'postseason.json')]
    for flag in ['--buzz','--race','--reporters','--talk','--voices']:
        cmd += [flag,str(out/'empty.json')]
    narration=out/'narration.json'
    subprocess.run(cmd+['--narration-out',str(narration)],check=True)
    if not narration.exists():
        raise ValueError('Historical narration was not produced')
    subprocess.run([sys.executable,'scripts/synthesize_narration.py','--narration',str(narration),
                    '--out-dir',str(out/'audio')],check=True)
    segments=json.loads((out/'audio/manifest.json').read_text(encoding='utf-8'))['segments']
    if not segments or any(not s.get('file') or s.get('duration',0)<=0 for s in segments):
        raise ValueError('Incomplete voice synthesis; do not upload')
    subprocess.run(cmd+['--audio-dir',str(out/'audio'),'--out',str(out/'video'),'--require-audio'],check=True)
    path=out/'video/collespo_morning_postseason.mp4'
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True)
    write(out/'quality.json',{'decoded':True,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})


def upload(day):
    import pilot_upload as pilot
    from googleapiclient.http import MediaFileUpload
    out=ROOT/day
    path=out/'video/collespo_morning_postseason.mp4'
    quality=json.loads((out/'quality.json').read_text(encoding='utf-8'))
    if not quality['decoded'] or quality['sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('Video differs from validated output')
    key='ps-labels-'+day+'-v1'
    yt=pilot.youtube_client()
    found=pilot.owned_videos(yt)  # verifies the channel, scans exact durable markers
    state,_=pilot.load_state()
    old_id=SOURCES[day][1]
    original=yt.videos().list(part='snippet,status',id=old_id).execute().get('items',[])
    if len(original)!=1 or original[0]['snippet']['channelId']!=pilot.CHANNEL_ID:
        raise ValueError('Original owner mismatch')
    existing=found.get(key)
    if existing:
        pilot.require_private(existing)
        vid=existing['id']
    elif state['entries'].get(key):
        raise RuntimeError('Reserved upload without matching video; inspect before retrying')
    else:
        snippet={k:v for k,v in original[0]['snippet'].items() if k in
                 ['title','description','categoryId','tags','defaultLanguage','defaultAudioLanguage']}
        snippet['description']=(day+'時点のポストシーズン進出争いです。地区優勝、PS進出確定、現在の地区首位を区別して表示しています。\n\n'
                                +snippet.get('description','')+'\n[COLLESPO-PILOT:'+key+']')
        pilot.record(key,{'status':'pending','old_video_id':old_id,'run_id':os.environ.get('GITHUB_RUN_ID')})
        request=yt.videos().insert(part='snippet,status',notifySubscribers=False,
            body={'snippet':snippet,'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False}},
            media_body=MediaFileUpload(str(path),mimetype='video/mp4',chunksize=8*1024*1024,resumable=True))
        response=None
        while response is None:
            _,response=request.next_chunk(num_retries=2)
        vid=response['id']
        pilot.record(key,{'status':'uploaded','video_id':vid,'old_video_id':old_id})
    for _ in range(30):
        rows=yt.videos().list(part='snippet,status,processingDetails',id=vid).execute().get('items',[])
        if len(rows)!=1:
            raise RuntimeError('Uploaded video missing; do not upload again')
        pilot.require_private(rows[0])
        if rows[0]['status'].get('uploadStatus')=='processed':
            receipt={'status':'confirmed','video_id':vid,'old_video_id':old_id,'privacy':'private',
                     'url':'https://www.youtube.com/watch?v='+vid,'day':day}
            pilot.record(key,receipt)
            write(out/'receipt.json',receipt)
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as f:
                    f.write('\n'+day+' 非公開修正版: '+receipt['url']+'\n')
            print(json.dumps(receipt,ensure_ascii=False))
            return
        time.sleep(5)
    raise RuntimeError('Private upload received; processing not confirmed. Do not duplicate.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','render','upload'])
    parser.add_argument('--day',choices=[*SOURCES,'all'],default='2026-09-25')
    args=parser.parse_args()
    for day in SOURCES if args.day=='all' else [args.day]:
        {'prepare':prepare,'render':render,'upload':upload}[args.action](day)


if __name__=='__main__':
    main()
