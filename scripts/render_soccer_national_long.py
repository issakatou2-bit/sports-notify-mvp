"""既存の週まとめ長編の札・字幕・BGM・描画器を代表の固定台本に適用する。"""
import argparse
import math
import os
from pathlib import Path
import sys
import wave

import soccer_national as n
import soccer_national_long as national
import render_soccer_weekly as weekly_render


def prepare(doc):
    national.validate_document(doc)
    import name_reading_guard
    name_reading_guard.validate_dialogue(doc)
    weekly_render.install(doc)
    weekly_render.preflight(doc)


def audio_duration(doc,manifest):
    """速める・途中で切る・空白を足すことで3〜4分に合わせない。"""
    import video_common
    rows=manifest['segments']
    if len(rows)!=len(doc['segments']):raise ValueError('長編の台本と音声の行数が一致しません')
    total=0
    for row,seg in zip(rows,doc['segments']):
        duration=float(row.get('duration') or 0)
        if (row.get('text')!=seg['text'] or row.get('speaker')!=seg['speaker'] or not row.get('file') or
                not Path(row['file']).is_file() or not math.isfinite(duration) or duration<=0):
            raise ValueError('長編の台本と音声が一致しないか、一部の声がありません')
        try:
            with wave.open(str(row['file']),'rb') as audio:
                measured=audio.getnframes()/audio.getframerate()
        except (OSError,EOFError,wave.Error) as error:
            raise ValueError('長編の実音声を測れません') from error
        if abs(measured-duration)>.02:raise ValueError('音声manifestと実際のWAVの長さが一致しません')
        row['duration']=measured
        row['panel']=seg['panel'];row['chapter']=seg['chapter']
        total+=max(1.6,measured+video_common.SEGMENT_TAIL)
    if not 180<=total<=240:
        raise ValueError(f'長編の実音声は{total:.1f}秒です。3〜4分に収まるよう原稿を見直してください')
    return total


def frames(doc,directory):
    prepare(doc)
    import longform_render_v3 as v3
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for index,(key,panel) in enumerate(doc['panels'].items()):
        seg=next(s for s in doc['segments'] if s['panel']==key)
        page=v3.paginate([seg])[0]
        image=v3.render_line(8,page,topic=doc['top'],panel=panel,panel_t=8,chapters=doc['chapters'],
                             chapter_t=8,progress=index/max(1,len(doc['panels'])-1),dur=10)
        image.save(directory/(key+'.png'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dialogue',required=True,type=Path)
    ap.add_argument('--frames',type=Path)
    ap.add_argument('--check',action='store_true')
    args,rest=ap.parse_known_args();doc=n.read(args.dialogue);prepare(doc)
    if args.frames:frames(doc,args.frames);return 0
    if args.check:return 0
    # 音声なしの本番動画は生成しない。静止画見本は上の--framesを使う。
    if '--require-audio' not in rest:raise ValueError('長編の動画は--require-audioが必要です')
    audio_dir=Path(rest[rest.index('--audio-dir')+1]) if '--audio-dir' in rest else Path('build/national_long/audio')
    manifest=n.read(audio_dir/'manifest.json');audio_duration(doc,manifest);n.save(audio_dir/'manifest.json',manifest)
    import generate_longform
    os.environ['COLLESPO_LONGFORM_STYLE']='v3'
    sys.argv=[sys.argv[0],'--dialogue',str(args.dialogue),*rest]
    result=generate_longform.main()
    if result==0:
        out=Path(rest[rest.index('--out')+1]) if '--out' in rest else Path('build/lf')
        n.save(out/'metadata.json',national.metadata(doc))
    return result


if __name__=='__main__':raise SystemExit(main())
