"""P0突合の再現用。保存資料だけを読み、標準出力へJSONを返す。"""
from collections import defaultdict
import json
from pathlib import Path

from backfill_records import kind_of
from ledger_adapter import convert, documents


def audit(docs, analytics, playlists):
    observations = [o for o in convert(docs) if o['service'] == 'youtube']
    by_video, by_publication = defaultdict(list), defaultdict(list)
    for obs in observations:
        if obs.get('video_id'):
            by_video[obs['video_id']].append(obs)
            by_publication[obs['publication_id']].append(obs)
    result = dict(video_in_multiple_editions=[], edition_with_multiple_videos=[],
                  cross_kind_registration=[], title_kind_mismatch=[],
                  saved_not_in_ledger=[], playlist_kind_mismatch=[])
    for vid, rows in sorted(by_video.items()):
        refs = sorted({o['source'] for o in rows})
        if len({o['publication_id'] for o in rows}) > 1:
            result['video_in_multiple_editions'].append(dict(video_id=vid, sources=refs))
        kinds = {o['legacy_kind'] for o in rows}
        if len(kinds) > 1:
            result['cross_kind_registration'].append(dict(video_id=vid, kinds=sorted(kinds), sources=refs))
    for pid, rows in sorted(by_publication.items()):
        ids = sorted({o['video_id'] for o in rows})
        if len(ids) > 1:
            result['edition_with_multiple_videos'].append(dict(publication_id=pid, video_ids=ids,
                sources=sorted({o['source'] for o in rows}),
                repair_documented=any(o['source'].startswith('video_repairs/') for o in rows)))
    for obs in observations:
        inferred = kind_of(obs['raw'].get('title', ''))
        if inferred and inferred != obs['legacy_kind']:
            result['title_kind_mismatch'].append(dict(video_id=obs['video_id'], source=obs['source'],
                kind=obs['legacy_kind'], title_kind=inferred, title=obs['raw']['title']))
    saved = defaultdict(list)
    for day, data in sorted(analytics.get('days', {}).items()):
        for row in data.get('videos', []):
            if row.get('video'):
                saved[row['video']].append(dict(source=f'analytics/days/{day}', title=row.get('title')))
    for kind, data in sorted(playlists.items()):
        for vid in data.get('videos', []):
            saved[vid].append(dict(source=f'playlists/{kind}'))
            # postseason等の広い分類は台帳kindと1対1ではないので判定しない。
            if kind in docs.get('published_videos', {}) and vid in by_video:
                actual = sorted({o['legacy_kind'] for o in by_video[vid]})
                if kind not in actual:
                    result['playlist_kind_mismatch'].append(dict(video_id=vid, playlist=kind, ledger_kinds=actual))
    for vid, evidence in sorted(saved.items()):
        if vid not in by_video:
            result['saved_not_in_ledger'].append(dict(video_id=vid, evidence=evidence))
    result['coverage'] = dict(youtube_observations=len(observations), ledger_video_ids=len(by_video),
                              saved_video_ids=len(saved), analytics_days=len(analytics.get('days', {})),
                              analytics_first=min(analytics.get('days', {}), default=None),
                              analytics_last=max(analytics.get('days', {}), default=None), playlists=len(playlists))
    return result


def read_audit(root):
    root = Path(root)
    return audit(documents(root), json.loads((root/'data/analytics.json').read_text(encoding='utf8')),
                 json.loads((root/'data/playlists.json').read_text(encoding='utf8')))


if __name__ == '__main__':
    print(json.dumps(read_audit(Path(__file__).resolve().parents[1]), ensure_ascii=False, indent=2))
