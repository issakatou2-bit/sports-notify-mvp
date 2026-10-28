"""実ファイルの声の出所だけを記録する。送信可否の判定はしない。"""
import hashlib
import json
from pathlib import Path
import re
import wave


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pending.replace(path)


def plan(data):
    """作り直す前の雨衣予定も保持。呼出時の環境から実声を推測しない。"""
    result = {key: data[key] for key in ('host_assignment', 'host_delivery', 'voice_resolution') if key in data}
    delivery = data.get('host_delivery') or data.get('host_assignment') or {}
    previous = delivery
    while isinstance(previous.get('previous_attempt'), dict):
        previous = previous['previous_attempt']
    result['planned_host'] = previous.get('planned_host', delivery.get('planned_host'))
    return result


def row(segment, index, directory, engine, planned=None):
    source = Path(segment['file']).resolve() if segment.get('file') else None
    exists = source is not None and source.is_file()
    sid = segment.get('speaker')
    key = segment.get('speaker_key') or {2: 'metan', 3: 'zundamon'}.get(sid, str(sid) if sid is not None else None)
    duration = float(segment.get('duration') or 0)
    if exists:
        with wave.open(str(source), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
    import os
    return dict(index=index, line_id=index + 1, speaker_key=key,
                voice_engine=engine if exists else None,
                speaker=sid if engine == 'voicevox' and exists else None,
                source_speaker=sid, actual_voice_key=('ui' if engine == 'voisona' else key) if exists and engine else None,
                planned_host=(planned or {}).get('planned_host'),
                planned_engine=('voisona' if (planned or {}).get('planned_host') == 'ui' else
                                'voicevox' if (planned or {}).get('planned_host') == 'metan' else engine),
                file=Path(os.path.relpath(source, Path(directory).resolve())).as_posix() if exists else None,
                duration=duration if exists else 0.0, sha256=sha256(source) if exists else None,
                text=segment.get('text', ''), status=('created' if engine else 'unknown') if exists else 'unavailable')


def save(directory, segments, data=None, default_engine='voicevox', status='complete'):
    """記録は確認用。失敗しても音声づくりは止めず、警告だけ出す。"""
    try:
        return _save(directory, segments, data, default_engine, status)
    except Exception as exc:
        print(f'::warning::声の出所の記録を保存できませんでした（{type(exc).__name__}: {exc}）')
        return None


def _save(directory, segments, data=None, default_engine='voicevox', status='complete'):
    directory = Path(directory)
    planned = plan(data or {})
    rows = [row(seg, seg.get('index', i), directory,
                seg.get('voice_engine', default_engine), planned)
            for i, seg in enumerate(segments)]
    payload = dict(version=1, status=status, segments=rows, **planned)
    write_json(directory / 'voice_manifest.json', payload)
    return payload


def record_file(destination, text, engine, speaker=None, *, index=None, planned=None):
    try:
        return _record_file(destination, text, engine, speaker, index=index, planned=planned)
    except Exception as exc:
        print(f'::warning::声の出所の記録を書き足せませんでした（{type(exc).__name__}: {exc}）')
        return None


def _record_file(destination, text, engine, speaker=None, *, index=None, planned=None):
    """共通関数の単独利用も記録する。呼出元の最終saveで全行の予定と結合する。"""
    path = Path(destination)
    target = path.parent / 'voice_manifest.json'
    saved = json.loads(target.read_text(encoding='utf-8')) if target.exists() else dict(version=1, segments=[])
    saved['status'] = 'partial'
    # 同じ行を短縮して作り直すseg_003_short.wavも元の行へ戻す。
    match = re.fullmatch(r'seg_(\d+)(?:_.*)?', path.stem)
    supplied = index is not None
    index = index if supplied else int(match[1]) if match else max((r['index'] for r in saved['segments']), default=-1) + 1
    existing = next((r for r in saved['segments'] if r.get('file') == path.name or r['index'] == index), None)
    if existing and not match and not supplied:
        index = existing['index']
    if planned is not None:
        saved.update(plan(planned))
    intended = dict(planned_host=(saved.get('planned_host') if planned is not None else None)
                    or (existing or {}).get('planned_host') or saved.get('planned_host'))
    item = row(dict(file=str(path), text=text, speaker=speaker), index, path.parent, engine, intended)
    saved['segments'] = [r for r in saved['segments'] if r['index'] != index and r.get('file') != path.name] + [item]
    saved['segments'].sort(key=lambda r: r['index'])
    write_json(target, saved)
