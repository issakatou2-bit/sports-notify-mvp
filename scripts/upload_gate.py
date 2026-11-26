"""YouTubeへ送る動画・台本・説明欄の投稿前検査。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib

import check_sample
import metan_tone


EXEMPT = {}  # 描画記録を作らない種類を承認したときだけ、種類と理由を記す。
SHORT_SIZE = (1080, 1920)
VOICE_NAMES = {'四国めたん': {'2', 'metan', '四国めたん', 'めたん'},
               'ずんだもん': {'3', 'zundamon', 'ずんだもん'}}
KATAKANA = re.compile(r'[ァ-ヺー]+(?:・[ァ-ヺー]+)*')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def probe_size(video):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=width,height', '-of', 'json', str(video)],
        check=True, capture_output=True, timeout=30,
    )
    stream = json.loads(result.stdout)['streams'][0]
    return int(stream['width']), int(stream['height'])


def credit_issues(segments, description):
    speakers = {str(row.get('speaker', row.get('who'))) for row in segments if row.get('voice_host') != 'ui'}
    ui = any(row.get('voice_host') == 'ui' for row in segments)
    required = ['VOICEVOX', *(name for name, aliases in VOICE_NAMES.items() if speakers & aliases)] if speakers else []
    if ui:
        required.append('雨衣')
    return [f'説明欄に「{name}」の表記がありません' for name in required if name not in description]


def with_voice_hosts(segments):
    """音声の明記がなければ、既存のソロ話者判定を使う。"""
    if metan_tone.metan_enabled(segments):
        return segments
    return [dict(row, voice_host=row.get('voice_host') or 'ui') for row in segments]


def protected_words(segments):
    words = {'VOICEVOX', *VOICE_NAMES}
    for row in segments:
        words.update(word for word in KATAKANA.findall(row['text'])
                     if len(word.replace('・', '')) >= 3)
    return sorted(words)


def wrap_issues(layout, words):
    by_role = defaultdict(list)
    for row in layout:
        if row.get('text', '').strip():
            by_role[row['role']].append(row)

    for role, rows in by_role.items():
        rows.sort(key=lambda row: (row['box'][1], row['box'][0]))
        joined, boundaries = '', []
        previous_top = previous_bottom = -1
        for row in rows:
            _, top, _, bottom = row['box']
            if top > previous_top and top >= previous_bottom and joined:
                boundaries.append(len(joined))
            else:
                joined += '\n'
            joined += row['text'].strip()
            previous_top, previous_bottom = top, bottom

        if not boundaries:
            continue
        for word in words:
            if any(match.start() < boundary < match.end()
                   for match in re.finditer(re.escape(word), joined) for boundary in boundaries):
                yield f'{role} の「{word}」が行の途中で折り返されています'


def check(video, segments_path, description, kind):
    """終了値と日本語の指摘を返す。入力を検査できない場合は終了値2。"""
    video, segments_path = Path(video), Path(segments_path)
    if not video.is_file() or not kind.strip():
        return 2, ['動画のファイルと種類を指定してください']
    try:
        segments = read_json(segments_path)['segments']
        if not isinstance(segments, list) or not segments or any(
                not isinstance(row, dict) or not isinstance(row.get('text'), str)
                for row in segments):
            raise ValueError
        voices = with_voice_hosts(segments)
        # 説明欄でも雨衣を確認してから、ソロ指定による口調の例外を適用する。
        tone_segments = voices if '雨衣' in description else segments
        issues = check_sample.script_issues(tone_segments, respect_solo_host=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 2, [f'台本の segments を読めません（{segments_path}）']
    issues.extend(credit_issues(voices, description))

    try:
        size = probe_size(video)
        if min(size) <= 0:
            raise ValueError
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return 2, [*issues, f'ffprobe で動画の寸法を確認できません（{video}）']

    evidence_path = video.with_suffix('.sample-check.json')
    layout_path = video.parent / 'layout_checks.json'
    has_sample = evidence_path.is_file()
    record_path = evidence_path if has_sample else layout_path
    if not record_path.is_file():
        if size == SHORT_SIZE and not EXEMPT.get(kind, '').strip():
            issues.append('描画の記録が無い（.sample-check.json または layout_checks.json）')
        return int(bool(issues)), issues

    try:
        record = read_json(record_path)
        frames = record['frames'] if has_sample else record
        if not isinstance(frames, list) or not frames:
            return 1, [*issues, f'描画の記録にコマがありません（{record_path}）']
        if has_sample and size in (SHORT_SIZE, (1920, 1080)):
            issues.extend(check_sample.video_issues(video, record))
        words = protected_words(segments)
        for index, frame in enumerate(frames):
            problems = []
            if size == SHORT_SIZE and not has_sample:
                problems.extend(check_sample.geometry_issues(frame, size))
            problems.extend(wrap_issues(frame['layout'], words))
            position = f'コマ{frame.get("frame", index)}'
            if 'scene' in frame:
                position = f'場面{frame["scene"]} {position}'
            issues.extend(f'{position} {problem}' for problem in problems)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError,
            TypeError, AttributeError, ImportError, zlib.error):
        return 2, [*issues, f'描画の記録を検査できません（{record_path}）']
    return int(bool(issues)), list(dict.fromkeys(' '.join(issue.splitlines()) for issue in issues))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--segments', type=Path, required=True)
    parser.add_argument('--description-file', type=Path, required=True)
    parser.add_argument('--kind', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        description = args.description_file.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        status, issues = 2, [f'説明欄のファイルを読めません（{args.description_file}）']
    else:
        status, issues = check(args.video, args.segments, description, args.kind)
    if args.json:
        print(json.dumps(dict(passed=status == 0, status=status, issues=issues), ensure_ascii=False))
    elif issues:
        print('\n'.join(issues))
    else:
        print('投稿前検査に合格しました')
    return status


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
