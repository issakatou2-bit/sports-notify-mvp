"""固定の試験材料で予告→結果を再現。投稿・通信なし。"""
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import bignumber_render as bn
import generate_morning_short as g
import mlb_forecast as f
import review_render_v3 as r3


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=Path('build/mlb-forecast-preview'))
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    fixture=json.loads((Path(__file__).parent/'fixtures/mlb-forecast/roundtrip.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as td,patch.dict('os.environ',COLLESPO_MLB_FORECAST='check'):
        for i,row in enumerate(fixture['samples']):Path(td,f'{i}.json').write_text(json.dumps(row),encoding='utf-8')
        narration=f.decorate(dict(segments=[dict(kind='game',text='山本由伸の先発です。',meta=dict(game_index=0))]),
                             [fixture['game']],fixture['created_at'],td)
        published={'daily':{'2026-09-22':dict(video_id='fixture-not-published',preview_binding=f.binding(narration))}}
        history={'2026-09-23':f.snapshot(narration,published)}
        answer=f.answer(fixture['result'],history)
        with patch.object(f,'read',return_value=history),patch.object(g,'week_line',return_value=('',[])):
            result=g.build_narration(fixture['result'],'players')
        bn._no_network()
        scenes=bn.scenes_from_morning(fixture['result'],result)
        scene=dict(scenes[0],label='固定の試験材料　9月23日',source='固定の試験材料（実試合の出力ではない）')
        r3.set_program_clock(0);r3.set_caption(result['segments'][0]['text'],7,7)
        r3.set_program_clock(2.5)
        im=bn.scene(2.5,scene);im.save(args.out/'answer.png')
        r3.set_program_clock(None)
        (args.out/'confirmation.json').write_text(json.dumps(dict(note=fixture['note'],preview=narration,
            saved=history,answer=answer,morning=result),ensure_ascii=False,indent=2),encoding='utf-8')
    print('固定の予告→結果を保存:',args.out)


if __name__=='__main__':main()
