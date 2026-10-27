#!/usr/bin/env python3
"""Assemble an isolated visual rehearsal from tracked sources; never deploy."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/visual/site')
    ap.add_argument('--fetch-standings', action='store_true', help='Optional official read request')
    ap.add_argument('--standings-fixture', action='store_true', help='Explicit synthetic standings, visibly labelled')
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'web', out, dirs_exist_ok=True)
    records = []
    for script, options in [
        ('generate_score_page.py', ['--out', out / 'score.html']),
        ('generate_soccer_page.py', ['--out', out / 'soccer.html']),
        ('generate_player_pages.py', ['--out-dir', out / 'players']),
        ('generate_archive_pages.py', ['--out-dir', out / 'archive', '--site-root', out]),
    ]:
        result = subprocess.run([sys.executable, str(ROOT/'scripts'/script), *map(str, options)],
                                cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace')
        records.append({'script': script, 'code': result.returncode, 'log': result.stdout + result.stderr})
    if args.fetch_standings:
        try:
            result = subprocess.run([sys.executable, 'scripts/generate_standings_page.py', '--out', str(out/'standings.html')],
                                    cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace', timeout=45)
            records.append({'script': 'generate_standings_page.py', 'code': result.returncode, 'log': result.stdout + result.stderr})
        except subprocess.TimeoutExpired:
            records.append({'script': 'generate_standings_page.py', 'code': 1, 'log': 'official fetch timeout'})
    if args.standings_fixture:
        import generate_standings_page as standings
        fixture=ROOT/'scripts/fixtures/visual/standings-data.json'
        data={int(k):v for k,v in json.loads(fixture.read_text(encoding='utf-8')).items()}
        page=standings.render_page(data,2026,datetime(2026,10,27,tzinfo=timezone.utc))
        page=page.replace('<body>','<body><p style="background:#ffe08a;color:#15242d;padding:12px">見た目検査用の架空データ。本番順位ではありません。</p>')
        (out/'standings.html').write_text(page,encoding='utf-8')
        records.append({'script':'standings-fixture','code':0,'log':'explicit synthetic test data; not official standings'})
    # Saved data, with provenance; do not pretend these are current production values.
    latest = sorted((ROOT/'archive').glob('????-??-??.json'))[-1]
    shutil.copy2(latest, out/'games.json')
    for name in ('news.json', 'player_stats.json'):
        source = ROOT / 'data' / name
        if source.exists(): shutil.copy2(source, out/name)
    (out/'visual-build.json').write_text(json.dumps({'source': subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip(),
        'games_source': latest.relative_to(ROOT).as_posix(), 'generators': records,
        'scope': 'local saved-data rehearsal, external requests blocked'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False))
    return int(any(r['code'] for r in records))


if __name__ == '__main__':
    raise SystemExit(main())
