"""保存台帳・分析・制作資料だけからショート一覧を作る（取得・公開なし）。"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

JST = timezone(timedelta(hours=9))
FIRST, LAST = '2026-10-14', '2026-10-27'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def category(kind, key):
    if kind != 'asset':
        return kind
    for prefix in ('season_game', 'season_story', 'season_player', 'season_team', 'season_league'):
        if key.startswith(prefix):
            return 'asset/'+prefix
    for prefix in ('venue_', 'rare_', 'legend_', 'ws_'):
        if key.startswith(prefix):
            return 'asset/'+prefix.rstrip('_')
    return 'asset/その他'


def published(root):
    rows = {}
    for name in ('data/published_videos.json', 'data/published_assets.json'):
        for kind, entries in read(root/name).items():
            for key, entry in entries.items():
                ident = entry.get('video_id')
                stamp = entry.get('publish_at') or entry.get('published_at')
                if not ident or not stamp:
                    continue
                day = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(JST).date().isoformat()
                if not FIRST <= day <= LAST or kind in ('longform', 'weekly'):
                    continue
                kind = 'asset' if kind == 'assets' else kind
                row = dict(day=day, kind=category(kind, key), key=key, video_id=ident,
                           title=entry.get('title'), privacy=entry.get('privacy', '記載なし'),
                           seconds=entry.get('duration_seconds'), duration_source=name if entry.get('duration_seconds') else None,
                           information=entry.get('short_information_count'), information_basis='台帳の描画前情報数' if entry.get('short_information_count') is not None else '全編の原稿未保存。題の主事実1件以上', sources=[name])
                if ident not in rows or name.endswith('published_videos.json'):
                    rows[ident] = row
    return list(rows.values())


def seconds(path):
    import imageio_ffmpeg
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-i', str(path)],
                            capture_output=True, text=True, encoding='utf8', errors='replace')
    found = re.search(r'Duration: (\d+):(\d+):([\d.]+)', result.stderr)
    return round(int(found[1])*3600+int(found[2])*60+float(found[3]), 3) if found else None


def enrich(rows, saved_root, root):
    import short_content
    import generated_topics
    topics = {}
    for filename in generated_topics.SOURCES:
        path = root/filename
        if path.exists():
            topics.update({t['key']:t for t in read(path).get('topics', [])})
    # 新しい補足処理を通さず、公開当時に保存した元の札も参照する。
    for directory in sorted((saved_root/'build').glob('channel-audit-202610*'), reverse=True):
        for filename in ('data_ps_game_topics.json', 'data_ps_story_topics.json', 'data_season_topics.json'):
            path = directory/filename
            if path.exists():
                for topic in read(path).get('topics', []):
                    topics.setdefault(topic['key'], topic)
    # 公開済み素材の原画面の札。現在も保存されている項目数を再現値として明示。
    for row in rows:
        spec = topics.get(row['key'])
        if spec and row['kind'].startswith('asset/'):
            document = dict(segments=[dict(kind='list',meta=dict(start=0,count=len(spec.get('items') or [])))]+
                [dict(kind='people',meta=dict(group=field)) for field in ('japanese','stars') if spec.get(field)])
            row.update(information=len(short_content.information(document,spec)),
                       information_basis='保存生成材料の独立した事実（公開映像の確定値ではない）')
    saved = saved_root/'build'
    for directory in sorted(saved.glob('channel-audit-202610*')):
        if len(directory.name) < 8:
            continue
        stamp = directory.name[-8:]
        day = stamp[:4]+'-'+stamp[4:6]+'-'+stamp[6:]
        if not FIRST <= day <= LAST:
            continue
        for path in directory.rglob('*.mp4'):
            rel = path.relative_to(directory).as_posix()
            candidates = []
            asset = re.search(r'collespo_asset_(.+)\.mp4$', path.name)
            if asset:
                candidates = [r for r in rows if r['key'] == asset[1] and r['day'] == day]
            else:
                kinds = {'morning/players.mp4':'morning', 'morning/press.mp4':'morning_press',
                         'morning/voices.mp4':'morning_voices', 'morning/postseason.mp4':'morning_postseason',
                         'preview/video/collespo_short.mp4':'daily', 'soccer/collespo_short.mp4':'daily_soccer',
                         'soccer-race/race/collespo_morning_soccer_race.mp4':'soccer_race',
                         'soccer-week/week/collespo_morning_soccer_week.mp4':'soccer_week'}
                candidates = [r for r in rows if r['day'] == day and r['kind'] == kinds.get(rel)]
            if len(candidates) == 1:
                candidates[0].update(seconds=seconds(path), duration_source=str(path.relative_to(saved_root)))
        program = directory/'preview/ps_program_forecast.json'
        if program.exists():
            info = short_content.information(read(program))
            for row in rows:
                if row['day'] == day and row['kind'] == 'daily':
                    row.update(information=len(info), information_basis=str(program.relative_to(saved_root)))
        for label, kind in (('race', 'soccer_race'), ('week', 'soccer_week')):
            path = directory/f'soccer-{label}/{label}_narration.json'
            if path.exists():
                info = short_content.information(read(path))
                for row in rows:
                    if row['day'] == day and row['kind'] == kind:
                        row.update(information=len(info), information_basis=str(path.relative_to(saved_root)))
        for label, kind in (('players','morning'), ('press','morning_press'), ('voices','morning_voices')):
            path = directory/f'claims/build/mr_narration_{label}.json'
            if not path.exists():
                continue
            doc = read(path)
            # 旧原稿の引用にはURLが分離していた。保存原稿で独立発言を確認できる下限。
            quotes = {short_content.normalized(q['said']) for s in doc['segments'] for q in
                      (s.get('meta') or {}).get('quote_rows', []) if q.get('said')}
            info = short_content.information(doc)
            if label == 'players':
                rankings = [x for s in doc['segments'] for x in (s.get('meta') or {}).get('ranking', [])]
                count = len(rankings) + sum(s['kind'] == 'week' for s in doc['segments'])
            else:
                count = len(quotes)
            for row in rows:
                if row['day'] == day and row['kind'] == kind:
                    row.update(information=count or len(info), information_basis=str(path.relative_to(saved_root))+'（引用は発言数）')
    # 分析値の平均視聴時間/平均率は尺の実測に変換しない。
    analytics = read(root/'data/analytics.json')
    ids = {v.get('video') for day in analytics.get('days', {}).values() for v in day.get('videos', [])}
    for row in rows:
        row['analytics_saved'] = row['video_id'] in ids
    return sorted(rows, key=lambda r: (r['kind'], r['day'], r['key']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = enrich(published(root), args.saved_root, root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(period_jst=[FIRST, LAST], rows=rows), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(videos=len(rows), kinds=dict(Counter(r['kind'] for r in rows)),
        measured=sum(r['seconds'] is not None for r in rows), unknown_seconds=sum(r['seconds'] is None for r in rows)), ensure_ascii=False))


if __name__ == '__main__':
    main()
