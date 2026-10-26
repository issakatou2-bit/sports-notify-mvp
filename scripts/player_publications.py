"""MLB選手の話題とシーズンまとめを7日間隔で選ぶ。両公開台帳を照合。"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATHS = ('data/published_videos.json', 'data/published_assets.json')
JST = timezone(timedelta(hours=9))


def read(path):
    p = ROOT/path
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else {}


def identity(player):
    pid = player.get('player_id') or player.get('id')
    if pid:
        return str(pid)
    hits = [k for k, row in read('data/roster_snapshot.json').get('players', {}).items()
            if row.get('name') == player.get('name_en')]
    return hits[0] if len(hits) == 1 else None


def load(*, refresh=False, assets_path=None):
    if not refresh:
        return read(PATHS[0]), read(assets_path or PATHS[1])
    subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=ROOT, check=True, capture_output=True)
    rows = []
    for path in PATHS:
        result = subprocess.run(['git', 'show', 'origin/main:'+path], cwd=ROOT,
                                check=True, capture_output=True, text=True, encoding='utf8')
        rows.append(json.loads(result.stdout))
    return tuple(rows)


def recent(player_id, kind, as_of=None, ledgers=None):
    if not player_id:
        return True  # 選手IDを照合できなければ公開しない。
    videos, assets = ledgers if ledgers is not None else load()
    as_of = as_of or datetime.now(timezone.utc)
    rows = list(videos.get('player_story', {}).values()) if kind == 'season_player' else []
    if kind == 'player_story':
        rows += [dict(row, player_id=row.get('player_id') or key.removeprefix('season_player_'))
                 for key, row in assets.get('assets', {}).items() if key.startswith('season_player_')]
    for row in rows:
        pid = row.get('player_id')
        if not pid and kind == 'season_player':
            # 旧記録にも対応。題の日本語名は既存登録表と一意に照合する。
            from notability_engine import JP_PLAYERS_MLB
            matches = [identity(p) for p in JP_PLAYERS_MLB if p['name_jp'] in row.get('title', '')]
            pid = matches[0] if len(matches) == 1 else None
        if str(pid) != str(player_id):
            continue
        try:
            at = datetime.fromisoformat((row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
            if at.tzinfo is None:
                return True
        except (ValueError, KeyError):
            return True
        if at > as_of and not row.get('publish_at'):
            continue  # 保存材料の過去時点に、まだ存在しない実投稿を持ち込まない。
        # 将来の予約済み動画も同じ7日窓で重複させない。
        if abs(as_of-at) <= timedelta(days=7):
            return True
    return False


def topic_id(topic):
    match = re.fullmatch(r'season_player_(\d+)', topic or '')
    return match[1] if match else None


def record(player_id, as_of=None):
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(JST)
    return dict(player_id=str(player_id), player_week_start=(as_of.date()-timedelta(days=as_of.weekday())).isoformat())


def publication(player_id, kind, as_of):
    if recent(player_id, kind, as_of, load(refresh=True)):
        return None
    return record(player_id, as_of)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sync', action='store_true')
    if ap.parse_args().sync:
        for path, rows in zip(PATHS, load(refresh=True)):
            (ROOT/path).write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
