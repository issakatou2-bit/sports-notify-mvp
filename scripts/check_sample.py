"""送付前の見本検査。APSC scripts/check_sample.py の台本・実画素照合を参考にした。"""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import zlib

import metan_tone
import shorts_safe_area
from voice_manifest import sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _speaker(row):
    return str(row.get('speaker', row.get('who', '')))


def _words(value):
    return re.sub(r'[\W_は]+', '', value)


def script_issues(segments, *, respect_solo_host=True):
    aliases = {'metan': 2, '四国めたん': 2, 'めたん': 2, 'zundamon': 3, 'ずんだもん': 3}
    segments = [dict(row, speaker=aliases.get(_speaker(row), row.get('speaker'))) for row in segments]
    check_tone = not respect_solo_host or metan_tone.metan_enabled(segments)
    problems = [f'台詞{i} めたんの語尾 {ending}'
                for i, ending in metan_tone.check(segments)] if check_tone else []
    previous = ''
    for i, row in enumerate(segments, 1):
        text = row.get('text') or ''
        who = _speaker(row)
        if who in ('3', 'zundamon', 'ずんだもん'):
            if re.search(r'(?:つながって|並べて|少しずつ)?見えてきたのだ[。！!]?$', text):
                problems.append(f'台詞{i} 話をつなぐだけの相づち')
            if '？' not in text and '?' not in text:
                statement = _words(re.sub(r'(?:なのですね|のですね|なのだ|のだ)[。！!]?', '', text))
                substantive = len(statement) >= 5 or (len(statement) >= 4 and any(c.isdigit() for c in statement))
                if substantive and statement in _words(previous):
                    problems.append(f'台詞{i} めたんの答えの言い直し')
        previous = text if who in ('2', 'metan', '四国めたん', 'めたん') else ''
    return problems


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def geometry_issues(frame, size):
    layout = frame['layout']
    if not layout:
        return ['描画した文字・顔の配置記録がありません']
    problems = [f"安全域外 {row['role']} {row.get('text', '')} {row['box']}"
                for issue in shorts_safe_area.problems(layout)
                for row in [issue['outside_shorts_safe_area']]]
    portraits = frame.get('portraits', [])
    if any(row.get('corner') for row in portraits):
        for entry in layout:
            if entry['role'] == 'ticker':
                problems.append(f"立ち絵の配置に字が途中で切れる帯が残っています {entry.get('text', '')}")
    for row in portraits:
        who = row['who']
        face = row.get('face')
        if not face:
            problems.append(f'{who} の顔の位置が未記録')
        if who in ('metan', 'zundamon'):
            side = row.get('side')
            expected = {'left': 'right', 'right': 'left'}.get(side)
            if not expected or row.get('facing') != expected:
                problems.append(f'{who} の内向きを確認できない')
        dy = row.get('dy', 0)
        if abs(dy) > (3 if row.get('active') else 0):
            problems.append(f'{who} の上下移動 {dy}px')
        if row.get('rotation') or row.get('dx') or row.get('blink_effect'):
            problems.append(f'{who} に回転・横移動・点滅の指定')
        ink = row.get('ink')
        if row.get('corner'):
            # 11/22 本人「8割くらい」で立ち絵を864→691に縮めたのに、この範囲は22〜28%のまま残り、
            # 正しい回まで止めていた（11/25 関門で発覚）。8割の17.6〜22.4%を含む17〜23%にする。
            if ink is None or not .17 * size[1] <= ink[3] - ink[1] <= .23 * size[1]:
                problems.append(f'{who} の胸上が画面高の17〜23%に収まらない {ink}')
            floor = row.get('floor', [])
            if (len(floor) != 2 or not 0 <= floor[0] < floor[1] <= size[0]
                    or floor[1] - floor[0] < 16 or row['box'][3] != size[1]):
                problems.append(f'{who} の体が画面の下端に接していません')
            if row.get('side') != {'zundamon': 'left', 'metan': 'right'}.get(who):
                problems.append(f'{who} の立ち位置が左右逆')
        if ink:
            for entry in layout:
                if (entry['role'] != 'face' and (entry.get('text') or entry['role'] == 'caption')
                        and intersects(ink, entry['box'])):
                    problems.append(f"{who} が {entry['role']} {entry.get('text', '')} に重なる")
        if face:
            for decoration in layout:
                if decoration['role'] in ('symbol', 'decoration') and intersects(face, decoration['box']):
                    problems.append(f"{who} の顔に記号が重なる {decoration['box']}")
    for row in layout:
        x, y, right, bottom = row['box']
        if not (0 <= x <= right <= size[0] and 0 <= y <= bottom <= size[1]):
            problems.append(f"見切れ {row['role']} {row['box']}")
    return problems


def translation(previous, current):
    """固定領域2つで、全体の揺れだけを検出する。照明の明暗差は差分から除く。"""
    import numpy as np
    offsets = []
    for top, bottom in ((41, 66), (82, 280)):
        a = previous[top:bottom:2, 24:222:2]
        if float(a.std()) < 11:
            continue
        a = a - a.mean()
        errors = {}
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                b = current[top + dy:bottom + dy:2, 24 + dx:222 + dx:2]
                errors[dx, dy] = float(np.abs(a - (b - b.mean())).mean())
        best = min(errors, key=errors.get)
        if errors[best] < 2.5 and errors[0, 0] - errors[best] > 2:
            offsets.append(best)
    return len(offsets) == 2 and offsets[0] == offsets[1] and offsets[0] != (0, 0)


def video_issues(path, evidence):
    import numpy as np
    from sample_evidence import REFERENCE_SIZE

    if evidence['video_sha256'] != sha256(path):
        return ['動画と描画記録の指紋が違う']
    if tuple(evidence['reference_size']) != REFERENCE_SIZE:
        return ['照合画像の寸法が違う']
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
        'stream=width,height,nb_frames', '-of', 'json', str(path)]))
    video = probe['streams'][0]
    size = [video['width'], video['height']]
    if size not in ([1080, 1920], [1920, 1080]) or size != evidence['size']:
        return ['完成動画と安全域の寸法が一致しない']
    landscape = size == [1920, 1080]
    stride = evidence.get('stride', 3)
    if type(stride) is not int or not 1 <= stride <= (12 if landscape else 3):
        return ['描画記録の検査間隔が不正']
    problems = script_issues(evidence['segments'])
    rows = evidence['frames']
    if not rows or rows[0]['frame'] != 0:
        return problems + ['冒頭からの描画記録がない']
    width, height = REFERENCE_SIZE
    expected_frames = int(video['nb_frames'])
    indexes = [row['frame'] for row in rows]
    if not (0 <= expected_frames - 1 - indexes[-1] < stride) or any(
            not 1 <= b-a <= stride for a, b in zip(indexes, indexes[1:])):
        problems.append('末尾までの描画記録がない')
    selected = {row['frame']: row for row in rows}
    command = ['ffmpeg', '-v', 'error', '-i', str(path), '-an', '-vf',
               f'scale={width}:{height}:flags=bilinear', '-pix_fmt', 'gray',
               '-f', 'rawvideo', '-threads', '1', 'pipe:1']
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        previous = last = last_row = None
        for index in range(expected_frames):
            raw = process.stdout.read(width * height)
            if len(raw) != width * height:
                problems.append(f'コマ{index} を復号できない')
                break
            if index not in selected:
                continue
            row = selected[index]
            if landscape:
                if not row['layout']:
                    problems.append(f'コマ{index} 描画した文字の配置記録がない')
                for text in row['layout']:
                    x, y, right, bottom = text['box']
                    if not (0 <= x <= right <= size[0] and 0 <= y <= bottom <= size[1]):
                        problems.append(f"コマ{index} 見切れ {text['text']}")
            else:
                for problem in geometry_issues(row, size):
                    problems.append(f'コマ{index} {problem}')
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width).astype('float32')
            ref = np.frombuffer(zlib.decompress(base64.b64decode(row['reference'])), dtype=np.uint8)
            delta = np.abs(arr - ref.reshape(height, width))
            if float(delta.mean()) > 8:
                problems.append(f'コマ{index} 完成画素が書き出し記録と違う')
            for portrait in row.get('portraits', []):
                if len(portrait.get('floor', [])) == 2:
                    a, b = (round(x * width / size[0]) for x in portrait['floor'])
                    if b - a >= 4 and float(delta[-3:, a:b].mean()) > 14:
                        problems.append(f"コマ{index} {portrait['who']} の下端の画素が記録と違う")
            layout = [item for item in row['layout'] if item['role'] != 'face']
            stable = previous is not None and last == layout and not row['transition']
            if stable and not landscape and translation(previous, arr):
                problems.append(f'コマ{index} 画面・字幕の揺れ')
            if stable:
                old = {p['who']: p for p in last_row['portraits']}
                for p in row['portraits']:
                    q = old.get(p['who'])
                    if not q:
                        continue
                    x, y = p.get('origin') or p['box'][:2]
                    old_x, old_y = q.get('origin') or q['box'][:2]
                    if x != old_x or y - p['dy'] != old_y - q['dy']:
                        problems.append(f"コマ{index} {p['who']} のメタデータに位置の揺れ")
            previous, last, last_row = arr, None if row['transition'] else layout, row
        if process.wait():
            problems.append('動画の復号に失敗')
    return list(dict.fromkeys(problems))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.target.suffix.lower() == '.mp4':
            evidence = args.evidence or args.target.with_suffix('.sample-check.json')
            if evidence.is_file():
                issues = video_issues(args.target, read(evidence))
            else:
                issues = ['動画に紐づいた描画記録がありません。向き・見切れ・揺れは未検査です']
                legacy = args.target.parent / 'layout_checks.json'
                if legacy.is_file():
                    issues.extend(f"旧配置 {problem}"
                                  for row in read(legacy) for problem in geometry_issues(
                                      dict(layout=row.get('layout') or []), [1080, 1920]))
        else:
            data = read(args.target)
            segments = data.get('segments')
            if not isinstance(segments, list) or not segments:
                raise ValueError('台本に segments がありません')
            issues = script_issues(segments)
            print('検査対象は台本。画面の検査は動画が必要です。')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        issues = [str(exc)]
    for issue in dict.fromkeys(issues):
        print(issue)
    print(f'指摘 {len(set(issues))}件')
    return bool(issues)


if __name__ == '__main__':
    raise SystemExit(main())
