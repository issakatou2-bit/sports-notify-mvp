"""既存Git履歴から、公開IDと一致する直近の題材だけを移行する（通信なし）。"""
import argparse
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import morning_topics as topics


def git(*args):
    result = subprocess.run(['git', *args], capture_output=True, encoding='utf-8',
                            errors='strict', check=True)
    return result.stdout


def selected(record, material, kind):
    if material.get('updated_at') and record.get('published_at'):
        collected = datetime.fromisoformat(material['updated_at'].replace('Z', '+00:00'))
        uploaded = datetime.fromisoformat(record['published_at'].replace('Z', '+00:00'))
        if not timedelta(0) <= uploaded - collected <= timedelta(hours=2):
            return []
    spoken = [record.get('title', '')] + [r.get('text', '') for r in record.get('dialogue_starts') or []]
    if kind == 'morning_voices':
        title = topics.evidence({'title': record.get('title', '')})
        return [topics.evidence(row) for row in material.get('voices') or []
                if topics.same(title, topics.evidence(row)) or
                (len(topics.normalize(topics.subject(row.get('video_topic') or ''))) >= 12
                 and topics.normalize(topics.subject(row['video_topic'])) in
                 topics.normalize(topics.subject(record.get('title', ''))))]
    # 発話に実際に残っている引用だけ。未採用の候補を既出とは扱わない。
    said = [topics.normalize(s) for s in spoken]
    from generate_morning_short import clip_sentences
    from local_reporters import baseball_jp
    out = []
    for row in (material.get('headlines') or []) + (material.get('posts') or []):
        raw = baseball_jp(row.get('jp') or '') or row.get('title') or row.get('text') or ''
        if row in (material.get('posts') or []):
            raw = clip_sentences(raw)
        body = topics.normalize(raw)
        if len(body) < 18:
            continue
        if any(body in text for text in said):
            out.append(topics.evidence(row))
    return out


def build(day):
    edition = date.fromisoformat(day)
    current = topics.read(topics.LEDGER)
    wanted = {kind: {key: row for key, row in (current.get(kind) or {}).items()
                     if edition - timedelta(days=7) <= date.fromisoformat(key) <= edition
                     and row.get('video_id')} for kind in topics.KINDS}
    revisions = git('log', '--since=' + (edition - timedelta(days=8)).isoformat(),
                    '--format=%H', '--', 'data/local_voices.json', 'data/local_reporters.json').splitlines()
    seed = {kind: {} for kind in topics.KINDS}
    for revision in revisions:
        ledger = json.loads(git('show', revision + ':' + topics.LEDGER))
        for kind, filename in [('morning_voices', 'data/local_voices.json'),
                               ('morning_press', 'data/local_reporters.json')]:
            material = json.loads(git('show', revision + ':' + filename))
            if kind == 'morning_voices':
                buzz = json.loads(git('show', revision + ':data/mlb_buzz.json'))
                videos = {str(v.get('video_id')): v for v in buzz.get('videos') or []}
                enriched = []
                for row in material.get('voices') or []:
                    video = videos.get(topics.canonical_url(row.get('url', '')).removeprefix('youtube:')) or {}
                    enriched.append(dict(row, video_topic=video.get('topic_jp', ''),
                                         game_date=video.get('game_date', '')))
                material['voices'] = enriched
            for key, current_row in wanted[kind].items():
                if key in seed[kind]:
                    continue
                record = (ledger.get(kind) or {}).get(key) or {}
                if record.get('video_id') != current_row['video_id']:
                    continue
                rows = selected(record, material, kind)
                if rows:
                    seed[kind][key] = {'video_id': record['video_id'], 'revision': revision,
                                      'source_topics': list({json.dumps(r, sort_keys=True): r for r in rows}.values())}
    return seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--out', default='data/morning_topic_seed.json')
    args = parser.parse_args()
    seed = build(args.date)
    Path(args.out).write_text(json.dumps(seed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for kind in topics.KINDS:
        count = sum(len(r['source_topics']) for r in seed[kind].values())
        print(f'{kind}: 公開{len(seed[kind])}本 / 題材{count}件をGit履歴から照合')


if __name__ == '__main__':
    main()
