"""音声専用枝のスナップショット。注文はデータだけ。コードを取得・実行しない。"""
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'ui-voice-queue'
MAX_BYTES = 90 * 1024 * 1024
PARTS_MAGIC = b'COLLESPO-UI-PARTS-AES256GCM-v1\0'
PARTS_REF = r'parts/[a-f0-9]{64}\.aesgcm'
UI_CREDIT = 'VoiSona Talk 雨衣 / ©Ui Shigure / ©INCOLORE'


class QueueError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def ffmpeg():
    tool = shutil.which('ffmpeg')
    if tool:
        return tool
    try:
        # ffmpegがないPCだけで使う任意の補助。Actionsの通常の依存にはしない。
        return importlib.import_module('imageio_ffmpeg').get_ffmpeg_exe()
    except ImportError:
        raise QueueError('PCにffmpegまたはimageio_ffmpegが必要です') from None


def script_key(narration):
    # labelや取得時刻は音声の同一性に含めない。数字・所属・札はmetaも含め照合。
    return digest(narration['segments'])


def validate_order(order):
    if (order.get('voice_host'), order.get('voice_engine'), order.get('voice_name')) != ('ui', 'voisona', 'ui_ja_JP'):
        raise QueueError('注文の実話者が雨衣ではありません')
    if not re.fullmatch(r'[a-f0-9]{64}', order['id']):
        raise QueueError('注文番号が不正です')
    segments = order['narration']['segments']
    if not 1 <= len(segments) <= 120 or len(encoded(order)) > 1024 * 1024:
        raise QueueError('注文が大きすぎます')
    if script_key(order['narration']) != order['script_key']:
        raise QueueError('原稿の指紋が違います')
    for seg in segments:
        if (str(seg.get('speaker', 3)) != '2' or (seg.get('meta') or {}).get('duo')
                or not isinstance(seg.get('text'), str) or not 1 <= len(seg['text']) <= 4000):
            raise QueueError('雨衣ソロの注文ではありません')
    if stamp(order['deadline']).tzinfo is None or stamp(order['created']).tzinfo is None:
        raise QueueError('注文の時刻に時差がありません')


def make_order(narration, episode, minutes=15, stock=False, at=None):
    at = at or now()
    key = script_key(narration)
    # Actions再実行も同じrun_id/episode。別の回や週の仕込みは別番号。
    identity = dict(script=key, episode=episode, stock=stock,
                    run=os.getenv('GITHUB_RUN_ID', at.date().isoformat()))
    result = dict(id=digest(identity), episode=episode, narration=copy.deepcopy(narration),
                  script_key=key, created=at.isoformat(), deadline=(at+timedelta(minutes=minutes)).isoformat(),
                  stock=stock, status='pending', voice_host='ui', voice_engine='voisona', voice_name='ui_ja_JP')
    validate_order(result)
    return result


def validate_file(path, blob):
    """公開treeの許可形式。平文の公式PNG/parts.jsonは読書きとも拒否。"""
    if blob.startswith(b'\x89PNG'):
        raise QueueError('公開キューに平文の画像は保存できません')
    if re.fullmatch(PARTS_REF, path):
        if not blob.startswith(PARTS_MAGIC) or len(blob) < len(PARTS_MAGIC)+28:
            raise QueueError('立ち絵は暗号化が必要です')
    elif path == 'worker-health.json':
        health = json.loads(blob)
        if (health.get('version') != 1 or health.get('status') not in ('ready', 'unavailable', 'blocked', 'failed')
                or stamp(health['checked_at']).tzinfo is None or len(blob) > 512):
            raise QueueError('係の確認時刻が不正です')
    elif path == 'parts/current.json':
        if not re.fullmatch(PARTS_REF, json.loads(blob).get('ref', '')):
            raise QueueError('共用部品の参照が不正です')
    elif not re.fullmatch(r'payload/[a-f0-9]{64}/(seg_[0-9]{3}\.flac|result\.json)', path):
        raise QueueError('音声専用枝に未知のファイルがあります')


def compact(state, files):
    # 最新の1組は次の注文にも再利用。旧版はready在庫の参照がある間だけ保持。
    refs = {o['parts_ref'] for o in state.values() if o.get('status') == 'ready' and o.get('parts_ref')}
    current = files.get('parts/current.json')
    if current:
        refs.add(json.loads(current)['ref'])
    result = {}
    for path, blob in files.items():
        validate_file(path, blob)
        if (path in ('parts/current.json', 'worker-health.json') or path in refs or
                (path.startswith('payload/') and state.get(path.split('/')[1], {}).get('status') == 'ready')):
            result[path] = blob
    return result


class GitQueue:
    """毎回親なしcommitをlease付きpush。競合時は再読・再適用し、他注文を残す。"""
    def __init__(self, root=ROOT, remote='origin'):
        self.root, self.remote = Path(root), remote
        (self.root/'build').mkdir(parents=True, exist_ok=True)

    def git(self, *args, data=None, env=None, check=True):
        try:
            r = subprocess.run(['git', '-c', 'safe.directory='+self.root.resolve().as_posix(),
                                '-C', str(self.root), *args], input=data,
                               capture_output=True, env=env, timeout=90)
        except (OSError, subprocess.SubprocessError):
            raise QueueError('音声専用枝に接続・更新できません') from None
        if check and r.returncode:
            # gitの応答に認証値/URLが含まれることがあるため、そのまま出さない。
            raise QueueError('音声専用枝に接続・更新できません')
        return r

    def read(self):
        r = self.git('ls-remote', '--refs', self.remote, 'refs/heads/'+BRANCH)
        head = r.stdout.decode().split()[0] if r.stdout.strip() else ''
        if not head:
            return '', {}, {}
        self.git('fetch', '--no-tags', '--no-write-fetch-head', self.remote, head)
        tree = self.git('ls-tree', '-r', '-l', head).stdout.decode().splitlines()
        files, total = {}, 0
        for row in tree:
            props, path = row.split('\t', 1)
            mode, kind, sha, size = props.split()
            total += int(size)
            if len(tree) > 2000 or total > MAX_BYTES or mode != '100644' or kind != 'blob':
                raise QueueError('音声専用枝の容量・形式が不正です')
            blob = self.git('cat-file', 'blob', sha).stdout
            if path != 'queue.json':
                validate_file(path, blob)
            files[path] = blob
        state = json.loads(files.pop('queue.json', b'{}'))
        if not isinstance(state, dict) or len(state) > 200:
            raise QueueError('音声注文が多すぎます')
        for key, order in state.items():
            validate_order(order)
            if key != order['id']:
                raise QueueError('注文番号が一致しません')
        return head, state, files

    def update(self, change):
        for _ in range(6):
            head, state, files = self.read()
            before = encoded(state), dict(files)
            result = change(state, files)
            # 終了済み/期限切れは7日で廃棄。古い音声blobを現行treeから落とす。
            for key, order in list(state.items()):
                if stamp(order['deadline']) < now()-timedelta(days=7):
                    del state[key]
            files = compact(state, files)
            if before == (encoded(state), files):
                return result
            if len(state) > 200 or sum(map(len, files.values()))+len(encoded(state)) > MAX_BYTES:
                raise QueueError('音声在庫の上限です。古い注文の期限切れを待ってください')
            with tempfile.TemporaryDirectory(dir=self.root/'build') as folder:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder)/'index'),
                           GIT_AUTHOR_NAME='Collespo voice queue', GIT_AUTHOR_EMAIL='voice-queue@localhost',
                           GIT_COMMITTER_NAME='Collespo voice queue', GIT_COMMITTER_EMAIL='voice-queue@localhost')
                self.git('read-tree', '--empty', env=env)
                for path, blob in {**files, 'queue.json': encoded(state)}.items():
                    sha = self.git('hash-object', '-w', '--stdin', data=blob).stdout.decode().strip()
                    self.git('update-index', '--add', '--cacheinfo', '100644', sha, path, env=env)
                tree = self.git('write-tree', env=env).stdout.decode().strip()
                commit = self.git('commit-tree', tree, data=b'voice queue snapshot\n', env=env).stdout.decode().strip()
            r = self.git('push', '--force-with-lease=refs/heads/'+BRANCH+':'+head,
                         self.remote, commit+':refs/heads/'+BRANCH, check=False)
            if not r.returncode:
                return result
        raise QueueError('音声注文の同時更新が続いたため再試行が必要です')


def enqueue(queue, order):
    def change(state, files):
        state.setdefault(order['id'], order)
        return copy.deepcopy(state[order['id']])
    return queue.update(change)


def terminal(queue, key, status):
    def change(state, files):
        if key in state:
            state[key]['status'] = status
            state[key]['closed_at'] = now().isoformat()
    queue.update(change)


def ensure_portrait(resolution, directory):
    ui_voice_parts = importlib.import_module('ui_voice_parts')
    try:
        return ui_voice_parts.validate(resolution.get('portrait_dir') or '')
    except Exception:
        return ui_voice_parts.receive(directory, ref=resolution.get('parts_ref'))


@contextmanager
def preview_portraits():
    """音声の注文より前の原稿検査にも共用部品を供給する。"""
    host = os.environ.get('COLLESPO_SOLO_HOST')
    try:
        if host == 'ui':
            try:
                directory = ensure_portrait(dict(portrait_dir=os.getenv('COLLESPO_UI_PORTRAIT_DIR')),
                                            ROOT/'build/ui_portrait_preview/portrait')
                os.environ['COLLESPO_UI_PORTRAIT_DIR'] = directory
            except QueueError:
                # まだ声を使っていない原稿検査。予定は維持し、実話者は合成時に確定。
                os.environ['COLLESPO_SOLO_HOST'] = 'metan'
        yield
    finally:
        if host is None:
            os.environ.pop('COLLESPO_SOLO_HOST', None)
        else:
            os.environ['COLLESPO_SOLO_HOST'] = host


def configure(args):
    """回ごとの実声を別プロセスの描画・説明・サムネイルに渡す。既定時は何もしない。"""
    import host_split
    split = host_split.enabled()
    saved_video = getattr(args, 'video', None)
    bound_video = saved_video and host_split.video_receipt(saved_video).is_file()
    audio = getattr(args, 'audio_dir', None)
    bound_audio = audio and (Path(audio)/'manifest.json').is_file()
    if os.getenv('COLLESPO_SOLO_HOST') != 'ui' and not split and not bound_video and not bound_audio:
        return
    if split:
        os.environ['COLLESPO_SOLO_HOST'] = 'metan'
        if getattr(args, 'narration_out', None):
            return
    candidates = []
    if audio and not getattr(args, 'upload', False) and not getattr(args, 'narration_out', None):
        candidates.append(Path(audio)/'manifest.json')
    video = getattr(args, 'video', None)
    if not video:
        # PS入口はuploadの引数をparse_known_argsで下流へ渡している。
        for index, value in enumerate(sys.argv[1:], 1):
            if value == '--video' and index+1 < len(sys.argv):
                video = sys.argv[index+1]
                break
            if value.startswith('--video='):
                video = value.split('=', 1)[1]
                break
    if video:
        if split or host_split.video_receipt(video).is_file():
            bound = host_split.video_receipt(video)
            if not bound.is_file() or not Path(video).is_file():
                return
            receipt = host_split.read(bound)
            if receipt.get('video_sha256') != hashlib.sha256(Path(video).read_bytes()).hexdigest():
                return
            candidates.append(bound)
        else:
            candidates.append(Path(video).parent/'voice-resolution.json')
    for name in ('narration', 'program', 'games'):
        value = getattr(args, name, None)
        if value:
            candidates.append(Path(value))
    for name in ('out', 'thumbnail_out'):
        value = getattr(args, name, None)
        if value:
            candidates.append(Path(value).parent/'voice-resolution.json')
    for path in candidates:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(data, dict):
            continue
        import ui_voice_policy
        ui_voice_policy.assert_publishable(data)
        resolution = data.get('voice_resolution')
        if not resolution:
            assignment = data.get('host_assignment')
            if split and host_split.valid(assignment):
                os.environ['COLLESPO_SOLO_HOST'] = ui_voice_policy.planned(data)
                return
            continue
        host = resolution['host']
        if host not in ('ui', 'metan'):
            raise QueueError('実声の記録が不正です')
        if host == 'ui' and audio and path == Path(audio)/'manifest.json':
            try:
                resolution['portrait_dir'] = ensure_portrait(resolution, Path(audio)/'portrait')
            except QueueError:
                source = Path(data.get('narration_path') or Path(audio)/'narration-rebuilt.json')
                narration = host_split.read(source) or data
                rebuilt = ui_voice_policy.failure(narration, source, audio, 'ui_portrait_unavailable')
                source.write_bytes(encoded(rebuilt))
                synthesize_narration = importlib.import_module('synthesize_narration')
                synthesize_narration.main(['--narration', str(source), '--out-dir', str(audio)])
                data = host_split.read(path)
                resolution = data['voice_resolution']
                host = resolution['host']
        os.environ['COLLESPO_SOLO_HOST'] = host
        if host == 'ui' and resolution.get('portrait_dir'):
            os.environ['COLLESPO_UI_PORTRAIT_DIR'] = str(Path(resolution['portrait_dir']).resolve())
        out = getattr(args, 'out', None)
        if out and not Path(out).suffix:
            Path(out).mkdir(parents=True, exist_ok=True)
            receipt = host_split.carry(data, dict(voice_resolution=resolution))
            (Path(out)/'voice-resolution.json').write_bytes(encoded(receipt))
        return


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', action='store_true')
    args = p.parse_args()
    if args.report:
        _, state, _ = GitQueue().read()
        for order in sorted(state.values(), key=lambda r: r['created']):
            print(order['episode'], order['status'], order['deadline'])


if __name__ == '__main__':
    main()
