"""保存材料の未読の事実で27秒を補う。通信・無音追加・話速変更なし。"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import soccer_look


def normalized(text):
    return re.sub(r'[\s。、！？]', '', text.replace('です', ''))


def candidates(mode, data, narr):
    """現在読んでいる札に対応する材料だけ。候補は有限、同じ文は再利用しない。"""
    segs = narr['segments']
    spoken = normalized(''.join(s['text'] for s in segs))
    found = []

    def add(index, text):
        if normalized(text) not in spoken and text not in [t for _, t in found]:
            found.append((index, text))

    if mode == 'race':
        import notability_engine as ne
        for i, seg in enumerate(segs):
            if seg['kind'] != 'standings':
                continue
            for row in seg['meta'].get('rows', []):
                rank, points = row.get('position'), row.get('points')
                if type(rank) is int and rank > 0 and type(points) is int and points >= 0:
                    club = ne.club_name_jp(row.get('team_en') or row['team'])
                    # 札の順位と勝点は入力順位表から構築済み。
                    add(i, f'{club}は{rank}位で勝点{points}です。')
    elif mode == 'preview':
        from soccer_story_lines import preview_facts
        for i, seg in enumerate(segs):
            if seg['kind'] != 'preview':
                continue
            meta = seg['meta']
            game = next((g for g in data.get('games', [])
                         if str(g.get('game_id')) == str(meta.get('game_id'))), None)
            if game:
                for text in preview_facts(game, []):
                    add(i, text)
    elif mode == 'week':
        for row in data.get('rows', []):
            if not all(type(row.get(k)) is int and row[k] >= 0 for k in ('gf', 'ga')):
                continue
            i = next((i for i, s in enumerate(segs) if s['kind'] == 'jp_player'
                      and s['meta'].get('club') == row.get('club')), None)
            if i is not None:
                add(i, f"{row['club']}は{row['opp']}との試合を{row['gf']}対{row['ga']}で終えました。")
    elif mode == 'results':
        import soccer_result_facts as facts
        for i, seg in enumerate(segs):
            ident = seg['meta'].get('event_id')
            if ident is None or seg['kind'] == 'outro':
                continue
            for person in data.get('players', []):
                if person.get('event_id') == ident and person.get('status') != 'none':
                    add(i, facts.player_line(person))
    return found


def append(narr, index, text):
    seg = narr['segments'][index]
    before = seg['text']
    seg['text'] += text
    if 'caption_units' in seg:
        seg['caption_units'].append(text)
    narr.setdefault('minimum_repair', []).append(dict(index=index, text=text, before=before))


def restore(base, saved, mode, data):
    """描画時も材料から再現し、保存原稿の任意の差替えを許さない。"""
    if not soccer_look.focus() or not saved.get('minimum_repair'):
        return base
    if base == saved:
        return base  # host_splitが保存音声に対応する確定原稿を解決済み。
    result = copy.deepcopy(base)
    for change in saved['minimum_repair']:
        index, text = change['index'], change['text']
        if (index, text) not in candidates(mode, data, result):
            raise ValueError('尺補充の文が未使用の入力事実と一致しません')
        append(result, index, text)
    if result != saved:
        raise ValueError('尺補充後の原稿が入力材料と一致しません')
    return result


def measured(mode, data, narr, audio):
    if mode != 'results':
        import soccer_slots_v4 as slots
        return slots.video_times(narr['segments'], audio)
    import soccer_results_render as render
    from soccer_readable import minimum_seconds
    times = render.durations(narr['segments'], audio)
    times = [max(t, minimum_seconds(s, data)) for s, t in zip(narr['segments'], times)]
    return [math.ceil(t * render.FPS) / render.FPS for t in times]


def target_seconds(narr):
    if narr.get('short_content_version') != '1108':
        return 27.0
    import short_content
    short_outro = any(seg.get('kind') == 'outro' and seg.get('meta', {}).get('short_outro')
                      for seg in narr.get('segments', []))
    minimum = short_content.SHORT_MIN_SECONDS if short_outro else short_content.MIN_SECONDS
    return minimum - short_content.SHORT_GRACE


def fit(mode, data, narr, audio, directory, *, measure=measured, rebuild=None):
    if not soccer_look.focus():
        return narr, audio, False
    import soccer_result_story as story
    rebuild = rebuild or story.rebuild_voice
    narr, audio = copy.deepcopy(narr), copy.deepcopy(audio)
    target = target_seconds(narr)
    while sum(measure(mode, data, narr, audio)) < target - 1e-6:
        options = candidates(mode, data, narr)
        if not options:
            return narr, audio, True
        index, text = options[0]
        append(narr, index, text)
        audio[index] = rebuild(narr['segments'][index], audio[index], directory, 'minimum')
    return narr, audio, False


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=('race', 'week', 'preview', 'results'), required=True)
    ap.add_argument('--data', type=Path, required=True)
    ap.add_argument('--narration', type=Path, required=True)
    ap.add_argument('--audio-dir', type=Path, required=True)
    args = ap.parse_args()
    if not soccer_look.focus():
        return
    import host_split
    narr = host_split.use_audio(read(args.narration), args.audio_dir)
    manifest_path = args.audio_dir/'manifest.json'
    manifest = read(manifest_path)
    narr, audio, skip = fit(args.mode, read(args.data), narr, manifest['segments'], args.audio_dir)
    write(args.audio_dir/'minimum_result.json', dict(status='skipped' if skip else 'ready',
          reason=f'追加できる未使用の事実がないため{target_seconds(narr):g}秒未満の回を見送ります' if skip else '',
          repairs=narr.get('minimum_repair', [])))
    write(args.narration, narr)
    if manifest.get('narration_path') and Path(manifest['narration_path']) != args.narration:
        write(manifest['narration_path'], narr)
    manifest['segments'] = audio
    write(manifest_path, manifest)
    import voice_manifest
    voice_manifest.save(args.audio_dir, audio, narr)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as stream:
            stream.write('skip='+str(skip).lower()+'\n')
    if skip:
        print(f'::notice::追加できる事実がなく{target_seconds(narr):g}秒未満のため制作を見送ります')
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf8') as stream:
                stream.write(f'\n{target_seconds(narr):g}秒未満。未使用の事実がないため制作見送り（正常終了）。\n')


if __name__ == '__main__':
    main()
