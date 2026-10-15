"""本人のPCから音声注文を取りに行く。タスク登録やVoiSonaの起動はしない。"""
import argparse
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys

import ui_voice_queue as q
import ui_voice_parts as parts_crypto

DEFAULT_APSC = 'C:/Users/issak/Desktop/apsc-video'


def available():
    # 認証なしのTCP確認だけ。起動していなければClientをimport/構築しない。
    try:
        with socket.create_connection(('127.0.0.1', 32766), timeout=1):
            return True
    except OSError:
        return False


@contextmanager
def single_worker(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'worker.lock').open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if (folder/'worker.lock').stat().st_size == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
        try:
            yield True
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def transcode(source, destination):
    r = subprocess.run([q.ffmpeg(), '-v', 'error', '-y', '-i', str(source), '-c:a', 'flac',
                        '-compression_level', '8', str(destination)], capture_output=True, timeout=120)
    if r.returncode:
        raise q.QueueError('音声の圧縮に失敗しました')


def portrait_payload(folder):
    """暗号化前のローカル部品。平文のままキューへ渡さない。"""
    from PIL import Image
    folder = folder.resolve()
    parts = json.loads((folder/'parts.json').read_text(encoding='utf8'))
    names = [parts['体']]+[name for key in ('右腕', '左腕', '眉', '目', '口') for name in parts[key].values()]
    mapping, files = {}, {}
    for i, name in enumerate(dict.fromkeys(names)):
        path = (folder/name).resolve()
        if not path.is_relative_to(folder) or path.suffix.lower() != '.png':
            raise q.QueueError('雨衣の部品の場所が不正です')
        with Image.open(path) as im:
            if im.size != tuple(parts['size']):
                raise q.QueueError('雨衣の部品の大きさが違います')
        mapping[name] = f'p{i:03d}.png'
        files[mapping[name]] = path.read_bytes()
    parts['体'] = mapping[parts['体']]
    for key in ('右腕', '左腕', '眉', '目', '口'):
        parts[key] = {k: mapping[v] for k, v in parts[key].items()}
    files['parts.json'] = q.encoded(parts)
    return files


def apsc_synthesizer(apsc):
    # APSCの実装・認証値は読まない。本人の既存Clientだけを使う。
    client = None

    def synthesize(text, destination):
        nonlocal client
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from notability_engine import apply_readings
        import name_reading_guard
        name_reading_guard.assert_known(text)
        # 出力先・パラメータはローカルコードで固定。注文のコマンドや設定は使わない。
        old_cwd = Path.cwd()
        os.chdir(apsc)
        try:
            sys.path.insert(0, str(apsc/'scripts'))
            vt = importlib.import_module('voisona_talk')
            if client is None:
                client = vt.Client()
            output = apsc/'build/ui_voice/collespo-queue'/destination.parent.name/destination.name
            output.parent.mkdir(parents=True, exist_ok=True)
            result = client.synthesize(vt.ui_say(apply_readings(text)), {}, output)
        finally:
            os.chdir(old_cwd)
        if Path(result).resolve() != output.resolve():
            raise q.QueueError('音声の出力先が違います')
        shutil.copyfile(result, destination)
    return synthesize


def process(queue, cache, synthesize, portraits, limit=10):
    """生成済み区間を保持し、返送に失敗しても同じ声を作り直さない。"""
    import wave
    secret = parts_crypto.key()
    # 合成より前に鍵・暗号依存・ローカル部品を確認する。
    parts_crypto.cipher(secret)
    parts_crypto.pack(portraits)
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    identity = cache/'identity.txt'
    if not identity.exists():
        import uuid
        identity.write_text(uuid.uuid4().hex, encoding='ascii')
    worker = identity.read_text(encoding='ascii')
    _, state, _ = queue.read()
    completed = 0
    for order in sorted(state.values(), key=lambda r: (r['stock'], r['created'])):
        if completed >= limit:
            break
        if order['status'] not in ('pending', 'working') or q.stamp(order['deadline']) <= q.now():
            continue
        key = order['id']

        def claim(rows, files):
            saved = rows.get(key, {})
            if (saved.get('status') not in ('pending', 'working') or
                    saved.get('worker', worker) != worker or q.stamp(saved['deadline']) <= q.now()):
                return False
            saved.update(status='working', worker=worker)
            return True
        if not queue.update(claim):
            continue
        folder = cache/key
        folder.mkdir(exist_ok=True)
        bundle = {}
        chunks = []
        for i, seg in enumerate(order['narration']['segments']):
            if q.now() >= q.stamp(order['deadline']):
                break
            wav = folder/f'seg_{i:03d}.wav'
            started = wav.with_suffix('.started')
            if not wav.exists():
                # 出力が残らなかった中断は再発注せず、この注文を破棄する。
                if started.exists():
                    q.terminal(queue, key, 'discarded')
                    print('[warn] 中断した注文を再生成せず破棄しました。次の注文へ進みます', file=sys.stderr)
                    break
                started.write_text('started', encoding='ascii')
                synthesize(seg['text'], wav)
            try:
                with wave.open(str(wav), 'rb') as audio:
                    if audio.getsampwidth() != 2 or not audio.getnframes() or audio.getframerate() > 96000:
                        raise ValueError('invalid PCM')
            except (OSError, wave.Error, ValueError, EOFError):
                q.terminal(queue, key, 'discarded')
                print('[warn] 不正な音声の注文を破棄しました。次の注文へ進みます', file=sys.stderr)
                break
            flac = wav.with_suffix('.flac')
            if not flac.exists():
                transcode(wav, flac)
            blob = flac.read_bytes()
            bundle[flac.name] = blob
            chunks.append(dict(file=flac.name, sha256=__import__('hashlib').sha256(blob).hexdigest()))
        else:
            result = dict(order=key, script_key=order['script_key'], voice_host='ui',
                          voice_engine='voisona', voice_name='ui_ja_JP', chunks=chunks)
            bundle['result.json'] = q.encoded(result)

            def deliver(rows, files):
                saved = rows.get(key, {})
                if (saved.get('status') != 'working' or saved.get('worker') != worker
                        or q.now() >= q.stamp(saved['deadline'])):
                    return False
                ref = parts_crypto.publish(files, portraits, secret)
                result['parts_ref'] = ref
                bundle['result.json'] = q.encoded(result)
                files.update({'payload/'+key+'/'+name: blob for name, blob in bundle.items()})
                saved.update(status='ready', parts_ref=ref)
                return True
            if queue.update(deliver):
                completed += 1
    return completed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apsc-root', type=Path, default=os.getenv('COLLESPO_APSC_ROOT', DEFAULT_APSC))
    p.add_argument('--cache', type=Path, default=q.ROOT/'build/ui-voice-worker')
    p.add_argument('--limit', type=int, default=10)
    args = p.parse_args()
    if not available():
        print('VoiSona Talk未起動のため終了')
        return
    with single_worker(args.cache) as acquired:
        if not acquired:
            return
        try:
            portraits = portrait_payload(args.apsc_root/'build/guest/ui')
            count = process(q.GitQueue(), args.cache, apsc_synthesizer(args.apsc_root.resolve()), portraits, args.limit)
            print(f'雨衣の声を返しました: {count}件')
        except Exception:
            # APSC側例外にも認証の詳細が混ざりうるので値/スタックを表示しない。
            print('音声の処理を完了できませんでした。VoiSona・注文キャッシュ・Git接続を確認してください', file=sys.stderr)
            raise SystemExit(1) from None


if __name__ == '__main__':
    main()
