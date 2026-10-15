"""音声専用枝のスナップショット。注文はデータだけ。コードを取得・実行しない。"""
import argparse
import copy
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
            if path != 'queue.json' and not re.fullmatch(r'payload/[a-f0-9]{64}/[a-zA-Z0-9_.-]+', path):
                raise QueueError('音声専用枝に未知のファイルがあります')
            files[path] = self.git('cat-file', 'blob', sha).stdout
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
            files = {k: v for k, v in files.items() if k.split('/')[1] in state
                     and state[k.split('/')[1]]['status'] == 'ready'}
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
    queue.update(change)


def configure(args):
    """回ごとの実声を別プロセスの描画・説明・サムネイルに渡す。既定時は何もしない。"""
    if os.getenv('COLLESPO_SOLO_HOST') != 'ui':
        return
    candidates = []
    audio = getattr(args, 'audio_dir', None)
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
        resolution = data.get('voice_resolution')
        if not resolution:
            continue
        host = resolution['host']
        if host not in ('ui', 'metan'):
            raise QueueError('実声の記録が不正です')
        os.environ['COLLESPO_SOLO_HOST'] = host
        if host == 'ui':
            os.environ['COLLESPO_UI_PORTRAIT_DIR'] = str(Path(resolution['portrait_dir']).resolve())
        out = getattr(args, 'out', None)
        if out and not Path(out).suffix:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out)/'voice-resolution.json').write_bytes(encoded(dict(voice_resolution=resolution)))
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
