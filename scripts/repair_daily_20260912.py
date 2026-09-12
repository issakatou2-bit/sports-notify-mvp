"""Rebuild the identified erroneous edition without any LLM calls.

The original is retained privately. A marker and a durable reservation prevent
blind duplicate uploads; a reservation without a matching upload requires review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import mlb_availability as availability
import pilot_upload

EDITION = '2026-09-12'
OLD = '-0QaGeYsSAo'
MARKER = '[COLLESPO-CORRECTION:2026-09-12-ohtani-il]'
KEY = 'correction-2026-09-12-ohtani-il'
TITLE = '【訂正版・9/13】ドジャース8連勝、地区優勝マジック5｜MLBの注目3試合 #Shorts'
NOTICE = ('【訂正】9月12日配信分の「大谷翔平 5日ぶりの出場なるか」は誤りでした。'
          '大谷選手は9月11日付で、9月8日に遡る15日間のILに登録されています。'
          '元動画は非公開にし、出場を期待させる見出し・音声・映像を修正しました。'
          '欠場の間隔だけで復帰を推測していた処理を撤廃しました。')
OUT = Path('build/daily-correction')


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare():
    if datetime.now(timezone.utc) >= datetime(2026, 9, 12, 20, 10, tzinfo=timezone.utc):
        raise ValueError('The first game has started; do not publish an outdated preview')
    payload = json.loads(Path('content/corrections/2026-09-12/games.json').read_text(encoding='utf-8'))
    snapshot = availability.collect(payload)
    payload['games'] = availability.prepare(payload['games'], snapshot)
    # Keep precisely these three identified fixtures, with their verified team facts.
    for g in payload['games']:
        g['is_notable'] = True
    intro = {'big':'8連勝中', 'sub':'ドジャース', 'sub_jp':'ドジャース', 'at':0}
    texts = [
        ('intro', 'ドジャースは8連勝中。9月13日の注目3試合です。',
         {'date_label':'09/13', 'hook':intro, 'top_game':{'matchup':'ドジャース vs マーリンズ','time':'05:10 JST'}}),
        ('game', '午前5時10分、マーリンズ対ドジャース。ドジャースは8連勝中で、地区優勝マジックは5です。', {'game_index':0,'order':0}),
        ('game', '午前7時10分、レイズ対アストロズ。どちらも地区1位で、ポストシーズン進出圏内のチーム同士です。', {'game_index':1,'order':1}),
        ('game', 'ブレーブス対フィリーズも、進出圏内同士の対戦。ブレーブスの地区優勝マジックは9です。', {'game_index':2,'order':2}),
        ('outro', '選手の出場予定は、直前の公式発表をご確認ください。コレスポ。', {})]
    narration = {'date_label':'09/13', 'segments':[{'kind':k,'text':t,'meta':m} for k,t,m in texts]}
    availability.check_narration(payload, narration, snapshot)
    write(OUT/'games.json', payload)
    write(OUT/'availability.json', snapshot)
    write(OUT/'narration.json', narration)
    print('Prepared correction; original source run 34686956353; LLM calls: 0')


def publish():
    from googleapiclient.http import MediaFileUpload
    import buffer_daily
    from upload_youtube import record_video
    payload = json.loads((OUT/'games.json').read_text(encoding='utf-8'))
    narration = json.loads((OUT/'narration.json').read_text(encoding='utf-8'))
    availability.check_narration(payload, narration, availability.load(OUT/'availability.json'))
    path=OUT/'video/collespo_short.mp4'
    duration=buffer_daily.verify_media(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    yt=pilot_upload.youtube_client()
    own=yt.channels().list(part='id,contentDetails',mine=True).execute()['items']
    if len(own)!=1 or own[0]['id']!=pilot_upload.CHANNEL_ID:
        raise ValueError('Wrong YouTube owner')
    original=yt.videos().list(part='snippet,status',id=OLD).execute()['items'][0]
    if original['snippet']['channelId']!=pilot_upload.CHANNEL_ID or original['status']['privacyStatus']!='private':
        raise ValueError('Original must be retained privately before publishing the correction')
    # Read the channel's upload list for the exact correction marker, not a title match.
    playlist=own[0]['contentDetails']['relatedPlaylists']['uploads']
    recent=yt.playlistItems().list(part='contentDetails',playlistId=playlist,maxResults=50).execute()['items']
    ids=','.join(r['contentDetails']['videoId'] for r in recent)
    items=yt.videos().list(part='snippet,status',id=ids).execute().get('items',[])
    existing=[v for v in items if MARKER in v['snippet'].get('description','')]
    if len(existing)>1:
        raise ValueError('Multiple corrections require inspection')
    state,_=pilot_upload.load_state()
    entry=state['entries'].get(KEY)
    if existing:
        vid=existing[0]['id']
    elif entry:
        raise ValueError('Reserved correction has no visible matching upload; do not retry blindly')
    else:
        pilot_upload.record(KEY,{'state':'reserved','old_video_id':OLD,'sha256':digest})
        body={'snippet':{'title':TITLE,'description':NOTICE+'\n\n'
               '公式登録異動：https://www.mlb.com/dodgers/roster/transactions/2026/09\n'
               '試合データ：MLB Stats API（9月12日の生成時点）\n'
               '音声：VOICEVOX:ずんだもん\nhttps://collespo.com/\n'+MARKER,
               'categoryId':'17','defaultLanguage':'ja'},
              'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False}}
        response=yt.videos().insert(part='snippet,status',body=body,
                 media_body=MediaFileUpload(str(path),mimetype='video/mp4',resumable=True)).execute()
        vid=response['id']
        pilot_upload.record(KEY,{'state':'uploaded','video_id':vid,'old_video_id':OLD,'sha256':digest})
    receipt={'video_id':vid,'old_video_id':OLD,'duration':duration,'sha256':digest}
    write(OUT/'receipt.json',receipt)
    for _ in range(60):
        item=yt.videos().list(part='status,processingDetails',id=vid).execute()['items'][0]
        if item['status'].get('uploadStatus')=='processed':
            break
        if item['status'].get('uploadStatus') in ('failed','rejected'):
            raise ValueError('YouTube processing failed')
        time.sleep(5)
    else:
        raise ValueError('YouTube processing not confirmed; correction remains private')
    yt.videos().update(part='status',body={'id':vid,'status':{'privacyStatus':'public','selfDeclaredMadeForKids':False}}).execute()
    check=yt.videos().list(part='status',id=vid).execute()['items'][0]
    if check['status']['privacyStatus']!='public':
        raise ValueError('Publication not confirmed')
    pilot_upload.record(KEY,{**receipt,'state':'public'})
    record_video('daily',EDITION,vid,TITLE)
    old_snippet=original['snippet']
    yt.videos().update(part='snippet',body={'id':OLD,'snippet':{
        'title':'【訂正・非公開】9/13 MLB注目試合（旧版）',
        'description':NOTICE+'\n訂正版：https://youtu.be/'+vid,
        'categoryId':old_snippet.get('categoryId','17')}}).execute()
    print('Corrected public video: https://youtu.be/'+vid)


def socials():
    import buffer_daily as b
    receipt=json.loads((OUT/'receipt.json').read_text(encoding='utf-8'))
    record={'video_id':receipt['video_id'],'title':TITLE}
    b.verify_youtube(record)
    run={'head_sha':os.environ['GITHUB_SHA'], 'html_url':os.environ['GITHUB_SERVER_URL']+'/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']}
    url=b.host_video(run,EDITION+'-correction',OUT/'video/collespo_short.mp4',receipt['sha256'])
    ledger=b.Ledger()
    for service in ('twitter','instagram','tiktok'):
        text=('【訂正】大谷選手はIL登録中です。「5日ぶりの出場なるか」は誤りでした。'
              'お詫びして、映像と音声を修正します。\n9/13の注目試合・訂正版\nhttps://youtu.be/'+receipt['video_id'])
        if service!='twitter':
            text+='\n音声：VOICEVOX:ずんだもん\n#MLB #コレスポ'
        if service=='twitter' and b.x_weight(text)>280:
            raise ValueError('Correction text exceeds X limit')
        post=b.submit_once(ledger,EDITION+':daily-correction:'+service,b.create_payload(service,text,url),
            {'source_run':int(os.environ['GITHUB_RUN_ID']),'youtube_id':receipt['video_id'],
             'corrects_youtube_id':OLD,'sha256':receipt['sha256'],'media_url':url})
        print(service,json.dumps(post,ensure_ascii=False))


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','publish','socials'])
    globals()[parser.parse_args().mode]()
