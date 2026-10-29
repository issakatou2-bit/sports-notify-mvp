#!/usr/bin/env python3
"""#269の実フレーム記録を#267へ接続する。外部通信・音声抽出はしない。"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import subprocess

import gemini_av_check as av


def load(path):
    value = av.read_json(av.checked_path(path))
    if not isinstance(value, dict):
        raise av.CheckError('入力JSONの最上位はobjectが必要です')
    return value


def frame_rows(rows, fps, count, label):
    if not isinstance(rows, list) or not rows:
        raise av.CheckError(label + 'の実フレーム記録がありません')
    cursor = 0
    for row in rows:
        if not isinstance(row, dict):
            raise av.CheckError(label + 'の行がobjectではありません')
        start, end = row.get('start_frame'), row.get('end_frame')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= count:
            raise av.CheckError(label + 'のフレーム範囲が不正です')
        if start != cursor:
            raise av.CheckError(label + 'に抜け・重なり・順序違いがあります（補間しません）')
        for key, frame in (('start', start), ('end', end)):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value-frame/fps) > 1e-7:
                raise av.CheckError(label + 'の秒と実フレームが一致しません')
        cursor = end
    if cursor != count:
        raise av.CheckError(label + 'が完成動画の末尾までありません')


def timeline(record, voice, video_hash, voice_hash, duration):
    if record.get('version') != 1 or voice.get('version') != 1:
        raise av.CheckError('記録はversion=1が必要です')
    if record.get('video_sha256') != video_hash or record.get('voice_manifest_sha256') != voice_hash:
        raise av.CheckError('動画・音声manifestと描画記録の指紋が一致しません')
    fps, count = record.get('fps'), record.get('frame_count')
    if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0 or type(count) is not int or count <= 0:
        raise av.CheckError('fps・完成フレーム数が不正です')
    if abs(count/fps-duration) > .08:
        raise av.CheckError('完成mp4の尺と実フレームの尺が一致しません')
    for name in ('lines', 'cuts', 'subtitles'):
        frame_rows(record.get(name), fps, count, name)
    av.validate_timeline(record, duration)
    segments = voice.get('segments')
    if not isinstance(segments, list) or not segments:
        raise av.CheckError('音声manifestの行がありません')
    sources = {}
    for row in segments:
        ident = row.get('line_id')
        if type(ident) is not int or ident < 1 or ident in sources or not isinstance(row.get('text'), str):
            raise av.CheckError('音声manifestの元行番号・本文が不正です')
        sources[ident] = row
    result = dict(version=1, lines=copy.deepcopy(record['lines']), cuts=[],
                  subtitles=copy.deepcopy(record['subtitles']),
                  record_video_sha256=video_hash)
    used = set()
    for line in result['lines']:
        ids = line.get('source_line_ids')
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in sources for i in ids):
            raise av.CheckError('描画行と音声manifestの元行が対応しません')
        expected = '\n'.join(dict.fromkeys(sources[i]['text'] for i in ids))
        if line.get('text') != expected:
            raise av.CheckError('描画行と保存音声の本文が一致しません')
        used.update(ids)
        pages = [p for p in result['subtitles'] if p['start_frame'] >= line['start_frame']
                 and p['end_frame'] <= line['end_frame']]
        if not pages or pages[0]['start_frame'] != line['start_frame'] or pages[-1]['end_frame'] != line['end_frame']:
            raise av.CheckError('字幕ページが行境界をまたぐか欠けています')
        if any(p.get('source_line_ids') != ids or not isinstance(p.get('subtitle'), str) for p in pages):
            raise av.CheckError('字幕ページと元行が対応しません')
        line['subtitle_pages'] = pages
        line['subtitle'] = '\n'.join(dict.fromkeys(p['subtitle'] for p in pages if p['subtitle']))
        # 音声durationから字幕の予定差や台詞の分割時刻を作らない。
    if used != set(sources):
        raise av.CheckError('描画されていない音声行があります')
    # 字幕ページの実切替も全カット検査の対象にする。声の行は分割しない。
    for cut in record['cuts']:
        for page in result['subtitles']:
            start = max(cut['start_frame'], page['start_frame'])
            end = min(cut['end_frame'], page['end_frame'])
            if start < end:
                result['cuts'].append(dict(cut_id=len(result['cuts'])+1,
                    source_cut_id=cut['cut_id'], start_frame=start, end_frame=end,
                    start=start/fps, end=end/fps, screen=cut['screen'],
                    subtitle=page['subtitle'], source_line_ids=page['source_line_ids'],
                    intentional=cut.get('intentional', '') + '。字幕ページの実切替も検査'))
    av.validate_timeline(result, duration)
    return result


def provenance(review_path, video, script_path, record_path, voice_path, voice, script):
    # 保存時の予定・受領記録を一切除去しない。音声ファイルを開く前に拒否。
    av.deny_markers([voice, load(record_path)])
    if not review_path:
        raise av.CheckError('送れない：描画コード・全画面・全素材の出所確認 --review がありません')
    review_path = av.checked_path(review_path)
    review = load(review_path)
    av.deny_markers(review)
    if review.get('video_sha256') != av.sha256(video) or review.get('render_timeline_sha256') != av.sha256(record_path):
        raise av.CheckError('送れない：出所確認がこの完成動画・描画記録に対応しません')
    if review.get('all_assets_accounted_for') is not True:
        raise av.CheckError('送れない：全素材の出所が確定していません')
    code = review.get('drawing_code')
    if not isinstance(code, list) or not code:
        raise av.CheckError('送れない：描画コードの根拠がありません')
    for item in code:
        path = av.checked_path(review_path.parent / item['path'])
        if path.suffix != '.py' or not item.get('evidence') or av.sha256(path) != item.get('sha256'):
            raise av.CheckError('送れない：描画コードの版・内容の確認が不足しています')
        item['path'] = str(path)
    if set(review.get('reviewed_cut_ids', [])) != {c['cut_id'] for c in script['cuts']}:
        raise av.CheckError('送れない：字幕ページを含む全画面の確認が不足しています')
    assets = copy.deepcopy(review.get('assets', []))
    for item in assets:
        path = av.checked_path(review_path.parent / item['path'])
        normalized = path.as_posix().casefold()
        # ASSET_PROVENANCEの公式/混在/不明を自己申告で自作へ変えない。
        if '/assets/' in normalized or item.get('classification') != 'self_created':
            raise av.CheckError('送れない：公式・混在・外部・不明素材は対象外です')
        item['path'] = str(path)
    for seg in voice['segments']:
        if seg.get('voice_engine') != 'voicevox' or seg.get('speaker') not in (2, 3):
            raise av.CheckError('送れない：許可されたVOICEVOXの実声記録ではありません')
        path = av.checked_path(voice_path.parent / seg['file'])
        if av.sha256(path) != seg.get('sha256'):
            raise av.CheckError('送れない：保存音声の指紋が一致しません')
        assets.append(dict(kind='voicevox', path=str(path), sha256=seg['sha256'],
                           engine='voicevox', speaker=seg['speaker'], self_created=True,
                           evidence='保存manifestの実声・元行・指紋を照合'))
    return dict(version=1, video_sha256=av.sha256(video), script_sha256=av.sha256(script_path),
                review=review.get('review', {}), assets=assets,
                audio_manifests=[dict(path=str(voice_path), sha256=av.sha256(voice_path))],
                drawing_code=code, render_timeline_sha256=av.sha256(record_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--render-timeline', required=True)
    parser.add_argument('--voice-manifest', required=True)
    parser.add_argument('--review', help='同じ完成版について人がコード・全画面・素材を確認したJSON')
    parser.add_argument('--out', required=True)
    parser.add_argument('--ffprobe', default='ffprobe')
    args = parser.parse_args(argv)
    out = av.checked_path(args.out)
    if out.exists() and any(out.iterdir()):
        print('送れない：新しい空の出力先を指定してください', file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    stage = 'timeline'
    try:
        video, record_path, voice_path = map(av.checked_path, (args.video, args.render_timeline, args.voice_manifest))
        record, voice = load(record_path), load(voice_path)
        script = timeline(record, voice, av.sha256(video), av.sha256(voice_path), av.media_probe(video, args.ffprobe))
        av.write_json(out/'timeline.json', script)
        stage = 'provenance'
        prov = provenance(args.review, video, out/'timeline.json', record_path, voice_path, voice, script)
        # 既存の送信境界と同じ検査を適用してから正式な出所JSONを作る。
        av.validate_sources(video, out/'timeline.json', out/'provenance.json', provenance_data=prov)
        av.write_json(out/'provenance.json', prov)
        av.write_json(out/'conversion.json', dict(status='ready_for_preflight', external_calls=False))
        return 0
    except (av.CheckError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, av.CheckError) else type(exc).__name__
        av.write_json(out/'conversion.json', dict(status='blocked', stage=stage, reason=reason, external_calls=False))
        print(reason if reason.startswith('送れない') else '送れない：' + reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
