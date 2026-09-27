"""Reject four unsupported expressions in generated game notification hooks.

This is a local check against rule-generated reasons, not a general fact checker.
Player names, AI summaries and standings alone never establish the four claims.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile


GUARDED_TERMS = ('守護神', 'クローザー', 'ストッパー', '決定戦')
SCOPE = 'notification_hookの4表現のみ。公式照合・全本文の意味検査ではない'


def rejection_reasons(game):
    """Return unsupported guarded terms; only reasons[].text is evidence."""
    hook = game.get('notification_hook')
    if not isinstance(hook, str) or not hook:
        return []
    reasons = game.get('reasons')
    evidence = [reason['text'] for reason in reasons
                if isinstance(reason, dict) and isinstance(reason.get('text'), str)] \
        if isinstance(reasons, list) else []
    return [f'「{term}」の根拠がルール由来のreasons.textにない'
            for term in GUARDED_TERMS
            if term in hook and not any(term in text for text in evidence)]


def validated_hook(game):
    """Preserve the exact original string, or return empty for fallback use."""
    hook = game.get('notification_hook')
    return hook if isinstance(hook, str) and not rejection_reasons(game) else ''


def _load(path):
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('games'), list):
        raise ValueError(f'{path}: games配列を持つJSONオブジェクトが必要')
    if any(not isinstance(game, dict) for game in data['games']):
        raise ValueError(f'{path}: gamesの各項目はオブジェクトが必要')
    return data, hashlib.sha256(raw).hexdigest()


def _generated_date(data):
    value = data.get('generated_at')
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return None


def _identity(game):
    game_id, league = game.get('game_id'), game.get('league')
    if game_id is None or not isinstance(league, str) or not league:
        return None
    return league, str(game_id)


def _write_json(path, data):
    """Replace one complete JSON file; an unchanged file is never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def sanitize_files(games_path, archive_dir=None, report_path=None):
    """Remove only rejected hook keys and their exact matching dated copies."""
    games_path = Path(games_path)
    payload, input_sha = _load(games_path)
    generated_date = _generated_date(payload)
    archive_path = Path(archive_dir) / f'{generated_date}.json' \
        if archive_dir is not None and generated_date else None
    if report_path is not None:
        report_path = Path(report_path)
        if report_path.resolve() in {games_path.resolve(),
                                     archive_path.resolve() if archive_path else None}:
            raise ValueError('reportは入力games/アーカイブとは別のファイルにする')
    rejected, exact_matches = [], set()
    checked_hooks = 0
    for index, game in enumerate(payload['games']):
        checked_hooks += isinstance(game.get('notification_hook'), str) \
            and bool(game.get('notification_hook'))
        reasons = rejection_reasons(game)
        if not reasons:
            continue
        old_hook = game.pop('notification_hook')
        rejected.append({'index': index, 'league': game.get('league'),
                         'game_id': game.get('game_id'), 'old_hook': old_hook,
                         'reasons': reasons})
        identity = _identity(game)
        if identity is not None:
            exact_matches.add((*identity, old_hook))

    archive_report = {'status': 'not_requested', 'modified_games': 0}
    archive_payload = None
    if archive_dir is not None:
        if generated_date is None:
            archive_report['status'] = 'skipped_invalid_generated_at'
        elif archive_path.resolve() == games_path.resolve():
            archive_report['status'] = 'same_as_games'
        elif not archive_path.exists():
            archive_report.update(status='not_found', path=str(archive_path))
        elif not rejected:
            archive_report.update(status='no_rejected_hooks', path=str(archive_path))
        else:
            archive_payload, archive_sha = _load(archive_path)
            archive_report.update(path=str(archive_path), input_sha256=archive_sha,
                                  status='no_exact_matches')
            if _generated_date(archive_payload) != generated_date:
                archive_report['status'] = 'skipped_generated_date_mismatch'
            else:
                for game in archive_payload['games']:
                    identity = _identity(game)
                    hook = game.get('notification_hook')
                    if identity is not None and isinstance(hook, str) \
                            and (*identity, hook) in exact_matches:
                        del game['notification_hook']
                        archive_report['modified_games'] += 1
                if archive_report['modified_games']:
                    archive_report['status'] = 'sanitized'

    report = {'scope': SCOPE, 'guarded_terms': list(GUARDED_TERMS),
              'input': {'path': str(games_path), 'sha256': input_sha,
                        'generated_at': payload.get('generated_at')},
              'checked_games': len(payload['games']), 'checked_hooks': checked_hooks,
              'rejected_count': len(rejected), 'modified_games': len(rejected),
              'rejections': rejected, 'archive': archive_report}
    # Read/validate the optional matching archive before changing either input.
    if rejected:
        _write_json(games_path, payload)
    if archive_report['modified_games']:
        _write_json(archive_path, archive_payload)
    if report_path is not None:
        _write_json(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', required=True, type=Path)
    parser.add_argument('--archive-dir', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    report = sanitize_files(args.games, args.archive_dir, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
