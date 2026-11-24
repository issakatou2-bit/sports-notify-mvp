"""速報2枠の試合ID台帳。pendingも使用済みとして扱う。"""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATH = 'data/soccer_flash_receipts.json'
KINDS = ('soccer_now', 'soccer_goal_short')


def load(*, refresh=False):
    paths = [PATH] + [f'data/{kind}_receipts.json' for kind in KINDS]
    if refresh:
        subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=ROOT, check=True, capture_output=True)
    ledger = {}
    for path in paths:
        if refresh:
            result = subprocess.run(['git', 'show', 'origin/main:'+path], cwd=ROOT,
                                    capture_output=True, text=True, encoding='utf8')
            if result.returncode:
                # A genuinely new ledger is absent in the tree; other git errors stop publication.
                exists = subprocess.run(['git', 'ls-tree', 'origin/main', '--', path],
                                        cwd=ROOT, check=True, capture_output=True)
                if exists.stdout.strip():
                    raise ValueError('速報台帳の再取得失敗')
                rows = {}
            else:
                rows = json.loads(result.stdout)
        else:
            p = ROOT/path
            rows = json.loads(p.read_text(encoding='utf8')) if p.exists() else {}
        for ident, entry in rows.items():
            ledger.setdefault(str(ident), dict(entry, kind=entry.get('kind') or
                (path.split('/')[-1].removesuffix('_receipts.json') if path != PATH else 'unknown')))
    return ledger


def goal_involvement(data):
    return any(p['status'] != 'none' and (p.get('goals') or p.get('assists'))
               for p in data['games'][0]['players'])


def eligible(data, ledger, *, goal_short=False):
    return (str(data['games'][0]['id']) not in ledger and
            (goal_involvement(data) if goal_short else not goal_involvement(data)))


def mirror_receipt(game_id, entry):
    from publication_writer import mirror_documents
    mirror_documents({'soccer_flash_receipts': {str(game_id): entry}}, root=ROOT)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sync', action='store_true')
    if ap.parse_args().sync:
        (ROOT/PATH).write_text(json.dumps(load(refresh=True), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        from publication_writer import mirror_file
        mirror_file(ROOT/PATH, root=ROOT)
