"""Reject unsupported game hooks and postseason qualification objectives.

This is a local check against rule-generated reasons, not a general fact checker.
Player names, AI summaries and standings alone never establish the four claims.
PS games have already qualified; do not frame their next game as qualifying for PS.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile


GUARDED_TERMS = ('守護神', 'クローザー', 'ストッパー', '決定戦')
SCOPE = 'hookの4表現とMLB PS試合の進出目的・現在の地区順位争い・期間不明の直近成績の齟齬。公式照合・全本文の意味検査ではない'
PS_ROUNDS = {'F', 'D', 'L', 'W'}
PS_ENTRY = re.compile(r'ポストシーズン(?:への|へ)?進出(?:をかけ|を賭け|を懸け|を決め|がかか)')
# A playoff series has wins, not a live regular-season division race.
# Keep explicit retrospective clauses and accurate series-lead statements.
PS_DIVISION_RACE = re.compile(
    r'(?:首位|[1-6一二三四五六]位)を(?:守る|維持して|キープ)'
    r'|ゲーム差.{0,12}(?:迫|詰め|縮め|追)'
    r'|(?:地区優勝|地区首位|地区の首位)(?:争い|を目指|を狙)')
# Standings recent form ends with the regular season. Require a named period
# before reusing it during playoffs; this does not calculate a PS winning streak.
PS_RECENT_FORM = re.compile(r'[0-9０-９]+連(?:勝|敗)中|直近[0-9０-９]+試合(?:は|が|で)')
PS_FORM_PERIOD = re.compile(r'レギュラーシーズン|シーズン(?:の)?(?:終盤|終了|最後)|ポストシーズン(?:で|では|の)|PS(?:で|では|の)|(?:WCS|DS|LCS|WS|ワイルドカードシリーズ|地区シリーズ|リーグ優勝決定シリーズ|ワールドシリーズ)(?:で|では|の)')
PS_FORM_PAST = re.compile(r'昨年|去年|前年|先週|先月|だった|終えた')
PS_HISTORY = re.compile(r'昨年|去年|前年|先週|先月|終了時|最終成績|だった|終えた|決めた')



def postseason_rejections(game, field):
    if game.get('league') != 'MLB' or game.get('game_type') not in PS_ROUNDS:
        return []
    text = game.get(field)
    if not isinstance(text, str):
        return []
    # The hook is about the upcoming game. In summaries, restrict to the
    # current-game clause; historical qualification mentions stay intact.
    clauses = re.split(r'[。！？]', text)
    bad = any(PS_ENTRY.search(c) and not re.search(r'昨年|去年|前年|先週|先月', c)
              and (field == 'notification_hook' or re.search(r'この|第[0-9０-９]+戦|明日', c))
              for c in clauses)
    rejected = ['PSの試合は既にPS進出済み。今の試合をPS進出のためとする表現は出さない'] if bad else []
    if any(PS_DIVISION_RACE.search(c) and not PS_HISTORY.search(c) for c in clauses):
        rejected.append('PS期間に終了済みの地区順位争いを現在進行形で説明しない')
    if any(PS_RECENT_FORM.search(c) and not PS_FORM_PERIOD.search(c)
           and not PS_FORM_PAST.search(c) for c in clauses):
        rejected.append('PS期間の連勝/直近成績は対象期間を明記。順位表の最終値を現在の勢いにしない')
    # With no series wins, the named team cannot extend a winning streak.
    # Do not infer recent form from regular-season standings or unknown context.
    context = game.get('series_context')
    if isinstance(context, dict):
        for side in ('home', 'away'):
            name = game.get(side + '_team_name')
            wins = context.get(side + '_wins_in_stretch')
            if not isinstance(name, str) or not name or wins != 0:
                continue
            pattern = re.compile(re.escape(name) + r'(?:は|が).{0,16}連勝')
            if any(pattern.search(c) and not PS_HISTORY.search(c) for c in clauses):
                rejected.append('シリーズ未勝利の球団に連勝を見込む説明は出せない')
    return rejected


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
            if term in hook and not any(term in text for text in evidence)] + postseason_rejections(game, 'notification_hook')


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


def sanitize_files(games_path, archive_dir=None, report_path=None, feed_path=None):
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
    feed_path = Path(feed_path) if feed_path is not None else None
    if feed_path is not None and feed_path.resolve() in {games_path.resolve(),
            archive_path.resolve() if archive_path else None,
            report_path.resolve() if report_path else None}:
        raise ValueError('feedは入力games/アーカイブ/reportとは別のファイルにする')
    feed = ET.parse(feed_path) if feed_path is not None else None
    rejected, exact_matches = [], set()
    checked_hooks = 0
    for index, game in enumerate(payload['games']):
        checked_hooks += isinstance(game.get('notification_hook'), str) \
            and bool(game.get('notification_hook'))
        for field, reasons in [('notification_hook', rejection_reasons(game)),
                               ('ai_summary', postseason_rejections(game, 'ai_summary'))]:
            if not reasons:
                continue
            old = game.pop(field)
            rejected.append({'index': index, 'league': game.get('league'),
                             'game_id': game.get('game_id'), 'field': field,
                             'old_hook': old if field == 'notification_hook' else None,
                             'old_value': old, 'reasons': reasons})
            identity = _identity(game)
            if identity is not None:
                exact_matches.add((*identity, field, old))

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
                    removed = False
                    for field in ('notification_hook', 'ai_summary'):
                        old = game.get(field)
                        if identity is not None and isinstance(old, str) \
                                and (*identity, field, old) in exact_matches:
                            del game[field]
                            removed = True
                    archive_report['modified_games'] += removed
                if archive_report['modified_games']:
                    archive_report['status'] = 'sanitized'

    refreshed = 0
    if feed is not None and generated_date:
        for row in rejected:
            if row['field'] != 'ai_summary' or row['league'] != 'MLB':
                continue
            guid = f"{row['game_id']}-{generated_date}"
            for item in feed.findall('.//item'):
                desc = item.find('description')
                if item.findtext('guid') == guid and desc is not None \
                        and desc.text and row['old_value'] in desc.text:
                    remaining = ''.join(desc.itertext()).replace(row['old_value'], '', 1).strip()
                    for child in list(desc):
                        desc.remove(child)
                    desc.text = remaining
                    refreshed += 1

    report = {'scope': SCOPE, 'guarded_terms': list(GUARDED_TERMS),
              'input': {'path': str(games_path), 'sha256': input_sha,
                        'generated_at': payload.get('generated_at')},
              'checked_games': len(payload['games']), 'checked_hooks': checked_hooks,
              'rejected_count': len(rejected), 'modified_games': len({r['index'] for r in rejected}),
              'rejections': rejected, 'archive': archive_report,
              'rss_refreshed': refreshed}
    # Read/validate the optional matching archive before changing either input.
    if rejected:
        _write_json(games_path, payload)
    if archive_report['modified_games']:
        _write_json(archive_path, archive_payload)
    if refreshed:
        feed.write(feed_path, encoding='utf-8', xml_declaration=True)
    if report_path is not None:
        _write_json(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', required=True, type=Path)
    parser.add_argument('--archive-dir', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--feed', type=Path, help='同じゲームID/材料日のRSSだけ本文を同期')
    args = parser.parse_args(argv)
    report = sanitize_files(args.games, args.archive_dir, args.report, args.feed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
