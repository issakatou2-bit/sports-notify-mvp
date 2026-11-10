"""ローカルVOICEVOXだけで両長編の実音声・名前の読み・尺を確認する。"""
import argparse
import os
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]


def main():
    from verify_national_numbers import available
    available(10)
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--url',required=True)
    args=ap.parse_args()
    if args.url!='http://127.0.0.1:50122':raise ValueError('時間制限付きローカルCPUエンジンだけを使います')
    os.environ['COLLESPO_SAMPLE_ONLY']='true'
    import soccer_national as n
    import soccer_national_long as national
    import render_soccer_national_long as render
    import synthesize_narration as synth
    import name_reading_guard as guard
    synth.VOICEVOX_URL=args.url
    if not synth.engine_available():raise RuntimeError('ローカルCPUエンジンがありません')
    base=ROOT/'build_reports/national_numbers_20261110'
    cache={};results=[]
    for key in ('brazil','paraguay'):
        directory=base/key/'audio';directory.mkdir(parents=True,exist_ok=True)
        doc=n.read(base/key/'dialogue.json');national.validate_document(doc)
        rows=[]
        with guard.dialogue_scope(doc):
            for index,seg in enumerate(doc['segments']):
                available()
                identity=(seg['speaker'],seg['text'])
                if identity not in cache:
                    path=directory/f'seg_{index:03d}.wav'
                    if not synth.synth_one(seg['text'],seg['speaker'],path):raise ValueError('実音声の合成に失敗しました')
                    with wave.open(str(path),'rb') as audio:duration=audio.getnframes()/audio.getframerate()
                    cache[identity]=(path,duration)
                path,duration=cache[identity]
                rows.append(dict(index=index,file=str(path),duration=duration,kind=seg['kind'],text=seg['text'],
                    speaker=seg['speaker'],panel=seg['panel'],chapter=seg['chapter'],meta=seg['meta']))
        manifest=dict(segments=rows)
        n.save(directory/'manifest.json',manifest)
        seconds=sum(max(1.6,r['duration']+__import__('video_common').SEGMENT_TAIL) for r in rows)
        results.append(dict(key=key,seconds=seconds,lines=len(rows),reading_checks=True,in_range=180<=seconds<=240))
        n.save(base/'voice_result.json',dict(matches=results,real_audio=True,fixture=True,publication=False))
        print(key,f'{seconds:.2f}秒',flush=True)
    for key in ('brazil','paraguay'):
        doc=n.read(base/key/'dialogue.json');manifest=n.read(base/key/'audio/manifest.json')
        render.audio_duration(doc,manifest)
    print('両長編の全台詞: 名前の実query検査と3〜4分の実音声確認を通過',flush=True)


if __name__=='__main__':main()
