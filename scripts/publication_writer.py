"""P1の二重書き。旧記録を保存してから呼ぶ。失敗は公開処理へ返さない。

読取入口publicationsはP0のまま。未確定のpendingを投稿許可に変えない。
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from ledger_adapter import convert
from publications import DATE_FIELDS, ROOT, identity


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def relative_path(obs):
    domain = obs['domain']
    if not re.fullmatch(r'[a-z][a-z0-9_-]*', domain):
        raise ValueError('unsafe domain')
    pid = obs['publication_id']
    name = re.sub(r'[^A-Za-z0-9_-]', '_', pid)[:90] + '-' + digest(pid)[:24]
    return Path('data/publications') / domain / (name + '.json')


def event(obs):
    # 題・本文・API応答全体は写さない。時刻の変化だけで履歴を増やさない。
    raw = obs.get('raw', {})
    details = {k: deepcopy(raw[k]) for k in (
        'privacy', 'held', 'status', 'publish_id', 'public_post_ids',
        'publicly_available', 'uri', 'post_id', 'sha256', 'player_id',
        'player_week_start', 'preview_binding', 'rkey', 'original_video_id',
        'replacement_video_id', 'source_run') if k in raw}
    item = {k: deepcopy(obs.get(k)) for k in (
        'source', 'service', 'video_id', 'state', 'scheduled_at', *DATE_FIELDS)}
    item.update(details=details, run_id=os.environ.get('GITHUB_RUN_ID'),
                attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
                recorded_at=datetime.now(timezone.utc).isoformat())
    if obs.get('original_video_id'):
        item['original_video_id'] = obs['original_video_id']
        item['original_publication_id'] = obs.get('original_publication_id')
    item['fingerprint'] = digest({k: v for k, v in item.items()
                                  if k not in ('run_at', 'run_id', 'attempt', 'recorded_at')})
    return item


def append(document, obs):
    ident = {k: deepcopy(obs[k]) for k in ('publication_id', 'domain', 'kind', 'key_parts')}
    result = deepcopy(document) if document is not None else dict(ident, version=1, history=[])
    if any(result[k] != v for k, v in ident.items()):
        raise ValueError('publication identity mismatch')
    item = event(obs)
    previous = next((x for x in reversed(result['history'])
                     if x['source'] == item['source'] and x['service'] == item['service']), None)
    if previous and previous['state'] == 'public_confirmed' and item['state'] == 'uploaded':
        # 同じ旧snapshotの再読だけで、実確認の確かさを下げない。
        confirmed = dict(item, state='public_confirmed')
        confirmed['fingerprint'] = digest({k: v for k, v in confirmed.items()
                                          if k not in ('run_at', 'run_id', 'attempt', 'recorded_at', 'fingerprint')})
        if confirmed['fingerprint'] == previous['fingerprint']:
            return result, False
    if previous and previous['fingerprint'] == item['fingerprint']:
        return result, False
    predecessor = result['history'][-1]['event_id'] if result['history'] else None
    item['event_id'] = digest([predecessor, item['fingerprint']])
    result['history'].append(item)
    return result, True


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def write(obs, root=ROOT):
    path = Path(root) / relative_path(obs)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    # 別の回は別lock。同じ回もread/append/replaceを一続きにする。
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            # Windowsでは他スレッドのunlink直後にもdelete-pendingでEACCESになる。
            time.sleep(.05)
    else:
        raise TimeoutError('publication lock unavailable')
    try:
        document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        result, changed = append(document, obs)
        if changed:
            atomic_json(path, result)
        return path
    finally:
        os.close(fd)
        lock.unlink()


def recover(obs, error, root=ROOT):
    # 例外の本文には認証情報が含まれ得るため型だけを残す。
    safe = {k: deepcopy(v) for k, v in obs.items() if k not in ('raw', 'repair')}
    safe['event'] = event(obs)
    record = dict(observation=safe, error_type=type(error).__name__,
                  next_action='旧記録とサービス側を照合して台帳だけ回収。自動再投稿は禁止')
    path = Path(root) / 'data/publication_recovery' / (digest(safe['event']['fingerprint']) + '.json')
    print(f'::warning::新公開台帳の保存失敗 ({type(error).__name__})。旧記録を保持、回収先 {path.name}',
          file=sys.stderr)
    try:
        atomic_json(path, record)
    except Exception as failure:
        # ディスク全体の書込不能でも、runnerログから鍵と状態を回収できる。
        print('::warning::公開台帳回収 ' + json.dumps(record, ensure_ascii=False) +
              ' recovery_error=' + type(failure).__name__, file=sys.stderr)


def normalized(obs):
    obs = deepcopy(obs)
    raw = obs.get('raw', {})
    if obs['service'] == 'tiktok' and (raw.get('outcome') == 'pending' or
                                      (raw.get('publish_id') and not raw.get('status'))):
        obs['state'] = 'upload_pending'
    if obs['service'] == 'youtube':
        if raw.get('publish_at'):
            obs['state'] = 'scheduled'
        elif raw.get('held') or raw.get('privacy') in ('private', 'unlisted'):
            obs['state'] = 'held'
    return obs


def mirror_documents(documents, *, root=ROOT, verified=False):
    try:
        observations = convert(documents)
    except Exception as error:
        # 変換失敗でも旧JSONに戻れるよう、公開の鍵を持つ最小記録を残す。
        obs = dict(identity('delivery', 'conversion_error', {'document_hash': digest(documents)}),
                   source='conversion', service='unknown', state='unknown',
                   legacy_documents=sorted(documents), raw={}, **{f: None for f in DATE_FIELDS})
        recover(obs, error, root)
        return
    for obs in observations:
        obs = normalized(obs)
        if verified and obs['service'] == 'youtube' and obs['raw'].get('privacy') == 'public':
            obs['state'] = 'public_confirmed'
        try:
            write(obs, root)
        except Exception as error:
            recover(obs, error, root)


def root_for(path):
    path = Path(path).resolve()
    return path.parent.parent if path.parent.name == 'data' else path.parent


def mirror_file(path, *, root=None, verified=False, ledger_name=None):
    path = Path(path)
    root = Path(root) if root is not None else root_for(path)
    try:
        name = ledger_name or path.stem
        docs = {name: json.loads(path.read_text(encoding='utf-8'))}
        # Blueskyは元YouTube IDが一意なときだけ同じ公開IDに結合する。
        if name == 'bluesky_delivery':
            for name in ('published_videos', 'published_assets'):
                source = root / 'data' / (name + '.json')
                if source.exists():
                    docs[name] = json.loads(source.read_text(encoding='utf-8'))
            rows = [o for o in convert(docs) if o['service'] == 'bluesky']
            for obs in rows:
                try:
                    write(obs, root)
                except Exception as error:
                    recover(obs, error, root)
            return
        mirror_documents(docs, root=root, verified=verified)
    except Exception as error:
        obs = dict(identity('delivery', 'file_error', {'file': path.name}),
                   source=path.stem, service='unknown', state='unknown', raw={},
                   **{f: None for f in DATE_FIELDS})
        recover(obs, error, root)


def buffer_observation(key, raw):
    # Bufferの鍵は日次以外にasset等もあるので、文字列を日付に流用しない。
    service = key.rsplit(':', 1)[-1]
    ident = identity('delivery', 'buffer', {'delivery_key': key})
    state = raw.get('state')
    st = ('distributed' if state == 'sent' else 'upload_pending' if state in ('reserved', 'sending')
          else 'error' if state in ('error', 'rejected') else 'scheduled' if state == 'scheduled'
          else 'uploaded' if raw.get('post_id') or raw.get('uri') else 'unknown')
    return dict(ident, source='buffer_delivery/deliveries/' + key, service=service,
                video_id=raw.get('youtube_id'), state=st, raw=raw,
                original_video_id=raw.get('youtube_id'),
                original_publication_id=None, scheduled_at=None,
                event_day=None, material_day=None, edition_day=None,
                run_at=raw.get('updated_at') or raw.get('reserved_at'))


def mirror_buffer(key, raw, github, branch, *, root=ROOT):
    """Buffer旧台帳と同じ状態枝に保存。新しい失敗で旧予約・投稿を止めない。"""
    import base64
    from urllib.error import HTTPError
    obs = buffer_observation(key, raw)
    path = relative_path(obs).as_posix()
    try:
        originals = {}
        for name in ('published_videos', 'published_assets'):
            original_path = Path(root) / 'data' / (name + '.json')
            if original_path.exists():
                for original in convert({name: json.loads(original_path.read_text(encoding='utf-8'))}):
                    if obs['video_id'] and original['video_id'] == obs['video_id']:
                        originals[original['publication_id']] = original
        if len(originals) == 1:
            obs['original_publication_id'] = next(iter(originals))
        try:
            saved = github('/contents/' + path + '?ref=' + branch)
            old = json.loads(base64.b64decode(saved['content']))
            sha = saved['sha']
        except HTTPError as error:
            if error.code != 404:
                raise
            old, sha = None, None
        result, changed = append(old, obs)
        if changed:
            body = dict(message='Record publication delivery history', branch=branch,
                        content=base64.b64encode(json.dumps(result, ensure_ascii=False).encode()).decode())
            if sha:
                body['sha'] = sha
            github('/contents/' + path, 'PUT', body)
    except Exception as error:
        recover(obs, error, root)


def mirror_visibility(video_id, saved, *, root=ROOT):
    """訂正で旧台帳から外れた動画も、履歴内の同じ公開IDへ追記する。"""
    try:
        matches = {}
        for path in (Path(root) / 'data/publications').glob('*/*.json'):
            doc = json.loads(path.read_text(encoding='utf-8'))
            if any((x.get('video_id') == video_id or x.get('details', {}).get('original_video_id') == video_id)
                   and x['service'] == 'youtube' for x in doc['history']):
                matches[doc['publication_id']] = {k: doc[k] for k in
                    ('publication_id', 'domain', 'kind', 'key_parts')}
        for name in ('published_videos', 'published_assets'):
            path = Path(root) / 'data' / (name + '.json')
            if path.exists():
                for obs in convert({name: json.loads(path.read_text(encoding='utf-8'))}):
                    if obs['video_id'] == video_id:
                        matches[obs['publication_id']] = {k: obs[k] for k in
                            ('publication_id', 'domain', 'kind', 'key_parts')}
        if not matches:
            ident = identity('delivery', 'youtube', {'video_id': video_id})
            matches[ident['publication_id']] = ident
        for ident in matches.values():
            raw = dict(video_id=video_id, privacy=saved.get('privacyStatus'),
                       publish_at=saved.get('publishAt'))
            st = ('scheduled' if raw['publish_at'] else 'public_confirmed' if raw['privacy'] == 'public'
                  else 'held')
            obs = dict(ident, source='visibility/' + video_id, service='youtube',
                       video_id=video_id, state=st, raw=raw, scheduled_at=raw['publish_at'],
                       **{f: None for f in DATE_FIELDS})
            try:
                write(obs, root)
            except Exception as error:
                recover(obs, error, root)
    except Exception as error:
        obs = dict(identity('delivery', 'youtube', {'video_id': video_id}),
                   source='visibility/' + video_id, service='youtube', video_id=video_id,
                   state='unknown', raw={}, **{f: None for f in DATE_FIELDS})
        recover(obs, error, root)


def mirror_correction(fix, video_id, *, root=ROOT):
    # 公開APIの確認をしていない段ではuploadedより先へ進めない。
    from ledger_adapter import observation
    raw = dict(video_id=video_id, original_video_id=fix['old_video'],
               replacement_video_id=video_id)
    obs = observation('asset', fix['topic'], raw, 'correction/' + fix['topic'])
    try:
        write(obs, root)
    except Exception as error:
        recover(obs, error, root)
