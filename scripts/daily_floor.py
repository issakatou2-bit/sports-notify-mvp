"""日本時間の公開・予約を数え、不足時はクラブ戦ショートを1回ずつ補う。"""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import soccer_club_topics as club
from soccer_results import JST, utc
from upload_youtube import LANDSCAPE_KINDS
from video_visibility import exclusion_reason

FLOOR = 3
WORKFLOW = 'soccer_club_topics.yml'


def count_by_kind(records, day):
    shorts, longform = Counter(), Counter()
    seen = set()
    for kind, rows in records.items():
        for row in rows.values():
            when = row.get('publish_at') or row.get('published_at')
            video = row.get('video_id')
            if not video or video in seen or not when:
                continue
            if exclusion_reason(row) not in (None, '予約時刻前'):
                continue
            if utc(when).astimezone(JST).date() == day:
                seen.add(video)
                (longform if kind in LANDSCAPE_KINDS else shorts)[kind] += 1
    return shorts, longform


class Actions:
    def __init__(self, repo, ref, token, url='https://api.github.com'):
        self.base = f'{url}/repos/{repo}/actions'
        self.ref = ref
        self.token = token

    def request(self, path, data=None):
        request = Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                          headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2026-03-10', 'Content-Type': 'application/json'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def dispatch(self, topic, day):
        run = self.request(f'/workflows/{WORKFLOW}/dispatches', dict(
            ref=self.ref, inputs=dict(topic_key=topic, publication_day=day.isoformat())))
        return run['workflow_run_id']

    def wait(self, run_id, deadline):
        while time.monotonic() < deadline:
            row = self.request(f'/runs/{run_id}')
            if row['status'] == 'completed':
                return row['conclusion']
            time.sleep(15)
        raise TimeoutError('クラブ戦の実行が制限時間内に終わりませんでした')

    def wait_for_idle(self, deadline):
        for status in ('queued', 'in_progress', 'pending', 'waiting', 'requested'):
            query = urlencode(dict(branch=self.ref, status=status, per_page=100))
            for run in self.request(f'/workflows/{WORKFLOW}/runs?{query}')['workflow_runs']:
                self.wait(run['id'], deadline)


def check_day(snapshot, now, enabled, publishing, actions=None):
    """公開台帳の最新版を毎回読み、実際に予約が増えた分を数える。"""
    day = now().astimezone(JST).date()
    attempted = set()
    deadline = time.monotonic() + 105 * 60
    notes = []
    while True:
        records, pool, ledger = snapshot(refresh=bool(attempted))
        current = now()
        shorts, longform = count_by_kind(records, day)
        docs = club.candidates(pool, ledger, current)
        if sum(shorts.values()) >= FLOOR:
            break
        if not enabled or not publishing or current.astimezone(JST).date() != day:
            if not enabled:
                notes.append('自動補充は off')
            elif not publishing:
                notes.append('クラブ戦の公開設定は false')
            else:
                notes.append('日本時間で日付をまたいだ')
            break
        try:
            actions.wait_for_idle(deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError('自動補充の制限時間を過ぎました')
            records, pool, ledger = snapshot(refresh=True)
            current = now()
            shorts, longform = count_by_kind(records, day)
            docs = club.candidates(pool, ledger, current)
            if sum(shorts.values()) >= FLOOR:
                break
            if current.astimezone(JST).date() != day or not club.reservation(current, ledger, records):
                notes.append('当日の予約枠なし')
                break
            doc = next((d for d in docs if d['topic_key'] not in attempted), None)
            if not doc:
                if docs:
                    notes.append('候補の実行後に予約を確認できなかった')
                break
            key = doc['topic_key']
            attempted.add(key)
            conclusion = actions.wait(actions.dispatch(key, day), deadline)
            if conclusion != 'success':
                notes.append(f'クラブ戦の実行結果 {conclusion}')
                # アップロード後に台帳保存だけ失敗した可能性もある。次を押す前に停止して再集計する。
                records, pool, ledger = snapshot(refresh=True)
                shorts, longform = count_by_kind(records, day)
                docs = club.candidates(pool, ledger, now())
                break
        except (URLError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            notes.append(f'クラブ戦の実行確認に失敗（{type(exc).__name__}）')
            break
    return day, shorts, longform, len(docs), notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', help='公開台帳とクラブ戦フローのブランチ')
    args = parser.parse_args(argv)
    enabled = os.getenv('COLLESPO_DAILY_FLOOR', 'off') == 'on'
    publishing = os.getenv('COLLESPO_CLUB_TOPICS_PUBLISH') == 'true'

    def snapshot(*, refresh):
        if refresh:
            subprocess.run(['git', 'fetch', '--no-tags', 'origin', args.ref], check=True, timeout=60)

        def read(path, optional=False):
            if refresh:
                result = subprocess.run(['git', 'show', f'FETCH_HEAD:{path}'], capture_output=True, check=True, timeout=30)
                return json.loads(result.stdout)
            return (club.read_pool if optional else club.national.read)(path)

        return (read('data/published_videos.json'), read('data/soccer_club_topic_candidates.json', optional=True),
                read('data/soccer_club_topics_published.json'))

    actions = None
    if enabled and publishing:
        if not args.ref:
            parser.error('自動補充時は --ref が必要です')
        actions = Actions(os.environ['GITHUB_REPOSITORY'], args.ref, os.environ['GH_TOKEN'], os.environ['GITHUB_API_URL'])

    day, shorts, longform, available, notes = check_day(snapshot, lambda: datetime.now(JST), enabled, publishing, actions)
    n = sum(shorts.values())
    detail = lambda counts: '、'.join(f'{k} {v}本' for k,v in sorted(counts.items())) or '0本'
    text = (f'## {day}（JST）\n\n今日はショート{n}本 / 目標{FLOOR}本（{detail(shorts)}）\n\n'
            f'長編 {sum(longform.values())}本（{detail(longform)}）\n')
    if n < FLOOR:
        stock = subprocess.run([sys.executable, 'scripts/next_asset.py', '--stock'],
                               capture_output=True, timeout=60, text=True, encoding='utf-8')
        inventory = stock.stdout.strip()
        if stock.returncode or not inventory.isdecimal():
            inventory = '未確認'
        line = f'今日は{n}本。あと{FLOOR-n}本。資産在庫{inventory}・クラブ戦候補{available}'
        line += '。' + '・'.join(notes) if notes else ''
        text += '\n' + line + '\n'
        print('::warning::' + line)
    print(text)
    out = os.getenv('GITHUB_STEP_SUMMARY')
    if out:
        with Path(out).open('a', encoding='utf-8') as summary:
            summary.write(text + '\n')


if __name__ == '__main__':
    main()
