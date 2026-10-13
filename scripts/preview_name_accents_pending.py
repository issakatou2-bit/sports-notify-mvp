"""未確認の呼称を両話者のいま/平板で聞き比べる。辞書は変更しない。"""
import argparse
import copy
import html
import json
from pathlib import Path

import requests

import check_name_accents as checker
import name_accent_guard as accents
from preview_name_accents import save
import voice_accent_common as common


def render(rows):
    content = ['<!doctype html><html lang="ja"><meta charset="utf-8">',
               '<meta name="viewport" content="width=device-width,initial-scale=1">',
               '<title>氏名の高低 聞き比べ2</title><style>body{font:18px system-ui;max-width:900px;margin:24px auto;padding:12px}audio{display:block;width:100%;max-width:480px}section{border-top:1px solid #bbb;padding:16px 0}label{margin-right:16px}</style>',
               f'<h1>未確認{len(rows)}呼称の聞き比べ</h1><p>めたんとずんだもんの「いま／平板の案」です。案は未確認です。同じ高低の呼称も省かず比較できます。選択はこのブラウザに保存され、JSONで書き出せます。未選択は未選択のまま保存します。</p>',
               '<button onclick="exportPicks()">判定をJSONで保存</button><p id="progress"></p>']
    for row in rows:
        content.append(f'<section><h2>{row["id"]} {html.escape(row["name"])}</h2>')
        for voice in row['voices']:
            label = 'めたん' if voice['speaker'] == 2 else 'ずんだもん'
            content.append(f'<h3>{label}</h3><p>いま：{voice["actual"]}</p><audio controls preload="none" src="{voice["current_file"]}"></audio><p>平板の案：{row["candidate_pattern"]}</p><audio controls preload="none" src="{voice["candidate_file"]}"></audio>')
        for value, label in [('current', 'いま'), ('candidate', '案（平板）'), ('hold', '保留')]:
            content.append(f'<label><input type="radio" name="pick-{row["id"]}" value="{value}">{label}</label>')
        content.append('</section>')
    mapping = [{k: r[k] for k in ('id', 'name', 'reading', 'candidate_pattern')} for r in rows]
    content.append('<script>const names=' + json.dumps(mapping, ensure_ascii=False) + ';' + '''
const key="name-accent-20261013-2";
function selections(){return names.map(r=>({...r,choice:document.querySelector(`input[name="pick-${r.id}"]:checked`)?.value||"unselected"}));}
function update(){document.getElementById("progress").textContent=`選択済み ${selections().filter(r=>r.choice!=="unselected").length} / ${names.length}`;}
try{for(const r of JSON.parse(localStorage.getItem(key)||"[]")){const e=document.querySelector(`input[name="pick-${r.id}"][value="${r.choice}"]`);if(e)e.checked=true;}}catch(e){}
document.addEventListener("change",()=>{try{localStorage.setItem(key,JSON.stringify(selections()));}catch(e){}update();});update();
function exportPicks(){const a=document.createElement("a");const url=URL.createObjectURL(new Blob([JSON.stringify({round:key,exported_at:new Date().toISOString(),picks:selections()},null,2)],{type:"application/json"}));a.href=url;a.download="name-accent-picks2.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
</script></html>''')
    return '\n'.join(content)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--url', default='http://127.0.0.1:50121')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, row in enumerate(accents.entries(), 1):
        if row['status'] != 'UNVERIFIED':
            continue
        result = dict(row, id=index, candidate_pattern='L'+'H'*(common.mora_count(row['reading'])-1), voices=[])
        for speaker in (2, 3):
            record = checker.audit(row['name']+'です。', speaker, args.url)
            query = record['query']
            alt = copy.deepcopy(query)
            pi, mi = accents.locations(record['text'], query)[0]['first']
            if mi:
                raise ValueError('単独氏名の開始位置が不正')
            phrase = alt['accent_phrases'][pi]
            phrase['accent'] = len(phrase['moras'])
            response = requests.post(args.url.rstrip('/')+'/mora_data', params=dict(speaker=speaker), json=[phrase], timeout=30)
            response.raise_for_status()
            alt['accent_phrases'][pi] = response.json()[0]
            actual_candidate = accents.inspect(record['text'], alt)[0]['actual']
            if actual_candidate != result['candidate_pattern']:
                raise ValueError('平板の案の高低不一致: '+row['name'])
            voice = dict(speaker=speaker, actual=record['check']['name_accents'][0]['actual'],
                         current_file=f'{index:02d}-speaker{speaker}-current.wav',
                         candidate_file=f'{index:02d}-speaker{speaker}-flat-candidate.wav')
            voice['current_duration'] = save(query, speaker, args.out/voice['current_file'], args.url)
            voice['candidate_duration'] = save(alt, speaker, args.out/voice['candidate_file'], args.url)
            result['voices'].append(voice)
        rows.append(result)
        print(index, row['name'], flush=True)
    (args.out/'samples.json').write_text(json.dumps(dict(round='name-accent-20261013-2', names=rows), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    (args.out/'index.html').write_text(render(rows), encoding='utf8')
    print(f'complete: {len(rows)} names / {len(rows)*4} WAVs')


if __name__ == '__main__':
    main()
