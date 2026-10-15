"""保存したソロ原稿を雨衣の口調へ。声の生成・接続・公開は行わない。"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import ui_tone


def prepare(source, out):
    import solo_host
    if solo_host.selected() != 'ui':
        raise ValueError('雨衣を選んだ実行だけで使えます')
    original = json.loads((source/'narration.json').read_text(encoding='utf8'))
    if solo_host.for_segments(original['segments'], 2) != 'ui':
        raise ValueError('保存原稿がめたんソロではありません')
    adapted = ui_tone.narration(original)
    if source.resolve() == out.resolve():
        raise ValueError('元の原稿は上書きせず、別の出力先を指定してください')
    out.mkdir(parents=True, exist_ok=True)
    def save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    save(out/'narration.json', adapted)
    if (source/'recap.json').exists():
        (out/'recap.json').write_bytes((source/'recap.json').read_bytes())
    # 本人の音声生成入口へ渡す依頼。WAVはまだ無いのでfile=None。
    save(out/'audio/manifest.json', dict(segments=[dict(seg, index=i, file=None, duration=0,
         voice_host='ui', voice_engine='voisona', voice_name='ui_ja_JP')
         for i, seg in enumerate(adapted['segments'])]))
    save(out/'tone-review.json', dict(source=str(source.resolve()), guidance=ui_tone.GUIDANCE,
         source_sha256=hashlib.sha256((source/'narration.json').read_bytes()).hexdigest(),
         examples=[dict(before=a['text'], after=b['text'])
                   for a,b in zip(original['segments'], adapted['segments'])]))
    return adapted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    # このコマンドの処理内だけの試作指定。本番や親プロセスの設定は変えない。
    os.environ['COLLESPO_SOLO_HOST'] = 'ui'
    result = prepare(args.source, args.out)
    print(f'雨衣原稿を保存: {args.out} / {len(result["segments"])}区間（声は未生成）')


if __name__ == '__main__':
    main()
