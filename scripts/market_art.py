"""市場の静かな挿絵。利用条件は台帳で確認し、本文・音声へ素材情報を混ぜない。"""
from datetime import date
import hashlib
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import socket
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlsplit

DIRECTORY = Path(__file__).resolve().parents[1]/'assets/illustrations'
LICENSES = frozenset({'CC0', 'CC BY', 'CC BY-SA', 'PD', 'いらすとや'})
MAX_BYTES = 4 * 1024 * 1024
_ATTEMPTS = set()
LOGGER = logging.getLogger(__name__)
NEWS_HOSTS = ('mlb.com', 'mlbstatic.com', 'npb.jp', 'gettyimages.com', 'gettyimages.co.jp',
              'reuters.com', 'apnews.com', 'apimages.com', 'afp.com', 'kyodonews.jp',
              'hanshintigers.jp', 'tigers.jp') + tuple(name+'.com' for name in
              'angels astros athletics bluejays braves brewers cardinals cubs dbacks diamondbacks dodgers giants sfgiants indians guardians mariners marlins mets nationals orioles padres phillies pirates rangers rays raysbaseball redsox reds rockies royals tigers twins whitesox yankees'.split())


@lru_cache(maxsize=128)
def digest(path, modified, size):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def filename(value):
    if (not isinstance(value, str) or not value or value in ('.', '..')
            or any(c in value for c in '/\\:\n\r') or value.startswith('.')
            or Path(value).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')):
        raise ValueError('illustrationはassets/illustrations内の画像ファイル名だけにしてください')
    return value


def ledger(root=None):
    root = Path(root or DIRECTORY)
    data = json.loads((root/'SOURCES.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('assets'), list):
        raise ValueError('素材台帳の書式が不正です')
    result = {}
    for row in data['assets']:
        if not isinstance(row, dict):
            raise ValueError('素材台帳の行が不正です')
        name = filename(row.get('filename'))
        if name in result:
            raise ValueError('素材台帳のファイル名が重複しています')
        result[name] = row
    return result


def download_url(value, *, irasutoya=False):
    url = urlsplit(value or '')
    host = (url.hostname or '').lower()
    if (url.scheme != 'https' or not host or url.username or url.password or url.port not in (None, 443)
            or (irasutoya and host != 'blogger.googleusercontent.com')):
        raise ValueError('画像取得元はHTTPSの本文画像URLが必要です（いらすとやはblogger.googleusercontent.com）')
    if not irasutoya:
        import ipaddress
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if host == 'localhost' or (address is not None and not address.is_global):
            raise ValueError('画像取得先にローカルアドレスは使えません')
        if any(host == h or host.endswith('.'+h) for h in NEWS_HOSTS):
            raise ValueError('報道写真・球団写真は使えません')
    return value


def available_image(path, row, *, sample=False):
    """正しいキャッシュを使う。取得・照合失敗は1実行で1度だけ試し、絵なしへ戻す。"""
    expected = row['sha256']
    try:
        if path.is_file() and path.stat().st_size <= MAX_BYTES:
            stamp = path.stat()
            if digest(path, stamp.st_mtime_ns, stamp.st_size) == expected:
                return True
    except OSError:
        pass
    target = row.get('download_url')
    attempt = (str(path), expected, target)
    if attempt in _ATTEMPTS:
        return False
    _ATTEMPTS.add(attempt)
    # 未確認URLは捏造しない。台帳への登録が済むまで取得できない素材として扱う。
    if not target:
        LOGGER.warning('挿絵なしで続行（取得元URL未登録）: %s', path.name)
        return False
    try:
        request = Request(target, headers={'User-Agent': 'Collespo-Market-Art/1.0'})
        with urlopen(request, timeout=4) as response:
            download_url(response.geturl(), irasutoya=row['license'] == 'いらすとや')
            data = response.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('画像サイズ上限またはSHA-256不一致')
        # 書込は照合後だけ。既存ファイルは削除・上書きせず、失敗なら絵なし。
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(data)
        return True
    except (OSError, URLError, socket.timeout, ValueError) as error:
        LOGGER.warning('挿絵なしで続行: %s (%s)', path.name, type(error).__name__)
        return False


def resolve(name, root=None, *, sample=False, catalog=None):
    root = Path(root or DIRECTORY).resolve()
    name = filename(name)
    row = (catalog if catalog is not None else ledger(root)).get(name)
    if not row:
        raise ValueError('素材台帳にない絵は使えません: ' + name)
    for key in ('source_url', 'author', 'license', 'terms', 'checked_on'):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError('素材台帳に必要な欄がありません: ' + key)
    if row['author'].strip().casefold() in ('不明', '未確認', 'unknown', 'anonymous'):
        raise ValueError('素材の作者が確認されていません')
    checked = date.fromisoformat(row['checked_on'])
    if checked > date.today():
        raise ValueError('素材の確認日が未来です')
    url = urlsplit(row['source_url'])
    host = (url.hostname or '').lower()
    if url.scheme != 'https' or not host or url.username or url.password:
        raise ValueError('素材の出典は資格情報なしのHTTPS URLが必要です')
    if not sample and (host == 'example.com' or host.endswith('.example.com')):
        raise ValueError('試験用の素材台帳を本番に使えません')
    if any(host == h or host.endswith('.'+h) for h in NEWS_HOSTS):
        raise ValueError('報道写真・球団写真は使えません')
    kind, license_name = row.get('type', 'illustration'), row['license']
    if kind not in ('illustration', 'photo') or license_name not in LICENSES:
        raise ValueError('素材の種類・ライセンスが未対応です')
    if license_name == 'いらすとや':
        if kind != 'illustration' or not (host == 'irasutoya.com' or host.endswith('.irasutoya.com')):
            raise ValueError('いらすとやは公式ページのイラストだけにしてください')
    if kind == 'photo' and (license_name not in LICENSES-{'いらすとや'} or row.get('origin') != 'independent'):
        raise ValueError('写真は報道・球団素材でないことをorigin=independentで確認してください')
    if not isinstance(row.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', row['sha256']):
        raise ValueError('素材台帳には画像のsha256（小文字64桁）が必要です')
    if row.get('download_url'):
        download_url(row['download_url'], irasutoya=license_name == 'いらすとや')
    path = (root/name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('素材が置き場の中にありません: ' + name)
    return dict(row, path=path, digest=row['sha256'], available=available_image(path,row,sample=sample))


def entry_rows(entry, *, sample=False, root=None):
    names = [r['illustration'] for group in ('facts', 'reports') for r in entry.get(group, []) if 'illustration' in r]
    if not names:
        return []
    catalog = ledger(root)
    rows = [resolve(name, root, sample=sample, catalog=catalog) for name in dict.fromkeys(names)]
    # 同じ絵の再掲・別名コピーは1点。同じ動画内の全行をまとめて数える。
    if len({r['digest'] for r in rows if r['license'] == 'いらすとや'}) > 20:
        raise ValueError('いらすとやは1本20点までです（重複は1点）')
    return rows


def validate_spec(spec):
    evidence = spec.get('offseason') or {}
    if evidence.get('kind') != 'market':
        return []
    return entry_rows(evidence['entry'], sample=bool(spec.get('offseason_sample')))


def credits(spec):
    rows = [row for row in validate_spec(spec) if row['available']]
    result = ['イラスト：いらすとや'] if any(r['license'] == 'いらすとや' for r in rows) else []
    seen = set()
    for row in rows:
        if row['license'] in ('CC BY', 'CC BY-SA'):
            line = f'{"写真" if row.get("type") == "photo" else "イラスト"}：{row["author"]} / {row["license"]}'
            if row.get('license_version'):
                line += ' ' + row['license_version']
            line += ' / ' + row['source_url']
            if row.get('license_url'):
                line += ' / ' + row['license_url']
            line += '（表示用に縮小）'
            if line not in seen:
                result.append(line)
                seen.add(line)
    return result


def for_item(spec, head, body):
    evidence = spec.get('offseason') or {}
    if evidence.get('kind') != 'market':
        return None
    rows = validate_spec(spec)
    event = next((r for r in evidence['events'] if (r['head'], r['body']) == (head, body)), {})
    name = event.get('illustration')
    return next((r for r in rows if r['filename'] == name and r['available']), None)
