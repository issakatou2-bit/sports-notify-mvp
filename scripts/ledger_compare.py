"""P1の新旧照合。読むだけ、食違いは警告。欠測を一致扱いにしない。"""
import json
from pathlib import Path

from ledger_adapter import FILES, convert
from publication_writer import buffer_observation, normalized
from publications import ROOT


def compare(root=ROOT, *, buffer_only=False):
    root = Path(root)
    issues, docs = [], {}
    names = ('buffer_delivery',) if buffer_only else FILES
    for name in names:
        try:
            docs[name] = json.loads((root / 'data' / (name + '.json')).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            issues.append(dict(issue='読取不能', publication_id=name, service='-', detail='旧台帳'))
    if buffer_only:
        observations = [buffer_observation(k, v) for k, v in docs.get('buffer_delivery', {}).get('deliveries', {}).items()]
    else:
        try:
            observations = [normalized(o) for o in convert(docs)]
        except (KeyError, TypeError, ValueError):
            observations = []
            issues.append(dict(issue='読取不能', publication_id='旧台帳', service='-', detail='変換'))
    expected = {(o['publication_id'], o['service'], o['source']): o for o in observations}
    actual, rows = {}, {}
    for path in sorted((root / 'data/publications').glob('*/*.json')):
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
            rows[doc['publication_id']] = doc
            for ev in doc['history']:
                if buffer_only != ev['source'].startswith('buffer_delivery/'):
                    continue
                actual[(doc['publication_id'], ev['service'], ev['source'])] = ev
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(dict(issue='読取不能', publication_id=path.name, service='-', detail='新台帳'))
    matched = 0
    for key, old in expected.items():
        pid, service, source = key
        new = actual.get(key)
        if new is None:
            issues.append(dict(issue='旧のみ', publication_id=pid, service=service, detail=source))
            continue
        # 状態確認は元のupload観測に加えて追記される。元IDと別IDを混ぜない。
        for ev in rows[pid]['history']:
            if ev['service'] == service and ev.get('video_id') == new.get('video_id') and ev['source'].startswith('visibility/'):
                new = dict(new, state=ev['state'])
        problems = []
        if old.get('video_id') != new.get('video_id'):
            problems.append(f"video_id: {old.get('video_id')} → {new.get('video_id')}")
        # public_confirmedは旧privacy=publicと矛盾しないが、旧記録だけでは証明しない。
        compatible = (new['state'] == 'public_confirmed' and old['state'] == 'uploaded'
                      and old.get('raw', {}).get('privacy') == 'public')
        if old['state'] != new['state'] and not compatible:
            problems.append(f"状態: {old['state']} → {new['state']}")
        if problems:
            issues.append(dict(issue='食違い', publication_id=pid, service=service, detail=' / '.join(problems)))
        else:
            matched += 1
    expected_groups = {(o['publication_id'], o['service']) for o in observations}
    for pid, service, source in actual:
        if (pid, service) not in expected_groups:
            issues.append(dict(issue='新のみ', publication_id=pid, service=service, detail=source))
    recovery = len(list((root / 'data/publication_recovery').glob('*.json')))
    if recovery:
        issues.append(dict(issue='要回収', publication_id='publication_recovery', service='-', detail=f'{recovery}ファイル'))
    return dict(matched=matched, legacy_observations=len(expected), issues=issues)


def health_table(root=ROOT, buffer_root=None):
    try:
        reports = [compare(root)]
        if buffer_root is not None and Path(buffer_root).exists():
            reports.append(compare(buffer_root, buffer_only=True))
        else:
            reports.append(dict(matched=0, issues=[dict(issue='未確認', publication_id='Buffer状態枝',
                                                       service='-', detail='取得なし')]))
        issues = [x for report in reports for x in report['issues']]
        count = sum(r['matched'] for r in reports)
        def cell(value):
            return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
        lines = ['', '## 公開台帳の新旧一致（警告のみ）', '',
                 f'一致 {count}記録 / 警告 {len(issues)}件。P1以前の未移行分も「旧のみ」に含む。', '',
                 '| 照合 | 公開ID | サービス | 詳細 |', '|---|---|---|---|']
        lines += ['| ' + ' | '.join(cell(issue[k]) for k in ('issue', 'publication_id', 'service', 'detail')) + ' |'
                  for issue in issues]
        if not issues:
            lines.append('| 一致 | 全件 | - | 食違いなし |')
        return lines
    except Exception as error:
        return ['', '## 公開台帳の新旧一致（警告のみ）', '',
                f'警告：照合できませんでした（{type(error).__name__}）。自動補完・再投稿はしません。']
