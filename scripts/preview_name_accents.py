"""確認済み氏名の修正前後、未確認59呼称の現在音声と少数の仮案。"""
import argparse
import copy
import json
from pathlib import Path
import sys
import wave

import requests

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import check_name_accents as checker
import name_accent_guard as accents
import synthesize_narration as sn
import voice_accent_common as common


def save(query,speaker,path,url):
    query=copy.deepcopy(query);query['speedScale']=sn.SPEED_SCALE
    for key,value in {'prePhonemeLength':sn.PRE_PHONEME,'postPhonemeLength':sn.POST_PHONEME,'pauseLengthScale':sn.PAUSE_SCALE,
                      **sn.SPEAKER_TUNE[speaker]}.items():
        if key in query:query[key]=value
    response=requests.post(url.rstrip('/')+'/synthesis',params=dict(speaker=speaker),json=query,timeout=120)
    response.raise_for_status();path.write_bytes(response.content)
    with wave.open(str(path)) as audio:
        if not audio.getnframes():raise ValueError('空の音声')
        duration=audio.getnframes()/audio.getframerate()
    path.with_suffix('.query.json').write_text(json.dumps(query,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return duration


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--url',default='http://127.0.0.1:50121');args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);rows=[];records=[];round1=[]
    for index,row in enumerate(accents.entries()):
        record=checker.audit(row['name']+'です。',2,args.url);records.append(record)
        q=record['query'];check=record['check']['name_accents'][0]
        filename=f'{index+1:02d}-current.wav';duration=save(q,2,args.out/filename,args.url)
        result=dict(row,id=index+1,file=filename,duration=duration,actual=check['actual'])
        if row['pattern']:
            before=f'{index+1:02d}-before-speaker2.wav';save(record['raw_query'],2,args.out/before,args.url)
            result['before_file']=before
            r3=checker.audit(row['name']+'です。',3,args.url);records.append(r3)
            save(r3['query'],3,args.out/f'{index+1:02d}-after-speaker3.wav',args.url)
            save(r3['raw_query'],3,args.out/f'{index+1:02d}-before-speaker3.wav',args.url)
        elif len(round1)<15 and check['actual']!='L'+'H'*(common.mora_count(row['reading'])-1):
            # 正解でなく、平板の仮案。辞書と本番は変更しない。
            alt=copy.deepcopy(q);pi,mi=accents.locations(record['text'],q)[0]['first']
            if mi:raise ValueError('単独氏名見本の開始位置が不正')
            phrase=alt['accent_phrases'][pi];phrase['accent']=len(phrase['moras'])
            response=requests.post(args.url+'/mora_data',params=dict(speaker=2),json=[phrase],timeout=30)
            response.raise_for_status();alt['accent_phrases'][pi]=response.json()[0]
            filename_alt=f'{index+1:02d}-flat-candidate.wav';save(alt,2,args.out/filename_alt,args.url)
            result['candidate_file']=filename_alt;result['candidate_pattern']='L'+'H'*(common.mora_count(row['reading'])-1)
            round1.append(result['id'])
        rows.append(result);print(index+1,row['name'],row['status'],flush=True)
    result=dict(base='2f86ba3f',date='2026-10-12',names=rows,first_round=round1,records=records,
                note='仮案は正解でない。本人のいま/案/保留の判定を共通辞書へ戻す。未確認は本番で補正しない。')
    (args.out/'samples.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    html='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>氏名の高低</title><style>body{font:18px system-ui;max-width:900px;margin:24px auto;padding:12px}audio{display:block;width:100%;max-width:480px}section{border-top:1px solid #bbb;padding:16px 0}label{margin-right:16px}</style><h1>氏名の高低</h1><p>確認済みは鎌田大地のみ。残る59呼称は未確認です。まず15人の「いま／平板の仮案」を比べ、いま・案・保留を選べます。仮案を正解と扱っていません。</p><button onclick="exportPicks()">15人の判定をJSONで保存</button>'
    known=[r for r in rows if r['pattern']];first=[r for r in rows if r['id'] in round1];rest=[r for r in rows if not r['pattern'] and r['id'] not in round1]
    for title,group in [('本人指定の鎌田大地',known),('最初の15人の聞き比べ',first),('残りの氏名の現在音声',rest)]:
        html+=f'<h2>{title}</h2>'
        for r in group:
            html+=f'<section><h3>{r["id"]} {r["name"]}</h3>'
            if r.get('before_file'):
                html+=f'<p>以前（めたん）</p><audio controls src="{r["before_file"]}"></audio><p>本人指定 LHHHHH（めたん）</p><audio controls src="{r["file"]}"></audio><p>以前（ずんだもん）</p><audio controls src="{r["id"]:02d}-before-speaker3.wav"></audio><p>本人指定（ずんだもん）</p><audio controls src="{r["id"]:02d}-after-speaker3.wav"></audio>'
            else:
                html+=f'<p>いま：{r["actual"]}（正解未確認）</p><audio controls src="{r["file"]}"></audio>'
                if r.get('candidate_file'):
                    html+=f'<p>平板の仮案：{r["candidate_pattern"]}</p><audio controls src="{r["candidate_file"]}"></audio>'
                    for value,label in [('current','いま'),('candidate','案'),('hold','保留')]:
                        html+=f'<label><input type="radio" name="pick-{r["id"]}" value="{value}">{label}</label>'
            html+='</section>'
    mapping={r['id']:r['name'] for r in first}
    html+='<script>const names='+json.dumps(mapping,ensure_ascii=False)+';function exportPicks(){const picks=[...document.querySelectorAll("input:checked")].map(e=>({id:Number(e.name.slice(5)),name:names[e.name.slice(5)],choice:e.value}));const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify({round:"name-accent-20261012-1",picks},null,2)],{type:"application/json"}));a.download="name-accent-picks.json";a.click();URL.revokeObjectURL(a.href);}</script></html>'
    (args.out/'index.html').write_text(html,encoding='utf8')
    print('name accent samples complete:',len(rows),'names / confirmed 1 / unverified 59 / first round',len(round1))


if __name__=='__main__':main()
