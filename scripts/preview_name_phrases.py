"""日本人氏名を一つなぎにした見本WAVと補正前後query。利用者辞書は触らない。"""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import wave

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import name_reading_guard as guard
import synthesize_narration as sn


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--url',default='http://127.0.0.1:50121')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    sn.VOICEVOX_URL=args.url;records=[]
    old_readings=json.loads(subprocess.check_output(['git','show','e4140012:data/player_kana.json'],cwd=ROOT))['readings']
    names=('鎌田大地','上田綺世','大谷翔平','山本由伸','三笘薫')
    for index,name in enumerate(names):
        for speaker in (2,3):
            text=name+'が出場します。';path=args.out/f'{index+1:02d}-speaker{speaker}.wav'
            if not sn.synth_one(text,speaker,path):raise RuntimeError('見本の合成に失敗')
            with wave.open(str(path)) as audio:
                if not audio.getnframes():raise RuntimeError('空の音声')
                duration=audio.getnframes()/audio.getframerate()
            reading=guard.player_readings()[name]
            # 姓名境界は旧main辞書から取得して比較する。生成物は見本フォルダだけ。
            old=old_readings[name]
            reply=requests.post(args.url+'/audio_query',params=dict(text=old+'が出場します。',speaker=speaker),timeout=30)
            reply.raise_for_status();before=reply.json()
            before['speedScale']=sn.SPEED_SCALE
            for key,value in {'prePhonemeLength':sn.PRE_PHONEME,'postPhonemeLength':sn.POST_PHONEME,
                              'pauseLengthScale':sn.PAUSE_SCALE,**sn.SPEAKER_TUNE[speaker]}.items():
                if key in before:before[key]=value
            sound=requests.post(args.url+'/synthesis',params=dict(speaker=speaker),json=before,timeout=120)
            sound.raise_for_status();before_path=path.with_name(path.stem+'-before.wav');before_path.write_bytes(sound.content)
            records.append(dict(name=name,speaker=speaker,reading=reading,file=path.name,
                                before_file=before_path.name,duration=duration,before_query=before))
    version=requests.get(args.url+'/version',timeout=5);version.raise_for_status()
    (args.out/'samples.json').write_text(json.dumps(dict(engine_version=version.json(),samples=records),ensure_ascii=False,indent=2),encoding='utf8')
    html='<!doctype html><meta charset="utf-8"><title>氏名をつなげる読み</title><style>body{font:18px system-ui;max-width:850px;margin:24px auto}audio{display:block;margin:8px 0}</style><h1>氏名をつなげる読み</h1><p>VOICEVOX 四国めたん(2) / ずんだもん(3)。本人の聴き比べ用。</p>'
    for r in records:
        html+=f'<h2>{r["name"]} 話者{r["speaker"]}</h2><p>以前</p><audio controls src="{r["before_file"]}"></audio><p>一つなぎ</p><audio controls src="{r["file"]}"></audio>'
    (args.out/'index.html').write_text(html,encoding='utf8')
    print('5 names / 2 speakers / 10 joined WAV + 10 before WAV PASS')


if __name__=='__main__':main()
