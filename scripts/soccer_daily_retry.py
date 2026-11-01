"""選定済みの次点を1回だけ制作する。公開は既存workflowと投稿台帳に任せる。"""
import argparse
import copy
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import sanity_budget

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def next_material(data):
    """再採点しない。選定済み2位がなければ止まる。3位へは進まない。"""
    selected = data.get('preview_selection') or {}
    ids = selected.get('selected_ids') or []
    if len(ids) < 2 or len(set(ids)) != len(ids):
        return None
    matches = [g for g in data['games'] if str(g.get('game_id')) == str(ids[1])]
    if len(matches) != 1:
        return None
    result = copy.deepcopy(data)
    for game in result['games']:
        game['is_notable'] = str(game.get('game_id')) == str(ids[1])
    result['preview_selection'].update(selected_ids=[ids[1]], count=1)
    return result


def segments_hash(document):
    return hashlib.sha256(json.dumps(document['segments'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def failure(sanity_outcome, video_outcome, sanity_file, out, narration_file):
    if sanity_outcome == 'failure':
        report = read(sanity_file) if Path(sanity_file).is_file() else {}
        if report.get('upload_held') and report.get('blocking_issues'):
            return dict(stage='sanity_high', reasons=report['blocking_issues'])
        return None
    if sanity_outcome != 'success' or video_outcome != 'failure':
        return None
    if not Path(narration_file).is_file():
        return None
    digest = segments_hash(read(narration_file))
    gate = Path(out)/'short_content_gate.json'
    if gate.is_file():
        report = read(gate)
        if (report.get('status') == 'held' and report.get('information_count', 3) < 3
                and report.get('segments_sha256') == digest):
            return dict(stage='information', reasons=report.get('reasons', []))
    layout = Path(out)/'layout_hold.json'
    if (layout.is_file() and (report := read(layout)).get('status') == 'held'
            and report.get('errors') and report.get('segments_sha256') == digest):
        return dict(stage='layout', reasons=report['errors'], scene=report.get('scene'))
    return None


def build(args, runner=None):
    runner = runner or (lambda command: subprocess.run(command, cwd=ROOT, check=False).returncode)
    evidence = Path(args.record).parent
    evidence.mkdir(parents=True, exist_ok=True)
    record = dict(version=1, kind='daily_soccer', status='held', rebuilt=False, attempts=[],
                  reason='作り直し対象外', run_id=os.getenv('GITHUB_RUN_ID', ''),
                  run_attempt=os.getenv('GITHUB_RUN_ATTEMPT', ''))
    if Path(args.record).is_file():
        previous = read(args.record)
        if (previous.get('rebuilt') and previous.get('run_id') == record['run_id']
                and previous.get('run_attempt') == record['run_attempt']):
            print('この実行では次点をすでに1回制作しています。再制作しません')
            return 1

    def finish(code):
        record['paid_checks'] = sanity_budget.state()
        write(args.record, record)
        # 初回と作り直しのhold本体は別ファイルで保存し、最終の既存記録からも辿れる。
        if Path(args.hold).is_file():
            held = read(args.hold)
            if code and record['status'] == 'held':
                held.update(status='held', reason=record['reason'])
                held['reasons'] = list(held.get('reasons') or []) + [record['reason']]
            held['soccer_retry'] = record
            write(args.hold, held)
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with Path(summary).open('a', encoding='utf8') as stream:
                stream.write('\n### サッカー予告の作り直し\n\n'+json.dumps(record, ensure_ascii=False)+'\n')
        print(json.dumps(record, ensure_ascii=False))
        return code

    data = read(args.games)
    # 既存の同日・同種台帳判定を共有。公開済みの回を次点へ差し替えない。
    import upload_youtube
    day = datetime.fromisoformat(data['generated_at'].replace('Z', '+00:00')).astimezone(
        timezone(timedelta(hours=9))).date().isoformat()
    if upload_youtube.published_video('daily_soccer', day, str(args.published)):
        record.update(status='already_published', reason='既存の公開台帳に予告あり・再制作なし')
        return finish(1)
    cause = failure(args.sanity_outcome, args.video_outcome, args.sanity, args.out, args.narration)
    if not cause:
        return finish(1)
    record['attempts'].append(dict(attempt=1, **cause))
    for source in (args.games, args.narration, args.sanity, args.hold):
        if Path(source).is_file():
            shutil.copy2(source, evidence/('first-'+Path(source).name))
    for name in ('short_content_gate.json', 'layout_hold.json'):
        if (Path(args.out)/name).is_file():
            shutil.copy2(Path(args.out)/name, evidence/('first-'+name))
    replacement = next_material(data)
    if replacement is None:
        record['reason'] = '選定済みの次点なし'
        return finish(1)
    # 初回の限定再点検ですでに追加分を使った場合、無料検査だけで公開しない。
    if not sanity_budget.available():
        record['reason'] = '追加の有料検査1回を消費済み'
        return finish(1)
    work = evidence/'second'
    games, narration, audio, video = work/'games.json', work/'soccer_narration.json', work/'audio', work/'video'
    sanity_file, hold_file = work/'sanity_soccer.json', work/'sanity_soccer_hold.json'
    write(games, replacement)
    record.update(rebuilt=True, original_ids=data['preview_selection']['selected_ids'],
                  replacement_ids=replacement['preview_selection']['selected_ids'])
    attempt = dict(attempt=2, selected_ids=record['replacement_ids'], status='held')
    record['attempts'].append(attempt)
    # 中断されても同じ実行で3本目を作らない。初回の証拠は上書きしない。
    write(args.record, record)
    commands = [
        ('narration', ['generate_narration.py', '--games', str(games), '--out', str(narration)]),
        ('sanity', ['sanity.py', '--general', '--strict', '--narration', str(narration),
                    '--out', str(sanity_file), '--hold-record', str(hold_file), '--kind', 'daily_soccer']),
        ('audio', ['synthesize_narration.py', '--narration', str(narration), '--out-dir', str(audio)]),
        ('video', ['generate_video.py', '--games', str(games), '--sport', 'soccer',
                   '--audio-dir', str(audio), '--out', str(video), '--require-audio'])]
    for stage, command in commands:
        try:
            code = runner([sys.executable, str(ROOT/'scripts'/command[0]), *command[1:]])
        except OSError as error:
            attempt.update(stage=stage, error_type=type(error).__name__)
            record['reason'] = '次点の制作処理を起動できず停止'
            return finish(1)
        if code:
            attempt.update(stage=stage, exit_code=code)
            for name, path in (('sanity', sanity_file), ('hold', hold_file),
                               ('content', video/'short_content_gate.json'), ('layout', video/'layout_hold.json')):
                if path.is_file():
                    attempt[name] = read(path)
            record['reason'] = '次点も検査・制作を通過せず停止'
            return finish(1)
        # CLI成功だけでhighを取り逃さない。短縮後の検査もgenerate_videoに任せる。
        if stage == 'sanity':
            report = read(sanity_file) if sanity_file.is_file() else {}
            held = read(hold_file) if hold_file.is_file() else {}
            if (report.get('upload_held') is not False or held.get('status') != 'passed'
                    or any(report.get(k) for k in ('blocking_issues', 'contradictions', 'impossible'))):
                attempt.update(stage=stage, reason='常識点検の合格記録なし', sanity=report)
                record['reason'] = '次点の常識点検記録が合格を満たさず停止'
                return finish(1)
    if not (video/'collespo_short.mp4').is_file() or not (video/'verification.json').is_file():
        attempt.update(stage='video', reason='完成動画・検査記録なし')
        return finish(1)
    # 合格した別ディレクトリの成果だけを従来の投稿入口へ戻す。初回の残骸は使わない。
    shutil.copytree(audio, args.audio_dir, dirs_exist_ok=True)
    shutil.copytree(video, args.out, dirs_exist_ok=True)
    for source, target in ((games, args.games), (narration, args.narration),
                           (sanity_file, args.sanity), (hold_file, args.hold)):
        shutil.copy2(source, target)
    attempt.update(status='passed')
    record.update(status='passed', reason='選定済み次点で1回作り直し・全検査通過')
    return finish(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in dict(games='data/soccer_games.json', narration='build/soccer_narration.json',
            sanity='data/sanity_soccer.json', hold='build/sanity_soccer_hold.json',
            audio_dir='build/soccer_audio', out='build/soccer',
            published='data/published_videos.json', record='build/soccer_retry/retry.json').items():
        parser.add_argument('--'+name.replace('_', '-'), type=Path, default=ROOT/default)
    parser.add_argument('--sanity-outcome', required=True)
    parser.add_argument('--video-outcome', required=True)
    args = parser.parse_args()
    if sanity_budget.path() is None:
        parser.error('初回から共有した検査回数記録が必要です')
    return build(args)


if __name__ == '__main__':
    raise SystemExit(main())
