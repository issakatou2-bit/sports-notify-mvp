"""公式立ち絵の転送専用。鍵と平文は公開キューへ保存しない。"""
import base64
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import re

import ui_voice_queue as q

MAGIC = q.PARTS_MAGIC
REF = q.PARTS_REF
MAX_PLAIN = 12 * 1024 * 1024


class PortraitUnavailable(q.QueueError):
    """声を使う前に、回全体をめたんへ戻すための区別。"""


def validate(directory):
    """口・目・腕の全状態が実際に描けることを受取時に確認する。"""
    from PIL import Image
    folder = Path(directory)
    spec = json.loads((folder/'parts.json').read_text(encoding='utf8'))
    required = {'右腕': ('基本', '上げ', '指', '考え'), '左腕': ('基本', '上げ'),
                '眉': ('基本', '上げ', '困り'), '目': ('開', '閉', '笑', '見開'),
                '口': ('閉', '開', '大', '笑')}
    names = [spec['体']]
    for group, states in required.items():
        names.extend(spec[group][state] for state in states)
    size, crop = spec['size'], spec['crop']
    if (len(size) != 2 or not all(isinstance(n, int) and 0 < n <= 8192 for n in size)
            or len(crop) != 4 or not 0 <= crop[0] < crop[2] <= size[0]
            or not 0 <= crop[1] < crop[3] <= size[1]):
        raise PortraitUnavailable('雨衣の立ち絵の範囲が不正です')
    for name in set(names):
        if not re.fullmatch(r'p[0-9]{3}\.png', name):
            raise PortraitUnavailable('雨衣の立ち絵の部品名が不正です')
        with Image.open(folder/name) as im:
            if im.size != tuple(size):
                raise PortraitUnavailable('雨衣の立ち絵の部品サイズが不一致です')
            im.verify()
    return str(folder.resolve())


def install(ref, blob, directory):
    """注文の声と原稿検査が使う、共通の復号・部品検査。"""
    try:
        files = decrypt(ref, blob)
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (folder/name).write_bytes(content)
        return validate(folder)
    except Exception:
        raise PortraitUnavailable('雨衣の立ち絵を受け取り・復号できません') from None


def receive(directory, queue=None, ref=None):
    """音声専用枝の共用部品。検証前のPS原稿も同じ部品を使う。"""
    try:
        key()
        _, _, files = (queue or q.GitQueue()).read()
        ref = ref or json.loads(files['parts/current.json'])['ref']
        return install(ref, files[ref], directory)
    except Exception:
        raise PortraitUnavailable('雨衣の立ち絵がありません') from None


def key():
    try:
        value = base64.b64decode(os.environ.get('COLLESPO_UI_PARTS_KEY', ''), validate=True)
        if len(value) != 32:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise q.QueueError('雨衣の部品鍵が未設定または不正です') from None


def cipher(secret):
    # 雨衣を選んだ時だけ必要な依存。未導入でも呼出元はめたんへ戻る。
    return importlib.import_module('cryptography.hazmat.primitives.ciphers.aead').AESGCM(secret)


def pack(files):
    if ('parts.json' not in files or len(files) > 100
            or any(n != 'parts.json' and not re.fullmatch(r'p[0-9]{3}\.png', n) for n in files)):
        raise q.QueueError('立ち絵の梱包形式が不正です')
    raw = q.encoded({n: base64.b64encode(b).decode('ascii') for n, b in files.items()})
    if len(raw) > MAX_PLAIN:
        raise q.QueueError('立ち絵が大きすぎます')
    return raw


def reference(raw, secret):
    identity = hmac.new(secret, MAGIC+raw, hashlib.sha256).hexdigest()
    return 'parts/'+identity+'.aesgcm'


def decrypt(ref, blob, secret=None):
    secret = key() if secret is None else secret
    try:
        if (not re.fullmatch(REF, ref) or not blob.startswith(MAGIC)
                or not len(MAGIC)+28 <= len(blob) <= MAX_PLAIN+len(MAGIC)+28):
            raise ValueError
        offset = len(MAGIC)
        raw = cipher(secret).decrypt(blob[offset:offset+12], blob[offset+12:], MAGIC+ref.encode('ascii'))
        if reference(raw, secret) != ref:
            raise ValueError
        files = {n: base64.b64decode(v, validate=True) for n, v in json.loads(raw).items()}
        if pack(files) != raw:
            raise ValueError
        return files
    except Exception:
        # 鍵、暗号ライブラリの例外詳細、復号途中の部品を出力しない。
        raise q.QueueError('雨衣の部品を復号・検証できません') from None


def publish(files, portraits, secret):
    """CAS再試行でも既存の暗号文を再利用。平文・鍵が変わった時だけ追加。"""
    raw = pack(portraits)
    ref = reference(raw, secret)
    if ref in files:
        if decrypt(ref, files[ref], secret) != portraits:
            raise q.QueueError('雨衣の共用部品が一致しません')
    else:
        nonce = os.urandom(12)
        files[ref] = MAGIC+nonce+cipher(secret).encrypt(nonce, raw, MAGIC+ref.encode('ascii'))
    files['parts/current.json'] = q.encoded(dict(ref=ref))
    return ref
