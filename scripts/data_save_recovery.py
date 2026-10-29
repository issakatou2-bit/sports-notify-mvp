"""保存の前にJSONを控える。失敗時は動画IDと復旧用の場所だけをログに出す。"""
import json
import pathlib
import subprocess
import sys
import tempfile


def video_ids(value):
    if isinstance(value, dict):
        ids = {value['video_id']} if isinstance(value.get('video_id'), str) else set()
        return ids.union(*(video_ids(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(video_ids(item) for item in value))
    return set()


def snapshot(paths):
    root = pathlib.Path('build/data-save-recovery')
    root.mkdir(parents=True, exist_ok=True)
    target = pathlib.Path(tempfile.mkdtemp(prefix='save-', dir=root))
    ids = set()
    expanded = []
    for name in paths:
        path = pathlib.Path(name)
        expanded.extend(sorted(path.rglob('*.json')) if path.is_dir() else [path])
    for name in expanded:
        path = pathlib.Path(name)
        if path.is_absolute() or '..' in path.parts or not path.is_file() or path.suffix != '.json':
            continue
        value = json.loads(path.read_text(encoding='utf-8'))
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        old = subprocess.run(['git', 'show', f'HEAD:{path.as_posix()}'],
                             capture_output=True, encoding='utf-8')
        before = json.loads(old.stdout) if old.returncode == 0 else {}
        if path.name.startswith('published_'):
            ids |= video_ids(value) - video_ids(before)
        if old.returncode == 0:
            base = target / 'base' / path
            base.parent.mkdir(parents=True, exist_ok=True)
            base.write_text(old.stdout, encoding='utf-8')
    (target / 'video_ids.json').write_text(json.dumps(sorted(ids)), encoding='utf-8')
    return target


def report(target, reason='保存処理に失敗（理由未指定）', state='unsaved'):
    target = pathlib.Path(target)
    ids = json.loads((target / 'video_ids.json').read_text(encoding='utf-8'))
    if state != 'saved':
        for video in ids:
            print(f'::error::公開済みだが記録が保存できなかった：{video}')
    status = subprocess.run(['git', 'status', '--short'], capture_output=True,
                            encoding='utf-8', errors='replace')
    details = (f'{reason}\nrecords: {state}\nvideo_ids: {", ".join(ids)}\n'
               f'git status:\n{status.stdout}{status.stderr}')
    for name in ('push', 'pull', 'merge'):
        log = target / (name + '.log')
        if log.exists():
            details += f'\nlast {name}:\n' + log.read_text(encoding='utf-8', errors='replace')
    (target / 'FAILED').write_text(details, encoding='utf-8')
    print(f'::error::{reason}')
    print(f'::error::復旧用の記録：{target}')


if __name__ == '__main__':
    if sys.argv[1] == 'snapshot':
        print(snapshot(sys.argv[2:]))
    else:
        report(*sys.argv[2:])
