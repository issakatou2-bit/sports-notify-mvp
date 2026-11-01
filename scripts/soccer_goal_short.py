"""日本人選手の得点・アシストが確認できた終了試合を1試合1本にする。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import soccer_now as now

ROOT = Path(__file__).resolve().parents[1]


def build(boards, summaries, clock, receipts=None):
    items, rejected = now.build(boards, summaries, clock, receipts, max_age=now.GOAL_MAX_AGE, goal_short=True)
    selected = []
    seen = set(receipts or {})
    for data in items:
        game = data['games'][0]
        if game['id'] in seen: continue
        if not any(p['status'] != 'none' and (p.get('goals') or p.get('assists')) for p in game['players']): continue
        seen.add(game['id'])
        ended = now.results.utc(game['finished_utc']).astimezone(now.results.JST)
        data['result_ticker'] = f"日本時間{ended.month}月{ended.day}日 {ended:%H:%M}終了　日本人選手の得点・アシスト"
        selected.append(data)
    return selected, rejected


def save(data, out):
    """朝の結果と同じ原稿・尺調整・v5描画を通す。"""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    material = out/'material.json'
    material.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    commands = [
        ['soccer_results_render.py', '--goal-short', '--data', str(material), '--narration-out', str(out/'narration.json')],
        ['synthesize_narration.py', '--narration', str(out/'narration.json'), '--out-dir', str(out/'audio')],
        ['soccer_result_story.py', '--narration', str(out/'narration.json'), '--audio-dir', str(out/'audio')],
        ['soccer_results_render.py', '--goal-short', '--data', str(material), '--audio-dir', str(out/'audio'), '--out', str(out)],
    ]
    for script, *args in commands:
        subprocess.run([sys.executable, str(ROOT/'scripts'/script), *args], cwd=ROOT, check=True)
    return out/'collespo_soccer_results.mp4'


def live_material(clock, receipts):
    """朝の結果と同じ大会表・最終名簿を使う。単日取得でUTC日付の境界も覆う。"""
    import soccer_extra_fixtures as fixtures
    import soccer_selection as selection
    first = clock-now.timedelta(hours=8)
    boards, summaries = {}, {}
    failures = []
    for competition in selection.competitions():
        code = competition['code']
        try:
            board = fixtures.fetch_board(competition, first.date(), days=(clock.date()-first.date()).days+1)
        except Exception as error:
            failures.append(code)
            print(f'::warning::{code}の取得失敗: {fixtures.error_reason(error)}')
            continue
        selected = [e for e in board['events'] if now.completed(e) and str(e['id']) not in receipts
                    and first <= now.results.utc(e['date']) <= clock]
        boards[code+'_'+clock.strftime('%Y%m%d')] = dict(board, events=selected)
        for event in selected:
            ident = str(event['id'])
            if ident in summaries: continue
            try:
                summaries[ident] = now.results.fetch_json(f"{now.results.ESPN}/{competition['espn']}/summary?event={ident}")
            except Exception as error:
                print(f'::warning::{code} 試合{ident}の最終名簿取得失敗: {fixtures.error_reason(error)}')
    if failures and not boards:
        raise RuntimeError('全大会の取得に失敗しました')
    return boards, summaries


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--sample', action='store_true')
    ap.add_argument('--out', type=Path, default=ROOT/'build/soccer-goal-short')
    args = ap.parse_args()
    os.environ.setdefault('COLLESPO_SOCCER_LOOK', 'v5')
    os.environ.setdefault('COLLESPO_SHORT_LOOK', 'v4')
    if args.sample:
        boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        items, _ = build(boards, summaries, now.results.utc('2026-09-20T17:15:00Z'))
        for item in items:
            item['sample_fictional'] = True
            print(save(item, args.out/item['games'][0]['id']))
        return
    if os.environ.get('COLLESPO_SOCCER_GOAL_SHORT') != 'on':
        print('go=0' if args.plan else 'disabled')
        return
    ledger = __import__('soccer_publications').load()
    clock = datetime.now(timezone.utc)
    boards, summaries = live_material(clock, ledger)
    items, rejected = build(boards, summaries, clock, ledger)
    if rejected: print('rejected:', json.dumps(rejected, ensure_ascii=False))
    if args.plan:
        print('go=1' if items else 'go=0')
        return
    for item in items:
        folder = args.out/item['games'][0]['id']
        save(item, folder)
        now.publish(item, folder, ledger, goal_short=True)


if __name__ == '__main__':
    main()
