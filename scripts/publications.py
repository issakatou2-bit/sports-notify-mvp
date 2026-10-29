"""公開台帳P0の読取専用入口。本番の書き手・通信には接続しない。

getは同一回の全観測を返す。重複や訂正を最後の1件で上書きしない。
日付の欠測はNone。unknownは保存資料だけでは決められない状態。
"""
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
STATES = frozenset(('planned', 'prepared', 'checked', 'upload_pending', 'uploaded',
                    'scheduled', 'public_confirmed', 'distributed',
                    'skipped_no_material', 'held', 'error', 'unknown'))
DATE_FIELDS = ('event_day', 'material_day', 'edition_day', 'run_at')


def publication_id(domain, kind, *parts):
    """部品内のコロン等をescapeし、異なる鍵の衝突を防ぐ。分解は禁止。"""
    if not domain or not kind or not parts or any(p is None or str(p) == '' for p in parts):
        raise ValueError('公開IDの部品がありません')
    return ':'.join(quote(str(p), safe='-_') for p in (domain, kind, *parts))


def identity(domain, kind, key_parts):
    return dict(publication_id=publication_id(domain, kind, *key_parts.values()),
                domain=domain, kind=kind, key_parts=deepcopy(key_parts))


class Reader:
    """呼出ごとのsnapshot。source observationsは履歴の推測ではない。"""
    def __init__(self, observations):
        self._rows = {}
        for observation in deepcopy(list(observations)):
            pid = observation['publication_id']
            if observation['state'] not in STATES:
                raise ValueError('未定義の状態')
            row = self._rows.setdefault(pid, {k: observation[k] for k in
                ('publication_id', 'domain', 'kind', 'key_parts')})
            if any(row[k] != observation[k] for k in ('domain', 'kind', 'key_parts')):
                raise ValueError('公開IDと鍵の不一致')
            row.setdefault('observations', []).append(observation)

    def get(self, publication_id):
        return deepcopy(self._rows.get(publication_id))

    def find(self, domain=None, kind=None, **dates):
        if set(dates) - set(DATE_FIELDS):
            raise ValueError('日付欄が不明です')
        return [deepcopy(row) for _, row in sorted(self._rows.items())
                if (domain is None or row['domain'] == domain)
                and (kind is None or row['kind'] == kind)
                and any(all(obs.get(k) == v for k, v in dates.items())
                        for obs in row['observations'])]

    def state(self, publication_id, service='youtube', video_id=None):
        row = self._rows.get(publication_id)
        if row is None:
            return None
        observations = [o for o in row['observations'] if o['service'] == service
                        and (video_id is None or o.get('video_id') == video_id)]
        states = {o['state'] for o in observations}
        videos = {o.get('video_id') for o in observations if o.get('video_id')}
        # 訂正前後や別IDの同居を「公開済み」1語で隠さない。
        if len(videos) <= 1:
            # 修復の確認は同じIDの旧upload観測を補うが、相反する確認は残す。
            confirmed = states & {'held', 'public_confirmed'}
            if len(confirmed) == 1 and states <= {'uploaded', 'scheduled', *confirmed}:
                return next(iter(confirmed))
        return next(iter(states)) if len(states) == 1 and len(videos) <= 1 else 'unknown'


def read(root=ROOT):
    from ledger_adapter import load
    return Reader(load(root))


def get(publication_id, *, root=ROOT):
    return read(root).get(publication_id)


def find(domain=None, kind=None, *, root=ROOT, **dates):
    return read(root).find(domain, kind, **dates)


def state(publication_id, *, root=ROOT, service='youtube', video_id=None):
    return read(root).state(publication_id, service, video_id)
